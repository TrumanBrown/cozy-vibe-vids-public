"""A color editor for his own footage, in the browser (user 2026-10-23: a simple editor to adjust highlights,
brightness, contrast and the like on the sample video, the way the iPhone's video editor does, colors only, then render
again from there).

  .venv\\Scripts\\python tools\\color_edit.py aquarium [--port 8765] [--no-browser]

Opens http://127.0.0.1:8765: a 4K frame of the recording, at any moment of the looped video, with iPhone's color
sliders and Sharpness (tools/color_grade.py). The page renders the whole 4K frame on the graphics card with the same
look the render uses (Sharpness as the same integer kernel, the colors as a 3D LUT baked from the same function), then
shows it at any zoom, so the picture follows a slider while it moves. Hold Space (or "Hold: as shot") to see the frame
as shot; Split shows before and after; Clipping marks what shows as pure white (red) or black (blue).

Save look writes the sliders to scenes/<scene>/footage.json `grade`, appends them to out/<scene>/color/history.jsonl,
and saves a before and after made by ffmpeg through the render's own filters (out/<scene>/color/saved_<look>.jpg).
Preview clip encodes 20 s of the shown moment with the look at the 10 h's settings and opens it in the default player.
The 10 h takes the look when it's rerendered: footage_loop.py window <scene> --tag <new>, then master. Local only.
"""
import argparse
import contextlib
import json
import math
import os
import struct
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import numpy as np

from cozy.paths import ROOT
from cozy.media import grab_frame
import color_grade as CG  # noqa: E402
import footage_loop as FL  # noqa: E402

PAGE = ROOT / "tools" / "color_edit.html"
CLIP_S = 20
KEEP_FRAMES = 6
MOMENTS = 10
MAX_BODY = 1 << 16                     # a posted look is a few hundred bytes
WORK_SLOTS = 2                         # 4K frame decodes and LUT builds at once; the rest wait their turn (each decode holds ~100 MB)
# the page is one file with its script and style inline, loading only from this server
HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
           "Referrer-Policy": "no-referrer", "Cross-Origin-Resource-Policy": "same-origin",
           "Content-Security-Policy": "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                                      "img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"}


def packet(header, *blobs):
    """[uint32 header length][JSON header padded to 4 bytes][blobs]: the page reads the arrays in place."""
    h = json.dumps(header).encode()
    h += b" " * (-len(h) % 4)
    return struct.pack("<I", len(h)) + h + b"".join(blobs)


def luma_stats(Y):
    """64-bin histogram of the displayed luma (above white counts as white), and the shares shown as pure white / black."""
    d = np.clip((np.asarray(Y, np.float64) - 64) / 876, 0, 1)
    h, _ = np.histogram(d, bins=64, range=(0, 1))
    return {"hist": (h / d.size).round(6).tolist(), "white": round(float((Y > 940).mean() * 100), 3),
            "black": round(float((Y < 64.5).mean() * 100), 3)}


class Busy(RuntimeError):
    """Every work slot stayed taken for the whole wait (the page gets a 503 and can ask again)."""


