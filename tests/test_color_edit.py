"""The color editor's local server (tools/color_edit.py): who it answers, what it refuses, how much work it takes on at
once. Offline and free: a stub editor stands in for the footage, nothing is decoded or saved.

  .venv\\Scripts\\python -m unittest discover -s tests -p test_color_edit.py -v

Only its own page may use it (a website could otherwise rewrite the look in footage.json, start 4K encodes, or read the
footage through a rebound name), a bad form gets a plain 400 and nothing is saved, and at most WORK_SLOTS 4K decodes or
LUT builds run at once (security review 2026-10-26).
"""
import http.client
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import color_edit as CE  # noqa: E402


class StubEditor(CE.Editor):
    """The editor's request handling without a recording: frames are made by a fake grab_frame."""

    def __init__(self, out):
        self.P, self.fps, self.out = {"s": 100, "o": 0, "N": 300}, 30.0, out
        self.v = {"width": 64, "height": 36}
        self.src = Path("stub.mp4")
        self.frames, self.order, self.pending, self.lock = {}, [], {}, threading.Lock()
        self.moments = [{"i": i, "video_s": i, "frame": 100 + i} for i in range(3)]
        self.thumbs, self.thumb_cv = {0: b"\xff\xd8jpeg"}, threading.Condition()
        self.job, self.saved = {"state": "idle"}, []

    def save(self, grade, k):
        self.saved.append(CE.CG.clean(grade))
        return {"ok": True, "grade": self.saved[-1]}

    def _clip(self, g, k, frames, path):
        self.job = {**self.job, "state": "done"}


