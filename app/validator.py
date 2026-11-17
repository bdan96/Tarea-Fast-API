"""Validación de sintaxis SQL con ubicación exacta del error (línea/columna).

Se apoya en `sqlglot` y añade:
  * división por statements (para reportar errores en todos, no solo el primero),
  * ubicación de comillas/comentarios sin cerrar (el tokenizador no da línea),
  * detección de coma sobrante (sqlglot la tolera),
  * sugerencias para palabras clave mal escritas (FORM -> FROM).

Límite conocido: valida SINTAXIS, no existencia de tablas/columnas, y los bloques
procedurales con ';' internos (BEGIN ... END) se dividirían por statement.
"""
from __future__ import annotations

import difflib
import re
from typing import TYPE_CHECKING

import sqlglot
from sqlglot.dialects.dialect import Dialect, Dialects
from sqlglot.errors import ErrorLevel, ParseError, TokenError
from sqlglot.tokens import Token, TokenType

if TYPE_CHECKING:  # evita import circular en tiempo de ejecución
    from app.models import SQLError

SUPPORTED_DIALECTS: set[str] = {d.value for d in Dialects if d.value}

STATEMENT_KEYWORDS = [
    "SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP", "WITH", "MERGE",
    "TRUNCATE", "EXPLAIN", "VALUES", "GRANT", "REVOKE", "SHOW", "DESCRIBE",
]
CLAUSE_KEYWORDS = [
    "SELECT", "FROM", "WHERE", "GROUP", "ORDER", "HAVING", "LIMIT", "JOIN", "INNER", "LEFT",
    "RIGHT", "OUTER", "UNION", "INSERT", "INTO", "VALUES", "UPDATE", "DELETE", "SET", "ON",
    "AND", "OR", "BETWEEN", "DISTINCT", "OFFSET",
]
BACKSLASH_DIALECTS = {"mysql", "bigquery", "spark", "databricks", "hive", "doris", "starrocks"}
TRAILING_COMMA_OK_BEFORE_FROM = {"bigquery", "duckdb", "snowflake"}
_CLAUSE_TOKENS = {
    TokenType.FROM: "FROM", TokenType.WHERE: "WHERE", TokenType.GROUP_BY: "GROUP BY",
    TokenType.ORDER_BY: "ORDER BY", TokenType.HAVING: "HAVING", TokenType.LIMIT: "LIMIT",
}


def _pos(sql: str, offset: int) -> tuple[int, int]:
    """Offset -> (línea, columna), ambas desde 1."""
    line = sql.count("\n", 0, offset) + 1
    col = offset - (sql.rfind("\n", 0, offset) + 1) + 1
    return line, col


def _line_text(sql: str, line: int) -> str | None:
    lines = sql.splitlines()
    return lines[line - 1] if 0 < line <= len(lines) else None


def _close(word: str, options: list[str]) -> str | None:
    if len(word) < 3 or word.upper() in options:
        return None
    m = difflib.get_close_matches(word.upper(), options, n=1, cutoff=0.75)
    return m[0] if m else None


def _find_unterminated(sql: str, backslash: bool) -> tuple[int, str] | None:
    """Localiza comillas o comentarios de bloque sin cerrar."""
    kinds = {"'": "cadena de texto", '"': "identificador entre comillas dobles", "`": "identificador entre acentos graves"}
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j == -1 else j + 1
            continue
        if sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            if j == -1:
                return i, "comentario de bloque"
            i = j + 2
            continue
        if c in kinds:
            start = i
            i += 1
            while i < n:
                if backslash and sql[i] == "\\":
                    i += 2
                    continue
                if sql[i] == c:
                    if i + 1 < n and sql[i + 1] == c:  # comilla escapada por duplicación
                        i += 2
                        continue
                    break
                i += 1
            else:
                return start, kinds[c]
        i += 1
    return None


def _translate(description: str, token_text: str | None) -> tuple[str, str]:
    d = re.sub(r"\s+", " ", description).strip()
    if d.startswith("Invalid expression / Unexpected token"):
        return "UNEXPECTED_TOKEN", f"Token inesperado '{token_text}'" if token_text else "Token inesperado"
    if d.startswith("Expecting "):
        return "EXPECTED_TOKEN", f"Se esperaba '{d[len('Expecting '):]}'"
    if d.startswith("Expected table name"):
        return "MISSING_TABLE_NAME", "Falta el nombre de la tabla"
    if d.startswith("Required keyword"):
        return "INCOMPLETE_EXPRESSION", "Expresión incompleta: falta un operando o palabra clave"
    return "SYNTAX_ERROR", re.sub(r"<[^>]*>", "", d)


def _split_statements(sql: str, tokens: list[Token]) -> list[tuple[int, int, list[Token]]]:
    """Divide por ';' devolviendo (offset_ini, offset_fin, tokens) de cada statement no vacío."""
    out, start, group = [], 0, []
    for t in tokens:
        if t.token_type == TokenType.SEMICOLON:
            if group:
                out.append((start, t.start, group))
            start, group = t.end + 1, []
        else:
            group.append(t)
    if group:
        out.append((start, len(sql), group))
    return out


