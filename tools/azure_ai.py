"""Shared client for the sandboxed Azure AI deployments (keyless: `az login`), with a spend log.

Every call appends one line to out/azure_usage.jsonl (time, deployment, purpose, tokens, estimated USD from
config/azure.json "prices_usd_per_1m"), so a run can be held to a budget. Real charges: Azure portal.

chat() can send a vision call to a local model instead (config/local_vision.json: llama.cpp's server on this PC's GPU,
started by tools/local_vision.py): every purpose listed in its "purposes" (none: nothing is decided by the local model
alone), or every call when COZY_VISION=local; COZY_VISION=azure keeps everything on Azure. backend="local" or "azure"
picks outright: tools/outdoor_check.py screens with the local model and leaves the final word to Azure (Truman
2026-10-22). Local calls are logged at $0.

Library:
  from azure_ai import chat_json, vision_json, generate_image, spend
  vision_json(prompt, images=[path_or_PIL, ...], purpose="analyze:<plate>")  -> dict (JSON mode)

CLI (repo root):
  .venv/Scripts/python tools/azure_ai.py spend [--since 2026-10-16]     # estimated spend from the log
  .venv/Scripts/python tools/azure_ai.py ask "question" [--image a.png]  # quick vision check
"""
import argparse
import base64
import datetime as dt
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

import requests

from cozy.paths import ROOT, config
CFG = config("azure")
LOCAL_CFG = ROOT / "config" / "local_vision.json"
LOG = ROOT / "out" / "azure_usage.jsonl"
AZ = shutil.which("az") or shutil.which("az.cmd") or "az"
_token = {"v": None, "exp": 0}


def token():
    if _token["v"] and time.time() < _token["exp"] - 300:
        return _token["v"]
    try:
        r = subprocess.run([AZ, "account", "get-access-token", "--resource", "https://cognitiveservices.azure.com", "-o", "json"],
                           capture_output=True, text=True)
    except FileNotFoundError:
        sys.exit("the Azure CLI (az) isn't installed or isn't on PATH: install it, then run `az login` (docs/SETUP.md)")
    if r.returncode != 0:
        sys.exit(f"az token failed (run `az login`):\n{r.stderr}")
    j = json.loads(r.stdout)
    _token.update(v=j["accessToken"], exp=float(j.get("expires_on", time.time() + 3000)))
    return _token["v"]


def _price(deployment):
    p = CFG.get("prices_usd_per_1m", {}).get(deployment) or {}
    return float(p.get("input", 0)), float(p.get("output", 0))


def log_usage(deployment, kind, usage, purpose="", extra=None):
    """Append one call to the spend log; returns the estimated cost (USD)."""
    usage = usage or {}
    tin = int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0)
    tout = int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0)
    pin, pout = _price(deployment)
    usd = round((tin * pin + tout * pout) / 1e6, 5)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    rec = {"t": dt.datetime.now().isoformat(timespec="seconds"), "deployment": deployment, "kind": kind,
           "purpose": purpose, "in": tin, "out": tout, "usd_est": usd, **(extra or {})}
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    return usd


_skipped_noted = []


def usage_records():
    """The spend log's records, oldest first. A line cut short by a stopped run is skipped (noted once on stderr), so it
    can't break the budget guard or a run's spend report."""
    if not LOG.exists():
        return []
    recs, bad = [], 0
    for line in LOG.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            r = None
        if isinstance(r, dict):
            recs.append(r)
        else:
            bad += 1
    if bad and not _skipped_noted:
        _skipped_noted.append(bad)
        print(f"spend log: skipped {bad} unreadable line(s) in {LOG}", file=sys.stderr)
    return recs


def spend(since=None):
    """(total USD, per-kind dict) from the log, optionally since an ISO date."""
    tot, per = 0.0, {}
    for r in usage_records():
        if since and str(r.get("t", "")) < since:
            continue
        usd = float(r.get("usd_est") or 0)
        k = f"{r.get('deployment')} {r.get('kind')}"
        tot += usd
        n, u = per.get(k, (0, 0.0))
        per[k] = (n + 1, u + usd)
    return tot, per


