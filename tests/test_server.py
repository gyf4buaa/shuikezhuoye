import json
import threading
import unittest
import urllib.error
import urllib.request

from localization.server import create_server


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_server("127.0.0.1", 0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def request(self, method, path, payload=None, headers=None):
        url = "http://127.0.0.1:%d%s" % (self.port, path)
        data = None
        request_headers = dict(headers or {})
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        request = urllib.request.Request(url, data=data, method=method, headers=request_headers)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), exc.read()

    def test_health(self):
        status, _, body = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["font_present"])
        self.assertFalse(data["llm_configured"])

    def test_demo_catalogue_and_payload(self):
        status, _, body = self.request("GET", "/api/demos")
        self.assertEqual(status, 200)
        names = [item["name"] for item in json.loads(body)["demos"]]
        self.assertIn("zh_ptbr", names)

        status, _, body = self.request("GET", "/api/demo?name=zh_ptbr")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["target_locale"], "pt-BR")
        self.assertEqual(len(payload["strings"]), 28)

    def test_unknown_demo(self):
        status, _, body = self.request("GET", "/api/demo?name=nope")
        self.assertEqual(status, 404)
        self.assertIn("error", json.loads(body))

    def test_index_and_static(self):
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn("LingoGuard", body.decode("utf-8"))

        status, headers, body = self.request("GET", "/static/app.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", headers["Content-Type"])

        status, headers, body = self.request("GET", "/assets/fonts/NotoSans-Variable.ttf")
        self.assertEqual(status, 200)
        self.assertGreater(len(body), 100_000)
        self.assertIn("font", headers["Content-Type"])

    def test_analyze_text(self):
        payload = {
            "text": '{"target_locale":"pt-BR","strings":[{"id":"a","source":"获得 {0} 金币","target":"Obteve moedas"}]}',
            "format": "json",
        }
        status, _, body = self.request("POST", "/api/analyze", payload)
        self.assertEqual(status, 200)
        report = json.loads(body)
        codes = [issue["code"] for issue in report["units"][0]["issues"]]
        self.assertIn("PH002", codes)

    def test_analyze_dataset_object(self):
        payload = {
            "dataset": {
                "target_locale": "pt-BR",
                "strings": [
                    {"id": "a", "source": "设置", "target": "Configurações", "ui": {"profile": "settings_tab"}}
                ],
            }
        }
        status, _, body = self.request("POST", "/api/analyze", payload)
        self.assertEqual(status, 200)
        report = json.loads(body)
        self.assertEqual(report["meta"]["target_locale"], "pt-BR")
        self.assertEqual(report["summary"]["overflow"]["overflow_units"], 1)

    def test_analyze_validation_errors(self):
        status, _, body = self.request("POST", "/api/analyze", {"text": "", "format": "json"})
        self.assertEqual(status, 400)
        self.assertIn("error", json.loads(body))

        status, _, body = self.request("POST", "/api/analyze", {"text": "not json", "format": "json"})
        self.assertEqual(status, 400)

        status, _, body = self.request("POST", "/api/analyze", {"text": "x", "format": "yaml"})
        self.assertEqual(status, 400)

    def test_invalid_json_body(self):
        status, _, body = self.request(
            "POST",
            "/api/analyze",
            payload=None,
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 400)
        self.assertIn("error", json.loads(body))

    def test_exports(self):
        dataset = {
            "target_locale": "pt-BR",
            "strings": [{"id": "a", "source": "设置", "target": "Configurações"}],
        }
        for fmt, marker, mime in (
            ("json", b'"summary"', "application/json"),
            ("csv", "id,key,screen".encode("utf-8"), "text/csv"),
            ("xliff", b"<xliff", "application/x"),
        ):
            status, headers, body = self.request("POST", "/api/export?format=" + fmt, {"dataset": dataset})
            self.assertEqual(status, 200, fmt)
            self.assertIn(marker, body, fmt)
            self.assertIn(mime, headers["Content-Type"])
            self.assertIn("attachment", headers["Content-Disposition"])

        status, _, body = self.request("POST", "/api/export?format=yaml", {"dataset": dataset})
        self.assertEqual(status, 400)

    def test_path_traversal_blocked(self):
        status, _, body = self.request("GET", "/static/../localization/server.py")
        self.assertEqual(status, 404)
        status, _, body = self.request("GET", "/assets/../README.md")
        self.assertEqual(status, 404)

    def test_unknown_route(self):
        status, _, body = self.request("GET", "/api/nope")
        self.assertEqual(status, 404)

    def test_head(self):
        status, headers, body = self.request("HEAD", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")


if __name__ == "__main__":
    unittest.main()
