"""Per-company full-text index over the VDR using SQLite FTS5.

Indexa contenido extraído de TXT/MD/HTML/PDF dentro del VDR de una
empresa. La BBDD vive en `<root>/companies/<slug>/.index/fts.db` y se
actualiza de forma incremental: cada writeFile/archive* llama a
`FullTextIndex.upsert(...)` y los borrados a `delete(...)`.

Diseno deliberado:
- SQLite FTS5 (in-stdlib, sin servidor) — más simple que Whoosh/embeddings,
  suficiente para gestorías pequeñas (cientos a decenas de miles de docs).
- Parseo robusto pero best-effort: si pypdf falla con un PDF protegido,
  guardamos texto vacío (la entrada sigue indexable por nombre).
- `reindex_company()` recorre el VDR completo — útil tras migraciones o si
  el índice se corrompe.
"""
from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import Iterable
from dataclasses import dataclass


@dataclass
class FullTextHit:
    relPath: str
    snippet: str
    score: float


INDEXABLE_TEXT = {".txt", ".md", ".csv", ".json", ".log"}
INDEXABLE_HTML = {".html", ".htm"}
INDEXABLE_PDF = {".pdf"}
MAX_INDEX_BYTES = 5_000_000  # 5MB cap por archivo


def _extract_text(abs_path: Path) -> str:
    suf = abs_path.suffix.lower()
    try:
        if suf in INDEXABLE_TEXT:
            data = abs_path.read_bytes()[:MAX_INDEX_BYTES]
            return data.decode("utf-8", errors="ignore")
        if suf in INDEXABLE_HTML:
            data = abs_path.read_bytes()[:MAX_INDEX_BYTES]
            from bs4 import BeautifulSoup  # lazy import
            soup = BeautifulSoup(data, "html.parser")
            return soup.get_text(separator=" ", strip=True)
        if suf in INDEXABLE_PDF:
            from pypdf import PdfReader  # lazy import
            reader = PdfReader(str(abs_path))
            parts: list[str] = []
            for page in reader.pages[:200]:  # cap a 200 paginas
                try:
                    parts.append(page.extract_text() or "")
                except Exception:
                    continue
            return "\n".join(parts)[:MAX_INDEX_BYTES]
    except Exception:
        return ""
    return ""


def _is_indexable(rel_path: str) -> bool:
    p = Path(rel_path)
    suf = p.suffix.lower()
    return suf in (INDEXABLE_TEXT | INDEXABLE_HTML | INDEXABLE_PDF)


class FullTextIndex:
    """SQLite FTS5 index for one company's VDR."""

    def __init__(self, company_root: Path):
        self.company_root = company_root
        self.index_dir = company_root / ".index"
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.index_dir / "fts.db"
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5(
                    rel_path UNINDEXED,
                    content,
                    tokenize='unicode61 remove_diacritics 2'
                );
                """
            )

    def upsert(self, rel_path: str, content: str | None = None) -> bool:
        """Index a file. Pass content=None to extract from disk.

        Returns True if indexed (file is indexable), False if skipped.
        """
        if not _is_indexable(rel_path):
            return False
        if content is None:
            abs_path = self.company_root / rel_path
            if not abs_path.exists() or not abs_path.is_file():
                return False
            content = _extract_text(abs_path)
        if not content:
            content = ""
        with self._connect() as conn:
            conn.execute("DELETE FROM docs WHERE rel_path = ?", (rel_path,))
            conn.execute("INSERT INTO docs (rel_path, content) VALUES (?, ?)", (rel_path, content))
        return True

    def delete(self, rel_path: str) -> int:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM docs WHERE rel_path = ?", (rel_path,))
            return cur.rowcount

    def search(self, query: str, max_results: int = 20) -> list[FullTextHit]:
        if not query.strip():
            return []
        # FTS5 espera comillas si hay espacios; envolver tokens en frases es robusto
        safe_query = self._sanitize(query)
        sql = (
            "SELECT rel_path, snippet(docs, 1, '[', ']', '...', 12) AS snippet, "
            "       bm25(docs) AS score "
            "FROM docs WHERE docs MATCH ? ORDER BY score LIMIT ?"
        )
        with self._connect() as conn:
            try:
                rows = conn.execute(sql, (safe_query, max_results)).fetchall()
            except sqlite3.OperationalError:
                return []
        return [FullTextHit(relPath=r["rel_path"], snippet=r["snippet"], score=float(r["score"])) for r in rows]

    @staticmethod
    def _sanitize(query: str) -> str:
        """FTS5 sintaxis: agrupamos tokens en una frase para evitar inyeccion de operadores."""
        cleaned = "".join(c if c.isalnum() or c.isspace() or c in "-_" else " " for c in query)
        tokens = [t for t in cleaned.split() if t]
        if not tokens:
            return '""'
        return " ".join(f'"{t}"' for t in tokens)

    def reindex_all(self, walker: Iterable[tuple[str, Path]]) -> int:
        """Reindex a whole company. `walker` yields (rel_path, abs_path) pairs."""
        with self._connect() as conn:
            conn.execute("DELETE FROM docs")
        count = 0
        for rel_path, abs_path in walker:
            if not _is_indexable(rel_path):
                continue
            content = _extract_text(abs_path)
            with self._connect() as conn:
                conn.execute("INSERT INTO docs (rel_path, content) VALUES (?, ?)", (rel_path, content))
            count += 1
        return count

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM docs").fetchone()
            return int(row["n"])