def budget_guard(limit_usd, since):
    """Exit before a call if the logged estimate has reached the run's budget."""
    tot, _ = spend(since)
    if tot >= limit_usd:
        sys.exit(f"budget guard: estimated spend ${tot:.2f} since {since} has reached ${limit_usd:.2f}")
    return tot


def daily_cap():
    """Today's cap on the logged Azure estimate (config/azure.json daily_cap_usd; COZY_DAILY_CAP_USD overrides it for one
    run, 0 turns it off)."""
    env = os.environ.get("COZY_DAILY_CAP_USD", "").strip()
    try:
        return float(env) if env else float(CFG.get("daily_cap_usd") or 0)
    except ValueError:
        sys.exit(f"COZY_DAILY_CAP_USD={env!r} isn't a number of dollars")


def daily_guard():
    """Stop before an Azure call once today's logged estimate has reached the daily cap, so a tool stuck in a loop can't
    run up the bill overnight. The busiest day so far logged $16 (2026-10-25)."""
    cap = daily_cap()
    if cap <= 0:
        return
    today = dt.date.today().isoformat()
    tot, _ = spend(today)
    if tot >= cap:
        sys.exit(f"daily cap: today's estimated Azure spend ${tot:.2f} has reached ${cap:.2f}. Nothing was sent. Raise "
                 "daily_cap_usd in config/azure.json, or set COZY_DAILY_CAP_USD for one run, if this much is meant")


class Unfinished(RuntimeError):
    """A request that timed out or broke off mid-answer and wasn't retried: Azure may have done and billed the work."""


def _post(url, body=None, files=None, data=None, timeout=600, retry_unfinished=True):
    # network errors are retried like a 5xx: a connection reset by the remote host in the middle of the Minecraft tea
    # house's outdoor check killed the whole check, and autopilot read the crash as a failed gate (2026-10-22).
    # retry_unfinished=False (every image call): a request that timed out or broke off mid-answer isn't retried, since
    # Azure may have made and billed that image already and a retry could pay for it twice (2026-10-26).
    daily_guard()
    unfinished = (requests.exceptions.Timeout, requests.exceptions.ChunkedEncodingError)
    for attempt in range(6):
        headers = {"Authorization": f"Bearer {token()}"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            r = requests.post(url, headers=headers, json=body, files=files, data=data, timeout=timeout)
        except (requests.exceptions.ConnectionError, *unfinished) as e:
            # a connect timeout is a ConnectionError too: the request never reached Azure, so it is always retried
            if not retry_unfinished and not isinstance(e, requests.exceptions.ConnectionError):
                raise Unfinished(f"no complete answer from Azure ({type(e).__name__}). It may have made and billed the work "
                                 "anyway: check the deployment's usage in the Azure portal before running it again") from e
            if attempt == 5:
                raise
            wait = 10 * (attempt + 1)
            print(f"  network error ({type(e).__name__}): retrying in {wait}s", flush=True)
            time.sleep(wait)
            continue
        # DeploymentNotFound: seen for a few minutes after tools/azure_provision.py creates a deployment
        if (r.status_code in (429, 500, 502, 503, 504) or (r.status_code in (401, 403) and attempt < 3)
                or (r.status_code == 404 and "DeploymentNotFound" in r.text and attempt < 5)):
            wait = int(r.headers.get("retry-after", 0) or 0) or 15 * (attempt + 1)
            print(f"  {r.status_code}: retrying in {wait}s ({r.text[:160]})", flush=True)
            time.sleep(wait)
            continue
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:2000]}")
        return r.json()
    raise RuntimeError("gave up after retries")


def image_data_url(img, max_side=1600, fmt="JPEG", quality=90):
    """Path or PIL image -> data URL (downscaled so the long side is <= max_side)."""
    from PIL import Image
    im = Image.open(img) if isinstance(img, (str, pathlib.Path)) else img
    im = im.convert("RGB")
    s = max_side / max(im.size)
    if s < 1:
        im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, fmt, quality=quality) if fmt == "JPEG" else im.save(buf, fmt)
    return f"data:image/{fmt.lower()};base64,{base64.b64encode(buf.getvalue()).decode()}"


