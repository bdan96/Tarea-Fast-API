# SQL Syntax Validator API

API con **FastAPI** que valida la sintaxis de consultas SQL y, cuando hay un error, indica **en qué línea y columna** está y **cuál es el problema**. Está pensada como herramienta (tool) para un agente de IA: el contrato se publica en `/openapi.json`.

> Valida **sintaxis**, no semántica: no comprueba que las tablas o columnas existan.

## Requisitos

- Python 3.10 o superior

## Instalación y ejecución

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

uvicorn app.main:app --reload --port 8000
```

- Documentación interactiva: http://localhost:8000/docs
- Contrato OpenAPI (para el agente): http://localhost:8000/openapi.json

Pruebas:

```bash
pytest -q
```

## Estructura

```
sql-validator-api/
├── app/
│   ├── main.py        # Endpoints FastAPI
│   ├── models.py      # Modelos de petición/respuesta
│   └── validator.py   # Lógica de validación (línea, columna, sugerencias)
├── tests/test_api.py
├── .github/skills/
│   └── sql-syntax-validator/SKILL.md   # Skill del agente (estándar Agent Skills)
└── requirements.txt
```

## Endpoints

| Método | Ruta | operationId | Descripción |
|---|---|---|---|
| POST | `/validate` | `validate_sql` | Valida una consulta SQL (respuesta completa, todos los errores) |
| POST | `/validate-syntax` | `validate_sql_syntax` | Respuesta simplificada para la skill: `is_valid`, `error_message`, `line`, `column` |
| GET | `/dialects` | `list_dialects` | Lista los dialectos soportados |
| GET | `/health` | `health` | Estado del servicio |

### `POST /validate`

Petición:

```json
{
  "sql": "SELECT id,\n name\nFORM users\nWHERE id = 1;",
  "dialect": "postgres"
}
```

`dialect` es opcional (por defecto, genérico). Consulta `GET /dialects`.

Respuesta:

```json
{
  "valid": false,
  "dialect": "postgres",
  "statements": 1,
  "errors": [
    {
      "statement_index": 1,
      "line": 3,
      "column": 1,
      "end_column": 5,
      "code": "UNKNOWN_KEYWORD",
      "message": "Palabra clave desconocida 'FORM'",
      "token": "FORM",
      "suggestion": "FROM",
      "context": "FORM users"
    }
  ],
  "summary": "Línea 3, columna 1: Palabra clave desconocida 'FORM'. ¿Quisiste decir FROM?"
}
```

Reglas de la respuesta:

- Una consulta inválida **no** es un error HTTP: siempre se responde `200` con `valid: false`.
- `line` y `column` empiezan en 1 y se refieren al texto SQL original, aunque haya varios statements.
- `errors` viene ordenado por línea y columna, e incluye errores de **todos** los statements.
- `summary` es un texto listo para mostrar al usuario.
- Un cuerpo mal formado (SQL vacío, dialecto desconocido) responde `422`.

Ejemplo con curl:

```bash
curl -s -X POST http://localhost:8000/validate \
  -H "Content-Type: application/json" \
  -d '{"sql": "SELECT * FROM t WHERE (a = 1", "dialect": "mysql"}'
```

### `POST /validate-syntax`

Contrato simplificado que usa la skill. Misma petición que `/validate`; responde solo con el **primer** error:

```json
{ "is_valid": false, "error_message": "Palabra clave desconocida 'FORM'. Sugerencia: FROM",
  "line": 3, "column": 1, "context": "FORM users" }
```

Si la consulta es válida: `{ "is_valid": true, "error_message": null, "line": null, "column": null }`.

## Códigos de error

| `code` | Significado |
|---|---|
| `UNKNOWN_KEYWORD` | Palabra clave mal escrita (con `suggestion`) |
| `UNEXPECTED_TOKEN` | Token que no corresponde en esa posición |
| `EXPECTED_TOKEN` | Falta un elemento, p. ej. `)` |
| `MISSING_TABLE_NAME` | Falta el nombre de la tabla |
| `INCOMPLETE_EXPRESSION` | Falta un operando o una palabra clave |
| `TRAILING_COMMA` | Coma sobrante (antes de `FROM`, `WHERE`, `)` o al final) |
| `UNTERMINATED_STRING` | Comilla o comentario de bloque sin cerrar |
| `EMPTY_QUERY` | Consulta vacía |
| `SYNTAX_ERROR` | Otro error de sintaxis |

## Cómo funciona

1. **Tokeniza** todo el texto con el dialecto elegido. Si hay una comilla o un comentario sin cerrar, localiza dónde se abrió.
2. **Divide** por `;` y valida cada statement por separado para reportar todos los errores. Cada statement se rellena con espacios para conservar las líneas y columnas originales.
3. **Detecta** palabras clave mal escritas y comas sobrantes, que el parser tolera.
4. **Parsea** con `sqlglot` y traduce sus errores a mensajes claros con posición exacta.

## Limitaciones

- No valida existencia de tablas, columnas ni tipos.
- Los bloques procedurales con `;` internos (`BEGIN ... END`) se dividen por statement.
- `sqlglot` es permisivo con algunas construcciones; la API cubre las más comunes (coma sobrante, palabras clave mal escritas), pero no garantiza detectar todo lo que rechazaría un motor real.
- Sin autenticación. Antes de exponerla fuera de un entorno local, añade una API key o un proxy.

## Integración con el agente

La skill `.github/skills/sql-syntax-validator/SKILL.md` obliga al agente a validar cada consulta que genere con la herramienta `validate_sql_syntax` y a corregirla en bucle hasta que sea válida. Esa herramienta corresponde al endpoint `POST /validate-syntax` (`operationId: validate_sql_syntax`), que el agente descubre desde `/openapi.json`.

Las skills adicionales van en `.github/skills/<nombre-de-la-skill>/SKILL.md`.
