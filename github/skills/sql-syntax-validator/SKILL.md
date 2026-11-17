---
name: sql-syntax-validator
description: Valida y corrige la sintaxis de consultas SQL con la herramienta validate_sql_syntax antes de entregarlas o ejecutarlas. Úsala siempre que escribas, generes, modifiques o revises una consulta SQL (SELECT, INSERT, UPDATE, DELETE, DDL) para asegurar que sea sintácticamente correcta en el dialecto objetivo.
---

## Skill: Validador y Corrector de Sintaxis SQL

### Propósito

Tu objetivo es garantizar que cualquier consulta SQL que escribas o generes sea estrictamente sintáctica y gramaticalmente correcta para el dialecto objetivo ANTES de darla por buena o ejecutarla.

### Herramienta asignada

- **`validate_sql_syntax`**: Envía una consulta y un dialecto para verificar su sintaxis. Devuelve un JSON con:
  - `is_valid`: boolean (`true` / `false`)
  - `error_message`: descripción del error de sintaxis.
  - `line`: número de línea donde ocurrió el fallo.
  - `column`: número de columna donde ocurrió el fallo.

### Protocolo de actuación obligatorio (Flujo de Trabajo)

1. **Generación inicial**: Escribe la consulta SQL requerida según el contexto del usuario y el dialecto especificado.
2. **Validación obligatoria**: Llama inmediatamente a la herramienta `validate_sql_syntax` pasándole tu consulta.
3. **Evaluación de la respuesta**:
   - Si `is_valid` es `true`: Prosigue con tu respuesta o la ejecución del siguiente paso.
   - Si `is_valid` es `false`:
     - Analiza el `error_message`, la `line` y la `column`.
     - Identifica exactamente qué token o carácter causó el fallo (ej. un paréntesis faltante, una coma sobrante, una palabra clave mal escrita).
     - Corrige la consulta internamente.
4. **Bucle de reintento**: Vuelve a llamar a la herramienta de validación con la consulta corregida. Repite este proceso de forma autónoma hasta obtener `is_valid: true`. No expongas consultas con errores de sintaxis al usuario final.
