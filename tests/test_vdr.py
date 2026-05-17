from pathlib import Path
import pytest
from gestnova_filesystem.vdr import VDR, STANDARD_FOLDERS


@pytest.fixture
def vdr(tmp_path: Path) -> VDR:
    return VDR(tmp_path)


def test_init_creates_root(tmp_path: Path):
    v = VDR(tmp_path / "data")
    assert v.root.exists()


def test_company_root(vdr: VDR):
    p = vdr.companyRoot("gestnova")
    assert "companies/gestnova" in str(p)


def test_ensure_layout_creates_standard_folders(vdr: VDR):
    created = vdr.ensureCompanyLayout("gestnova")
    for f in STANDARD_FOLDERS:
        assert f in created
        assert (vdr.companyRoot("gestnova") / f).exists()


def test_ensure_layout_is_idempotent(vdr: VDR):
    vdr.ensureCompanyLayout("gestnova")
    vdr.ensureCompanyLayout("gestnova")  # no raise


def test_invalid_slug_rejected(vdr: VDR):
    with pytest.raises(ValueError):
        vdr.companyRoot("../escape")
    with pytest.raises(ValueError):
        vdr.companyRoot("Invalid Slug")
    with pytest.raises(ValueError):
        vdr.companyRoot("UPPERCASE")


def test_path_traversal_blocked(vdr: VDR):
    vdr.ensureCompanyLayout("gestnova")
    with pytest.raises(ValueError):
        vdr.readFile("gestnova", "../other-company/secret.txt")
    with pytest.raises(ValueError):
        vdr.readFile("gestnova", "/etc/passwd")
    with pytest.raises(ValueError):
        vdr.writeFile("gestnova", "../escape.txt", "x")


def test_write_then_list_then_read(vdr: VDR):
    vdr.ensureCompanyLayout("gestnova")
    entry = vdr.writeFile("gestnova", "facturas/2026/Q2/F-001.html", "<html>factura</html>")
    assert entry.relPath == "facturas/2026/Q2/F-001.html"
    assert entry.sizeBytes > 0

    listing = vdr.listFolder("gestnova", "facturas/2026/Q2")
    names = [e.name for e in listing]
    assert "F-001.html" in names

    read = vdr.readFile("gestnova", "facturas/2026/Q2/F-001.html")
    assert read["content"] == "<html>factura</html>"


def test_write_refuses_overwrite_by_default(vdr: VDR):
    vdr.writeFile("gestnova", "a.txt", "first")
    with pytest.raises(FileExistsError):
        vdr.writeFile("gestnova", "a.txt", "second")
    # With overwrite=True works
    e = vdr.writeFile("gestnova", "a.txt", "second", overwrite=True)
    assert e.sizeBytes == len("second")


def test_move_file(vdr: VDR):
    vdr.writeFile("gestnova", "a.txt", "data")
    e = vdr.moveFile("gestnova", "a.txt", "facturas/2026/Q2/b.txt")
    assert e.relPath == "facturas/2026/Q2/b.txt"
    # Original gone
    with pytest.raises(FileNotFoundError):
        vdr.readFile("gestnova", "a.txt")


def test_delete_file(vdr: VDR):
    vdr.writeFile("gestnova", "tmp.txt", "x")
    assert vdr.deleteFile("gestnova", "tmp.txt") is True
    assert vdr.deleteFile("gestnova", "tmp.txt") is False  # already gone


def test_delete_folder_refused(vdr: VDR):
    vdr.ensureCompanyLayout("gestnova")
    with pytest.raises(ValueError):
        vdr.deleteFile("gestnova", "facturas")


def test_search_files_by_substring(vdr: VDR):
    vdr.writeFile("gestnova", "facturas/2026/Q2/F-001-Acme.html", "x")
    vdr.writeFile("gestnova", "facturas/2026/Q2/F-002-Other.html", "x")
    vdr.writeFile("gestnova", "gastos/2026/Q2/recibo-luz.html", "x")

    results = vdr.searchFiles("gestnova", "Acme")
    assert len(results) == 1
    assert "F-001-Acme.html" in results[0].relPath

    results2 = vdr.searchFiles("gestnova", "2026")
    assert len(results2) == 3   # all under 2026


def test_read_binary_returns_marker(vdr: VDR, tmp_path: Path):
    vdr.ensureCompanyLayout("gestnova")
    # Write raw bytes directly to simulate a PDF
    bin_path = vdr.companyRoot("gestnova") / "facturas" / "2026" / "Q2" / "raw.pdf"
    bin_path.parent.mkdir(parents=True, exist_ok=True)
    bin_path.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x01\x02\x03")
    res = vdr.readFile("gestnova", "facturas/2026/Q2/raw.pdf")
    assert res["encoding"] == "binary"
    assert res["content"] is None


def test_read_too_large_truncated(vdr: VDR):
    big = "x" * 2_000_000
    vdr.writeFile("gestnova", "huge.txt", big)
    res = vdr.readFile("gestnova", "huge.txt", maxBytes=1_000_000)
    assert res["truncated"] is True
    assert res["content"] is None


def test_archive_invoice_uses_year_quarter_structure(vdr: VDR):
    e = vdr.archiveInvoice("gestnova", "F-2026-042", "<html>...</html>", "2026-05-14")
    assert e.relPath == "facturas/2026/Q2/F-2026-042.html"


def test_archive_payroll_uses_year_month(vdr: VDR):
    e = vdr.archivePayroll("gestnova", "emp-1", "2026-05", "<html>nómina</html>")
    assert e.relPath == "nominas/2026/05/emp-1.html"


def test_archive_compliance_uses_doctype_version(vdr: VDR):
    e = vdr.archiveComplianceDoc("gestnova", "lopd-rgpd", "<html>...</html>", "v2")
    assert e.relPath == "compliance/lopd-rgpd/v2.html"


def test_tenants_isolated(vdr: VDR):
    vdr.writeFile("acme", "secret.txt", "secret-acme")
    vdr.writeFile("other-co", "secret.txt", "secret-other")
    acme_files = vdr.listFolder("acme")
    other_files = vdr.listFolder("other-co")
    assert any("secret.txt" in e.name for e in acme_files)
    assert any("secret.txt" in e.name for e in other_files)
    # Cannot access acme from other-co
    res = vdr.readFile("acme", "secret.txt")
    assert res["content"] == "secret-acme"
    res2 = vdr.readFile("other-co", "secret.txt")
    assert res2["content"] == "secret-other"
