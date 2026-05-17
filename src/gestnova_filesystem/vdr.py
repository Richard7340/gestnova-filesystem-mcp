"""Per-company Virtual Data Room (VDR) — pure filesystem operations
with standardized folder layout enforced.

Safety:
- All paths normalized + checked to live under the company's root.
- Path traversal (.., absolute paths, symlinks escape) rejected.
- Companies cannot read/write to each other's folders.
"""
from __future__ import annotations
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


STANDARD_FOLDERS = [
    "facturas",
    "gastos",
    "nominas",
    "compliance",
    "contratos/clientes",
    "contratos/proveedores",
    "scenarios",
    "informes",
]


SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


def _check_slug(slug: str) -> None:
    if not SLUG_RE.match(slug):
        raise ValueError(f"Invalid company slug: {slug!r} — must match {SLUG_RE.pattern}")


@dataclass
class FileEntry:
    relPath: str        # relative to company root: e.g. 'facturas/2026/Q2/F-001.pdf'
    name: str
    isFile: bool
    sizeBytes: int
    modifiedAt: str     # ISO 8601


class VDR:
    """One VDR instance manages all companies under a shared root."""

    def __init__(self, root: str | Path):
        self._root = Path(root).expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def companyRoot(self, slug: str) -> Path:
        _check_slug(slug)
        return self._root / "companies" / slug

    def ensureCompanyLayout(self, slug: str) -> list[str]:
        """Create the standard folders for a company. Idempotent.
        Returns the list of folders that exist after the call."""
        root = self.companyRoot(slug)
        created: list[str] = []
        for sub in STANDARD_FOLDERS:
            target = root / sub
            target.mkdir(parents=True, exist_ok=True)
            created.append(sub)
        return created

    def _resolveCompanyPath(self, slug: str, relPath: str) -> Path:
        """Resolve a relPath under the company root, rejecting traversal."""
        root = self.companyRoot(slug)
        # Normalize: forbid leading slash, forbid '..' segments
        if relPath.startswith("/"):
            raise ValueError(f"Path must be relative: {relPath!r}")
        # Use os.path.normpath to collapse, then ensure it doesn't escape
        clean = os.path.normpath(relPath)
        if clean.startswith("..") or clean.startswith("/"):
            raise ValueError(f"Path traversal not allowed: {relPath!r}")
        target = (root / clean).resolve()
        # Final safety: target must be inside root
        try:
            target.relative_to(root.resolve())
        except ValueError:
            raise ValueError(f"Path escapes company root: {relPath!r}") from None
        return target

    def listFolder(self, slug: str, relPath: str = "") -> list[FileEntry]:
        target = self._resolveCompanyPath(slug, relPath) if relPath else self.companyRoot(slug)
        if not target.exists():
            return []
        if not target.is_dir():
            raise ValueError(f"Not a directory: {relPath!r}")
        entries: list[FileEntry] = []
        for child in sorted(target.iterdir()):
            if child.name == ".index":
                continue
            stat = child.stat()
            rel = str(child.relative_to(self.companyRoot(slug)))
            entries.append(FileEntry(
                relPath=rel,
                name=child.name,
                isFile=child.is_file(),
                sizeBytes=stat.st_size if child.is_file() else 0,
                modifiedAt=__import__("datetime").datetime.fromtimestamp(stat.st_mtime).isoformat(),
            ))
        return entries

    def readFile(self, slug: str, relPath: str, maxBytes: int = 1_000_000) -> dict:
        target = self._resolveCompanyPath(slug, relPath)
        if not target.exists():
            raise FileNotFoundError(f"Not found: {relPath!r}")
        if not target.is_file():
            raise ValueError(f"Not a file: {relPath!r}")
        size = target.stat().st_size
        if size > maxBytes:
            return {
                "relPath": relPath,
                "name": target.name,
                "sizeBytes": size,
                "truncated": True,
                "content": None,
                "reason": f"File too large ({size} bytes > {maxBytes} max).",
            }
        # Detect binary vs text
        try:
            content = target.read_text(encoding="utf-8")
            return {"relPath": relPath, "name": target.name, "sizeBytes": size, "content": content, "encoding": "utf-8"}
        except UnicodeDecodeError:
            return {
                "relPath": relPath,
                "name": target.name,
                "sizeBytes": size,
                "content": None,
                "encoding": "binary",
                "reason": "Binary file — use a download URL instead.",
            }

    def writeFile(self, slug: str, relPath: str, content: str, overwrite: bool = False) -> FileEntry:
        target = self._resolveCompanyPath(slug, relPath)
        if target.exists() and not overwrite:
            raise FileExistsError(f"Exists (overwrite=False): {relPath!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        stat = target.stat()
        self._index_upsert(slug, relPath, content)
        return FileEntry(
            relPath=relPath,
            name=target.name,
            isFile=True,
            sizeBytes=stat.st_size,
            modifiedAt=__import__("datetime").datetime.fromtimestamp(stat.st_mtime).isoformat(),
        )

    def moveFile(self, slug: str, fromRel: str, toRel: str) -> FileEntry:
        src = self._resolveCompanyPath(slug, fromRel)
        dst = self._resolveCompanyPath(slug, toRel)
        if not src.exists():
            raise FileNotFoundError(f"Not found: {fromRel!r}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        stat = dst.stat()
        self._index_delete(slug, fromRel)
        self._index_upsert(slug, toRel, None)
        return FileEntry(
            relPath=toRel, name=dst.name, isFile=dst.is_file(),
            sizeBytes=stat.st_size if dst.is_file() else 0,
            modifiedAt=__import__("datetime").datetime.fromtimestamp(stat.st_mtime).isoformat(),
        )

    def deleteFile(self, slug: str, relPath: str) -> bool:
        target = self._resolveCompanyPath(slug, relPath)
        if not target.exists():
            return False
        if target.is_file():
            target.unlink()
            self._index_delete(slug, relPath)
            return True
        # Refuse to delete folders directly via this API
        raise ValueError(f"Refusing to delete folder via deleteFile: {relPath!r}")

    # ── Full-text index hooks ──────────────────────────────────────────────

    def _index_for(self, slug: str):
        from .fulltext import FullTextIndex  # lazy import to keep core light
        return FullTextIndex(self.companyRoot(slug))

    def _index_upsert(self, slug: str, relPath: str, content: str | None) -> None:
        try:
            self._index_for(slug).upsert(relPath, content)
        except Exception:
            pass  # never fail a write because the index hiccuped

    def _index_delete(self, slug: str, relPath: str) -> None:
        try:
            self._index_for(slug).delete(relPath)
        except Exception:
            pass

    def searchContent(self, slug: str, query: str, max_results: int = 20) -> list[dict]:
        idx = self._index_for(slug)
        hits = idx.search(query, max_results)
        return [{"relPath": h.relPath, "snippet": h.snippet, "score": h.score} for h in hits]

    def reindexCompany(self, slug: str) -> int:
        root = self.companyRoot(slug)
        if not root.exists():
            return 0
        idx = self._index_for(slug)
        def walker():
            for child in root.rglob("*"):
                if not child.is_file():
                    continue
                rel = str(child.relative_to(root))
                if rel.startswith(".index/"):
                    continue
                yield rel, child
        return idx.reindex_all(walker())

    def searchFiles(self, slug: str, query: str, max_results: int = 50) -> list[FileEntry]:
        """Simple substring match on filename + path. Case insensitive."""
        root = self.companyRoot(slug)
        if not root.exists():
            return []
        q = query.lower()
        results: list[FileEntry] = []
        for child in root.rglob("*"):
            if not child.is_file():
                continue
            rel = str(child.relative_to(root))
            if rel.startswith(".index/"):
                continue
            if q in rel.lower():
                stat = child.stat()
                results.append(FileEntry(
                    relPath=rel,
                    name=child.name,
                    isFile=True,
                    sizeBytes=stat.st_size,
                    modifiedAt=__import__("datetime").datetime.fromtimestamp(stat.st_mtime).isoformat(),
                ))
                if len(results) >= max_results:
                    break
        return results

    def getFolderTree(self, slug: str, depth: int = 3, relPath: str = "") -> dict:
        """Recursive tree representation. depth=0 only top-level folder."""
        root = self._resolveCompanyPath(slug, relPath) if relPath else self.companyRoot(slug)
        if not root.exists():
            return {"name": "(empty)", "type": "dir", "children": []}
        return self._tree(root, depth, root)

    def _tree(self, current: Path, depth: int, anchor: Path) -> dict:
        node: dict = {
            "name": current.name or str(current),
            "type": "dir" if current.is_dir() else "file",
            "relPath": str(current.relative_to(self.companyRoot(slug=current.relative_to(anchor.parent).parts[1] if len(current.relative_to(anchor.parent).parts) > 1 else 'unknown'))) if False else str(current.relative_to(anchor)),
        }
        if current.is_dir() and depth > 0:
            children = []
            for child in sorted(current.iterdir()):
                if child.name == ".index":
                    continue
                if child.is_dir():
                    children.append(self._tree(child, depth - 1, anchor))
                else:
                    children.append({
                        "name": child.name,
                        "type": "file",
                        "relPath": str(child.relative_to(anchor)),
                        "sizeBytes": child.stat().st_size,
                    })
            node["children"] = children
        elif current.is_file():
            node["sizeBytes"] = current.stat().st_size
        return node

    # ── Convenience archive helpers (auto-organization) ────────────────────

    def archiveInvoice(self, slug: str, number: str, content: str, dateISO: str) -> FileEntry:
        """Stores an invoice under facturas/<year>/Q<n>/<number>.pdf-or-html."""
        year = dateISO[:4]
        month = int(dateISO[5:7])
        quarter = (month - 1) // 3 + 1
        rel = f"facturas/{year}/Q{quarter}/{number}.html"
        return self.writeFile(slug, rel, content, overwrite=True)

    def archivePayroll(self, slug: str, employeeId: str, period: str, content: str) -> FileEntry:
        """Stores a payroll under nominas/<year>/<month>/<employeeId>.html.
        period: 'YYYY-MM'."""
        year, month = period.split("-")
        rel = f"nominas/{year}/{int(month):02d}/{employeeId}.html"
        return self.writeFile(slug, rel, content, overwrite=True)

    def archiveComplianceDoc(self, slug: str, docType: str, content: str, version: str = "v1") -> FileEntry:
        rel = f"compliance/{docType}/{version}.html"
        return self.writeFile(slug, rel, content, overwrite=True)
