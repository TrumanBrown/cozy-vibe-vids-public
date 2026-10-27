"""Provision (idempotently) the sandboxed Azure image-generation resources for this repo.

Everything lives in ONE dedicated resource group so nothing else in the tenant is touched:
  resource group  rg-cozyvibevids-img          (tags: project=cozy-vibe-vids, owner=agent)
  AI Services     cvvimg-<suffix>             (kind AIServices, custom subdomain, API keys DISABLED)
  deployments     gpt-image-2-5-sunburst, gpt-image-2   (GlobalStandard, capacity 1): key art
                  gpt-6-sol                             (GlobalStandard, 100K TPM): vision analysis + QA (tools/azure_ai.py)
                  gpt-audio-1-5                         (GlobalStandard, 10K TPM): listens to music (tools/music_screen.py)
  role            "Cognitive Services OpenAI User" for the signed-in user (keyless Entra ID auth)

Usage (repo root, after `az login`):
  python tools/azure_provision.py            # create/verify; writes config/azure.json (no secrets)
  python tools/azure_provision.py --teardown # delete the whole resource group (asks to confirm)

Non-secret settings are committed in config/azure.json, so another machine only needs
`az login` + (if the resource group was torn down) a re-run of this script.
"""
import argparse
import json
import secrets
import subprocess
import sys
import time

from cozy.paths import ROOT
CFG = ROOT / "config" / "azure.json"
DEFAULTS = {
    "resource_group": "rg-cozyvibevids-img",
    "location": "eastus2",
    "account": None,  # filled on first run: cvvimg-<6 hex>
    "api_version": "2025-04-01-preview",
    "deployments": [
        {"name": "gpt-image-2-5-sunburst", "model": "gpt-image-2.5-sunburst", "version": "2026-09-08", "sku": "GlobalStandard", "capacity": 1},
        {"name": "gpt-image-2", "model": "gpt-image-2", "version": "2026-04-21", "sku": "GlobalStandard", "capacity": 1},
        {"name": "gpt-6-sol", "model": "gpt-6-sol", "version": "2026-09-22", "sku": "GlobalStandard", "capacity": 100},
        {"name": "gpt-audio-1-5", "model": "gpt-audio-1.5", "version": "2026-02-23", "sku": "GlobalStandard", "capacity": 10},
    ],
    "default_deployment": "gpt-image-2-5-sunburst",
    "vision_deployment": "gpt-6-sol",
    "audio_deployment": "gpt-audio-1-5",
    "tags": {"project": "cozy-vibe-vids", "purpose": "image-generation", "owner": "agent"},
}

from azure_ai import AZ  # noqa: E402  (the one place the az CLI is found)


def az(*args, check=True, parse=True):
    try:
        r = subprocess.run([AZ, *args, "-o", "json"], capture_output=True, text=True)
    except FileNotFoundError:
        raise SystemExit("the Azure CLI (az) isn't installed or isn't on PATH: install it, then run `az login` (docs/SETUP.md)")
    if check and r.returncode != 0:
        raise SystemExit(f"az {' '.join(args)} failed:\n{r.stderr.strip()}")
    if r.returncode != 0:
        return None
    return json.loads(r.stdout) if parse and r.stdout.strip() else r.stdout


def load_cfg():
    cfg = dict(DEFAULTS)
    if CFG.exists():
        cfg.update(json.loads(CFG.read_text(encoding="utf-8")))
    return cfg


# The account's IDs stay with `az account show`, out of the committed config: the repo is public (security review
# 2026-10-26). Nothing here needs them; an old config's copies are dropped on the next save.
PRIVATE = ("subscription_id", "tenant_id")


def save_cfg(cfg):
    CFG.parent.mkdir(parents=True, exist_ok=True)
    CFG.write_text(json.dumps({k: v for k, v in cfg.items() if k not in PRIVATE}, indent=2) + "\n", encoding="utf-8")


def provision():
    acct = az("account", "show")
    print(f"subscription: {acct['name']} ({acct['id']}) as {acct['user']['name']}")
    cfg = load_cfg()
    if not cfg.get("account"):
        cfg["account"] = f"cvvimg-{secrets.token_hex(3)}"
    rg, loc, name = cfg["resource_group"], cfg["location"], cfg["account"]
    tags = [f"{k}={v}" for k, v in cfg["tags"].items()]

    print(f"resource group {rg} ({loc})")
    az("group", "create", "-n", rg, "-l", loc, "--tags", *tags)

    existing = az("cognitiveservices", "account", "show", "-g", rg, "-n", name, check=False)
    if not existing:
        print(f"creating AI Services account {name} (keys disabled, Entra ID only)")
        az("cognitiveservices", "account", "create", "-g", rg, "-n", name, "-l", loc, "--kind", "AIServices",
           "--sku", "S0", "--custom-domain", name, "--tags", *tags, "--yes")
    # Disable key auth (keyless only). Idempotent.
    rid = az("cognitiveservices", "account", "show", "-g", rg, "-n", name)["id"]
    az("resource", "update", "--ids", rid, "--set", "properties.disableLocalAuth=true")
    endpoint = az("cognitiveservices", "account", "show", "-g", rg, "-n", name)["properties"]["endpoint"]
    cfg["endpoint"] = endpoint

    have = {d["name"] for d in (az("cognitiveservices", "account", "deployment", "list", "-g", rg, "-n", name) or [])}
    for d in cfg["deployments"]:
        if d["name"] in have:
            print(f"deployment {d['name']}: exists")
            continue
        print(f"deploying {d['model']} {d['version']} as {d['name']}")
        az("cognitiveservices", "account", "deployment", "create", "-g", rg, "-n", name, "--deployment-name", d["name"],
           "--model-name", d["model"], "--model-version", d["version"], "--model-format", "OpenAI",
           "--sku-name", d["sku"], "--sku-capacity", str(d["capacity"]))

    me = az("ad", "signed-in-user", "show")["id"]
    role = "Cognitive Services OpenAI User"
    assigned = az("role", "assignment", "list", "--assignee", me, "--scope", rid, "--role", role)
    if not assigned:
        print(f"granting '{role}' to signed-in user on {name}")
        az("role", "assignment", "create", "--assignee-object-id", me, "--assignee-principal-type", "User",
           "--role", role, "--scope", rid)
        print("  (role assignments can take a few minutes to propagate)")
    save_cfg(cfg)
    print(f"\nendpoint: {endpoint}\nconfig written: {CFG.relative_to(ROOT)}")


def teardown():
    cfg = load_cfg()
    rg = cfg["resource_group"]
    if input(f"Delete resource group {rg} and everything in it? type the name to confirm: ").strip() != rg:
        sys.exit("aborted")
    az("group", "delete", "-n", rg, "--yes", "--no-wait", parse=False)
    print(f"deleting {rg} (async). Purge the soft-deleted account later with:\n"
          f"  az cognitiveservices account purge -g {rg} -n {cfg.get('account')} -l {cfg['location']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--teardown", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    teardown() if a.teardown else provision()
    print(f"done in {time.time() - t0:.0f}s")
