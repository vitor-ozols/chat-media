"""Flask routes for the local Wikipedia explorer and the Gemma chat."""
from __future__ import annotations

import json
import threading
import urllib.error

from flask import Response, jsonify, request, stream_with_context

from .dump import WikiLibrary
from .rag import Ollama, answer


def register_wiki(web, library: WikiLibrary | None = None, llm: Ollama | None = None) -> None:
    library = library or WikiLibrary()
    llm = llm or Ollama()
    # Ollama runs one request at a time on the Pi; queue here so the UI can say so.
    busy = threading.BoundedSemaphore(2)

    def dump_or_404():
        dump = library.get(request.args.get("dump"))
        if dump is None:
            return None, (jsonify(error="Nenhum dump da Wikipédia indexado. Veja o README (wiki.build)."), 404)
        return dump, None

    @web.get("/api/wiki/status")
    def wiki_status():
        try:
            models, model_error = llm.models(), None
        except (OSError, urllib.error.URLError, ValueError) as exc:
            models, model_error = [], f"Ollama indisponível em {llm.url}: {exc}"
        return jsonify(root=str(library.root), dumps=[d.status() for d in library.dumps()], model=llm.model,
                       models=models, model_ready=llm.model in models, model_error=model_error)

    @web.get("/api/wiki/search")
    def wiki_search():
        dump, error = dump_or_404()
        if error:
            return error
        query = request.args.get("q", "").strip()[:200]
        return jsonify(results=dump.search(query, min(30, request.args.get("limit", 15, type=int))) if query else [])

    @web.get("/api/wiki/suggest")
    def wiki_suggest():
        dump, error = dump_or_404()
        if error:
            return error
        return jsonify(titles=dump.suggest(request.args.get("q", "")[:200]))

    @web.get("/api/wiki/random")
    def wiki_random():
        dump, error = dump_or_404()
        if error:
            return error
        return jsonify(title=dump.random())

    @web.get("/api/wiki/article")
    def wiki_article():
        dump, error = dump_or_404()
        if error:
            return error
        title = request.args.get("title", "").strip()[:300]
        found = dump.article(title) if title else None
        if found is None:
            return jsonify(error=f"Artigo “{title}” não encontrado neste dump."), 404
        payload = found.payload()
        if request.args.get("raw") == "1":
            row, _ = dump.resolve(found.title)
            payload["wikitext"] = dump.wikitext(row)
        return jsonify(payload)

    @web.post("/api/wiki/chat")
    def wiki_chat():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify(error="Envie um objeto JSON."), 400
        question = body.get("question")
        history = body.get("history") or []
        article = body.get("article")
        if not isinstance(question, str) or not question.strip() or len(question) > 4000:
            return jsonify(error="Digite uma pergunta de até 4 mil caracteres."), 400
        if not isinstance(history, list) or (article is not None and not isinstance(article, str)):
            return jsonify(error="Histórico ou artigo inválido."), 400
        dump = library.get(body.get("dump") if isinstance(body.get("dump"), str) else None)
        if not busy.acquire(blocking=False):
            return jsonify(error="O modelo já está respondendo outra pergunta. Aguarde um instante."), 409
        released = threading.Event()

        def release():
            if not released.is_set():
                released.set()
                busy.release()

        def events():
            try:
                for event in answer(llm, dump, question.strip(), history, article or None, bool(body.get("use_wiki", True))):
                    yield json.dumps(event, ensure_ascii=False) + "\n"
            except (OSError, urllib.error.URLError) as exc:
                yield json.dumps({"type": "error", "error": f"Falha ao falar com o Ollama: {exc}"}, ensure_ascii=False) + "\n"
            except Exception as exc:  # Keep the stream well-formed for the browser.
                yield json.dumps({"type": "error", "error": f"Erro inesperado: {exc}"}, ensure_ascii=False) + "\n"
            finally:
                release()

        response = Response(stream_with_context(events()), mimetype="application/x-ndjson",
                            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})
        # Runs even when the browser disconnects before the stream starts.
        response.call_on_close(release)
        return response
