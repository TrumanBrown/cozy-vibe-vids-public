"""The one Azure client (TASKS.md T4), with requests and the token mocked: nothing is sent and nothing is spent.

  .venv\\Scripts\\python -m unittest discover -s tests -p test_azure.py -v

keyart.py goes through azure_ai: a dropped connection and a DeploymentNotFound right after provisioning are waited out,
a request that timed out or broke off is not sent again for any image call (Azure may have billed it), while chat calls
still retry it. Every finished call lands in the spend log once, and no call is sent once the day's logged estimate has
reached the daily cap.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import azure_ai  # noqa: E402
import keyart  # noqa: E402


class Reply:
    def __init__(self, status=200, body=None, text="", headers=None):
        self.status_code, self._body, self.text, self.headers = status, body or {}, text, headers or {}

    def json(self):
        return self._body


OK = Reply(200, {"created": 1, "usage": {"input_tokens": 10, "output_tokens": 20}, "data": [{"b64_json": ""}]})


class OneClient(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / "usage.jsonl"
        for p in (mock.patch.object(azure_ai, "token", return_value="t"), mock.patch.object(azure_ai.time, "sleep"),
                  mock.patch.object(azure_ai, "LOG", self.log)):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def post(self, *replies):
        p = mock.patch.object(azure_ai.requests, "post", side_effect=list(replies))
        m = p.start()
        self.addCleanup(p.stop)
        return m

    def logged(self):
        return [json.loads(x) for x in self.log.read_text(encoding="utf-8").splitlines()] if self.log.exists() else []

    def test_keyart_success_logs_once(self):
        m = self.post(OK)
        res = keyart.generate("a cozy room", "gpt-image-2", "2560x1440", "high", 1, purpose="keyart:x:hero")
        self.assertEqual(res["created"], 1)
        self.assertEqual(m.call_count, 1)
        url = m.call_args.args[0]
        self.assertIn("/openai/deployments/gpt-image-2/images/generations", url)
        self.assertEqual(m.call_args.kwargs["json"]["prompt"], "a cozy room")
        rows = self.logged()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["deployment"], rows[0]["kind"], rows[0]["purpose"]), ("gpt-image-2", "image", "keyart:x:hero"))

    def test_keyart_retries_a_dropped_connection(self):
        m = self.post(requests.exceptions.ConnectionError("reset"), OK)
        keyart.generate("p", "gpt-image-2", "1024x1024", "high", 1)
        self.assertEqual(m.call_count, 2)

    def test_keyart_retries_a_connect_timeout(self):
        m = self.post(requests.exceptions.ConnectTimeout("never reached Azure"), OK)
        keyart.generate("p", "gpt-image-2", "1024x1024", "high", 1)
        self.assertEqual(m.call_count, 2)

    def test_keyart_never_resends_an_unfinished_request(self):
        for err in (requests.exceptions.ReadTimeout("slow"), requests.exceptions.ChunkedEncodingError("cut")):
            with self.subTest(err=type(err).__name__):
                m = self.post(err, OK)
                with self.assertRaises(SystemExit) as cm:
                    keyart.generate("p", "gpt-image-2", "1024x1024", "high", 1)
                self.assertEqual(m.call_count, 1)
                self.assertIn("billed", str(cm.exception.code))
        self.assertEqual(self.logged(), [])

    def test_waits_out_deployment_not_found(self):
        m = self.post(Reply(404, text='{"error": {"code": "DeploymentNotFound"}}'), OK)
        keyart.generate("p", "gpt-image-2", "1024x1024", "high", 1)
        self.assertEqual(m.call_count, 2)

    def test_other_http_errors_end_keyart_with_the_message(self):
        self.post(Reply(400, text="content policy"))
        with self.assertRaises(SystemExit) as cm:
            keyart.generate("p", "gpt-image-2", "1024x1024", "high", 1)
        self.assertIn("HTTP 400", str(cm.exception.code))

    def test_chat_still_retries_an_unfinished_request(self):
        m = self.post(requests.exceptions.ReadTimeout("slow"), Reply(200, {"choices": [{"message": {"content": "hi"}}], "usage": {}}))
        with mock.patch.dict("os.environ", {"COZY_VISION": "azure"}):
            text, _ = azure_ai.chat([{"role": "user", "content": "hello"}], purpose="test")
        self.assertEqual(text, "hi")
        self.assertEqual(m.call_count, 2)

    def test_image_calls_never_resend_an_unfinished_request(self):
        from PIL import Image
        calls = (("generate", lambda: azure_ai.generate_image("p", size="1024x1024")),
                 ("edit", lambda: azure_ai.edit_image(Image.new("RGB", (8, 8)), "p", size="1024x1024")))
        for name, call in calls:
            for err in (requests.exceptions.ReadTimeout("slow"), requests.exceptions.ChunkedEncodingError("cut")):
                with self.subTest(call=name, err=type(err).__name__):
                    m = self.post(err, OK)
                    with self.assertRaises(azure_ai.Unfinished):
                        call()
                    self.assertEqual(m.call_count, 1)
        self.assertEqual(self.logged(), [])

    def test_an_image_call_can_still_choose_to_resend(self):
        m = self.post(requests.exceptions.ReadTimeout("slow"), OK)
        azure_ai.generate_image("p", size="1024x1024", retry_unfinished=True)
        self.assertEqual(m.call_count, 2)

    def spent_today(self, usd, day=None):
        day = day or azure_ai.dt.date.today().isoformat()
        rec = {"t": f"{day}T01:00:00", "deployment": "gpt-image-2", "kind": "image", "purpose": "x", "usd_est": usd}
        self.log.write_text(json.dumps(rec) + "\n", encoding="utf-8")

    def test_daily_cap_stops_before_anything_is_sent(self):
        self.spent_today(40.5)
        m = self.post(OK, OK)
        with mock.patch.dict("os.environ", {"COZY_DAILY_CAP_USD": ""}), mock.patch.dict(azure_ai.CFG, {"daily_cap_usd": 40}):
            with self.assertRaises(SystemExit) as cm:
                azure_ai.generate_image("p", size="1024x1024")
            self.assertIn("daily cap", str(cm.exception.code))
            self.assertEqual(m.call_count, 0)
            with mock.patch.dict("os.environ", {"COZY_DAILY_CAP_USD": "0"}):          # 0 turns it off for one run
                azure_ai.generate_image("p", size="1024x1024")
            self.assertEqual(m.call_count, 1)
            with mock.patch.dict("os.environ", {"COZY_DAILY_CAP_USD": "100"}):        # or raises it
                azure_ai.generate_image("p", size="1024x1024")
            self.assertEqual(m.call_count, 2)

    def test_daily_cap_counts_only_today(self):
        self.spent_today(500.0, day="2000-01-01")
        m = self.post(OK)
        with mock.patch.dict("os.environ", {"COZY_DAILY_CAP_USD": ""}), mock.patch.dict(azure_ai.CFG, {"daily_cap_usd": 40}):
            azure_ai.generate_image("p", size="1024x1024")
        self.assertEqual(m.call_count, 1)

    def test_daily_cap_is_set(self):
        self.assertGreater(float(azure_ai.CFG.get("daily_cap_usd") or 0), 16, "config/azure.json daily_cap_usd: above the busiest day")


if __name__ == "__main__":
    unittest.main()