def validate_sql(sql: str, dialect: str | None = None) -> tuple[int, list["SQLError"]]:
    """Devuelve (cantidad_de_statements, errores)."""
    from app.models import SQLError

    name = dialect or ""
    dialect_obj = Dialect.get_or_raise(name)

    def make(idx: int, offset: int, code: str, message: str, token: str | None = None,
             suggestion: str | None = None) -> SQLError:
        line, col = _pos(sql, offset)
        return SQLError(
            statement_index=idx, line=line, column=col,
            end_column=col + len(token) if token else None,
            code=code, message=message, token=token, suggestion=suggestion,
            context=_line_text(sql, line),
        )

    if not sql.strip():
        return 0, [make(1, 0, "EMPTY_QUERY", "La consulta está vacía")]

    try:
        tokens = dialect_obj.tokenize(sql)
    except TokenError:
        found = _find_unterminated(sql, name in BACKSLASH_DIALECTS)
        if found:
            off, kind = found
            return 1, [make(1, off, "UNTERMINATED_STRING", f"{kind.capitalize()} sin cerrar")]
        return 1, [make(1, 0, "TOKENIZE_ERROR", "No se pudo tokenizar la consulta (carácter o literal inválido)")]

    statements = _split_statements(sql, tokens)
    if not statements:
        return 0, [make(1, 0, "EMPTY_QUERY", "La consulta no contiene ningún statement")]

    errors: list[SQLError] = []
    seen: set[tuple[int, int]] = set()

    def add(err: SQLError) -> None:
        if (err.line, err.column) not in seen:
            seen.add((err.line, err.column))
            errors.append(err)

    for idx, (s_off, e_off, toks) in enumerate(statements, start=1):
        # 1) Primera palabra mal escrita (SELEC -> SELECT)
        first = toks[0]
        if first.token_type == TokenType.VAR and (kw := _close(first.text, STATEMENT_KEYWORDS)):
            add(make(idx, first.start, "UNKNOWN_KEYWORD",
                     f"Palabra clave desconocida '{first.text}'", first.text, kw))
            continue

        # 2) Coma sobrante
        for i, t in enumerate(toks):
            if t.token_type != TokenType.COMMA:
                continue
            nxt = toks[i + 1] if i + 1 < len(toks) else None
            if nxt is None or nxt.token_type == TokenType.R_PAREN:
                what = "el final de la consulta" if nxt is None else "')'"
                add(make(idx, t.start, "TRAILING_COMMA", f"Coma sobrante antes de {what}", ",", "Eliminar la coma"))
            elif nxt.token_type in _CLAUSE_TOKENS:
                clause = _CLAUSE_TOKENS[nxt.token_type]
                if clause == "FROM" and name in TRAILING_COMMA_OK_BEFORE_FROM:
                    continue
                add(make(idx, t.start, "TRAILING_COMMA", f"Coma sobrante antes de {clause}", ",", "Eliminar la coma"))

        # 3) Errores del parser (se parsea el statement con relleno para conservar línea/columna)
        padded = re.sub(r"[^\n]", " ", sql[:s_off]) + sql[s_off:e_off]
        try:
            sqlglot.parse(padded, read=name or None, error_level=ErrorLevel.RAISE)
        except ParseError as exc:
            for info in exc.errors:
                line, col = info.get("line"), info.get("col")
                pos = next((k for k, t in enumerate(toks) if t.line == line and t.col == col), None)
                tok = toks[pos] if pos is not None else None
                code, msg = _translate(info.get("description", ""), tok.text if tok else info.get("highlight"))
                # ¿El token anterior es una palabra clave mal escrita? (FORM -> FROM)
                if pos and toks[pos - 1].token_type == TokenType.VAR:
                    prev = toks[pos - 1]
                    if kw := _close(prev.text, CLAUSE_KEYWORDS):
                        add(make(idx, prev.start, "UNKNOWN_KEYWORD",
                                 f"Palabra clave desconocida '{prev.text}'", prev.text, kw))
                        continue
                if tok is not None:
                    add(make(idx, tok.start, code, msg, tok.text))
                else:
                    add(SQLError(statement_index=idx, line=line or 1, column=col or 1, code=code,
                                 message=msg, context=_line_text(sql, line or 1)))

    errors.sort(key=lambda e: (e.line, e.column))
    return len(statements), errors


def build_summary(valid: bool, errors: list["SQLError"]) -> str:
    if valid:
        return "La sintaxis SQL es válida."
    first = errors[0]
    extra = f" (y {len(errors) - 1} error(es) más)" if len(errors) > 1 else ""
    sug = f" ¿Quisiste decir {first.suggestion}?" if first.suggestion and first.code == "UNKNOWN_KEYWORD" else ""
    return f"Línea {first.line}, columna {first.column}: {first.message}.{sug}{extra}"
