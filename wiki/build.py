"""Build ``wiki.db`` (offsets + lead FTS) for a multistream dump directory.

    python -m wiki.build /mnt/sata/wikipedia/simplewiki [--workers 3]

The dump is only read, never extracted. Work happens in ``wiki.db.tmp``,
which replaces ``wiki.db`` at the end, so the app keeps serving the old index.
"""
from __future__ import annotations

import argparse
import bz2
import os
import re
import sqlite3
import sys
import time
from multiprocessing import Pool
from pathlib import Path

from .dump import find_files, parse_pages
from .text import lead

_DUMP: Path | None = None


def _init(dump: str) -> None:
    global _DUMP
    _DUMP = Path(dump)


def _block(span: tuple[int, int]):
    offset, length = span
    with open(_DUMP, "rb") as handle:
        handle.seek(offset)
        xml = bz2.decompress(handle.read(length)).decode("utf-8", "replace")
    rows = []
    for page_id, title, ns, redirect, text in parse_pages(xml):
        if ns != 0:
            continue
        try:
            summary = "" if redirect else lead(text)
        except Exception:  # One odd page must not abort a multi-hour build.
            summary = ""
        rows.append((page_id, title, offset, length, redirect, summary, len(text)))
    return rows


def read_index(index_file: Path) -> list[int]:
    offsets = set()
    with bz2.open(index_file, "rt", encoding="utf-8") as handle:
        for line in handle:
            offset, _, _ = line.partition(":")
            if offset:
                offsets.add(int(offset))
    return sorted(offsets)


def siteinfo(dump_file: Path, first_offset: int) -> dict:
    with open(dump_file, "rb") as handle:
        header = bz2.decompress(handle.read(first_offset)).decode("utf-8", "replace")
    info = {}
    for key in ("sitename", "dbname", "base", "generator"):
        match = re.search(rf"<{key}>(.*?)</{key}>", header)
        if match:
            info[key] = match.group(1)
    if "base" in info:
        info["base_url"] = info["base"].rsplit("/", 1)[0] + "/"
    return info


def build(directory: Path, workers: int = 3) -> Path:
    dump_file, index_file = find_files(directory)
    if not dump_file or not index_file:
        raise SystemExit(f"Dump multistream ou índice não encontrado em {directory}")
    started = time.time()
    progress = directory / "build.progress"
    progress.write_text("lendo índice")
    offsets = read_index(index_file)
    size = dump_file.stat().st_size
    spans = [(start, (offsets[i + 1] if i + 1 < len(offsets) else size) - start) for i, start in enumerate(offsets)]

    tmp = directory / "wiki.db.tmp"
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript("""
        PRAGMA journal_mode = OFF; PRAGMA synchronous = OFF; PRAGMA page_size = 8192;
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE pages (id INTEGER PRIMARY KEY, title TEXT NOT NULL, offset INTEGER NOT NULL, length INTEGER NOT NULL,
                            redirect TEXT, lead TEXT NOT NULL DEFAULT '', size INTEGER NOT NULL DEFAULT 0);
        CREATE VIRTUAL TABLE pages_fts USING fts5(title, lead, content='pages', content_rowid='id',
                                                 tokenize='unicode61 remove_diacritics 2');
    """)
    articles = redirects = 0
    with Pool(workers, initializer=_init, initargs=(str(dump_file),)) as pool:
        for done, rows in enumerate(pool.imap(_block, spans, chunksize=16), 1):
            db.executemany("INSERT OR REPLACE INTO pages VALUES (?,?,?,?,?,?,?)", rows)
            redirects += sum(1 for r in rows if r[4])
            articles += sum(1 for r in rows if not r[4])
            if done % 500 == 0 or done == len(spans):
                progress.write_text(f"{done}/{len(spans)} blocos · {articles} artigos")
                print(f"\r{done}/{len(spans)} blocos · {articles} artigos · {redirects} redirecionamentos", end="", file=sys.stderr)
    print(file=sys.stderr)
    progress.write_text("indexando texto (FTS5)")
    db.execute("INSERT INTO pages_fts(pages_fts) VALUES ('rebuild')")
    db.execute("CREATE INDEX pages_title ON pages(title)")
    db.execute("CREATE INDEX pages_title_nocase ON pages(title COLLATE NOCASE)")
    info = siteinfo(dump_file, offsets[0]) if offsets else {}
    stat = dump_file.stat()
    info |= {"articles": articles, "redirects": redirects, "blocks": len(spans), "dump_file": dump_file.name,
             "dump_mtime": int(stat.st_mtime), "built_at": int(time.time()), "build_seconds": int(time.time() - started)}
    db.executemany("INSERT INTO meta VALUES (?, ?)", [(k, str(v)) for k, v in info.items()])
    db.commit()
    db.execute("INSERT INTO pages_fts(pages_fts) VALUES ('optimize')")
    db.commit()
    db.close()
    os.replace(tmp, directory / "wiki.db")
    progress.unlink(missing_ok=True)
    print(f"Pronto: {articles} artigos em {info['build_seconds']}s", file=sys.stderr)
    return directory / "wiki.db"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = parser.parse_args(argv)
    try:
        build(args.directory, args.workers)
    finally:
        (args.directory / "build.progress").unlink(missing_ok=True)
        (args.directory / "wiki.db.tmp").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
