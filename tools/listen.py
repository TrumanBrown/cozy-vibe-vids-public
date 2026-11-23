"""Let the audio model hear a sound before Truman does (the agent can't listen): blind first (what is it?), then rated
against what it should be. ~$0.03 per ask (Azure gpt-audio, config/azure.json audio_deployment).

  .venv\\Scripts\\python tools\\listen.py <file> [--start 10] [--want "gentle water trickling in a home aquarium"]
"""
import argparse
import base64
import json
import pathlib
import tempfile

import azure_ai  # noqa: E402
from cozy.media import run_ffmpeg

BLIND = ("Listen to this 30 second sound clip. Reply as JSON only: {\"what\": \"what this sound most likely is, in a few "
         "words\", \"real_or_synth\": \"real recording or synthesized, and why\", \"problems\": \"anything harsh, clicky, "
         "hissy, rhythmic, looping or annoying, or none\"}")
RATED = ("This sound should be: {want}. Listen to the 30 second clip and reply as JSON only: {{\"match\": 0-10 (how well it "
         "is that), \"natural\": 0-10 (sounds like a real recording), \"calm\": 0-10 (good under music for relaxing or "
         "studying), \"balance\": \"what stands out too much or too little\", \"fix\": \"the one change that would help "
         "most\"}}")


def clip(path, start, dur=30.0):
    with tempfile.TemporaryDirectory() as d:
        out = pathlib.Path(d) / "x.mp3"
        run_ffmpeg(["-v", "error", "-y", "-ss", f"{start:.1f}", "-t", f"{dur:g}", "-i", str(path), "-ac", "1",
                    "-ar", "24000", "-b:a", "64k", str(out)], capture=False)
        return base64.b64encode(out.read_bytes()).decode()


def ask(prompt, audio, purpose):
    usd = 0.0
    for attempt in range(3):
        msgs = [{"role": "user", "content": [prompt + ("\nReply with the JSON object only." if attempt else ""),
                                             {"type": "input_audio", "input_audio": {"data": audio, "format": "mp3"}}]}]
        text, usage = azure_ai.chat(msgs, deployment=azure_ai.CFG.get("audio_deployment"), purpose=purpose, max_tokens=600)
        usd += usage.get("usd_est") or 0.0
        s, e = text.find("{"), text.rfind("}")
        try:
            return json.loads(text[s: e + 1]), usd
        except json.JSONDecodeError:
            continue
    return {"error": text[:300]}, usd


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("file")
    ap.add_argument("--start", type=float, default=10.0)
    ap.add_argument("--want", default="")
    a = ap.parse_args()
    audio = clip(a.file, a.start)
    blind, u1 = ask(BLIND, audio, "listen blind")
    print("blind:", json.dumps(blind, ensure_ascii=False))
    u2 = 0.0
    if a.want:
        rated, u2 = ask(RATED.format(want=a.want), audio, "listen rated")
        print("rated:", json.dumps(rated, ensure_ascii=False))
    print(f"cost about ${u1 + u2:.3f}")


if __name__ == "__main__":
    main()