class EditorServer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ed = StubEditor(Path(self.tmp.name))
        self.decodes, self.live, self.peak = [], 0, 0
        self.count = threading.Lock()

        def grab(src, ss, frames=1, pix_fmt=None):
            with self.count:
                self.live += 1
                self.peak = max(self.peak, self.live)
                self.decodes.append(ss)
            time.sleep(0.2)
            with self.count:
                self.live -= 1
            return bytes(64 * 36 * 2 * 2)

        mock.patch.object(CE, "grab_frame", grab).start()
        mock.patch.object(CE.Handler, "ed", self.ed).start()
        self.addCleanup(mock.patch.stopall)
        self.srv = CE.Server(("127.0.0.1", 0), CE.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.port = self.srv.server_address[1]
        self.own = f"http://127.0.0.1:{self.port}"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def req(self, method, path, body=None, headers=None, length=None):
        headers = dict(headers or {})
        if body is not None or length is not None:
            headers.setdefault("Content-Type", "application/json")
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        c.putrequest(method, path, skip_host="Host" in headers)
        for k, v in headers.items():
            c.putheader(k, v)
        if body is not None or length is not None:
            c.putheader("Content-Length", str(length if length is not None else len(body)))
        c.endheaders(body if length is None else None)
        r = c.getresponse()
        data = r.read()
        hdrs = dict(r.getheaders())
        c.close()
        try:
            err = json.loads(data).get("error", "")
        except ValueError:
            err = ""
        return r.status, err, hdrs, data

    def test_only_its_own_page(self):
        look = b'{"grade": {"brightness": -100}}'
        for name, headers in [("a cross-site no-cors POST", {"Content-Type": "text/plain;charset=UTF-8", "Origin": "https://evil.example"}),
                              ("a POST that isn't JSON", {"Content-Type": "text/plain"}),
                              ("a JSON POST from another site", {"Origin": "https://evil.example"}),
                              ("a JSON POST from origin null", {"Origin": "null"}),
                              ("a POST through a rebound name", {"Host": f"rebind.example:{self.port}"})]:
            with self.subTest(name):
                self.assertEqual(self.req("POST", "/api/save", look, headers)[0], 403)
        self.assertEqual(self.ed.saved, [])
        self.assertEqual(self.req("GET", "/api/job", headers={"Host": f"rebind.example:{self.port}"})[0], 403)
        self.assertEqual(self.req("GET", "/api/job", headers={"Host": f"localhost:{self.port}"})[0], 200)
        self.assertEqual(self.req("POST", "/api/save", look, {"Origin": self.own})[0], 200)
        self.assertEqual(self.ed.saved, [{"brightness": -100}])

    def test_security_headers(self):
        status, _, h, _ = self.req("GET", "/api/job")
        self.assertEqual(status, 200)
        self.assertEqual((h["X-Content-Type-Options"], h["X-Frame-Options"], h["Referrer-Policy"]), ("nosniff", "DENY", "no-referrer"))
        self.assertIn("default-src 'none'", h["Content-Security-Policy"])
        self.assertIn("frame-ancestors 'none'", h["Content-Security-Policy"])
        self.assertNotIn("Python", h.get("Server", ""))

    def test_bad_forms_get_a_plain_400_and_nothing_is_saved(self):
        for body, want in [(b"not json", "wasn't JSON"), (b"[1, 2]", "JSON object"), (b'{"grade": [1]}', "set of sliders"),
                           (b'{"grade": {"highlights": "abc"}}', "whole numbers"), (b'{"grade": {"highlights": 1.5}}', "whole numbers"),
                           (b'{"grade": {"highlights": 101}}', "outside"), (b'{"grade": {"nope": 1}}', "unknown slider"),
                           (b'{"grade": {}, "k": 1e400}', "isn't a frame number"), (b'{"grade": {}, "k": 99999}', "outside the loop")]:
            with self.subTest(body=body):
                status, err, _, _ = self.req("POST", "/api/save", body)
                self.assertEqual(status, 400)
                self.assertIn(want, err)
        for path, body, want in [("/api/clip", b'{"k": 150, "seconds": "abc"}', "isn't a number of seconds"),
                                 ("/api/clip", b'{"k": 150, "seconds": NaN}', "isn't a number of seconds"),
                                 ("/api/clip", b'{"seconds": 20}', "no frame to start")]:
            with self.subTest(path=path, body=body):
                status, err, _, _ = self.req("POST", path, body)
                self.assertEqual(status, 400)
                self.assertIn(want, err)
        self.assertEqual(self.ed.saved, [])
        self.assertEqual(self.req("POST", "/api/save", length=100000)[0], 413)
        self.assertEqual(self.req("POST", "/api/save", length=-5)[0], 400)
        for path, want in [("/api/frame", "frame None"), ("/api/frame?k=abc", "frame 'abc'"), ("/api/frame?k=99999", "outside the loop")]:
            with self.subTest(path=path):
                status, err, _, _ = self.req("GET", path)
                self.assertEqual(status, 400)
                self.assertIn(want, err)

    def test_an_unknown_thumbnail_answers_at_once(self):
        for path in ("/api/thumb/abc", "/api/thumb/999"):
            t0 = time.time()
            self.assertEqual(self.req("GET", path)[0], 404)
            self.assertLess(time.time() - t0, 3)
        self.assertEqual(self.req("GET", "/api/thumb/0")[0], 200)

    def test_at_most_two_decodes_at_once(self):
        ks = [150 + i for i in range(6)]
        threads = [threading.Thread(target=self.req, args=("GET", f"/api/frame?k={k}")) for k in ks]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        self.assertEqual(len(self.decodes), 6)
        self.assertLessEqual(self.peak, CE.WORK_SLOTS)

    def test_the_same_frame_asked_three_times_is_decoded_once(self):
        threads = [threading.Thread(target=self.req, args=("GET", "/api/frame?k=150")) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        self.assertEqual(len(self.decodes), 1)

    def test_a_busy_editor_says_so(self):
        held = [CE.Editor.work.acquire(timeout=1) for _ in range(CE.WORK_SLOTS)]
        try:
            with self.assertRaises(CE.Busy):
                with self.ed.slot(wait_s=0.1):
                    pass
            with mock.patch.object(StubEditor, "frame", side_effect=CE.Busy("the editor is busy")):
                status, err, _, _ = self.req("GET", "/api/frame?k=150")
            self.assertEqual((status, err), (503, "the editor is busy"))
        finally:
            for ok in held:
                if ok:
                    CE.Editor.work.release()


if __name__ == "__main__":
    unittest.main()
