"""Small, dependency-free wikitext cleaner.

It does not try to be a full MediaWiki parser: it keeps prose, headings,
lists, internal links and the short fields of infoboxes, which is what the
explorer shows and what the local model needs as context.
"""
from __future__ import annotations

import html
import re

LINK_OPEN, LINK_SEP, LINK_CLOSE = "⟦", "❘", "⟧"  # ⟦target❘label⟧
_DROP_LINK_NS = ("file:", "image:", "category:", "media:", "wikt:", "wiktionary:", "commons:")
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_REF = re.compile(r"<ref[^>/]*?/>|<ref[^>]*?>.*?</ref>", re.S | re.I)
_DROP_TAGS = re.compile(r"<(gallery|math|score|timeline|syntaxhighlight|source|imagemap|templatedata)[^>]*>.*?</\1>", re.S | re.I)
_TAG = re.compile(r"</?[a-zA-Z][^>]*?/?>")
_EXTERNAL = re.compile(r"\[(?:https?:)?//[^\s\]]+(?:\s+([^\]]*))?\]")
_BOLD_ITALIC = re.compile(r"'{2,5}")
_HEADING = re.compile(r"^(={2,6})\s*(.*?)\s*\1\s*$")
_LINK_MARK = re.compile(f"{LINK_OPEN}([^{LINK_SEP}{LINK_CLOSE}]*){LINK_SEP}([^{LINK_CLOSE}]*){LINK_CLOSE}")
_INLINE_TEMPLATES = {"lang": -1, "nowrap": 1, "small": 1, "nobr": 1, "transl": -1, "nihongo": 1, "w": 1}


def _balanced(text: str, opener: str, closer: str, start: int) -> int:
    """Return the index just after the closer matching the opener at ``start`` (or len)."""
    depth, i, size = 0, start, len(text)
    while i < size:
        if text.startswith(opener, i):
            depth += 1
            i += len(opener)
        elif text.startswith(closer, i):
            depth -= 1
            i += len(closer)
            if depth == 0:
                return i
        else:
            i += 1
    return size


def _split_top(body: str) -> list[str]:
    """Split template/link bodies on ``|`` outside nested braces and brackets."""
    parts, depth, current = [], 0, []
    i = 0
    while i < len(body):
        pair = body[i:i + 2]
        if pair in ("{{", "[["):
            depth += 1
            current.append(pair)
            i += 2
            continue
        if pair in ("}}", "]]"):
            depth = max(0, depth - 1)
            current.append(pair)
            i += 2
            continue
        if body[i] == "|" and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(body[i])
        i += 1
    parts.append("".join(current))
    return parts


def _template(body: str, infobox: list[str] | None) -> str:
    parts = _split_top(body)
    name = parts[0].strip().lower().replace("_", " ")
    if name.startswith("infobox") and infobox is not None:
        for part in parts[1:]:
            key, sep, value = part.partition("=")
            value = re.sub(r"\s+", " ", to_plain(clean_wikitext(value))).strip() if sep else ""
            key = key.strip().replace("_", " ")
            skip = ("image", "caption", "logo", "map", "alt", "signature", "background", "bgcolo", "colo", "apsis", "width", "size", "module")
            if value and key and len(value) <= 160 and not value.startswith("#") and not key.lower().startswith(skip):
                infobox.append(f"{key}: {value}")
        return ""
    if name == "convert" and len(parts) >= 3:
        return _strip_structures(f"{parts[1].strip()} {parts[2].strip()}", None)
    if name in _INLINE_TEMPLATES and len(parts) > 1:
        args = [p for p in parts[1:] if "=" not in p]
        if args:
            index = _INLINE_TEMPLATES[name]
            return _strip_structures(args[index] if -len(args) <= index < len(args) else args[-1], None)
    return ""


