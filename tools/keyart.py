"""Generate key-art images with the sandboxed Azure OpenAI image deployments (keyless, uses `az login`).

Usage (repo root):
  python tools/keyart.py scenes/<scene>/keyart.json [--only <id>] [--model gpt-image-2] [--n 2] [--quality high]
  python tools/keyart.py --prompt "..." --out assets/keyart/test --size 2560x1440

keyart.json: {"items": [{"id": "...", "prompt": "...", "size": "2560x1440", "quality": "high", "n": 2, "deployment": "..."}]}
Outputs: assets/keyart/<scene>/<id>_<deployment>_<k>.png  +  same name .json sidecar (prompt, model, size, quality,
timestamps, revised_prompt if returned). Endpoint/deployments come from config/azure.json (tools/azure_provision.py).
"""
import argparse
import base64
import datetime as dt
import json
import pathlib
import sys
import time

import requests

from cozy.paths import ROOT
from azure_ai import CFG, generate_image  # noqa: E402  (one client: token, retries, spend log out/azure_usage.jsonl)


def generate(prompt, deployment, size, quality, n, purpose=""):
    """One generation through azure_ai. A dropped connection is retried like a 5xx. A request that timed out or broke
    off mid-answer isn't: Azure may have made and billed that image already, so a retry could pay for it twice."""
    try:
        return generate_image(prompt, deployment=deployment, size=size, quality=quality, n=n, purpose=purpose,
                              retry_unfinished=False)
    except requests.exceptions.ConnectionError as e:
        sys.exit(f"network error ({type(e).__name__}) on every try: check the connection and run it again")
    except RuntimeError as e:          # an HTTP error, retries used up, or an unfinished request (azure_ai.Unfinished)
        sys.exit(str(e))


def run_item(item, out_dir, defaults):
    dep = item.get("deployment", defaults["deployment"])
    size, quality, n = item.get("size", defaults["size"]), item.get("quality", defaults["quality"]), item.get("n", defaults["n"])
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    print(f"{item['id']}: {dep} {size} {quality} x{n} ...", flush=True)
    res = generate(item["prompt"], dep, size, quality, n, purpose=f"keyart:{out_dir.name}:{item['id']}")
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    for k, d in enumerate(res.get("data", [])):
        base = out_dir / f"{item['id']}_{dep}_{stamp}_{k + 1}"
        base.with_suffix(".png").write_bytes(base64.b64decode(d["b64_json"]))
        meta = {"id": item["id"], "prompt": item["prompt"], "deployment": dep, "size": size, "quality": quality,
                "created": res.get("created"), "revised_prompt": d.get("revised_prompt"), "usage": res.get("usage"),
                "endpoint": CFG["endpoint"], "generated_at": stamp}
        base.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        print(f"  -> {base.with_suffix('.png').relative_to(ROOT)}", flush=True)
    print(f"  {time.time() - t0:.0f}s, usage: {res.get('usage')}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", nargs="?")
    ap.add_argument("--only", default="")
    ap.add_argument("--prompt")
    ap.add_argument("--out", default="assets/keyart/adhoc")
    ap.add_argument("--model", help="deployment name override (e.g. gpt-image-2)")
    ap.add_argument("--size", default="2560x1440")
    ap.add_argument("--quality", default="high")
    ap.add_argument("--n", type=int, default=1)
    a = ap.parse_args()
    defaults = {"deployment": a.model or CFG["default_deployment"], "size": a.size, "quality": a.quality, "n": a.n}
    if a.prompt:
        run_item({"id": "adhoc", "prompt": a.prompt}, ROOT / a.out, defaults)
        return
    if not a.spec:
        ap.error("give a keyart.json spec or --prompt")
    spec_path = pathlib.Path(a.spec)
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        sys.exit(f"no spec at {spec_path.resolve()}")
    except json.JSONDecodeError as e:
        sys.exit(f"{spec_path} isn't valid JSON: {e}")
    if not isinstance(spec.get("items"), list) or not all(isinstance(i, dict) and i.get("id") and i.get("prompt") for i in spec["items"]):
        sys.exit(f'{spec_path} needs "items": [{{"id": ..., "prompt": ...}}, ...]')
    out_dir = ROOT / "assets" / "keyart" / spec_path.parent.name
    only = set(filter(None, a.only.split(",")))
    unknown = only - {i["id"] for i in spec["items"]}
    if unknown:
        sys.exit(f"--only {', '.join(sorted(unknown))}: not in {spec_path} (ids: {', '.join(i['id'] for i in spec['items'])})")
    for item in spec["items"]:
        if only and item["id"] not in only:
            continue
        if a.model:
            item = {**item, "deployment": a.model}
        run_item(item, out_dir, {**defaults, **spec.get("defaults", {}), **({"deployment": a.model} if a.model else {})})


if __name__ == "__main__":
    main()
