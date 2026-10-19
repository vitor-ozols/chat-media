import io
import json
import unittest
from unittest.mock import patch

from api import create_app
from support import fake_service


class ChatNavigationTests(unittest.TestCase):
    def setUp(self):
        self.service = fake_service()
        with patch.dict("os.environ", {"BASE_PATH": "chat"}):
            self.app = create_app(service=self.service)
        self.app.testing = True
        self.client = self.app.test_client()
        self.addCleanup(lambda: self.app.extensions["chat_runs"].executor.shutdown(wait=True))

    def test_web_routes_and_assets_preserve_chat_base_path(self):
        self.assertEqual(self.client.get("/").location, "/chat/")
        self.assertEqual(self.client.get("/chat").location, "/chat/")
        self.assertEqual(self.client.get("/chat/chat").location, "/chat/")
        for path in ["/chat/", "/chat/torrents"]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'data-api="/chat/api/"', response.data)
            self.assertIn(b'/chat/static/app.js', response.data)
        with self.client.get("/chat/static/app.js") as asset:
            self.assertEqual(asset.status_code, 200)

    def test_can_list_history_and_continue_by_thread_id(self):
        self.assertEqual(self.client.get("/chat/api/threads").json["threads"][0]["id"], "thread-old")
        self.assertEqual(self.client.get("/chat/api/threads/thread-old/messages").json["messages"][0]["content"], "Olá")
        self.service.list_codex_messages.assert_called_once_with("thread-old")

    def test_run_returns_immediately_and_sse_replays_progress(self):
        response = self.client.post("/chat/api/runs", json={"prompt": "Oi", "thread_id": "thread-old"})
        self.assertEqual(response.status_code, 202)
        run_id = response.json["id"]
        stream = self.client.get(f"/chat/api/runs/{run_id}/events")
        self.assertEqual(stream.mimetype, "text/event-stream")
        self.assertEqual(stream.headers["X-Accel-Buffering"], "no")
        events = [json.loads(line[6:]) for line in stream.data.decode().splitlines() if line.startswith("data: ")]
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(events[-1]["thread_id"], "thread-old")
        run = self.app.extensions["chat_runs"].get(run_id)
        replay = self.client.get(f"/chat/api/runs/{run_id}/events", headers={"Last-Event-ID": str(run.sequence - 1)})
        self.assertEqual(replay.data.decode().count("data: "), 1)
        self.assertEqual(self.client.get(f"/chat/api/runs/{run_id}").json["state"], "completed")

    def test_invalid_requests_do_not_start_turns(self):
        for body in [[], {"prompt": ""}, {"prompt": 3}, {"prompt": "oi", "sandbox": "bad"}, {"prompt": "oi", "effort": "bad"}, {"prompt": "oi", "model": []}, {"prompt": "oi", "thread_id": 4}]:
            self.assertEqual(self.client.post("/chat/api/runs", json=body).status_code, 400)
        self.assertFalse(self.service.codex_sdk.started.is_set())
        self.assertEqual(self.client.get("/chat/api/runs/missing/events").status_code, 404)
        self.assertEqual(self.client.post("/chat/api/runs/missing/cancel").status_code, 404)
        self.assertEqual(self.client.post("/chat/api/runs", json={"prompt": "Oi"}, headers={"Origin": "https://other.example"}).status_code, 403)

    def test_history_errors_are_visible(self):
        self.service.codex_error.return_value = "Falha ao consultar histórico"
        self.assertEqual(self.client.get("/chat/api/threads").status_code, 502)
        self.assertEqual(self.client.get("/chat/api/threads/thread-old/messages").status_code, 502)

    def test_torrents_preserve_controls_without_exposing_resume_data(self):
        data = self.client.get("/chat/api/torrents").json
        self.assertNotIn("resume_data", data["torrents"][0])
        self.assertTrue(data["engine"]["available"])
        self.assertEqual(self.client.post("/chat/api/torrents/torrent-test/remove").status_code, 200)
        self.service.torrent_service.remove_torrent.assert_called_once_with("torrent-test", delete_files=False)
        self.assertEqual(self.client.post("/chat/api/torrents/torrent-test/unknown").status_code, 400)

    def test_upload_passes_file_and_destination_to_existing_engine(self):
        engine = self.service.torrent_service
        engine.add_torrent_file.return_value = engine.list_torrents.return_value[0]
        response = self.client.post("/chat/api/torrents", data={"files": (io.BytesIO(b"torrent-data"), "test.torrent"), "download_dir": "/downloads", "start_paused": "true"})
        self.assertEqual(response.status_code, 201)
        engine.add_torrent_file.assert_called_once_with("test.torrent", b"torrent-data", "/downloads", start_paused=True)

    def test_download_api_and_health_stay_compatible(self):
        self.service.list_downloads.return_value = []
        self.assertEqual(self.client.get("/downloads").json, {"downloads": []})
        self.assertEqual(self.client.get("/health").json["status"], "ok")

    def test_empty_base_path_is_supported(self):
        with patch.dict("os.environ", {"BASE_PATH": ""}):
            app = create_app(service=self.service)
        self.addCleanup(lambda: app.extensions["chat_runs"].executor.shutdown(wait=True))
        self.assertIn(b'data-api="/api/"', app.test_client().get("/").data)
