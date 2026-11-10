"""Retrieval by context management: no embeddings, just FTS + a character budget.

1. the model rewrites the question as a short English search query;
2. FTS5 (BM25 over title + lead) picks the articles;
3. each article is read from the dump and its lead, infobox and the
   paragraphs that share the most keywords with the question are packed
   into a fixed budget, so the small model always gets a short prompt;
4. the answer streams from Ollama, citing the numbered excerpts.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Iterator

from .dump import WikiDump, keywords
from .text import sections, to_plain

CONTEXT_CHARS = int(os.environ.get("WIKI_CONTEXT_CHARS", "3500"))
HISTORY_CHARS = int(os.environ.get("WIKI_HISTORY_CHARS", "1500"))
SHARES = (0.5, 0.3, 0.2)  # budget per retrieved article, best match first

SYSTEM = (
    "You are a concise assistant that answers using numbered Wikipedia excerpts. "
    "Always answer in the same language the user writes in (Brazilian Portuguese if the user writes Portuguese). "
    "Use only facts from the excerpts, cite them like [1] or [2], and if the excerpts do not contain the answer, "
    "say so plainly instead of guessing. Be brief: at most 5 sentences unless asked for detail."
)
SYSTEM_PLAIN = ("You are a concise, friendly assistant running locally on a Raspberry Pi. "
                "Answer in the same language the user writes in (Brazilian Portuguese if the user writes Portuguese).")
REWRITE = (
    "You write search queries for an English Wikipedia index. Do NOT answer the question. "
    "Reply with 2 to 6 English keywords naming the subject of the question, nothing else.\n"
    "Examples:\nQuem pintou a Mona Lisa? -> Mona Lisa painting\n"
    "Qual a capital da Austrália? -> Australia capital city\n"
    "How does photosynthesis work? -> photosynthesis"
)
_PT = set("é não são também qual quais quem quando onde como porque por que você sobre está foi ser uma um isso essa esse da dos das na nos nas".split())


SYSTEM_PT = (
    "Você é um assistente conciso que responde em português do Brasil usando trechos numerados da Wikipédia "
    "(os trechos estão em inglês: traduza). Use só fatos dos trechos e cite-os como [1] ou [2]. "
    "Se os trechos não tiverem a resposta, diga isso claramente em vez de inventar. Não escreva introduções. "
    "Seja breve: no máximo 5 frases, a menos que peçam detalhes."
)
SYSTEM_PLAIN_PT = "Você é um assistente conciso e simpático rodando num Raspberry Pi. Responda sempre em português do Brasil."


_EN = set("the what which who whom whose how why when where is are was were does did do can could would should tell explain about of".split())


def is_portuguese(question: str) -> bool:
    """The interface is Portuguese: assume Portuguese unless the question is clearly English."""
    words = set(re.findall(r"\w+", question.lower()))
    if words & _PT or re.search(r"[ãõçâêôáéíóú]", question.lower()):
        return True
    return len(words & _EN) < 2 and not words & {"the", "what", "how", "why", "who"}


def language_hint(question: str) -> str:
    if is_portuguese(question):
        return "Responda em português do Brasil."
    return "Answer in the same language as the question."


class Ollama:
    def __init__(self, url: str | None = None, model: str | None = None):
        self.url = (url or os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.model = model or os.environ.get("WIKI_MODEL", "gemma3:1b")
        self.options = {"num_ctx": int(os.environ.get("WIKI_NUM_CTX", "4096")), "temperature": 0.3,
                        "repeat_penalty": 1.15, "repeat_last_n": 256, "num_predict": 450}

    def _post(self, path: str, body: dict, timeout: float = 600):
        request = urllib.request.Request(f"{self.url}{path}", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
        return urllib.request.urlopen(request, timeout=timeout)

    def models(self) -> list[str]:
        with urllib.request.urlopen(f"{self.url}/api/tags", timeout=5) as response:
            return [m["name"] for m in json.load(response).get("models", [])]

    def complete(self, messages: list[dict], **options) -> str:
        body = {"model": self.model, "messages": messages, "stream": False, "options": self.options | options}
        with self._post("/api/chat", body) as response:
            return json.load(response)["message"]["content"]

    def stream(self, messages: list[dict]) -> Iterator[dict]:
        body = {"model": self.model, "messages": messages, "stream": True, "options": self.options}
        with self._post("/api/chat", body) as response:
            for line in response:
                if line.strip():
                    yield json.loads(line)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def passages(article, terms: set[str], budget: int) -> str:
    """Lead first, then the best keyword-matching paragraphs (kept in reading order)."""
    chunks = []
    for section in sections(article.text):
        for paragraph in section["paragraphs"]:
            plain = re.sub(r"\s+", " ", to_plain(paragraph)).strip()
            if len(plain) > 30:
                chunks.append((section["title"], plain))
    if not chunks:
        return ""
    picked, used = [0], len(chunks[0][1])
    words = [set(re.findall(r"\w+", f"{t} {p}".lower())) for t, p in chunks]
    ranked = sorted(range(1, len(chunks)), key=lambda i: (-len(terms & words[i]), i))
    for i in ranked:
        if not terms & words[i] or used >= budget:
            break
        picked.append(i)
        used += len(chunks[i][1])
    lines = []
    facts = [f for f in article.infobox if terms & set(re.findall(r"\w+", f.lower()))] or article.infobox[:6]
    if facts:
        lines.append("Facts: " + "; ".join(facts[:8]))
    for i in sorted(picked):
        title, text = chunks[i]
        lines.append(f"({title}) {text}" if title else text)
    return _clip("\n".join(lines), budget)


def trim_history(history: list[dict], limit: int = HISTORY_CHARS) -> list[dict]:
    """Newest turns first until the budget runs out; long answers are clipped."""
    kept, used = [], 0
    for message in reversed(history[-10:]):
        if message.get("role") not in ("user", "assistant") or not isinstance(message.get("content"), str):
            continue
        content = _clip(message["content"], 500 if message["role"] == "assistant" else 300)
        if used + len(content) > limit:
            break
        kept.append({"role": message["role"], "content": content})
        used += len(content)
    kept.reverse()
    while kept and kept[0]["role"] != "user":
        kept.pop(0)
    return kept


def search_query(llm: Ollama, question: str, history: list[dict]) -> str:
    previous = next((m["content"] for m in reversed(history) if m.get("role") == "user"), "")
    prompt = f"Previous question: {_clip(previous, 200)}\nQuestion: {question}" if previous else question
    try:
        text = llm.complete([{"role": "system", "content": REWRITE}, {"role": "user", "content": prompt}],
                            temperature=0, num_predict=24)
    except (OSError, urllib.error.URLError, KeyError, ValueError):
        return question
    text = text.strip().splitlines()[0] if text.strip() else question
    text = text.split("->")[-1].strip(" \"'`*.").removeprefix("Query:").strip()
    return _clip(text, 100) or question


def answer(llm: Ollama, dump: WikiDump | None, question: str, history: list[dict],
           article_title: str | None = None, use_wiki: bool = True) -> Iterator[dict]:
    history = trim_history(history)
    sources, context = [], []
    if use_wiki and dump is not None:
        if article_title:
            found = dump.article(article_title)
            articles = [found] if found else []
            shares = (1.0,)
            # English keywords pick the right paragraphs of the pinned article.
            yield {"type": "status", "label": f"Procurando a resposta em “{article_title}”"}
            query = search_query(llm, question, history)
        else:
            named = dump.entities(question)
            if named:
                # The question names its subject: no rewriting round-trip needed.
                query = " ".join(named)
                yield {"type": "status", "label": f"Encontrei “{' · '.join(named)}” no índice", "query": query}
                titles, shares = named, (1.0,) if len(named) == 1 else (0.55, 0.45)
            else:
                yield {"type": "status", "label": "Entendendo a pergunta"}
                query = search_query(llm, question, history)
                yield {"type": "status", "label": f"Buscando “{query}” na Wikipédia", "query": query}
                hits = dump.search(query, 5)
                if len(hits) < 3:
                    seen = {h["title"] for h in hits}
                    hits += [h for h in dump.search(question, 5) if h["title"] not in seen]
                # An exact title match is the subject: give it the whole budget.
                shares = (1.0,) if hits and hits[0].get("exact") else SHARES
                titles = [h["title"] for h in hits]
            articles = [a for a in (dump.article(t) for t in titles[:len(shares)]) if a]
        terms = keywords(question) | keywords(" ".join(a.title for a in articles[:1]))
        terms |= keywords(query)
        yield {"type": "status", "label": "Lendo os artigos"}
        for n, (item, share) in enumerate(zip(articles, shares), 1):
            excerpt = passages(item, terms, int(CONTEXT_CHARS * share))
            if excerpt:
                context.append(f"[{n}] {item.title}\n{excerpt}")
                sources.append({"n": n, "title": item.title, "url": item.url, "via": item.redirected_from, "chars": len(excerpt)})
        yield {"type": "sources", "sources": sources}

    portuguese = is_portuguese(question)
    if context and portuguese:
        user = ("Trechos da Wikipédia (em inglês):\n\n" + "\n\n".join(context) +
                f"\n\nPergunta: {question}\n\nResponda só a essa pergunta, em até 5 frases, em português do Brasil, "
                "citando os trechos como [1]. Não traduza nem resuma os trechos inteiros.")
        system = SYSTEM_PT
    elif context:
        user = ("Wikipedia excerpts:\n\n" + "\n\n".join(context) +
                f"\n\nQuestion: {question}\n\nAnswer only this question in at most 5 sentences. "
                f"{language_hint(question)} Cite the excerpts like [1].")
        system = SYSTEM
    else:
        user, system = question, SYSTEM_PLAIN_PT if portuguese else SYSTEM_PLAIN
        if use_wiki:
            system += (" Nenhum trecho da Wikipédia foi encontrado: avise isso antes de responder com o que você sabe."
                       if portuguese else " No Wikipedia excerpt was found for this question; say so before answering from general knowledge.")
    messages = [{"role": "system", "content": system}, *history, {"role": "user", "content": user}]
    yield {"type": "status", "label": "Gerando resposta"}
    final = {}
    for chunk in llm.stream(messages):
        delta = chunk.get("message", {}).get("content", "")
        if delta:
            yield {"type": "delta", "text": delta}
        if chunk.get("done"):
            final = chunk
    stats = {"model": llm.model, "prompt_chars": len(system) + len(user) + sum(len(m["content"]) for m in history),
             "prompt_tokens": final.get("prompt_eval_count"), "tokens": final.get("eval_count"),
             "seconds": round((final.get("total_duration") or 0) / 1e9, 1)}
    if final.get("eval_duration"):
        stats["tokens_per_second"] = round(final["eval_count"] / final["eval_duration"] * 1e9, 1)
    yield {"type": "done", "stats": stats}
