from __future__ import annotations

import os
from dataclasses import asdict
from urllib.parse import urlparse

from flask import Blueprint, Response, jsonify, redirect, render_template, request, url_for

from media_manager.chat_runs import ChatRuns


def register_web(app, service):
    web = Blueprint("web", __name__, template_folder="templates", static_folder="static")
    runs = ChatRuns(service.codex_sdk)
    app.extensions["chat_runs"] = runs

    @web.before_request
    def same_origin_mutations():
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("Origin")
            if origin and urlparse(origin).netloc != request.host:
                return jsonify(error="Origem da requisição não permitida."), 403

    @web.get("/torrents")
    @web.get("/")
    def index():
        return render_template("index.html", api_base=url_for("web.bootstrap").removesuffix("bootstrap"))

    @web.get("/chat")
    def legacy_chat():
        return redirect(url_for("web.index"))

    @web.get("/api/bootstrap")
    def bootstrap():
        return jsonify(available=service.codex_sdk.is_available(), models=service.list_codex_models(),
                       skills=service.list_codex_skills(), model_error=service.codex_error("models"),
                       download_dir=service.torrent_service.get_default_download_dir())

    @web.get("/api/threads")
    def threads():
        rows = service.list_codex_threads(limit=100)
        error = service.codex_error("threads")
        return (jsonify(error=error), 502) if error else jsonify(threads=rows)

    @web.get("/api/threads/<thread_id>/messages")
    def messages(thread_id):
        rows = service.list_codex_messages(thread_id)
        error = service.codex_error("messages")
        return (jsonify(error=error), 502) if error else jsonify(messages=rows)

    @web.post("/api/runs")
    def start_run():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify(error="Envie um objeto JSON."), 400
        prompt = body.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 100000:
            return jsonify(error="Digite uma mensagem de até 100 mil caracteres."), 400
        effort, sandbox = body.get("effort", "medium"), body.get("sandbox", "full")
        if (not isinstance(effort, str) or not isinstance(sandbox, str)
                or effort not in {"low", "medium", "high", "xhigh"} or sandbox not in {"read", "write", "full"}):
            return jsonify(error="Configuração de execução inválida."), 400
        for key in ("model", "thread_id"):
            if body.get(key) is not None and (not isinstance(body[key], str) or len(body[key]) > 256):
                return jsonify(error=f"Campo {key} inválido."), 400
        if not service.codex_sdk.is_available():
            return jsonify(error="O SDK do Codex não está disponível neste ambiente."), 503
        options = {"prompt": prompt.strip(), "thread_id": body.get("thread_id") or None,
                   "model": body.get("model") or None, "effort": effort, "sandbox": sandbox}
        try:
            run = runs.start(options)
        except RuntimeError as exc:
            return jsonify(error=str(exc)), 409
        return jsonify(id=run.id), 202

    @web.get("/api/runs/<run_id>/events")
    def events(run_id):
        run = runs.get(run_id)
        if not run:
            return jsonify(error="Execução não encontrada. O serviço pode ter sido reiniciado."), 404
        try:
            after = max(0, int(request.headers.get("Last-Event-ID") or request.args.get("after", 0)))
        except ValueError:
            return jsonify(error="Cursor de eventos inválido."), 400
        return Response(run.stream(after), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})

    @web.post("/api/runs/<run_id>/cancel")
    def cancel_run(run_id):
        run = runs.get(run_id)
        if not run:
            return jsonify(error="Execução não encontrada."), 404
        try:
            run.cancel()
        except Exception as exc:
            return jsonify(error=f"Não foi possível interromper: {exc}"), 502
        return jsonify(status=run.state, cancel_requested=run.cancel_requested)

    @web.get("/api/runs/<run_id>")
    def run_status(run_id):
        run = runs.get(run_id)
        if not run:
            return jsonify(error="Execução não encontrada."), 404
        return jsonify(id=run.id, state=run.state, thread_id=run.thread_id)

    def torrent_payload(row):
        return {key: value for key, value in asdict(row).items() if key != "resume_data"}

    @web.get("/api/torrents")
    def torrents():
        engine = service.torrent_service
        return jsonify(torrents=[torrent_payload(row) for row in engine.list_torrents()],
                       engine=asdict(engine.get_engine_snapshot()),
                       events=[asdict(row) for row in engine.list_events(limit=30)])

    @web.post("/api/torrents")
    def add_torrents():
        engine = service.torrent_service
        try:
            if request.mimetype == "multipart/form-data":
                uploads = request.files.getlist("files")
                if not uploads or any(not (item.filename or "").lower().endswith(".torrent") for item in uploads):
                    return jsonify(error="Selecione arquivos .torrent."), 400
                directory = request.form.get("download_dir") or engine.get_default_download_dir()
                rows = [engine.add_torrent_file(item.filename, item.read(), directory,
                        start_paused=request.form.get("start_paused") == "true") for item in uploads]
            else:
                body = request.get_json(silent=True)
                if not isinstance(body, dict):
                    return jsonify(error="Envie magnets em um objeto JSON."), 400
                magnets = body.get("magnets")
                if not isinstance(magnets, list) or not magnets or len(magnets) > 100 or any(
                    not isinstance(m, str) or not m.startswith("magnet:?") for m in magnets
                ):
                    return jsonify(error="Informe até 100 links magnet válidos."), 400
                directory = body.get("download_dir") or engine.get_default_download_dir()
                if not isinstance(directory, str) or len(directory) > 4096:
                    return jsonify(error="Diretório inválido."), 400
                rows = engine.add_magnets(magnets, directory, start_paused=bool(body.get("start_paused")))
            return jsonify(torrents=[torrent_payload(row) for row in rows]), 201
        except (ValueError, OSError, RuntimeError) as exc:
            return jsonify(error=str(exc)), 400

    @web.post("/api/torrents/<torrent_id>/<action>")
    def torrent_action(torrent_id, action):
        engine = service.torrent_service
        actions = {"pause": engine.pause_torrent, "resume": engine.resume_torrent,
                   "restart": engine.restart_torrent, "recheck": engine.force_recheck,
                   "remove": lambda key: engine.remove_torrent(key, delete_files=False)}
        if action not in actions:
            return jsonify(error="Ação inválida."), 400
        try:
            result = actions[action](torrent_id)
        except (ValueError, OSError, RuntimeError) as exc:
            return jsonify(error=str(exc)), 400
        if result is None:
            return jsonify(error="Torrent não encontrado."), 404
        return jsonify(ok=True)

    @web.get("/api/torrents/<torrent_id>/files")
    def torrent_files(torrent_id):
        return jsonify(files=[asdict(row) for row in service.torrent_service.list_files(torrent_id)])

    base = os.environ.get("BASE_PATH", os.environ.get("STREAMLIT_SERVER_BASE_URL_PATH", "chat")).strip("/")
    app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
    app.register_blueprint(web, url_prefix=f"/{base}" if base else "")
    if base:
        app.add_url_rule("/", "home", lambda: redirect(url_for("web.index")))
        # Preserve the old address without a trailing slash behind the proxy.
        app.add_url_rule(f"/{base}", "web_base", lambda: redirect(url_for("web.index")))