def _strip_structures(text: str, infobox: list[str] | None) -> str:
    out, i, size = [], 0, len(text)
    while i < size:
        if text.startswith("{{", i):
            end = _balanced(text, "{{", "}}", i)
            out.append(_template(text[i + 2:end - 2], infobox))
            i = end
        elif text.startswith("{|", i):
            i = _balanced(text, "{|", "|}", i)
        elif text.startswith("[[", i):
            end = _balanced(text, "[[", "]]", i)
            inner = text[i + 2:end - 2]
            target, _, label = inner.partition("|")
            lowered = target.strip().lower().lstrip(":")
            if not lowered.startswith(_DROP_LINK_NS) and "\n" not in target:
                target = target.split("#")[0].strip()
                label = _strip_structures(label, None) if label else target
                label = label.rsplit("|", 1)[-1].strip() or target
                out.append(f"{LINK_OPEN}{target}{LINK_SEP}{label}{LINK_CLOSE}" if target else label)
            i = end
        else:
            nxt = min((p for p in (text.find("{{", i), text.find("{|", i), text.find("[[", i)) if p != -1), default=size)
            out.append(text[i:nxt])
            i = nxt
    return "".join(out)


def clean_wikitext(text: str, infobox: list[str] | None = None) -> str:
    """Convert wikitext into readable text, keeping ``== headings ==`` and link marks."""
    text = html.unescape(text)
    text = _COMMENT.sub("", text)
    text = _REF.sub("", text)
    text = _DROP_TAGS.sub("", text)
    text = _strip_structures(text, infobox)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = _TAG.sub("", text)
    text = _EXTERNAL.sub(lambda m: m.group(1) or "", text)
    text = _BOLD_ITALIC.sub("", text)
    text = html.unescape(text).replace(" ", " ")
    lines = []
    for line in text.splitlines():
        line = line.rstrip()
        if line.startswith(("__", "|", "!")) or line.lower().startswith(("#redirect", "thumb|")):
            continue
        stripped = line.lstrip("*#:; ")
        if line[:1] in "*#" and stripped:
            line = f"- {stripped}"
        elif line[:1] in ":;":
            line = stripped
        lines.append(re.sub(r"[ \t]{2,}", " ", line))
    text = "\n".join(lines)
    text = re.sub(r"\(\s*[,;]?\s*\)", "", text)
    text = re.sub(r" +([,.;:])", r"\1", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def to_plain(text: str) -> str:
    """Drop link marks, keeping their labels."""
    return _LINK_MARK.sub(lambda m: m.group(2), text)


def sections(text: str) -> list[dict]:
    """Split cleaned text into ``[{title, level, paragraphs}]``; the lead has title ''."""
    result = [{"title": "", "level": 1, "paragraphs": []}]
    for block in re.split(r"\n\s*\n|\n(?==)", text):
        block = block.strip()
        if not block:
            continue
        first, _, rest = block.partition("\n")
        heading = _HEADING.match(first)
        if heading:
            result.append({"title": to_plain(heading.group(2)), "level": len(heading.group(1)), "paragraphs": []})
            block = rest.strip()
            if not block:
                continue
        result[-1]["paragraphs"].append(block)
    # Drop reference-like tail sections and empty sections.
    tail = {"references", "notes", "sources", "external links", "further reading", "see also", "bibliography", "footnotes", "other websites", "related pages"}
    return [s for s in result if s["paragraphs"] and s["title"].lower() not in tail]


def lead(text: str, limit: int = 600) -> str:
    """First prose paragraph(s) of an article, as plain text."""
    body = re.split(r"\n=={1,5}[^=]", "\n" + text, maxsplit=1)[0]
    plain = to_plain(clean_wikitext(body))
    paragraphs = [p.strip() for p in plain.split("\n\n") if len(p.strip()) > 40 and not p.strip().startswith("- ")]
    out = " ".join(paragraphs) if paragraphs else plain
    out = re.sub(r"\s+", " ", out).strip()
    return out if len(out) <= limit else out[:limit].rsplit(" ", 1)[0] + "…"
