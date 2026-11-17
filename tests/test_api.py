from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def post(sql, dialect=None):
    body = {"sql": sql}
    if dialect:
        body["dialect"] = dialect
    r = client.post("/validate", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_health_and_dialects():
    assert client.get("/health").json() == {"status": "ok"}
    d = client.get("/dialects").json()["dialects"]
    assert "postgres" in d and "mysql" in d


def test_valid_queries():
    assert post("SELECT a FROM t JOIN u ON t.id = u.id")["valid"] is True
    assert post("INSERT INTO t (a, b) VALUES (1, 2);")["valid"] is True
    assert post("-- comentario\nSELECT 1;\nSELECT 2;")["statements"] == 2


def test_typo_keyword_reports_line():
    r = post("SELECT id,\n name\nFORM users\nWHERE id = 1;", "postgres")
    assert r["valid"] is False
    e = r["errors"][0]
    assert (e["line"], e["column"]) == (3, 1)
    assert e["code"] == "UNKNOWN_KEYWORD" and e["suggestion"] == "FROM"
    assert r["summary"].startswith("Línea 3, columna 1")


def test_first_word_typo():
    e = post("SELEC * FROM t")["errors"][0]
    assert (e["line"], e["column"], e["suggestion"]) == (1, 1, "SELECT")


def test_missing_paren():
    e = post("SELECT *\nFROM t\nWHERE (a = 1 AND b = 2")["errors"][0]
    assert e["line"] == 3 and e["code"] == "EXPECTED_TOKEN"


def test_unterminated_string_and_comment():
    e = post("SELECT 1;\nSELECT 'abc\nFROM t")["errors"][0]
    assert (e["line"], e["column"], e["code"]) == (2, 8, "UNTERMINATED_STRING")
    e = post("SELECT 1\n/* sin cerrar")["errors"][0]
    assert (e["line"], e["column"]) == (2, 1)


def test_trailing_comma():
    e = post("SELECT a,\nFROM t")["errors"][0]
    assert (e["line"], e["column"], e["code"]) == (1, 9, "TRAILING_COMMA")
    assert post("SELECT a, FROM t", "bigquery")["valid"] is True  # permitido en BigQuery


def test_multiple_statements_all_reported():
    r = post("SELECT 1;\nSELECT * FROM;\nSELECT 2 FROM t WHERE;")
    assert [e["line"] for e in r["errors"]] == [2, 3]
    assert [e["statement_index"] for e in r["errors"]] == [2, 3]


def test_empty_query():
    e = post("   ;  ")["errors"][0]
    assert e["code"] == "EMPTY_QUERY"


def test_request_validation():
    assert client.post("/validate", json={"sql": ""}).status_code == 422
    assert client.post("/validate", json={"sql": "SELECT 1", "dialect": "nope"}).status_code == 422
    assert client.post("/validate", json={}).status_code == 422


def test_openapi_exposes_operation_id():
    ops = [m["operationId"] for p in client.get("/openapi.json").json()["paths"].values() for m in p.values()]
    assert "validate_sql" in ops


def test_validate_syntax_contract_for_skill():
    ok = client.post("/validate-syntax", json={"sql": "SELECT 1"}).json()
    assert ok["is_valid"] is True and ok["error_message"] is None and ok["line"] is None

    bad = client.post("/validate-syntax", json={"sql": "SELECT id,\n name\nFORM users", "dialect": "postgres"}).json()
    assert bad["is_valid"] is False
    assert (bad["line"], bad["column"]) == (3, 1)
    assert "FORM" in bad["error_message"] and "FROM" in bad["error_message"]


def test_openapi_has_skill_tool_name():
    ops = [m["operationId"] for p in client.get("/openapi.json").json()["paths"].values() for m in p.values()]
    assert "validate_sql_syntax" in ops
