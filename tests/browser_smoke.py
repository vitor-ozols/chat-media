"""Browser checks using a fake agent; no model requests or real downloads.

Install playwright and its Chromium browser, then run python tests/browser_smoke.py.
Screenshots are written to /tmp/chat-media-previews.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import WSGIRequestHandler, make_server

from api import create_app
from support import fake_service


class QuietHandler(WSGIRequestHandler):
    def log(self, *args, **kwargs):
        pass


def main():
    service = fake_service()
    service.codex_sdk.delay = 1.5
    app = create_app(service=service)
    server = make_server("127.0.0.1", 0, app, threaded=True, request_handler=QuietHandler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    previews = Path("/tmp/chat-media-previews")
    previews.mkdir(exist_ok=True)
    base = f"http://127.0.0.1:{server.server_port}/chat/"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(args=["--no-sandbox"])
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base)
            expect(page.locator("#connection-label")).to_have_text("Pronto para ajudar")
            page.screenshot(path=str(previews / "desktop.png"))
            # History -> continue -> new chat.
            page.get_by_role("button", name="Organizar minha biblioteca", exact=True).click()
            expect(page.locator("#messages")).to_contain_text("Como posso ajudar?")
            page.locator("#new-chat").click()
            expect(page.locator("#welcome")).to_be_visible()
            # Streaming, real activity, and recovery without a duplicate user message.
            page.locator("#prompt").fill("Confira minha biblioteca")
            page.locator("#prompt").press("Enter")
            expect(page.locator(".message.commentary")).to_contain_text("Vou conferir")
            expect(page.locator("#stop")).to_be_visible()
            page.locator(".activity-panel summary").click()
            expect(page.locator(".activity-row")).to_contain_text("ls -lah media/")
            page.reload()
            expect(page.locator(".message.user")).to_have_count(1)
            expect(page.locator("#messages")).to_contain_text("Encontrei 3 downloads", timeout=10000)
            expect(page.locator(".message.assistant:not(.commentary)")).to_have_count(1)
            expect(page.locator("#stop")).to_be_hidden()
            page.get_by_role("button", name="Copiar", exact=True).click()
            expect(page.get_by_role("button", name="✓ Copiado", exact=True)).to_be_visible()
            page.screenshot(path=str(previews / "chat.png"))
            # Cancel the SDK turn instead of merely hiding the stream.
            page.locator("#prompt").fill("Uma tarefa demorada")
            page.locator("#send").click()
            expect(page.locator("#stop")).to_be_visible()
            page.locator("#stop").click()
            expect(page.locator("#messages")).to_contain_text("Execução interrompida", timeout=10000)
            assert service.codex_sdk.interrupted.is_set()
            # Skills and persistent preferences.
            page.locator("#settings-open").click()
            page.locator("#effort").select_option("high")
            page.get_by_role("button", name="$organizar-midia", exact=True).click()
            expect(page.locator("#prompt")).to_have_value("$organizar-midia ")
            # Agent text cannot inject HTML or javascript: links.
            safe = page.evaluate('''async () => {
                const {markdown} = await import('./static/markdown.js');
                const el = document.createElement('div');
                el.innerHTML = markdown('<img src=x onerror="window.pwned=1">\\n[bad](javascript:alert%281%29)\\n\\n| Nome | Status |\\n| --- | --- |\\n| Música | Pronto |');
                return !!el.querySelector('table') && !el.querySelector('img') && !el.querySelector('script') && !el.querySelector('a[href^="javascript:"]');
            }''')
            assert safe
            # Torrent controls call the preserved engine.
            page.locator("#torrents-nav").click()
            expect(page.locator("#download-list")).to_contain_text("Meu download")
            page.get_by_role("button", name="Ⅱ Pausar", exact=True).click()
            expect(page.locator("#toast")).to_contain_text("Ação aplicada")
            service.torrent_service.pause_torrent.assert_called_once_with("torrent-test")
            page.screenshot(path=str(previews / "downloads.png"))
            page.locator("#add-download-open").click()
            page.locator("#download-form button[type=submit]").click()
            expect(page.locator("#download-form-error")).to_contain_text("Informe um magnet")
            page.keyboard.press("Escape")
            page.goto(base + "torrents")
            expect(page.locator("#downloads-view")).to_be_visible()
            expect(page.locator("#connection-label")).to_have_text("Pronto para ajudar")
            page.locator("#new-chat").click()
            expect(page.locator("#chat-view")).to_be_visible()
            expect(page.locator("#welcome")).to_be_visible()
            assert not errors, errors
            context.close()
            # Narrow mobile layouts, touch navigation, composer and dialogs.
            mobile = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, device_scale_factor=1)
            page = mobile.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base)
            expect(page.locator("#connection-label")).to_have_text("Pronto para ajudar")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(previews / "mobile.png"))
            page.locator("#menu-toggle").click()
            expect(page.locator("#sidebar")).to_have_class("sidebar open")
            page.get_by_role("button", name="Organizar minha biblioteca", exact=True).click()
            expect(page.locator("#messages")).to_contain_text("Como posso ajudar?")
            expect(page.locator("#sidebar-backdrop")).to_be_hidden()
            page.locator("#prompt").fill("Mensagem no celular")
            page.locator("#send").click()
            expect(page.locator("#messages")).to_contain_text("Encontrei 3 downloads", timeout=10000)
            page.screenshot(path=str(previews / "mobile-chat.png"))
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert not errors, errors
            mobile.close()
            browser.close()
        print("Browser checks passed: desktop, mobile, history, streaming, reload recovery, cancellation, skills, safe markdown and torrent actions.")
        print(f"Screenshots: {previews}")
    finally:
        server.shutdown()
        app.extensions["chat_runs"].executor.shutdown(wait=True)


if __name__ == "__main__":
    main()
