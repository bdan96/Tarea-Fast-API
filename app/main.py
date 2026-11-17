"""API de validación de sintaxis SQL, pensada como herramienta (tool) para un agente de IA.

El agente puede descubrir el contrato leyendo /openapi.json.
"""
from __future__ import annotations

from fastapi import FastAPI

from app.models import DialectsResponse, SyntaxCheckResponse, ValidateRequest, ValidateResponse
from app.validator import SUPPORTED_DIALECTS, build_summary, validate_sql

app = FastAPI(
    title="SQL Syntax Validator API",
    version="1.0.0",
    description=(
        "Valida la sintaxis de consultas SQL y, si hay errores, indica la línea, la columna "
        "y el motivo de cada uno. Valida sintaxis únicamente: no comprueba que existan "
        "tablas o columnas."
    ),
)


@app.get("/health", summary="Estado del servicio", operation_id="health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/dialects", response_model=DialectsResponse, summary="Dialectos SQL soportados",
         operation_id="list_dialects", tags=["sql"])
def dialects() -> DialectsResponse:
    return DialectsResponse(dialects=sorted(SUPPORTED_DIALECTS))


@app.post(
    "/validate",
    response_model=ValidateResponse,
    summary="Validar la sintaxis de una consulta SQL",
    operation_id="validate_sql",
    tags=["sql"],
    description=(
        "Devuelve siempre 200 con `valid` y la lista `errors`. Una consulta inválida NO es un "
        "error HTTP: es un resultado normal de la validación. Cada error incluye `line`, "
        "`column`, `code` y `message`; `summary` es un texto listo para mostrar al usuario."
    ),
)
def validate(req: ValidateRequest) -> ValidateResponse:
    count, errors = validate_sql(req.sql, req.dialect)
    valid = not errors
    return ValidateResponse(
        valid=valid,
        dialect=req.dialect or "generic",
        statements=count,
        errors=errors,
        summary=build_summary(valid, errors),
    )


@app.post(
    "/validate-syntax",
    response_model=SyntaxCheckResponse,
    summary="Validar sintaxis SQL (respuesta simplificada para agentes)",
    operation_id="validate_sql_syntax",
    tags=["sql"],
    description=(
        "Versión simplificada de /validate. Devuelve `is_valid` y, si hay error, "
        "`error_message`, `line` y `column` del PRIMER error. Corrige ese error y vuelve a "
        "llamar hasta obtener `is_valid: true`."
    ),
)
def validate_syntax(req: ValidateRequest) -> SyntaxCheckResponse:
    _, errors = validate_sql(req.sql, req.dialect)
    if not errors:
        return SyntaxCheckResponse(is_valid=True)
    first = errors[0]
    msg = first.message
    if first.suggestion:
        msg += f". Sugerencia: {first.suggestion}"
    if len(errors) > 1:
        msg += f" (hay {len(errors) - 1} error(es) más; se mostrarán al corregir este)"
    return SyntaxCheckResponse(
        is_valid=False, error_message=msg, line=first.line, column=first.column, context=first.context
    )
