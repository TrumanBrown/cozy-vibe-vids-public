"""The local vision model's server (llama.cpp's llama-server; config/local_vision.json), moved verbatim from
local_vision.py (TASKS.md T12). tools/outdoor_check.py starts and stops it from here, so it no longer imports
local_vision.py, which imports outdoor_check for its comparisons: the two don't import each other any more.

  serve() / stop()   start it with the model in use and wait until it answers; stop the one this started (frees the GPU)
  up(cfg())          whether it answers; model() the model in use, loaded() the one the server has
  auth()             the header every request to it carries: the server takes requests with its key only

The server listens on 127.0.0.1 with an API key (out/local_vision/server.key, made once, never committed) and answers
browsers only from localhost pages, so a website open while a check runs can't use it; the model files are checked
against the SHA-256 in the config before it starts (security review 2026-10-26).
"""
import hashlib
import json
import os
import pathlib
import secrets
import signal
import subprocess
import time
import urllib.parse

import requests

from cozy.paths import ROOT
OUT = ROOT / "out" / "local_vision"
PIDF = OUT / "server.pid"
KEYF = OUT / "server.key"
CHECKED = OUT / "checked.json"


def api_key():
    if not KEYF.exists():
        OUT.mkdir(parents=True, exist_ok=True)
        KEYF.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    return KEYF.read_text(encoding="utf-8").strip()


def auth():
    return {"Authorization": f"Bearer {api_key()}"}


def check_files(mc):
    """The model and its projector must be the files the config names (models.<m>.sha256: Hugging Face's own hashes).
    A file checked before at the same size and time isn't read again (out/local_vision/checked.json)."""
    seen = json.loads(CHECKED.read_text(encoding="utf-8")) if CHECKED.exists() else {}
    for part, want in sorted((mc.get("sha256") or {}).items()):
        p = ROOT / mc[part]
        st = p.stat()
        stamp = [st.st_size, st.st_mtime_ns, want.lower()]
        if seen.get(mc[part]) == stamp:
            continue
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 24), b""):
                h.update(chunk)
        if h.hexdigest() != want.lower():
            raise RuntimeError(f"{p} isn't the file config/local_vision.json names (SHA-256 {h.hexdigest()}, "
                               f"not {want.lower()}): download it again (docs/SETUP.md section 7)")
        seen[mc[part]] = stamp
        OUT.mkdir(parents=True, exist_ok=True)
        CHECKED.write_text(json.dumps(seen, indent=1), encoding="utf-8")


def cfg():
    from azure_ai import local_cfg
    return local_cfg()


def model():
    from azure_ai import local_model
    return local_model()


def base_url(lc):
    return lc["endpoint"].rstrip("/").rsplit("/v1", 1)[0]


def up(lc):
    try:
        return requests.get(base_url(lc) + "/health", headers=auth(), timeout=3).status_code == 200
    except requests.exceptions.RequestException:
        return False


def loaded(lc):
    """The model file the running server has loaded (its /v1/models id), or None."""
    try:
        data = requests.get(base_url(lc) + "/v1/models", headers=auth(), timeout=5).json().get("data") or []
        return pathlib.Path(str(data[0].get("id", ""))).name if data else None
    except (requests.exceptions.RequestException, ValueError):
        return None


def serve(wait_s=600, detach=True):
    """Start llama-server with the model in use (COZY_LOCAL_MODEL, else the config's active one) unless it answers
    already with that model. Returns True when this call started it; raises RuntimeError when it can't run (a machine
    without the setup in docs/SETUP.md: callers like outdoor_check then stay on Azure)."""
    lc = cfg()
    name, mc = model()
    if up(lc):
        have = loaded(lc)
        if have and have != pathlib.Path(mc["model"]).name:
            if not PIDF.exists():
                raise RuntimeError(f"a server with {have} is running at {lc['endpoint']}, not {name}; stop it first")
            stop()
        else:
            print(f"local vision: {name} already running at {lc['endpoint']}")
            return False
    sv = lc["server"]
    for p in (sv["exe"], mc["model"], mc["mmproj"]):
        if not (ROOT / p).exists():
            raise RuntimeError(f"missing {ROOT / p} (config/local_vision.json; setup: docs/SETUP.md)")
    check_files(mc)
    api_key()
    u = urllib.parse.urlparse(lc["endpoint"])
    cmd = [str(ROOT / sv["exe"]), "-m", str(ROOT / mc["model"]), "--mmproj", str(ROOT / mc["mmproj"]),
           "-c", str(mc.get("ctx", 16384)), "--host", u.hostname, "--port", str(u.port),
           "--api-key-file", str(KEYF), "--cors-origins", "localhost", *[str(a) for a in sv.get("args", [])]]
    OUT.mkdir(parents=True, exist_ok=True)
    log = open(OUT / "server.log", "w", encoding="utf-8")
    flags = 0
    if os.name == "nt" and detach:
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    p = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, creationflags=flags, cwd=str(ROOT))
    PIDF.write_text(str(p.pid))
    t0 = time.time()
    while time.time() - t0 < wait_s:
        if p.poll() is not None:
            PIDF.unlink(missing_ok=True)
            raise RuntimeError(f"llama-server exited ({p.returncode}); see {OUT / 'server.log'}")
        if up(lc):
            print(f"local vision: {name} ready at {lc['endpoint']} in {time.time() - t0:.0f} s (pid {p.pid})")
            return True
        time.sleep(2)
    stop()
    raise RuntimeError(f"llama-server didn't answer within {wait_s} s; see {OUT / 'server.log'}")


def stop():
    if not PIDF.exists():
        print("local vision: no server started by this tool")
        return 0
    pid = int(PIDF.read_text().strip())
    if os.name == "nt":
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, text=True)
        alive = "llama-server" in r.stdout
        if alive:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        cmdline = pathlib.Path(f"/proc/{pid}/cmdline")
        alive = cmdline.exists() and b"llama-server" in cmdline.read_bytes()
        if alive:
            os.kill(pid, signal.SIGTERM)
    print(f"local vision: stopped (pid {pid})" if alive else f"local vision: pid {pid} isn't running")
    PIDF.unlink(missing_ok=True)
    return 0
