"""Full-text indexing + search tests."""
import tempfile
from pathlib import Path
import pytest

from gestnova_filesystem.vdr import VDR
from gestnova_filesystem.fulltext import FullTextIndex, _extract_text


@pytest.fixture
def vdr():
    tmp = tempfile.mkdtemp(prefix="vdr-fts-")
    v = VDR(tmp)
    v.ensureCompanyLayout("gestnova")
    return v


def test_index_created_per_company(vdr):
    idx = FullTextIndex(vdr.companyRoot("gestnova"))
    assert idx.db_path.exists()
    assert idx.count() == 0


def test_write_indexes_content_automatically(vdr):
    vdr.writeFile("gestnova", "contratos/clientes/acme.txt", "Cliente Acme con preaviso de treinta dias", overwrite=True)
    idx = FullTextIndex(vdr.companyRoot("gestnova"))
    assert idx.count() == 1
    hits = idx.search("preaviso")
    assert len(hits) == 1
    assert hits[0].relPath == "contratos/clientes/acme.txt"
    assert "preaviso" in hits[0].snippet.lower()


def test_search_content_via_vdr(vdr):
    vdr.writeFile("gestnova", "informes/2026/05/note.txt", "Aurora dijo que la consciencia emerge de la integracion", overwrite=True)
    vdr.writeFile("gestnova", "informes/2026/05/other.txt", "Reunion con Ignacio sobre trading", overwrite=True)
    results = vdr.searchContent("gestnova", "consciencia")
    assert len(results) == 1
    assert results[0]["relPath"] == "informes/2026/05/note.txt"


def test_delete_removes_from_index(vdr):
    vdr.writeFile("gestnova", "informes/borrame.txt", "contenido temporal", overwrite=True)
    assert len(vdr.searchContent("gestnova", "temporal")) == 1
    vdr.deleteFile("gestnova", "informes/borrame.txt")
    assert vdr.searchContent("gestnova", "temporal") == []


def test_move_reindexes(vdr):
    vdr.writeFile("gestnova", "informes/old.txt", "factura del mes de mayo", overwrite=True)
    vdr.moveFile("gestnova", "informes/old.txt", "informes/new.txt")
    results = vdr.searchContent("gestnova", "factura")
    assert len(results) == 1
    assert results[0]["relPath"] == "informes/new.txt"


def test_binary_files_skipped(vdr):
    # .jpg is not in INDEXABLE_*
    abs_path = vdr.companyRoot("gestnova") / "informes" / "img.jpg"
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(b"\x89PNG\r\n\x1a\nfake-binary")
    idx = FullTextIndex(vdr.companyRoot("gestnova"))
    indexed = idx.upsert("informes/img.jpg")
    assert indexed is False


def test_html_extraction():
    tmp = Path(tempfile.mkdtemp(prefix="fts-html-")) / "doc.html"
    tmp.write_text("<html><body><h1>Factura</h1><p>Total <b>1234.56</b> EUR</p></body></html>")
    text = _extract_text(tmp)
    assert "Factura" in text
    assert "1234.56" in text


def test_isolation_between_companies(vdr):
    vdr.ensureCompanyLayout("otracorp")
    vdr.writeFile("gestnova", "informes/secret.txt", "informacion confidencial gestnova", overwrite=True)
    vdr.writeFile("otracorp", "informes/public.txt", "informacion publica otracorp", overwrite=True)
    gestnova_hits = vdr.searchContent("gestnova", "informacion")
    otracorp_hits = vdr.searchContent("otracorp", "informacion")
    assert len(gestnova_hits) == 1 and gestnova_hits[0]["relPath"] == "informes/secret.txt"
    assert len(otracorp_hits) == 1 and otracorp_hits[0]["relPath"] == "informes/public.txt"


def test_reindex_rebuilds_index(vdr):
    company_root = vdr.companyRoot("gestnova")
    # Drop a file directly on disk (bypassing writeFile so no auto-index)
    f = company_root / "informes" / "manual.txt"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("contenido manual no auto-indexado")
    assert vdr.searchContent("gestnova", "manual") == []
    n = vdr.reindexCompany("gestnova")
    assert n >= 1
    hits = vdr.searchContent("gestnova", "manual")
    assert len(hits) >= 1


def test_sanitize_rejects_fts_operators(vdr):
    vdr.writeFile("gestnova", "informes/a.txt", "Hola mundo cruel", overwrite=True)
    # Should not blow up with FTS5 operator chars / parens / asterisks
    assert vdr.searchContent("gestnova", "(hola)") != []
    assert vdr.searchContent("gestnova", "hola*") != []
    # Operators stripped to plain tokens; "AND/OR" become required tokens, which is fine
    # The important thing is no SQL/FTS injection crash.
    vdr.searchContent("gestnova", "hola; DROP TABLE docs;--")
    vdr.searchContent("gestnova", '" injected "')
