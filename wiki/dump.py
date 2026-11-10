"""Random access to Wikipedia ``pages-articles-multistream`` dumps.

The multistream dump is a concatenation of bz2 streams of ~100 pages each.
``build.py`` stores, for every article, the byte range of its stream in a
SQLite database (``wiki.db``) together with its lead paragraph indexed by
FTS5. Reading an article is then one seek plus one small decompression.
"""
from __future__ import annotations

import bz2
import html
import os
import random
import re
import sqlite3
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from .text import clean_wikitext, lead, sections, to_plain

_PAGE = re.compile(r"<page>(.*?)</page>", re.S)
_FIELD = {name: re.compile(rf"<{name}>(.*?)</{name}>", re.S) for name in ("title", "ns", "id")}
_REDIRECT = re.compile(r'<redirect title="([^"]*)"')
_TEXT = re.compile(r"<text\b[^>]*?(?:/>|>(.*?)</text>)", re.S)
_WORD = re.compile(r"\w+", re.U)
STOPWORDS = set("""a an and are as at be by for from has have how in is it its of on or that the this to was were what when where which who why with
o os as um uma uns umas de do da dos das em no na nos nas por para pelo pela com sem que qual quais quem como quando onde porque é e ou se ser foi era
me fale sobre explique conte diga quero saber me tell about explain does did do can could would please""".split())


def parse_pages(xml: str):
    """Yield ``(id, title, ns, redirect, wikitext)`` from a decompressed stream."""
    for match in _PAGE.finditer(xml):
        body = match.group(1)
        title = html.unescape(_FIELD["title"].search(body).group(1))
        ns = int(_FIELD["ns"].search(body).group(1))
        page_id = int(_FIELD["id"].search(body).group(1))
        redirect = _REDIRECT.search(body)
        text = _TEXT.search(body)
        yield page_id, title, ns, html.unescape(redirect.group(1)) if redirect else None, html.unescape((text.group(1) or "") if text else "")


def find_files(directory: Path) -> tuple[Path | None, Path | None]:
    dumps = sorted(directory.glob("*-pages-articles-multistream.xml.bz2"))
    indexes = sorted(directory.glob("*-pages-articles-multistream-index.txt.bz2"))
    return (dumps[-1] if dumps else None), (indexes[-1] if indexes else None)


def fts_query(text: str, max_terms: int = 12) -> str:
    """Turn free text into a safe FTS5 OR query (terms are quoted)."""
    seen, terms = set(), []
    for word in _WORD.findall(text.lower()):
        if len(word) < 2 or word in STOPWORDS or word in seen:
            continue
        seen.add(word)
        terms.append(f'"{word}"')
    return " OR ".join(terms[:max_terms])


def keywords(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) > 2 and w not in STOPWORDS}


@dataclass
class Article:
    id: int
    title: str
    redirected_from: str | None
    text: str          # cleaned text with link marks
    infobox: list[str]
    size: int
    url: str

    def payload(self) -> dict:
        return {"id": self.id, "title": self.title, "redirected_from": self.redirected_from, "url": self.url,
                "size": self.size, "infobox": self.infobox, "sections": sections(self.text)}