class Editor:
    work = threading.BoundedSemaphore(WORK_SLOTS)

    @contextlib.contextmanager
    def slot(self, wait_s=120):
        """One of the WORK_SLOTS for a 4K decode or a LUT build: many frame requests at once (a fast scrub, or another
        program on this PC) queue here instead of starting an ffmpeg decode each."""
        if not self.work.acquire(timeout=wait_s):
            raise Busy("the editor is busy with other frames: try again in a moment")
        try:
            yield
        finally:
            self.work.release()

    def __init__(self, scene, open_clips=True):
        self.scene = scene
        self.open_clips = open_clips
        self.cfg_path = ROOT / "scenes" / scene / "footage.json"
        self.cfg = FL.load_cfg(scene)
        CG.clean(self.cfg.get("grade"))                 # fail early on a grade the sliders can't show
        self.src = self.cfg["_src"]
        self.v = FL.probe_video(self.src)
        self.P = FL.plan_of(scene, self.cfg)
        self.fps = self.P["fps"]
        self.out = ROOT / "out" / scene / "color"
        self.out.mkdir(parents=True, exist_ok=True)
        pub = ROOT / "assets" / "publish" / f"{scene}.json"
        self.name = json.loads(pub.read_text(encoding="utf-8")).get("name", scene) if pub.exists() else scene
        self.lock = threading.Lock()
        self.frames, self.order, self.pending = {}, [], {}
        s, o, N = self.P["s"], self.P["o"], self.P["N"]
        self.moments = []
        for i in range(MOMENTS):
            m = int(round(i * N / MOMENTS))
            self.moments.append({"i": i, "video_s": round(m / self.fps, 2), "frame": s + (o + m) % N})
        self.thumbs, self.thumb_cv = {}, threading.Condition()
        self.job = {"state": "idle"}
        threading.Thread(target=self._thumbs, daemon=True).start()

    # frames ---------------------------------------------------------------------------------------------------------
    def _thumbs(self):
        from io import BytesIO
        from PIL import Image
        for m in self.moments:
            try:
                img = Image.fromarray(FL.grab(self.src, m["frame"], self.fps, 320))
                b = BytesIO()
                img.save(b, "JPEG", quality=85)
                data = b.getvalue()
            except Exception:                            # a missing thumbnail only leaves its box grey
                data = b""
            with self.thumb_cv:
                self.thumbs[m["i"]] = data
                self.thumb_cv.notify_all()

    def thumb(self, i):
        if not 0 <= i < len(self.moments):                   # no such moment: don't wait for one that never comes
            return b""
        with self.thumb_cv:
            self.thumb_cv.wait_for(lambda: i in self.thumbs, timeout=120)
            return self.thumbs.get(i, b"")

    def frame(self, k):
        """Source frame k: the page's packet (Y, U, V codes as float16 at full size) and small arrays for the histogram.
        A frame already being decoded for another request is waited for, not decoded twice."""
        with self.lock:
            if k in self.frames:
                self.order.remove(k)
                self.order.append(k)
                return self.frames[k]
            ev = self.pending.get(k)
            if ev is None:
                ev = self.pending[k] = threading.Event()
                mine = True
            else:
                mine = False
        if not mine:
            ev.wait(timeout=300)
            with self.lock:
                if k in self.frames:
                    return self.frames[k]
            return self.frame(k)                             # that decode failed: try it here
        try:
            with self.slot():
                f = self._decode(k)
            with self.lock:
                self.frames[k] = f
                self.order.append(k)
                while len(self.order) > KEEP_FRAMES:
                    self.frames.pop(self.order.pop(0), None)
            return f
        finally:
            with self.lock:
                self.pending.pop(k, None)
            ev.set()

    def _decode(self, k):
        W, H = self.v["width"], self.v["height"]
        raw = grab_frame(self.src, FL.ss(k, self.fps), frames=1, pix_fmt="yuv422p10le")
        a = np.frombuffer(raw, np.uint16)
        if a.size != W * H * 2:
            raise RuntimeError(f"frame {k}: got {a.size} samples, expected {W * H * 2}")
        CW = W // 2
        Y = a[:W * H].reshape(H, W)
        U = a[W * H: W * H + CW * H].reshape(H, CW)
        V = a[W * H + CW * H:].reshape(H, CW)
        sY, sU, sV = (x.astype(np.float64) for x in (Y[::8, ::8], U[::8, ::4], V[::8, ::4]))
        return {"packet": packet({"k": k, "w": W, "h": H, "cw": CW, "video_s": self.video_s(k), "source_s": round(k / self.fps, 2)},
                                 Y.astype(np.float16).tobytes(), U.astype(np.float16).tobytes(), V.astype(np.float16).tobytes()),
                "small": (sY, sU, sV), "stats0": luma_stats(sY)}

    def video_s(self, k):
        return round(((k - self.P["s"] - self.P["o"]) % self.P["N"]) / self.fps, 2)

    def check_k(self, k):
        try:
            k = int(k)
        except (TypeError, ValueError, OverflowError):
            raise ValueError(f"frame {k!r} isn't a frame number") from None
        if not (self.P["s"] <= k < self.P["s"] + self.P["N"]):
            raise ValueError(f"frame {k} is outside the loop")
        return k

    # looks ----------------------------------------------------------------------------------------------------------
    def lut(self, grade, n, k):
        g = CG.clean(grade)
        try:
            n = int(n)
        except (TypeError, ValueError, OverflowError):
            n = 33
        n = n if n in (17, 33, 65) else 33
        with self.slot():
            kk = CG.kernel(g)
            hdr = {"n": n, "grade": g, "color": bool(CG.color(g)), "sharp": {"k": kk[0], "rdiv": kk[1]} if kk else None}
            f = self.frames.get(k) if k is not None else None
            if f is not None:
                sY, sU, sV = f["small"]
                st = luma_stats(CG.grade(sY, sU, sV, g)[0])
                hdr.update({"hist": st["hist"], "white": st["white"], "black": st["black"], "hist0": f["stats0"]["hist"],
                            "white0": f["stats0"]["white"], "black0": f["stats0"]["black"]})
            return packet(hdr, CG.lut(g, n, "yuv").astype(np.float16).tobytes())

    def state(self):
        self.cfg = FL.load_cfg(self.scene)
        g = CG.clean(self.cfg.get("grade"))
        return {"scene": self.scene, "name": self.name, "source": self.cfg["source"], "sliders": CG.ALL, "help": CG.HELP, "grade": g,
                "describe": CG.describe(g), "moments": self.moments, "fps": self.fps, "loop_s": self.P["N"] / self.fps,
                "loop": {"s": self.P["s"], "o": self.P["o"], "N": self.P["N"]}, "size": [self.v["width"], self.v["height"]],
                "clip_s": CLIP_S, "file": str(self.cfg_path)}

    def compare(self, g, k):
        """Before | after at 1920 wide, both made by ffmpeg, the after through the render's own filters."""
        from PIL import Image, ImageDraw, ImageFont
        a = FL.grab(self.src, k, self.fps, 1920)
        b = FL.grab(self.src, k, self.fps, 1920, vf=FL.grade_vf(g))
        img = Image.fromarray(np.concatenate([a, b], 1))
        d = ImageDraw.Draw(img)

        def font_of(size):
            try:
                return ImageFont.truetype("segoeui.ttf", size)
            except OSError:
                return ImageFont.load_default()
        for x, text in ((0, "as shot"), (1920, f"your look: {CG.describe(g)}")):
            size = 40
            font = font_of(size)
            while d.textlength(text, font=font) > 1860 and size > 18:   # a long look shrinks to fit its half
                size -= 2
                font = font_of(size)
            w = d.textlength(text, font=font)
            d.rectangle([x, 0, x + w + 40, int(size * 1.6)], fill=(0, 0, 0))
            d.text((x + 20, int(size * 0.2)), text, font=font, fill=(255, 255, 255))
        path = self.out / f"saved_{CG.key(g)}.jpg"
        img.save(path, quality=90)
        return path

    def save(self, grade, k):
        g = CG.clean(grade)
        d = json.loads(self.cfg_path.read_text(encoding="utf-8"))
        if g:
            d["grade"] = g
            d["_grade"] = (f"his look, set in tools/color_edit.py {time.strftime('%Y-%m-%d %H:%M')}: {CG.describe(g)} "
                           "(iPhone-style sliders, -100..100, tools/color_grade.py). A new look needs a new window --tag, then master")
        else:
            d.pop("grade", None)
            d.pop("_grade", None)
        tmp = self.cfg_path.with_name(self.cfg_path.name + ".tmp")
        tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(self.cfg_path)
        self.cfg = FL.load_cfg(self.scene)
        with open(self.out / "history.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "grade": g, "frame": k}) + "\n")
        path = self.compare(g, k) if k is not None else None
        return {"ok": True, "grade": g, "describe": CG.describe(g), "file": str(self.cfg_path), "compare": str(path) if path else None}

    def clip(self, grade, k, seconds):
        g = CG.clean(grade)
        try:
            seconds = float(seconds)
        except (TypeError, ValueError):
            raise ValueError(f"clip length {seconds!r} isn't a number of seconds") from None
        if not math.isfinite(seconds):
            raise ValueError(f"clip length {seconds!r} isn't a number of seconds")
        with self.lock:
            if self.job.get("state") == "running":
                return {"ok": False, "error": "a clip is already being made"}
            frames = int(round(max(5, min(60, seconds)) * self.fps))
            path = self.out / f"clip_{CG.key(g)}_{k}.mp4"
            self.job = {"state": "running", "done": 0, "total": frames, "path": str(path), "describe": CG.describe(g)}
        threading.Thread(target=self._clip, args=(g, k, frames, path), daemon=True).start()
        return {"ok": True}

    def _clip(self, g, k, frames, path):
        tmp = path.with_name(path.stem + ".new.mp4")
        try:
            vf = FL.grade_vf(g)
            cmd = ["ffmpeg", "-v", "error", "-y", "-nostats", "-progress", "pipe:1", "-ss", FL.ss(k, self.fps), "-i", str(self.src),
                   "-map", "0:v:0", "-vf", f"{vf + ',' if vf else ''}format=p010le", "-frames:v", str(frames),
                   *FL.enc_args(self.cfg), "-movflags", "+faststart", str(tmp)]
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for line in p.stdout:
                if line.startswith("frame="):
                    self.job["done"] = int(line.split("=", 1)[1].strip() or 0)
            err = p.stderr.read()
            if p.wait():
                raise RuntimeError(err.strip()[-600:] or "ffmpeg failed")
            tmp.replace(path)
            opened = bool(self.open_clips and hasattr(os, "startfile"))
            self.job = {**self.job, "state": "done", "done": frames, "opened": opened}
            if opened:
                os.startfile(path)
        except Exception as e:
            self.job = {**self.job, "state": "error", "error": str(e)}


class Handler(BaseHTTPRequestHandler):
    ed = None
    server_version = "color-edit"          # not the Python version
    sys_version = ""

    def log_message(self, fmt, *args):
        pass

    def send(self, code, body, ctype):
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in HEADERS.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass                                            # the page moved on (another frame was asked for)

    def json(self, obj, code=200):
        self.send(code, json.dumps(obj).encode(), "application/json")

    def own_page(self, post):
        """Whether the request comes from the editor's own page. The Host must be this server, so a website that rebinds
        its name to 127.0.0.1 can't read the footage; a POST must be JSON from this origin, which a page on another site
        can't send without a CORS preflight this server never answers, so it can't change the look or start clips."""
        port = self.server.server_address[1]
        hosts = (f"127.0.0.1:{port}", f"localhost:{port}")
        if self.headers.get("Host") not in hosts:
            return False
        if post:
            origin = self.headers.get("Origin")
            if origin is not None and origin not in tuple(f"http://{h}" for h in hosts):
                return False
            if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
                return False
        return True

    def refuse(self):
        self.close_connection = True
        self.json({"ok": False, "error": "this editor only answers its own page"}, 403)

    def fail(self, e):
        """A request that went wrong: 400 with the reason when the request was at fault (the checks raise ValueError),
        503 when the editor stayed busy, else 500 with what broke, so the page can say it either way."""
        if isinstance(e, ValueError):
            self.json({"ok": False, "error": str(e)}, 400)
        elif isinstance(e, Busy):
            self.json({"ok": False, "error": str(e)}, 503)
        else:
            self.json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)

    def do_GET(self):
        if not self.own_page(post=False):
            return self.refuse()
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path == "/":
                self.send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            elif u.path == "/api/state":
                self.json(self.ed.state())
            elif u.path == "/api/frame":
                self.send(200, self.ed.frame(self.ed.check_k(q["k"][0] if "k" in q else None))["packet"], "application/octet-stream")
            elif u.path.startswith("/api/thumb/"):
                i = u.path.rsplit("/", 1)[1]
                data = self.ed.thumb(int(i)) if i.isdigit() else b""
                self.send(200 if data else 404, data, "image/jpeg")
            elif u.path == "/api/job":
                self.json(self.ed.job)
            else:
                self.send(404, b"not found", "text/plain")
        except Exception as e:
            self.fail(e)

    def do_POST(self):
        if not self.own_page(post=True):
            return self.refuse()
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if not 0 <= n <= MAX_BODY:                          # unread, so the connection can't be reused
            self.close_connection = True
            self.json({"ok": False, "error": f"a request here is JSON of at most {MAX_BODY} bytes"}, 413 if n > MAX_BODY else 400)
            return
        try:
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                raise ValueError("the request wasn't JSON") from None
            if not isinstance(body, dict):
                raise ValueError("the request should be a JSON object")
            u = urlparse(self.path).path
            k = self.ed.check_k(body["k"]) if body.get("k") is not None else None
            if u == "/api/lut":
                self.send(200, self.ed.lut(body.get("grade"), body.get("n", 33), k), "application/octet-stream")
            elif u == "/api/save":
                self.json(self.ed.save(body.get("grade"), k))
            elif u == "/api/clip":
                if k is None:
                    raise ValueError("no frame to start the clip from")
                self.json(self.ed.clip(body.get("grade"), k, body.get("seconds", CLIP_S)))
            else:
                self.send(404, b"not found", "text/plain")
        except Exception as e:
            self.fail(e)


class Server(ThreadingHTTPServer):
    allow_reuse_address = False            # on Windows reuse would let a second editor take a port that's in use
    daemon_threads = True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true", help="don't open the page")
    ap.add_argument("--no-open", action="store_true", help="don't open finished preview clips in the player")
    a = ap.parse_args()
    Handler.ed = Editor(a.scene, open_clips=not a.no_open)
    srv = None
    for port in range(a.port, a.port + 20):
        try:
            srv = Server(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    if srv is None:
        sys.exit(f"no free port from {a.port} to {a.port + 19}")
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"color editor for {a.scene}: {url}  (Ctrl+C stops it)", flush=True)
    if not a.no_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