def local_cfg():
    return json.loads(LOCAL_CFG.read_text(encoding="utf-8")) if LOCAL_CFG.exists() else {}


def local_model(lc=None):
    """(name, settings) of the local model in use: COZY_LOCAL_MODEL, else the config's "active"."""
    lc = lc or local_cfg()
    name = os.environ.get("COZY_LOCAL_MODEL") or lc.get("active")
    if name not in (lc.get("models") or {}):
        raise RuntimeError(f"local model {name!r} isn't in {LOCAL_CFG} models")
    return name, lc["models"][name]


def use_local(purpose, deployment=None):
    """Whether a vision call goes to the local model (module docstring). An explicit deployment other than the vision
    one (an image or audio model) always stays on Azure."""
    if deployment and deployment != CFG["vision_deployment"]:
        return False
    env = os.environ.get("COZY_VISION", "").strip().lower()
    if env in ("azure", "local"):
        return env == "local"
    return any(purpose == p or purpose.startswith(p + ":") for p in local_cfg().get("purposes") or [])


def _local_chat(msgs, purpose, json_mode, max_tokens):
    lc = local_cfg()
    name, mc = local_model(lc)
    for m in msgs:                                     # llama-server takes the OpenAI parts; Azure's "detail" is dropped
        if isinstance(m["content"], list):
            for p in m["content"]:
                if p.get("type") == "image_url":
                    p["image_url"].pop("detail", None)
    body = {"model": name, "messages": msgs, "max_tokens": min(max_tokens, int(mc.get("max_tokens", 4096))),
            **(mc.get("sampling") or {}), **(mc.get("request") or {})}
    # a thinking model is left free to think: the JSON is taken from its answer (vision_json) instead of a grammar
    if json_mode and mc.get("json_mode", True):
        body["response_format"] = {"type": "json_object"}
    t0 = time.time()
    from cozy.llama import auth                        # the server takes requests with its key only
    try:
        r = requests.post(lc["endpoint"].rstrip("/") + "/chat/completions", json=body, headers=auth(),
                          timeout=lc.get("timeout_s", 600))
    except requests.exceptions.ConnectionError:
        raise RuntimeError(f"the local vision model isn't running at {lc['endpoint']}: "
                           ".venv\\Scripts\\python tools\\local_vision.py serve")
    if r.status_code == 401:
        raise RuntimeError(f"the local server at {lc['endpoint']} refused this process's key (out/local_vision/server.key "
                           "changed since it started): .venv\\Scripts\\python tools\\local_vision.py stop, then serve")
    if r.status_code != 200:
        raise RuntimeError(f"local model HTTP {r.status_code}: {r.text[:2000]}")
    res = r.json()
    text = res["choices"][0]["message"].get("content") or ""
    usage = res.get("usage") or {}
    log_usage(f"local:{name}", "chat", usage, purpose, {"s": round(time.time() - t0, 1)})
    return text, {**usage, "usd_est": 0.0, "local": name}


def chat(messages, deployment=None, purpose="", json_mode=False, max_tokens=8000, effort=None, detail="high", backend=None):
    """Chat completion; returns (text, usage). Image parts may be given as {"image": path_or_PIL}. backend "local" or
    "azure" picks the model outright (outdoor_check's first pass and final word); None routes by config."""
    dep = deployment or CFG["vision_deployment"]
    msgs = []
    for m in messages:
        c = m["content"]
        if isinstance(c, list):
            parts = []
            for p in c:
                if isinstance(p, str):
                    parts.append({"type": "text", "text": p})
                elif "image" in p:
                    parts.append({"type": "image_url", "image_url": {"url": image_data_url(p["image"], p.get("max_side", 1600)), "detail": detail}})
                else:
                    parts.append(p)
            c = parts
        msgs.append({"role": m["role"], "content": c})
    if backend == "local" or (backend is None and use_local(purpose, deployment)):
        return _local_chat(msgs, purpose, json_mode, max_tokens)
    body = {"messages": msgs, "max_completion_tokens": max_tokens}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if effort:
        body["reasoning_effort"] = effort
    url = f"{CFG['endpoint']}openai/deployments/{dep}/chat/completions?api-version={CFG['api_version']}"
    t0 = time.time()
    res = _post(url, body)
    text = res["choices"][0]["message"].get("content") or ""
    usd = log_usage(dep, "chat", res.get("usage"), purpose, {"s": round(time.time() - t0, 1)})
    return text, {**(res.get("usage") or {}), "usd_est": usd}