class WikiDump:
    """One dump directory (e.g. ``/mnt/sata/wikipedia/simplewiki``)."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.name = self.directory.name
        self.dump_file, self.index_file = find_files(self.directory)
        self.db_path = self.directory / "wiki.db"
        self._local = threading.local()
        self._blocks: OrderedDict[int, str] = OrderedDict()
        self._lock = threading.Lock()

    # -- state -----------------------------------------------------------
    @property
    def ready(self) -> bool:
        return self.dump_file is not None and self.db_path.exists()

    def _db(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    def meta(self) -> dict:
        return {row["key"]: row["value"] for row in self._db().execute("SELECT key, value FROM meta")}

    def status(self) -> dict:
        info = {"name": self.name, "ready": self.ready,
                "dump_file": self.dump_file.name if self.dump_file else None,
                "dump_bytes": self.dump_file.stat().st_size if self.dump_file else 0,
                "index_file": self.index_file.name if self.index_file else None}
        progress = self.directory / "build.progress"
        if progress.exists():
            info["building"] = progress.read_text().strip()
        if self.ready:
            info.update(self.meta())
            info["db_bytes"] = self.db_path.stat().st_size
        return info

    # -- reading ---------------------------------------------------------
    def _block(self, offset: int, length: int) -> str:
        with self._lock:
            if offset in self._blocks:
                self._blocks.move_to_end(offset)
                return self._blocks[offset]
        with open(self.dump_file, "rb") as handle:
            handle.seek(offset)
            raw = handle.read(length) if length > 0 else handle.read()
        xml = bz2.decompress(raw).decode("utf-8", "replace")
        with self._lock:
            self._blocks[offset] = xml
            while len(self._blocks) > 24:
                self._blocks.popitem(last=False)
        return xml

    def _row_by_title(self, title: str):
        db = self._db()
        row = db.execute("SELECT * FROM pages WHERE title = ?", (title,)).fetchone()
        if row is None:
            row = db.execute("SELECT * FROM pages WHERE title = ? COLLATE NOCASE", (title,)).fetchone()
        return row

    def wikitext(self, row) -> str:
        for page_id, _, _, _, text in parse_pages(self._block(row["offset"], row["length"])):
            if page_id == row["id"]:
                return text
        raise LookupError(f"Página {row['id']} não encontrada no bloco {row['offset']}.")

    def resolve(self, title: str):
        row, origin = self._row_by_title(title.replace("_", " ").strip()), None
        for _ in range(3):
            if row is None or not row["redirect"]:
                break
            origin = origin or row["title"]
            row = self._row_by_title(row["redirect"].split("#")[0])
        return row, origin

    def article(self, title: str) -> Article | None:
        row, origin = self.resolve(title)
        if row is None or row["redirect"]:
            return None
        raw = self.wikitext(row)
        infobox: list[str] = []
        text = clean_wikitext(raw, infobox)
        base = self.meta().get("base_url", "")
        return Article(row["id"], row["title"], origin, text, infobox[:20], len(raw),
                       f"{base}{row['title'].replace(' ', '_')}" if base else "")

    # -- searching -------------------------------------------------------
    def search(self, query: str, limit: int = 10) -> list[dict]:
        match = fts_query(query)
        if not match:
            return []
        rows = self._db().execute(
            """SELECT p.id, p.title, p.redirect, p.lead, p.size, bm25(pages_fts, 8.0, 1.0) AS score
               FROM pages_fts JOIN pages p ON p.id = pages_fts.rowid
               WHERE pages_fts MATCH ? ORDER BY score LIMIT ?""", (match, limit * 4)).fetchall()
        exact = self.resolve(query)[0]
        results, seen = [], set()
        candidates = ([dict(exact) | {"score": -1e9, "exact": True}] if exact is not None and not exact["redirect"] else []) + [dict(r) for r in rows]
        for row in candidates:
            via = None
            if row["redirect"]:
                target, _ = self.resolve(row["redirect"])
                if target is None or target["redirect"]:
                    continue
                via, row = row["title"], dict(target) | {"score": row["score"]}
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            results.append({"title": row["title"], "lead": row["lead"], "size": row["size"], "via": via,
                            "exact": bool(row.get("exact"))})
            if len(results) >= limit:
                break
        return results

    def entities(self, question: str, limit: int = 2) -> list[str]:
        """Article titles named in the question (longest capitalized n-grams first).

        Proper nouns are usually the same across languages, so this finds
        "Raspberry Pi" or "Brasil" (a redirect) without asking the model.
        """
        words = re.findall(r"[\w'’-]+", question)
        found, used = [], set()
        for size in (4, 3, 2, 1):
            for start in range(len(words) - size + 1):
                span = set(range(start, start + size))
                gram = words[start:start + size]
                if span & used or not any(w[:1].isupper() for w in gram) or all(w.lower() in STOPWORDS for w in gram):
                    continue
                if size == 1 and (len(gram[0]) < 3 or gram[0].lower() in STOPWORDS):
                    continue
                row, _ = self.resolve(" ".join(gram))
                if row is not None and not row["redirect"] and row["title"] not in found:
                    found.append(row["title"])
                    used |= span
                    if len(found) >= limit:
                        return found
        return found

    def suggest(self, prefix: str, limit: int = 8) -> list[str]:
        prefix = prefix.strip()
        if not prefix:
            return []
        prefix = prefix[0].upper() + prefix[1:]  # Wikipedia titles start uppercase.
        rows = self._db().execute(
            "SELECT title FROM pages WHERE title >= ? AND title < ? ORDER BY redirect IS NOT NULL, length(title), title LIMIT ?",
            (prefix, prefix + "\U0010ffff", limit)).fetchall()
        return [r["title"] for r in rows]

    def random(self) -> str | None:
        db = self._db()
        top = db.execute("SELECT max(id) FROM pages").fetchone()[0] or 0
        for _ in range(8):
            row = db.execute("SELECT title FROM pages WHERE id >= ? AND redirect IS NULL AND size > 1500 ORDER BY id LIMIT 1",
                             (random.randint(0, top),)).fetchone()
            if row:
                return row["title"]
        return None


class WikiLibrary:
    """All dump directories under ``WIKI_DIR``."""

    def __init__(self, root: str | os.PathLike | None = None):
        self.root = Path(root or os.environ.get("WIKI_DIR", "/mnt/sata/wikipedia"))
        self._dumps: dict[str, WikiDump] = {}

    def dumps(self) -> list[WikiDump]:
        if not self.root.is_dir():
            return []
        found = []
        for directory in sorted(p for p in self.root.iterdir() if p.is_dir()):
            if find_files(directory)[0] is None and not (directory / "wiki.db").exists():
                continue
            dump = self._dumps.get(directory.name)
            if dump is None or (not dump.ready and (directory / "wiki.db").exists()):
                dump = self._dumps[directory.name] = WikiDump(directory)
            found.append(dump)
        return found

    def get(self, name: str | None) -> WikiDump | None:
        ready = [d for d in self.dumps() if d.ready]
        if name:
            return next((d for d in ready if d.name == name), None)
        return ready[0] if ready else None


__all__ = ["Article", "WikiDump", "WikiLibrary", "fts_query", "keywords", "lead", "parse_pages", "to_plain"]
