"""Modelos de entrada/salida de la API (también documentan el OpenAPI que consume el agente)."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.validator import SUPPORTED_DIALECTS


class ValidateRequest(BaseModel):
    sql: str = Field(
        ...,
        min_length=1,
        max_length=200_000,
        description="Texto SQL a validar. Puede contener varios statements separados por ';'.",
    )
    dialect: str | None = Field(
        default=None,
        description="Dialecto SQL (p. ej. 'postgres', 'mysql', 'tsql', 'bigquery'). "
        "Si se omite se usa un dialecto genérico. Ver GET /dialects.",
    )

    @field_validator("dialect")
    @classmethod
    def _check_dialect(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().lower()
        if v in ("", "generic"):
            return None
        if v not in SUPPORTED_DIALECTS:
            raise ValueError(f"Dialecto '{v}' no soportado. Usa GET /dialects para ver la lista.")
        return v

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"sql": "SELECT id,\n name\nFORM users\nWHERE id = 1;", "dialect": "postgres"}
            ]
        }
    }


class SQLError(BaseModel):
    statement_index: int = Field(..., description="Número del statement (desde 1) donde ocurre el error.")
    line: int = Field(..., description="Línea del error (desde 1) en el texto SQL original.")
    column: int = Field(..., description="Columna del error (desde 1).")
    end_column: int | None = Field(default=None, description="Columna final del token problemático.")
    code: str = Field(..., description="Código estable del error, p. ej. UNEXPECTED_TOKEN, UNKNOWN_KEYWORD.")
    message: str = Field(..., description="Descripción del error en español.")
    token: str | None = Field(default=None, description="Token donde se detectó el error.")
    suggestion: str | None = Field(default=None, description="Corrección sugerida, si existe.")
    context: str | None = Field(default=None, description="Texto de la línea donde ocurre el error.")


class ValidateResponse(BaseModel):
    valid: bool = Field(..., description="True si la sintaxis es correcta.")
    dialect: str = Field(..., description="Dialecto usado en la validación.")
    statements: int = Field(..., description="Cantidad de statements detectados.")
    errors: list[SQLError] = Field(default_factory=list, description="Errores ordenados por línea y columna.")
    summary: str = Field(..., description="Resumen legible para mostrar directamente al usuario.")


class DialectsResponse(BaseModel):
    dialects: list[str]


class SyntaxCheckResponse(BaseModel):
    """Contrato simple usado por la skill `sql-syntax-validator`."""

    is_valid: bool = Field(..., description="True si la sintaxis es correcta.")
    error_message: str | None = Field(
        default=None, description="Descripción del primer error (null si es válida)."
    )
    line: int | None = Field(default=None, description="Línea del primer error (null si es válida).")
    column: int | None = Field(default=None, description="Columna del primer error (null si es válida).")
    context: str | None = Field(default=None, description="Texto de la línea con el error.")