def vision_json(prompt, images=(), system=None, purpose="", effort="medium", max_tokens=12000, max_side=1600, backend=None):
    """Ask the vision model for a JSON object about one or more images."""
    content = [prompt] + [{"image": im, "max_side": max_side} for im in images]
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": content}]
    text, usage = chat(msgs, purpose=purpose, json_mode=True, effort=effort, max_tokens=max_tokens, backend=backend)
    try:
        return json.loads(text), usage
    except json.JSONDecodeError:
        s, e = text.find("{"), text.rfind("}")
        return json.loads(text[s: e + 1]), usage


def generate_image(prompt, deployment=None, size="2560x1440", quality="high", n=1, purpose="", background=None,
                   retry_unfinished=False):
    """gpt-image generation; returns the API JSON (b64 images in data[].b64_json). background="transparent" for sprites.
    A request that timed out or broke off isn't sent again (raises Unfinished; see _post): Azure may have made and billed
    the image already. retry_unfinished=True sends it again anyway."""
    dep = deployment or CFG["default_deployment"]
    url = f"{CFG['endpoint']}openai/deployments/{dep}/images/generations?api-version={CFG['api_version']}"
    body = {"prompt": prompt, "n": n, "size": size, "quality": quality, "output_format": "png"}
    if background:
        body["background"] = background
    res = _post(url, body, retry_unfinished=retry_unfinished)
    log_usage(dep, "image", res.get("usage"), purpose, {"n": n, "size": size, "quality": quality})
    return res


def edit_image(image, prompt, mask=None, deployment=None, size="2560x1440", quality="high", purpose="", background=None, images=(),
               retry_unfinished=False):
    """gpt-image edit (inpainting where `mask` alpha is 0, if given); returns the API JSON. background="transparent" for
    sprites; `images`: more reference images sent with it (the first is `image`). Like generate_image, an unfinished
    request isn't sent again unless retry_unfinished=True."""
    dep = deployment or CFG["default_deployment"]
    url = f"{CFG['endpoint']}openai/deployments/{dep}/images/edits?api-version={CFG['api_version']}"

    def png(x):
        from PIL import Image
        im = Image.open(x) if isinstance(x, (str, pathlib.Path)) else x
        b = io.BytesIO()
        im.save(b, "PNG")
        return b.getvalue()
    if images:
        files = [("image[]", (f"image{i}.png", png(x), "image/png")) for i, x in enumerate([image, *images])]
        if mask is not None:
            files.append(("mask", ("mask.png", png(mask), "image/png")))
    else:
        files = {"image": ("image.png", png(image), "image/png")}
        if mask is not None:
            files["mask"] = ("mask.png", png(mask), "image/png")
    data = {"prompt": prompt, "size": size, "quality": quality, "n": "1"}
    if background:
        data["background"] = background
    res = _post(url, files=files, data=data, retry_unfinished=retry_unfinished)
    log_usage(dep, "image_edit", res.get("usage"), purpose, {"size": size})
    return res


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("spend")
    s.add_argument("--since")
    q = sub.add_parser("ask")
    q.add_argument("question")
    q.add_argument("--image", action="append", default=[])
    a = ap.parse_args()
    if a.cmd == "spend":
        tot, per = spend(a.since)
        for k, (n, u) in sorted(per.items()):
            print(f"  {k:40s} {n:4d} calls  ${u:7.3f}")
        print(f"estimated total: ${tot:.2f}" + (f" since {a.since}" if a.since else ""))
    elif a.cmd == "ask":
        text, usage = chat([{"role": "user", "content": [a.question] + [{"image": p} for p in a.image]}], purpose="ask")
        print(text)
        print(f"[{usage.get('prompt_tokens')} in, {usage.get('completion_tokens')} out, ~${usage['usd_est']:.4f}]")


if __name__ == "__main__":
    main()
