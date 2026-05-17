"""Integration tests for the HTTP wrapper using FastAPI TestClient."""
import os
import tempfile
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="vdr-http-")
    monkeypatch.setenv("VDR_ROOT_PATH", tmp)
    # Re-import to pick up env
    import importlib
    from gestnova_filesystem import http_server
    importlib.reload(http_server)
    return TestClient(http_server.app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert int(data["tools_loaded"]) == 13


def test_list_tools(client):
    r = client.get("/tools")
    assert r.status_code == 200
    tools = r.json()
    names = {t["name"] for t in tools}
    assert {"ensureCompanyLayout", "writeFile", "readFile", "archiveInvoice", "searchFiles"} <= names
    for t in tools:
        assert t["description"]
        assert t["input_schema"]["type"] == "object"


def test_call_unknown_tool(client):
    r = client.post("/call", json={"name": "doesNotExist", "arguments": {}})
    assert r.status_code == 404


def test_full_flow(client):
    # 1. ensure layout
    r = client.post("/call", json={"name": "ensureCompanyLayout", "arguments": {"companySlug": "gestnova"}})
    assert r.status_code == 200
    assert r.json()["slug"] == "gestnova"

    # 2. write a file
    r = client.post("/call", json={
        "name": "writeFile",
        "arguments": {"companySlug": "gestnova", "relPath": "informes/2026/05/note.txt", "content": "hola"},
    })
    assert r.status_code == 200
    assert r.json()["name"] == "note.txt"

    # 3. read it back
    r = client.post("/call", json={
        "name": "readFile",
        "arguments": {"companySlug": "gestnova", "relPath": "informes/2026/05/note.txt"},
    })
    assert r.status_code == 200
    assert r.json()["content"] == "hola"

    # 4. archive an invoice
    r = client.post("/call", json={
        "name": "archiveInvoice",
        "arguments": {
            "companySlug": "gestnova",
            "number": "F-2026-001",
            "content": "<html>factura</html>",
            "dateISO": "2026-05-14",
        },
    })
    assert r.status_code == 200
    assert "facturas/2026/Q2" in r.json()["relPath"]

    # 5. search for it
    r = client.post("/call", json={
        "name": "searchFiles",
        "arguments": {"companySlug": "gestnova", "query": "F-2026-001"},
    })
    assert r.status_code == 200
    assert len(r.json()["results"]) >= 1

    # 6. folder tree
    r = client.post("/call", json={
        "name": "getFolderTree",
        "arguments": {"companySlug": "gestnova", "depth": 2},
    })
    assert r.status_code == 200
    tree = r.json()
    assert tree["type"] in {"folder", "dir"}
    child_names = {c["name"] for c in tree["children"]}
    assert "facturas" in child_names


def test_path_traversal_blocked(client):
    client.post("/call", json={"name": "ensureCompanyLayout", "arguments": {"companySlug": "gestnova"}})
    r = client.post("/call", json={
        "name": "writeFile",
        "arguments": {"companySlug": "gestnova", "relPath": "../../etc/passwd", "content": "x"},
    })
    assert r.status_code == 200
    body = r.json()
    assert "error" in body


def test_invalid_slug(client):
    r = client.post("/call", json={"name": "ensureCompanyLayout", "arguments": {"companySlug": "BAD slug!"}})
    body = r.json()
    assert "error" in body
