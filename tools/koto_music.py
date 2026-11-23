"""Koto music for the Yuzu Spring video (look pencil-night): old Japanese melodies and new pieces, played in code.

Not in use: on the sample (2026-11-12) Truman found the music weird and the video went back to the Minecraft allowlist
(lessons L222). Kept for the record of what was tried; the look's music no longer points here.

Truman asked for old-timey Japanese music. No recordings of real Japanese pieces could be found under CC0 for a
monetized video (Free Music Archive's are CC BY-NC, archive.org's license marks can't be trusted, Pixabay and Kevin
MacLeod aren't CC0), so this tool makes its own performances (2026-11-12). No AI model makes any of it.

  fetch    download the source recordings: RutgerMuller's koto improvisations on Freesound (pack "Acoustic Ethnic
           Instruments - Melodic and Drone", CC0 1.0), the HQ preview MP3s, which need no login. Each page is read
           again and must still show Creative Commons 0. Kept in out/koto_music/src/.
  mine     look for clean single plucks in them (onsets by spectral flux, pitch by YIN on the first 150 ms; kept when
           the string was quiet before, rang 1.2 s with no new note 20 dB or less below it, and held its pitch) and
           measure how a koto string decays: each partial's decay rate against its frequency. The sessions are fast
           amateur playing: of 6,670 onsets only 15 plucks pass (56 with looser limits), most cut off after about a
           second, with big gaps in pitch. Too few for a sampler, so the koto is a physical model tuned to those
           measurements (out/koto_music/calibration.json), and no audio from the recordings is in the tracks.
  render   the playlist into music/pencil-night/: public-domain melodies (Sakura Sakura, Kojo no Tsuki, Furusato,
           Yuki, Nanatsu no Ko, Usagi) arranged for koto, and new pieces in the in (miyako-bushi), yo and min'yo
           scales. The koto: modal synthesis of a plucked string (partials with the pluck point's comb, two
           polarizations that decay at different rates, a tension glide at the attack, a plectrum click), with
           pressed bends (oshide, tsuki-iro), vibrato (yuri-iro), octaves and grace notes; velocity sets level and
           brightness. Two string voices: "tetron" rings longer, "silk" (the pre-war string) dies sooner and is more
           nasal; the audio model heard four pieces as piano with tetron, and silk fixed two of them. Slow, rubato,
           with space between phrases. A warm small room (a seeded synthetic stereo impulse response) and a softened
           top end give the old-record color; no vinyl crackle, hiss or wow (they read as fire or rain over the
           ambience). 44.1 kHz stereo MP3 at 256 kbps, -20 LUFS, true peak under -1.5 dBTP, a sidecar each.
           Haru no Ogawa and a piece called Snow on the Rocks were dropped: the audio model heard them as piano.
  ledger   append the source recordings and the finished tracks to docs/asset-ledger.csv (rows already there stay).

All randomness is seeded from the track's name and nothing reads the clock, so a run gives the same files to the bit.

  .venv\\Scripts\\python tools\\koto_music.py fetch
  .venv\\Scripts\\python tools\\koto_music.py mine
  .venv\\Scripts\\python tools\\koto_music.py render [--only sakura,yuki] [--out music\\pencil-night] [--jobs 3]
  .venv\\Scripts\\python tools\\koto_music.py ledger
"""
import argparse
import csv
import hashlib
import json
import pathlib
import sys
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from cozy.ledger import LEDGER, row as ledger_row
from cozy.media import run_ffmpeg
from cozy.paths import ROOT

SR = 44100
WORK = ROOT / "out" / "koto_music"
SRC = WORK / "src"
OUT = ROOT / "music" / "pencil-night"
VERIFIED = "2026-11-12"
ARTIST, ALBUM = "Yuzu Spring Ensemble", "Yuzu Spring"
PACK = "https://freesound.org/people/RutgerMuller/packs/20565/"
CC0_URL = "https://creativecommons.org/publicdomain/zero/1.0/"
TARGET_LUFS, PEAK_DBTP = -20.0, -1.6
SOURCES = [
    {"id": "364807", "title": "Japan_Koto_My_Amateur_Improv_Session_1.wav", "dur": "10:59",
     "preview": "https://cdn.freesound.org/previews/364/364807_179538-hq.mp3"},
    {"id": "365215", "title": "Japan_Koto_My_Amateur_Improv_Session_2.wav", "dur": "10:20",
     "preview": "https://cdn.freesound.org/previews/365/365215_179538-hq.mp3"},
    {"id": "365242", "title": "Japan_Koto_Improv_Amateur_Session_3.wav", "dur": "12:59",
     "preview": "https://cdn.freesound.org/previews/365/365242_179538-hq.mp3"},
]
for _s in SOURCES:
    _s["page"] = f"https://freesound.org/people/RutgerMuller/sounds/{_s['id']}/"
    _s["file"] = SRC / f"{_s['id']}-hq.mp3"


def seed_of(*parts):
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:12], 16)


def decode(path, sr=SR, ch=1):
    raw = run_ffmpeg(["-v", "error", "-i", str(path), "-vn", "-ac", str(ch), "-ar", str(sr), "-f", "f32le", "-"]).stdout
    x = np.frombuffer(raw, np.float32).astype(np.float64)
    return x.reshape(-1, ch) if ch > 1 else x


# ---------------------------------------------------------------------------------------------------------------- fetch

def fetch(force=False):
    from music_fetch import get
    SRC.mkdir(parents=True, exist_ok=True)
    for s in SOURCES:
        html = get(s["page"])
        if "publicdomain/zero" not in html or "Creative Commons 0" not in html:
            sys.exit(f"{s['page']}: the page no longer shows Creative Commons 0; not using it")
        if force or not s["file"].exists():
            s["file"].write_bytes(get(s["preview"], binary=True))
        print(f"  {s['id']} {s['title']}: Creative Commons 0 on the page, {s['file'].stat().st_size / 1e6:.1f} MB, "
              f"sha256 {hashlib.sha256(s['file'].read_bytes()).hexdigest()[:16]}", flush=True)


# ----------------------------------------------------------------------------------------------------------------- mine

HOP, NFFT = 256, 2048


def frames(x, n, hop):
    m = 1 + (len(x) - n) // hop
    return np.lib.stride_tricks.as_strided(x, (m, n), (x.strides[0] * hop, x.strides[0]), writeable=False)


def onset_flux(x):
    """Spectral flux of log magnitudes (60 Hz to 8 kHz), one value per HOP."""
    w = np.hanning(NFFT).astype(np.float32)
    F = frames(np.ascontiguousarray(x, np.float32), NFFT, HOP)
    lo, hi = int(60 * NFFT / SR), int(8000 * NFFT / SR)
    flux, prev = np.zeros(len(F), np.float32), None
    for a in range(0, len(F), 4096):
        M = np.log1p(100 * np.abs(np.fft.rfft(F[a: a + 4096] * w, axis=1))[:, lo:hi])
        d = np.diff(M, axis=0, prepend=(M[:1] if prev is None else prev[None]))
        flux[a: a + len(M)] = np.maximum(d, 0).sum(1)
        prev = M[-1]
    return flux


def pick_onsets(flux):
    """Flux peaks above the local median (0.5 s) by a margin, at least 60 ms apart."""
    k = int(0.5 * SR / HOP) | 1
    med = np.median(frames(np.pad(flux, k // 2, mode="edge").astype(np.float64), k, 1), axis=1)[:len(flux)]
    loc = (flux >= np.roll(flux, 1)) & (flux >= np.roll(flux, -1)) & (flux > med + 0.35 * np.std(flux) + 0.5)
    out = []
    for i in np.nonzero(loc)[0]:
        if out and i - out[-1] < int(0.06 * SR / HOP):
            if flux[i] > flux[out[-1]]:
                out[-1] = i
            continue
        out.append(i)
    return np.array(out, int)


def yin(x, fmin=75.0, fmax=1300.0):
    """(f0 in Hz, aperiodicity) of a short window by YIN."""
    tmax, tmin = int(SR / fmin), int(SR / fmax)
    W = len(x) - tmax
    if W < 256:
        return 0.0, 1.0
    d = np.array([np.sum((x[:W] - x[t: t + W]) ** 2) for t in range(tmax + 1)])
    cm = np.concatenate([[1.0], d[1:] * np.arange(1, tmax + 1) / np.maximum(np.cumsum(d[1:]), 1e-12)])
    cand = np.nonzero(cm[tmin:] < 0.15)[0]
    t = (cand[0] + tmin) if len(cand) else int(np.argmin(cm[tmin:])) + tmin
    while t + 1 <= tmax and cm[t + 1] < cm[t]:
        t += 1
    off = 0.0
    if 1 <= t < tmax:
        a, b, c = cm[t - 1], cm[t], cm[t + 1]
        off = 0.5 * (a - c) / (a - 2 * b + c) if abs(a - 2 * b + c) > 1e-12 else 0.0
    return SR / (t + off), float(cm[t])


def clean_plucks(x, strict=True):
    """Isolated plucks: (start sample, clean length in samples, f0, aperiodicity, pitch drift in cents)."""
    on = pick_onsets(onset_flux(x))
    env = 20 * np.log10(np.sqrt(np.convolve(x ** 2, np.ones(441) / 441, mode="same")) + 1e-9)    # 10 ms RMS, dB
    rise_min, keep_min = (14.0, 1.2) if strict else (12.0, 0.7)
    out = []
    for j, f in enumerate(on):
        t0 = f * HOP + NFFT // 2
        lo, hi = t0 - int(0.04 * SR), t0 + int(0.08 * SR)
        if lo < int(0.3 * SR) or hi + 3 * SR >= len(x):
            continue
        pk = int(np.argmax(env[lo:hi])) + lo
        a0 = lo + int(np.nonzero(env[lo:pk + 1] >= env[pk] - 6)[0][0]) - int(0.008 * SR)
        if env[pk] - env[a0 - int(0.2 * SR): a0 - int(0.01 * SR)].max() < rise_min:
            continue                                        # the strings were not quiet before it
        end = t0 + 3 * SR
        for k in on[j + 1:]:
            tk = k * HOP + NFFT // 2
            if tk >= end:
                break
            if env[tk: tk + int(0.06 * SR)].max() > env[pk] - (20 if strict else 15):
                end = tk - int(0.02 * SR)
                break
        if end - a0 < int(keep_min * SR):
            continue
        fa, ap = yin(x[a0 + int(0.03 * SR): a0 + int(0.18 * SR)])
        fb, _ = yin(x[a0 + int(0.30 * SR): a0 + int(0.45 * SR)])
        drift = 1200 * abs(np.log2(max(fb, 1.0) / max(fa, 1.0)))
        if 75 < fa < 1300 and ap < 0.2 and drift < 25:
            out.append((a0, end - a0, fa, ap, drift))
    return on, out


def partial_decays(seg, f0):
    """(frequency, decay dB/s) of the first partials of one pluck, from a line fit to each partial's level."""
    n, hop = 4096, 512
    F = frames(np.pad(seg, (0, n)), n, hop)
    S = np.abs(np.fft.rfft(F * np.hanning(n), axis=1))
    fr = np.fft.rfftfreq(n, 1 / SR)
    ts = (np.arange(len(F)) * hop + n / 2) / SR
    sel = (ts > 0.08) & (ts < len(seg) / SR - 0.05)
    out = []
    for k in range(1, 13):
        band = (fr > k * f0 * 0.97) & (fr < k * f0 * 1.03)
        if not band.any() or sel.sum() < 4 or k * f0 > 6000:
            continue
        A = 20 * np.log10(S[:, band].max(1) + 1e-9)
        if A[1] < A[1:].max() - 1 or A[1] < 20 * np.log10(S[1].max() + 1e-9) - 40:
            continue
        out.append((float(fr[band][np.argmax(S[1, band])]), float(-np.polyfit(ts[sel], A[sel], 1)[0])))
    return out


def mine():
    report, pts = {"sources": [], "date": VERIFIED}, []
    for s in SOURCES:
        x = decode(s["file"])
        x = x - x.mean()
        on, strict = clean_plucks(x, strict=True)
        _, loose = clean_plucks(x, strict=False)
        names = "C C# D Eb E F F# G G# A Bb B".split()
        pitches = sorted({names[int(round(69 + 12 * np.log2(p[2] / 440))) % 12] for p in loose})
        for a0, n, f0, ap, _ in loose:
            if ap < 0.08:
                pts += partial_decays(x[a0: a0 + n], f0)
        r = {"id": s["id"], "onsets": int(len(on)), "clean_strict": len(strict), "clean_loose": len(loose),
             "clean_loose_over_2s": sum(1 for p in loose if p[1] > 2 * SR), "pitch_classes_loose": pitches}
        report["sources"].append(r)
        print(f"  {s['id']}: {r['onsets']} onsets; isolated plucks {r['clean_strict']} (1.2 s, 20 dB), "
              f"{r['clean_loose']} (0.7 s, 15 dB), {r['clean_loose_over_2s']} of them over 2 s; "
              f"pitch classes {' '.join(pitches)}", flush=True)
    f, d = np.array(pts).T
    ok = (d > 0) & (d < 150)
    edges = [100, 200, 400, 800, 1600, 3200, 6400]                   # median per octave band, then a line through them
    bands = [(float(np.median(f[ok & (f >= lo) & (f < hi)])), float(np.median(d[ok & (f >= lo) & (f < hi)])))
             for lo, hi in zip(edges, edges[1:]) if (ok & (f >= lo) & (f < hi)).sum() >= 5]
    bf, bd = np.array(bands).T
    b, a = np.polyfit(bf, bd, 1)
    report["decay_bands"] = [{"hz": round(x), "db_per_s": round(y, 1)} for x, y in bands]
    report["decay_fit_db_per_s"] = {"a": round(float(a), 2), "b_per_hz": round(float(b), 5), "partials": int(ok.sum())}
    print("  partial decay by band: " + ", ".join(f"{x:.0f} Hz {y:.0f} dB/s" for x, y in bands))
    print(f"  line through the bands: {a:.1f} + {b * 1000:.1f} dB/s per kHz ({ok.sum()} partials); "
          f"the koto model uses {DECAY_A} + {DECAY_B * 1000:.0f} dB/s per kHz")
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "calibration.json").write_text(json.dumps(report, indent=1), encoding="utf-8")


# ------------------------------------------------------------------------------------------------------------ the koto

DECAY_A, DECAY_B = 10.0, 0.0135  # prompt decay of a partial in dB/s, A + B * f: the line through the recordings' octave
                                 # bands from 150 Hz to 2.3 kHz (mine: 11, 13, 20, 26 and 41 dB/s)
SLOW, SLOW_SHARE = 0.5, 0.25     # the second polarization rings on at half that rate (the aftersound)
MAX_NOTE = 9.0                   # s
_NOTES = {}


def hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def smoothstep(u):
    u = np.clip(u, 0, 1)
    return u * u * (3 - 2 * u)


def koto_note(m, vel, take, bend=(), vib=None, voice="tetron"):
    """One plucked koto string (mono, unit-ish level): partials k f0 sqrt(1 + B k^2) with the pluck point's comb,
    a rolloff that opens with velocity, decay rates from the recordings, two polarizations (the second slightly sharp
    and slower), a few cents of tension glide at the attack and a plectrum click. bend: (start s, length s, semitones)
    presses; vib: (start s, rate Hz, depth semitones). voice "silk" is the older string: it dies sooner (the measured
    line, 1.4 times, since the recordings carry their room), barely rings on, is nearly harmonic and more nasal.
    The same pitch, take, velocity and voice give the same samples."""
    rng = np.random.default_rng(seed_of("koto", round(m * 100), take))
    silk = voice == "silk"
    f0 = hz(m)
    beta = rng.uniform(0.07, 0.12)                                  # plucked near the bridge, as with a tsume
    B = 1.2e-5 if silk else min(4e-4, 3e-5 * (f0 / 400) ** 3)
    K = max(1, int(min(36, 9500 / f0)))
    k = np.arange(1, K + 1)
    fk = k * f0 * np.sqrt(1 + B * k * k)
    jitter = rng.uniform(0.85, 1.15, K)
    a = np.abs(np.sin(np.pi * k * beta)) / k ** 1.4 * jitter
    a /= np.sqrt(1 + (fk / (2000 + 7000 * vel ** 1.2)) ** 4)
    if silk:
        a *= 1 + 0.9 * np.exp(-0.5 * (np.log(fk / 2300) / 0.4) ** 2)
    a /= a[0]
    d1 = (DECAY_A + DECAY_B * fk) * (1.4 if silk else 1.0)
    d2 = (0.7 if silk else SLOW) * d1 + 0.5
    share = 0.08 if silk else SLOW_SHARE
    l1, l2 = d1 * np.log(10) / 20, d2 * np.log(10) / 20
    n = int(SR * min(MAX_NOTE, 70 / d2[0] + 0.3))
    t = np.arange(n) / SR
    ratio = 1 + (0.011 if silk else 0.007) * vel * np.exp(-t / (0.05 if silk else 0.06))
    if bend or vib:
        c = np.zeros(n)
        for t0, ln, semis in bend:
            c += semis * smoothstep((t - t0) / ln)
        if vib:
            v0, rate, depth = vib
            c += depth * smoothstep((t - v0) / 0.8) * np.sin(2 * np.pi * rate * np.maximum(t - v0, 0))
        ratio = ratio * 2 ** (c / 12)
    tau = np.concatenate([[0.0], np.cumsum(ratio[:-1])]) / SR
    det = 2 ** (0.8 / 1200)
    out = np.zeros(n)
    for i in range(K):
        if a[i] < 3e-4:
            continue
        L = int(min(n, SR * (75 / d2[i])))
        ph = 2 * np.pi * fk[i] * tau[:L]
        tt = t[:L]
        out[:L] += a[i] * ((1 - share) * np.exp(-l1[i] * tt) * np.sin(ph) + share * np.exp(-l2[i] * tt) * np.sin(ph * det))
    nb = int(0.016 * SR)                                            # the tsume (plectrum) on the string
    Z = np.fft.rfft(rng.standard_normal(nb))
    fz = np.fft.rfftfreq(nb, 1 / SR)
    Z *= np.exp(-0.5 * (np.log(np.maximum(fz, 1.0) / 3500) / 0.6) ** 2)
    z = np.fft.irfft(Z, nb) * np.exp(-np.arange(nb) / (0.0022 * SR))
    out[:nb] += z / (np.abs(z).max() + 1e-12) * (0.3 if silk else 0.22) * vel
    r = int(0.0015 * SR)
    out[:r] *= np.linspace(0, 1, r)
    tail = int(0.3 * SR)
    out[-tail:] *= np.cos(np.linspace(0, np.pi / 2, tail)) ** 2
    return out * vel ** 1.6 * (f0 / 300) ** -0.18


def note_samples(ev):
    voice = ev.get("voice", "tetron")
    if ev.get("bend") or ev.get("vib"):
        return koto_note(ev["m"], ev["v"], ev["take"], tuple(ev.get("bend") or ()), ev.get("vib"), voice)
    key = (round(ev["m"] * 100), round(ev["v"] * 40), ev["take"], voice)
    if key not in _NOTES:
        _NOTES[key] = koto_note(ev["m"], round(ev["v"] * 40) / 40, ev["take"], voice=voice)
    return _NOTES[key]


# ------------------------------------------------------------------------------------------------- the player and scores

MODES = {"in": [0, 1, 5, 7, 8], "in_up": [0, 1, 5, 7, 10], "yo": [0, 2, 5, 7, 9], "minyo": [0, 3, 5, 7, 10],
         "major": [0, 2, 4, 5, 7, 9, 11], "minor": [0, 2, 3, 5, 7, 8, 10]}
NAMES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def scale_notes(mode, tonic, lo, hi):
    pcs = {(tonic + p) % 12 for p in MODES[mode]}
    return [m for m in range(lo, hi + 1) if m % 12 in pcs]


def note_num(s):
    """'F#4' or 'Bb3' to a MIDI number."""
    acc = s[1:-1]
    return NAMES[s[0]] + {"": 0, "#": 1, "b": -1}[acc] + 12 * (int(s[-1]) + 1)


def parse(text, transpose=0):
    """Phrases from 'A4:1 A4:1 B4:2 / ...': note:beats, r:beats for a rest; '/' ends a phrase."""
    phrases, cur = [], []
    for tok in text.split():
        if tok == "/":
            phrases.append(cur)
            cur = []
            continue
        name, beats = tok.split(":")
        cur.append((float(beats), None if name == "r" else note_num(name) + transpose))
    if cur:
        phrases.append(cur)
    return phrases


class Player:
    """Turns phrases (beats, pitch) into timed, ornamented plucks: slow rubato, a ritardando into every phrase end,
    a breath after it, velocity arched over the phrase, and the koto's own touches by seeded chance: grace notes
    (a quick lower string first), awasezume (the octave with it), yuri-iro (vibrato on long notes) and ato-oshi
    (pressing the ringing string up a step instead of plucking the next note)."""

    def __init__(self, slug, bpm, tonic, mode, voice="tetron", orn=1.0):
        self.rng = np.random.default_rng(seed_of("piece", slug))
        self.bpm, self.tonic, self.mode, self.voice, self.orn = bpm, tonic, mode, voice, orn
        self.sc = scale_notes(mode, tonic, tonic - 26, tonic + 31)
        self.t = 0.35
        self.ev = []
        self.takes = {}

    def pluck(self, t, m, v, **kw):
        m = int(round(m))
        while m < 43:
            m += 12
        take = self.takes.get(m, -1)
        take = (take + 1 + int(self.rng.integers(0, 2))) % 3          # round robin over three takes
        self.takes[m] = take
        pan = float(np.clip((m - 64) / 34, -0.38, 0.38) + self.rng.normal(0, 0.04))
        if self.voice != "tetron":
            kw["voice"] = self.voice
        self.ev.append({"t": max(0.0, float(t)), "m": m, "v": float(np.clip(v, 0.1, 0.95)), "take": take, "pan": pan, **kw})

    def near(self, m, steps):
        """The scale tone `steps` scale steps from m (m itself snapped to the scale)."""
        i = int(np.argmin([abs(x - m) for x in self.sc]))
        return self.sc[int(np.clip(i + steps, 0, len(self.sc) - 1))]

    def phrase(self, notes, vel=0.5, rit=0.32, push=0.05, breath=(0.5, 1.3), grace=0.12, octave=0.0, vib=0.5,
               oshi=0.25, tsuki=0.1, low=None, tempo=1.0):
        rng = self.rng
        oshi, tsuki, grace = oshi * self.orn, tsuki * self.orn, grace * self.orn
        total = sum(b for b, _ in notes)
        bpm = self.bpm * tempo * (1 + rng.normal(0, 0.025))
        grid = np.linspace(0, total, max(2, int(total * 32)) + 1)
        u = grid / total
        spb = 60 / bpm * (1 - push * np.sin(np.pi * u) + rit * np.clip((u - 0.6) / 0.4, 0, 1) ** 2)
        sec = np.concatenate([[0.0], np.cumsum(0.5 * (spb[1:] + spb[:-1]) * np.diff(grid))])
        t0 = self.t
        at = lambda b: t0 + float(np.interp(b, grid, sec))
        starts = np.array([at(sum(x for x, _ in notes[:i])) for i in range(len(notes) + 1)])
        gaps = np.minimum(np.diff(starts), 4.2)                         # no note waits more than 4.2 s for the next
        starts = np.concatenate([[starts[0]], starts[0] + np.cumsum(gaps)])
        onset = lambda i: float(starts[i])
        if low is not None:
            self.pluck(t0 - 0.03, low, vel * 0.62)
        skip = set()
        sounding = [(i, d, m) for i, (d, m) in enumerate(notes) if m is not None]
        for j, (i, d, m) in enumerate(sounding):
            b = sum(x for x, _ in notes[:i])
            if i in skip:
                continue
            uu = b / total
            v = vel * (0.86 + 0.24 * np.sin(np.pi * min(1.0, uu * 1.1 + 0.05))) * (1.05 if b % 2 == 0 else 1.0)
            v *= 1 + rng.normal(0, 0.04)
            t = onset(i) + float(np.clip(rng.normal(0, 0.011), -0.025, 0.025))
            kw = {}
            nxt = sounding[j + 1] if j + 1 < len(sounding) else None
            if nxt and 0 < nxt[2] - m <= 2 and d <= 1.0 and nxt[1] <= 1.5 and rng.random() < oshi and j > 0:
                start = onset(nxt[0]) - t - 0.05
                if start > 0.12:
                    kw["bend"] = [(start, 0.11, nxt[2] - m)]
                    skip.add(nxt[0])
            elif d >= 2 and rng.random() < (vib if j < len(sounding) - 1 else max(vib, 0.65)):
                kw["vib"] = (0.35 + rng.uniform(0, 0.25), rng.uniform(4.6, 5.6), rng.uniform(0.14, 0.24))
            elif 1 <= d < 2 and j > 0 and rng.random() < tsuki:          # tsuki-iro: a quick push and release
                s = rng.uniform(0.18, 0.3)
                kw["bend"] = [(s, 0.07, 0.6), (s + 0.12, 0.16, -0.6)]
            if j > 0 and d >= 1 and rng.random() < grace:
                g = self.near(m, -1)
                if g < m:
                    self.pluck(t - rng.uniform(0.06, 0.09), g, v * 0.5)
            if (j == 0 and rng.random() < octave) or (d >= 3 and rng.random() < octave * 0.6):
                self.pluck(t - 0.018, m - 12, v * 0.6)
            self.pluck(t, m, v, **kw)
        self.t = onset(len(notes)) + float(rng.uniform(*breath))
        return self

    def rest(self, s):
        self.t += s
        return self

    def roll(self, ms, vel=0.45, gap=0.06, ring=0.0):
        """Notes struck one after another, low to high (a rolled chord)."""
        for i, m in enumerate(ms):
            self.pluck(self.t + i * gap * (1 + self.rng.normal(0, 0.12)), m, vel * (0.85 + 0.15 * i / max(1, len(ms) - 1)))
        self.t += gap * len(ms) + ring
        return self

    def gliss(self, lo, hi, vel=0.32, gap=0.055, ring=1.2, down=False):
        """Sararin: a soft sweep across the strings of the scale, the last one a little louder."""
        ms = [m for m in self.sc if lo <= m <= hi]
        ms = ms[::-1] if down else ms
        for i, m in enumerate(ms):
            w = 0.7 + 0.3 * (i / max(1, len(ms) - 1))
            self.pluck(self.t + i * gap * (1 + self.rng.normal(0, 0.1)), m, vel * w)
        self.t += gap * len(ms) + ring
        return self


# ------------------------------------------------------------------------------------------------------------ melodies

SONGS = {
    "sakura": {
        "title": "Sakura Sakura (koto)", "mode": "in", "tonic": 69, "transpose": 5, "voice": "silk", "orn": 1.4, "bpm": 54, "target": 200,
        "composition": "Sakura Sakura, traditional Japanese melody, first published in the Sokyokushu koto collection (1888)",
        "pd": "Traditional; first printed in 1888 for the Ministry of Education, author unknown. Public domain everywhere.",
        "melody": """A4:1 A4:1 B4:2 A4:1 A4:1 B4:2 /
            A4:1 B4:1 C5:1 B4:1 A4:1 B4:0.5 A4:0.5 F4:2 / E4:1 C4:1 E4:1 F4:1 E4:1 E4:0.5 C4:0.5 B3:2 /
            A4:1 B4:1 C5:1 B4:1 A4:1 B4:0.5 A4:0.5 F4:2 / E4:1 C4:1 E4:1 F4:1 E4:1 E4:0.5 C4:0.5 B3:2 /
            A4:1 A4:1 B4:2 A4:1 A4:1 B4:2 / E4:1 F4:1 B4:0.5 A4:0.5 F4:1 E4:4"""},
    "kojo": {
        "title": "Kojo no Tsuki (koto)", "mode": "minor", "tonic": 64, "transpose": 7, "bpm": 50, "target": 230,
        "composition": "Kojo no Tsuki (The Moon over the Ruined Castle), Taki Rentaro, 1901, in the form Yamada Kosaku revised in 1918",
        "pd": "Taki Rentaro died in 1903 and Yamada Kosaku in 1965; both are public domain in Japan (life plus 50 years, "
              "ended before the 2018 extension) and in the US (published before 1929).",
        "melody": """E4:1 E4:1 A4:1 B4:1 C5:1 B4:1 A4:2 F4:1 F4:1 E4:1 D4:1 E4:3 r:1 /
            E4:1 E4:1 A4:1 B4:1 C5:1 B4:1 A4:2 F4:1 D4:1 E4:1.5 E4:0.5 A3:3 r:1 /
            C5:1 C5:1 B4:1 A4:1 F4:1.5 F4:0.5 E4:2 D4:1 E4:1 F4:1.5 F4:0.5 E4:3 r:1 /
            E4:1 E4:1 A4:1 B4:1 C5:1 B4:1 A4:2 F4:1 D4:1 E4:1.5 E4:0.5 A3:4"""},
    "furusato": {
        "title": "Furusato (koto)", "mode": "major", "tonic": 70, "transpose": 3, "voice": "silk", "orn": 1.4, "bpm": 60, "target": 210,
        "composition": "Furusato (Hometown), Okano Teiichi, 1914 (Jinjo Shogaku Shoka)",
        "pd": "Okano Teiichi died in 1941 and the lyricist Takano Tatsuyuki in 1947 (the words are not used). Public "
              "domain in Japan and in the US (published 1914).",
        "melody": """G4:1 G4:1 G4:1 A4:1.5 B4:0.5 A4:1 B4:1 B4:1 C5:1 D5:2 r:1 /
            C5:1 D5:1 E5:1 B4:1.5 C5:0.5 B4:1 A4:1 A4:1 F#4:1 G4:2 r:1 /
            A4:0.5 G4:0.5 A4:1 D4:1 G4:0.5 A4:0.5 B4:1 B4:1 C5:0.5 B4:0.5 C5:1.5 E5:0.5 D5:0.5 C5:0.5 B4:1 r:1 /
            D5:1 D5:1 D5:1 G4:1.5 A4:0.5 B4:1 C5:1 C5:1 A4:1 G4:3"""},
    "yuki": {
        "title": "Yuki (koto)", "mode": "major", "tonic": 70, "transpose": 5, "bpm": 58, "target": 190,
        "composition": "Yuki (Snow), Monbusho school song, 1911 (Jinjo Shogaku Shoka), composer not named",
        "pd": "Published anonymously by the Ministry of Education in 1911. Public domain in Japan and in the US.",
        "melody": """C5:0.75 D5:0.25 C5:0.75 D5:0.25 C5:1 A4:0.5 r:0.5 A4:0.75 Bb4:0.25 A4:0.75 Bb4:0.25 A4:1 F4:0.5 r:0.5 /
            A4:1 F4:0.5 G4:0.5 A4:1 F4:0.5 G4:0.5 A4:0.75 Bb4:0.25 C5:0.5 C5:0.5 G4:0.75 A4:0.25 G4:0.5 r:0.5 /
            C5:0.75 D5:0.25 C5:0.75 D5:0.25 C5:0.5 C5:0.5 A4:0.5 A4:0.5 A4:0.75 Bb4:0.25 A4:0.75 Bb4:0.25 A4:0.5 A4:0.5 F4:0.5 r:0.5 /
            D5:1 C5:0.5 A4:0.5 C5:0.5 C5:0.5 A4:0.5 F4:0.5 A4:0.5 A4:0.5 G4:0.75 G4:0.25 F4:2"""},
    "nanatsu": {
        "title": "Nanatsu no Ko (koto)", "mode": "major", "tonic": 72, "transpose": 5, "bpm": 56, "target": 220,
        "composition": "Nanatsu no Ko (Seven Little Ones), Motoori Nagayo, 1921",
        "pd": "Motoori Nagayo died in 1945 and the lyricist Noguchi Ujo in 1945 (the words are not used). Public domain "
              "in Japan (life plus 50 years) and in the US (published 1921).",
        "melody": """B4:1 A4:0.5 G4:0.5 A4:1 r:1 B4:0.5 G4:0.5 E4:0.5 G4:0.5 D4:1 r:1 E4:0.5 D4:0.5 B3:0.5 D4:0.5 E4:1 G4:1 A4:3 r:1 /
            B4:1.5 C5:0.5 D5:1 B4:1 D5:1 E5:0.5 D5:0.5 B4:1 G4:1 A4:0.5 A4:0.5 B4:0.5 G4:0.5 E4:1 D4:1 G4:3 r:1 /
            A4:1 A4:1 A4:1 r:1 A4:1.5 A4:0.5 A4:1 B4:1 C5:1 B4:1 A4:1 A4:1 A4:1 B4:1 E4:1 r:1 /
            D4:1 D4:1 D4:1 r:1 G4:1.5 G4:0.5 G4:1 A4:1 B4:1 C5:1 E4:1 G4:1 A4:3 r:1 /
            B4:1 A4:0.5 G4:0.5 A4:1 r:1 B4:0.5 G4:0.5 E4:0.5 G4:0.5 D4:1 r:1 E4:0.5 D4:0.5 B3:0.5 D4:0.5 E4:1 G4:1 A4:3 r:1 /
            B4:1.5 C5:0.5 D5:1 B4:1 D5:1 E5:0.5 D5:0.5 B4:1 G4:1 A4:1 B4:0.5 G4:0.5 E4:1 D4:1 G4:3"""},
    "usagi": {
        "title": "Usagi (koto)", "mode": "in", "tonic": 74, "transpose": 10, "bpm": 52, "target": 175,
        "composition": "Usagi (Rabbit, Rabbit), traditional warabe uta about the rabbit watching the full moon",
        "pd": "Traditional children's song from the Edo period, in school songbooks from 1892, author unknown. Public "
              "domain everywhere.",
        "melody": """F4:1 F4:0.5 A4:0.5 B4:0.5 A4:0.5 B4:0.5 r:0.5 F4:0.5 F4:0.5 F4:0.5 A4:0.5 B4:0.5 A4:0.5 B4:0.5 r:0.5 /
            A4:0.5 B4:0.5 C5:0.5 C5:0.5 B4:0.5 A4:0.25 A4:0.25 F4:0.5 E4:0.5 A4:0.5 F4:0.5 E4:1 F4:0.5 E4:0.5 D4:1 E4:2"""},
}


def song(slug, spec):
    """A melody as koto players lay out a song: a soft opening, the tune plainly with low strings under the phrase
    starts, a short interlude on its opening notes, the tune again with octaves and presses, more passes in other
    registers while there's time, and a slow last phrase into a rolled tonic."""
    P = Player(slug, spec["bpm"], spec["tonic"], spec["mode"], spec.get("voice", "tetron"), spec.get("orn", 1.0))
    ph = parse(spec["melody"], spec["transpose"])
    rng = P.rng
    T, target = spec["tonic"], spec["target"]
    low = lambda i: T - 12 if i % 2 == 0 else T - 5                      # the tonic or the fifth below
    P.pluck(P.t, T - 12, 0.42)
    P.rest(0.25).gliss(T - 5, ph[0][0][1] or T, vel=0.28, ring=1.6)

    def pass_(vel, shift=0, octave=0.0, oshi=0.12, grace=0.06, bass=0.7, tempo=1.0):
        for i, p in enumerate(ph):
            notes = [(d, None if m is None else m + shift) for d, m in p]
            P.phrase(notes, vel=vel, octave=octave, oshi=oshi, grace=grace, low=low(i) if rng.random() < bass else None,
                     tempo=tempo)

    pass_(0.5, octave=0.3, oshi=0.25, grace=0.12, bass=0.35)
    P.rest(0.6)
    head = [(d * 1.5, m) for d, m in ph[0][:4] if m is not None]          # interlude: the opening, slower
    P.phrase(head + [(3, P.near(head[-1][1], -1))], vel=0.42, low=T - 12, octave=0.5)
    P.phrase([(d * 1.5, m + 12 if max(x for _, x in head) + 12 <= 81 else m) for d, m in head] + [(4, T + 12 if T + 12 <= 79 else T)],
             vel=0.38, tsuki=0.2)
    P.rest(0.8)
    pass_(0.56, octave=0.5, oshi=0.35, grace=0.15, bass=0.3)
    n = 0
    lo_m = min(m for p in ph for _, m in p if m is not None)
    hi_m = max(m for p in ph for _, m in p if m is not None)
    while P.t < target - 45 and n < 3:                                      # more passes while the track is short
        P.rest(0.6).gliss(T, T + 12, vel=0.24, ring=1.0, down=bool(n % 2))
        shift = 12 if n % 2 == 0 and hi_m + 12 <= 86 else (-12 if n % 2 and lo_m - 12 >= 62 else 0)
        pass_(0.44 if shift else 0.5, shift=shift, octave=0.35, oshi=0.3, grace=0.12, bass=0.3, tempo=0.97)
        n += 1
    last = ph[-1]
    P.rest(0.4).phrase([(d * 1.4, m) for d, m in last], vel=0.4, rit=0.5, tempo=0.9, low=T - 12)
    P.rest(0.3).roll([T - 12, T - 5, T], vel=0.4, gap=0.09, ring=0.5)
    P.pluck(P.t + 1.2, T + 12, 0.26)
    P.t += 1.2
    return P


# ------------------------------------------------------------------------------------------------------- new pieces

PIECES = {
    "lantern-over-the-water": {"title": "Lantern Over the Water", "mode": "in", "tonic": 57, "bpm": 50, "start": 5,
                               "motif": [(0, 2), (-1, 1), (-2, 1), (-1, 3)], "form": "I A A2 L B A2 C", "texture": "octaves"},
    "yuzu-floating": {"title": "Yuzu Floating", "mode": "yo", "tonic": 67, "bpm": 58, "start": 2, "drop": 3,
                      "motif": [(0, 1), (1, 1), (2, 2), (1, 1), (0, 1)], "form": "I A A2 B L A2 C", "texture": "answer"},
    "the-bamboo-spout": {"title": "The Bamboo Spout", "mode": "in", "tonic": 64, "bpm": 60, "start": 2,
                         "motif": [(0, 1.5), (1, 0.5), (2, 1), (1, 1)], "form": "I A A2 B A2 L C", "texture": "ostinato"},
    "steam-over-the-spring": {"title": "Steam Over the Spring", "mode": "minyo", "tonic": 62, "bpm": 52, "start": 3, "drop": 3,
                              "motif": [(0, 1), (-1, 1), (-2, 2)], "form": "I A A2 B A2 L C", "texture": "gliss"},
    "moon-through-the-cedars": {"title": "Moon Through the Cedars", "mode": "in_up", "tonic": 62, "bpm": 48, "start": 3,
                                "motif": [(0, 2), (1, 1), (2, 1), (1, 2)], "form": "I A L A2 B A2 C", "texture": "octaves"},
    "the-monkey-dozes": {"title": "The Monkey Dozes", "mode": "yo", "tonic": 62, "bpm": 60, "start": 2, "beats": 12,
                         "motif": [(0, 2), (1, 1), (0, 2), (-1, 1)], "form": "I A A2 B A2 C", "texture": "drone"},
    "stoat-in-the-warm-water": {"title": "Stoat in the Warm Water", "mode": "in", "tonic": 67, "bpm": 56, "start": 2, "drop": 3, "voice": "silk", "orn": 1.4,
                                "motif": [(0, 0.5), (1, 0.5), (0, 1), (-2, 1), (-1, 1)], "form": "I A A2 B L A2 C",
                                "texture": "answer"},
    "frost-on-the-paper-door": {"title": "Frost on the Paper Door", "mode": "in", "tonic": 59, "bpm": 52, "start": 6,
                                "motif": [(0, 1), (-1, 1), (0, 2), (-2, 2)], "form": "I A L A2 B A2 C", "texture": "octaves"},
    "last-bath-before-dawn": {"title": "Last Bath Before Dawn", "mode": "yo", "tonic": 65, "bpm": 54, "start": 2, "drop": 3, "voice": "silk", "orn": 1.4,
                              "motif": [(0, 1), (1, 1), (2, 1), (1, 1), (0, 2)], "form": "I A A2 B A2 L C", "texture": "ostinato"},
    "snowfall-slowly": {"title": "Snowfall, Slowly", "mode": "in", "tonic": 62, "bpm": 46, "start": 0,
                        "motif": [(0, 2), (1, 1), (3, 3)], "form": "I A A2 L B A2 C", "texture": "drone"},
}


def make_phrase(P, start, motif, end, beats, var=0, approach_up=True):
    """Motif at scale index `start`, a walk toward the cadence, the step above (or below) the last tone, and a long
    last tone at index `end`, in `beats` beats. var 1 changes one motif tone, var 2 also stretches its rhythm."""
    rng, sc = P.rng, P.sc
    mot = list(motif)
    if var >= 1 and len(mot) > 2:
        i = int(rng.integers(1, len(mot) - 1))
        mot[i] = (mot[i][0] + int(rng.choice([-1, 1])), mot[i][1])
    if var >= 2:
        mot = [(o, d * 1.5) for o, d in mot]
    hi = len(sc) - 1
    idx = [int(np.clip(start + o, 0, hi)) for o, _ in mot]
    notes = [(d, sc[i]) for (_, d), i in zip(mot, idx)]
    final = float(rng.choice([2, 3, 3, 4]))
    app = int(np.clip(end + (1 if approach_up or rng.random() < 0.5 else -1), 0, hi))
    remain = beats - sum(d for d, _ in notes) - final - 1
    cur = idx[-1]
    while remain > 0.24:
        d = float(rng.choice([1, 1, 1, 2, 0.5])) if remain >= 2 else (1.0 if remain >= 1 else 0.5)
        d = min(d, remain)
        way = np.sign(app - cur) or int(rng.choice([-1, 1]))
        step = int(rng.choice([way, way, way, -way, 2 * way, 0], p=[0.25, 0.2, 0.15, 0.2, 0.1, 0.1]))
        nxt = int(np.clip(cur + step, max(0, P.home - 5), min(hi, P.home + 9)))
        if len(notes) >= 2 and sc[nxt] == notes[-1][1] == notes[-2][1]:
            nxt = int(np.clip(nxt + way, 0, hi))
        notes.append((d, sc[nxt]))
        cur = nxt
        remain -= d
    if notes[-1][1] == sc[app]:
        notes[-1] = (notes[-1][0], sc[int(np.clip(app + 1, 0, hi))])
    notes.append((1.0, sc[app]))
    notes.append((final, sc[end]))
    return notes


def piece(slug, spec):
    """A new piece from one motif: an opening, then sections that each state the motif and answer it (question
    phrases end on the fifth, answers on the tonic, approached from the half step above as in miyako-bushi), a
    middle section higher and slower, a low-register answer, and a coda that fades on the tonic."""
    P = Player(slug, spec["bpm"], spec["tonic"], spec["mode"], spec.get("voice", "tetron"), spec.get("orn", 1.0))
    rng, sc = P.rng, P.sc
    P.home = home = sc.index(spec["tonic"])
    s0, motif, beats = home + spec["start"], spec["motif"], spec.get("beats", 8)
    fifth, octv, T = home + 3, home + 5, spec["tonic"]
    up = spec["mode"] in ("in", "in_up")
    tex = spec["texture"]
    vel0 = 0.5
    step = [0]

    def play(notes, vel=vel0, low=None, **kw):
        if tex == "drone" and step[0] % 2 == 0 and low is None:
            low = T - 12
        if tex == "ostinato" and step[0] % 2 == 1:                     # a slow low figure under every other phrase
            base = P.t
            for i, m in enumerate([T - 12, T - 5, T]):
                P.pluck(base + 0.6 + i * 60 / P.bpm * 2, m, 0.26)
        if tex == "answer" and step[0] % 4 == 3:
            notes = [(d, m - 12 if m - 12 >= 48 else m) for d, m in notes]
        step[0] += 1
        P.phrase(notes, vel=vel, low=low, octave=(0.5 if tex == "octaves" else 0.15), **kw)

    def section(sec):
        if sec == "I":
            P.pluck(P.t, T - 12, 0.4)
            if tex == "gliss" or rng.random() < 0.5:
                P.rest(0.3).gliss(T - 5, sc[min(s0, len(sc) - 1)], vel=0.27, ring=1.4)
            else:
                P.rest(1.6)
            play(make_phrase(P, s0, motif[:3], fifth, beats - 2, 0, up), vel=0.44, low=T - 12)
        elif sec in ("A", "A2"):
            v = 1 if sec == "A2" else 0
            play(make_phrase(P, s0, motif, fifth if rng.random() < 0.7 else octv, beats, v, up))
            play(make_phrase(P, s0, motif, home, beats, v + (sec == "A2"), up), low=T - 12)
            if sec == "A2" and tex == "gliss":
                P.rest(0.2).gliss(T, T + 12, vel=0.24, down=True, ring=1.0)
        elif sec == "B":
            hi = min(s0 + 3, len(sc) - 4)
            play(make_phrase(P, hi, motif, octv, beats + 4, 2, up), vel=0.54, tempo=0.95)
            play(make_phrase(P, hi - 1, motif, fifth, beats, 1, up), vel=0.52)
            play(make_phrase(P, s0, motif, home, beats, 1, up), vel=0.48, low=T - 12)
        elif sec == "L":
            lo = max(3, s0 - spec.get("drop", 5))                     # the answer below: an octave, or a fifth
            play([(d, m) for d, m in make_phrase(P, lo, motif, max(0, home - 5) if T - 12 >= 50 else home, beats, 1, up)],
                 vel=0.46, rit=0.4)
            P.rest(0.5)
        elif sec == "C":
            frag = [(d * 1.5, sc[int(np.clip(s0 + o, 0, len(sc) - 1))]) for o, d in motif[:3]]
            P.phrase(frag + [(1.5, sc[home + 1]), (4, T)], vel=0.42, rit=0.55, tempo=0.88, low=T - 12)
            P.phrase([(d, m - 12 if m - 12 >= 48 else m) for d, m in frag] + [(4, T - 12 if T - 12 >= 48 else T)],
                     vel=0.34, rit=0.6, tempo=0.85)
            P.rest(0.4).roll([T - 12, T - 5, T], vel=0.36, gap=0.1, ring=0.4)
            P.pluck(P.t + 1.3, T + 12, 0.22)
            P.t += 1.3

    extra = 0
    for sec in spec["form"].split():
        while sec == "C" and P.t < spec.get("target", 180) - 28 and extra < 3:   # a short piece gets more sections
            section(("A2", "L", "B")[extra])
            extra += 1
        section(sec)
    return P


# ------------------------------------------------------------------------------------------------------------- the room

def room_ir(seed=11, length=2.4):
    """A warm small room (a tatami room with paper doors): early reflections over the first 40 ms, then a dense tail
    whose high frequencies die first (1.3 s low, 0.4 s at the top). Stereo, seeded."""
    rng = np.random.default_rng(seed)
    n = int(length * SR)
    t = np.arange(n) / SR
    ir = np.zeros((n, 2))
    for ch in range(2):
        times = np.sort(rng.uniform(0.004, 0.042, 16))
        gains = rng.uniform(0.3, 0.7, 16) * np.exp(-times / 0.025) * rng.choice([-1.0, 1.0], 16)
        np.add.at(ir[:, ch], (times * SR).astype(int), gains)
    N = np.fft.rfft(rng.standard_normal((n, 2)), axis=0)
    f = np.fft.rfftfreq(n, 1 / SR)
    tail = np.zeros((n, 2))
    edges = [0, 250, 900, 2500, 6000, SR / 2]
    rts = [1.3, 1.05, 0.8, 0.55, 0.38]
    lf = np.log(np.maximum(f, 1.0))
    for i, rt in enumerate(rts):
        lo, hi = np.log(max(edges[i], 1.0)), np.log(edges[i + 1])
        m = np.clip((lf - lo) / 0.25 + 0.5, 0, 1) if i else np.ones_like(f)
        m = m * (np.clip((hi - lf) / 0.25 + 0.5, 0, 1) if i < len(rts) - 1 else 1.0)
        tail += np.fft.irfft(N * m[:, None], n, axis=0) * np.exp(-6.91 * t / rt)[:, None]
    tail *= smoothstep((t - 0.01) / 0.035)[:, None]
    early_e = np.sqrt((ir ** 2).sum(0).mean())
    tail *= early_e * 1.6 / np.sqrt((tail ** 2).sum(0).mean())
    ir += tail
    return ir / np.sqrt((ir ** 2).sum(0).mean())


def fft_conv(x, h, block=1 << 17):
    """Overlap-add convolution of mono x with each column of h."""
    L = len(x) + len(h) - 1
    nfft = 1 << int(np.ceil(np.log2(block + len(h) - 1)))
    H = np.fft.rfft(h, nfft, axis=0)
    y = np.zeros((L, h.shape[1]))
    for s in range(0, len(x), block):
        seg = x[s: s + block]
        Y = np.fft.irfft(np.fft.rfft(seg, nfft)[:, None] * H, nfft, axis=0)
        e = min(L, s + nfft)
        y[s:e] += Y[: e - s]
    return y


def tone(x):
    """The old-record color: a little body from the koto's long box (200 Hz, 650 Hz), a gentle low cut and a top
    end that softens from 6 kHz. Zero-phase, by FFT over the whole track."""
    f = np.fft.rfftfreq(len(x), 1 / SR)
    pts = np.array([[10, -24], [35, -8], [70, -1.5], [120, 0], [200, 2.0], [330, 0.5], [650, 1.5], [1100, 0], [2600, 0.5],
                    [4200, 0], [6000, -0.5], [9000, -2.5], [12000, -5], [16000, -10], [22050, -18]], float)
    g = 10 ** (np.interp(np.log(np.maximum(f, 1.0)), np.log(pts[:, 0]), pts[:, 1]) / 20)
    return np.fft.irfft(np.fft.rfft(x, axis=0) * g[:, None], len(x), axis=0)


# --------------------------------------------------------------------------------------------------------- loudness

def k_weight(x):
    """ITU-R BS.1770 K-weighting at 44.1 kHz (the two biquads computed for this rate)."""
    from audio_analyze import lfilter
    K = np.tan(np.pi * 1681.974450955533 / SR)
    Vh = 10 ** (3.999843853973347 / 20)
    Vb, Q = Vh ** 0.4996667741545416, 0.7071752369554196
    a0 = 1 + K / Q + K * K
    x = lfilter([(Vh + Vb * K / Q + K * K) / a0, 2 * (K * K - Vh) / a0, (Vh - Vb * K / Q + K * K) / a0],
                [1.0, 2 * (K * K - 1) / a0, (1 - K / Q + K * K) / a0], x)
    K, Q = np.tan(np.pi * 38.13547087602444 / SR), 0.5003270373238773
    a0 = 1 + K / Q + K * K
    return lfilter([1.0, -2.0, 1.0], [1.0, 2 * (K * K - 1) / a0, (1 - K / Q + K * K) / a0], x)


def lufs(x):
    xk = k_weight(x)
    win, hop = int(0.4 * SR), int(0.1 * SR)
    c = np.concatenate([[0.0], np.cumsum((xk ** 2).sum(1))])
    s = np.arange(0, len(xk) - win + 1, hop)
    p = (c[s + win] - c[s]) / win
    lv = -0.691 + 10 * np.log10(np.maximum(p, 1e-20))
    g = p[lv > -70]
    rel = -0.691 + 10 * np.log10(g.mean()) - 10
    return float(-0.691 + 10 * np.log10(p[(lv > -70) & (lv > rel)].mean()))


def true_peak(x, block=1 << 16, pad=512):
    """dBTP: 4x oversampled by FFT in overlapping blocks."""
    pk = 0.0
    for s in range(0, len(x), block):
        a, b = max(0, s - pad), min(len(x), s + block + pad)
        seg = x[a:b]
        n = len(seg)
        X = np.fft.rfft(seg, axis=0)
        Y = np.zeros((2 * n + 1, x.shape[1]), complex)
        Y[: len(X)] = X
        up = np.fft.irfft(Y, 4 * n, axis=0) * 4
        pk = max(pk, float(np.abs(up[4 * (s - a): 4 * (s - a + min(block, len(x) - s))]).max()))
    return 20 * np.log10(max(pk, 1e-12))


# ---------------------------------------------------------------------------------------------------------- render

def perform(P):
    """The dry stereo koto of a Player's plucks (each string damped when it is plucked again), the room, the tone,
    soft ends, and the level: TARGET_LUFS, lowered if needed to keep the true peak under PEAK_DBTP."""
    ev = sorted(P.ev, key=lambda e: (e["t"], e["m"]))
    t0 = min(e["t"] for e in ev)
    for e in ev:
        e["t"] -= t0 - 0.12
    last = {}
    for e in reversed(ev):                                     # the next pluck of the same string stops this one
        e["stop"] = last.get(e["m"])
        last[e["m"]] = e["t"]
    end = max(e["t"] for e in ev) + MAX_NOTE
    dry = np.zeros((int(end * SR) + SR, 2))
    for e in ev:
        x = note_samples(e)
        if e["stop"] is not None:
            n = int((e["stop"] - e["t"] + 0.04) * SR)
            if n < len(x):
                x = x[:n].copy()
                f = min(n, int(0.08 * SR))
                x[-f:] *= np.cos(np.linspace(0, np.pi / 2, f)) ** 2
        i = int(round(e["t"] * SR))
        th = (e["pan"] + 1) * np.pi / 4
        dry[i: i + len(x), 0] += x * np.cos(th)
        dry[i: i + len(x), 1] += x * np.sin(th)
    loud = np.nonzero(np.abs(dry).max(1) > 1e-5)[0]
    dry = dry[: loud[-1] + 1]
    wet = fft_conv(dry.mean(1), room_ir())
    mix = np.zeros_like(wet)
    mix[: len(dry)] += dry
    mix += 0.38 * wet
    mix = tone(mix)
    env = np.abs(mix).max(1)
    ends = np.nonzero(env > env.max() * 10 ** (-46 / 20))[0]          # the last ring ends 46 dB under the peak
    mix = mix[: ends[-1] + 1]
    fo = min(len(mix) // 4, int(2.5 * SR))
    mix[-fo:] *= (np.cos(np.linspace(0, np.pi / 2, fo)) ** 2)[:, None]
    fi = int(0.02 * SR)
    mix[:fi] *= np.linspace(0, 1, fi)[:, None]
    g = 10 ** ((TARGET_LUFS - lufs(mix)) / 20)
    tp = true_peak(mix * g)
    if tp > PEAK_DBTP:
        g *= 10 ** ((PEAK_DBTP - tp) / 20)
    return mix * g


def encode(x, path, title):
    pcm = np.clip(x, -1, 1).astype("<f4").tobytes()
    run_ffmpeg(["-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-", "-c:a", "libmp3lame",
                "-b:a", "256k", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:a", "+bitexact",
                "-metadata", f"title={title}", "-metadata", f"artist={ARTIST}", "-metadata", f"album={ALBUM}",
                "-id3v2_version", "3", str(path)], input=pcm)


def catalog():
    out = {}
    for slug, spec in SONGS.items():
        out[slug] = {"kind": "song", **spec}
    for slug, spec in PIECES.items():
        out[slug] = {"kind": "original", "composition": f"{spec['title']}, an original piece in the "
                     f"{ {'in': 'in (miyako-bushi)', 'in_up': 'in (kumoi)', 'yo': 'yo', 'minyo': 'min-yo'}[spec['mode']]} scale "
                     f"made for this video by tools/koto_music.py", "pd": "A new composition made in code for this "
                     "channel, its own.", **spec}
    return out


# The channel's own performances (and its own pieces): no license is granted on them, so the ledger and the sidecars say
# "original", as for the ambience made in code; music.credits gives them no credit line (2026-11-12: whether to dedicate
# them to the public domain is Truman's call, never a tool's)
OWN = "original"


def sidecar(slug, c, stats, screen):
    pages = "; ".join(f"{s['page']} ({s['title']}, preview {s['preview']})" for s in SOURCES)
    picked = ("made for Yuzu Spring (look pencil-night) on 2026-11-12: old-timey koto, slow and sparse, for a snowy hot "
              "spring at night")
    if screen:
        heard = "; ".join(f"{', '.join(x.get('instruments') or [])}, {x.get('mood', '')}" for x in screen["excerpts"])
        picked += f"; audio-model screen {screen['score']} (heard: {heard})"
    return {
        "title": c["title"], "artist": ARTIST, "album": ALBUM,
        "source": (f"performed in code by tools/koto_music.py: a modeled koto string whose decay was measured from CC0 "
                   f"koto recordings by RutgerMuller on Freesound ({PACK}), with no audio from those recordings in the "
                   f"track; composition: {c['composition']}, "
                   + ("public domain" if c["kind"] == "song" else "this channel's own")),
        "license": OWN, "license_url": "", "ai_made": False, "verified": VERIFIED,
        "origin": f"rendered by tools/koto_music.py render (piece '{slug}'); koto model calibrated on {pages}, each page "
                  f"showing Creative Commons 0 on {VERIFIED}",
        "composition": c["composition"], "composition_pd": c["pd"],
        "instrument": f"koto modeled in code, {c.get('voice', 'tetron')} strings, in a synthetic small room",
        "picked": picked,
        "length_s": stats["length_s"], "lufs": stats["lufs"], "true_peak_dbtp": stats["true_peak_dbtp"],
    }


def render_one(slug, out_dir):
    c = catalog()[slug]
    P = song(slug, c) if c["kind"] == "song" else piece(slug, c)
    x = perform(P)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"yuzu_{slug.replace('-', '_')}.mp3"
    encode(x, path, c["title"])
    y = decode(path, ch=2)
    stats = {"length_s": round(len(y) / SR, 1), "lufs": round(lufs(y), 2), "true_peak_dbtp": round(true_peak(y), 2),
             "notes": len(P.ev)}
    sp = out_dir / "screen.json"                    # tools/music_screen.py's verdict on this exact file, if it has one
    screen = json.loads(sp.read_text(encoding="utf-8")).get(path.name) if sp.exists() else None
    if screen and screen.get("sha1") != hashlib.sha1(path.read_bytes()).hexdigest()[:16]:
        screen = None
    stats["screen"] = screen["score"] if screen else None
    side = sidecar(slug, c, stats, screen)
    path.with_name(path.name + ".json").write_text(json.dumps(side, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return slug, path.name, stats


def render(only=None, out_dir=OUT, jobs=3):
    slugs = [s for s in catalog() if not only or s in only]
    with ProcessPoolExecutor(max_workers=max(1, jobs)) as ex:
        for slug, name, st in ex.map(render_one, slugs, [out_dir] * len(slugs)):
            print(f"  {name:38} {int(st['length_s']) // 60}:{int(st['length_s']) % 60:02d}  {st['lufs']:6.2f} LUFS  "
                  f"{st['true_peak_dbtp']:6.2f} dBTP  {st['notes']} plucks  screen {st['screen']}", flush=True)


# ---------------------------------------------------------------------------------------------------------- ledger

def ledger(out_dir=OUT):
    with open(LEDGER, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fields = list(rows[0].keys()) if rows else None
    have = {r["path"] for r in rows}
    new = []
    for s in SOURCES:
        p = f"out/koto_music/src/{s['id']}-hq.mp3"
        if p in have:
            continue
        sha = hashlib.sha256(s["file"].read_bytes()).hexdigest()[:16] if s["file"].exists() else "not downloaded"
        new.append({"path": p, "kind": "music source samples (CC0 koto recordings, mined for single plucks)",
                    "title": s["title"], "author": "RutgerMuller (Freesound)", "source_url": s["page"],
                    "license": "CC0 1.0 Universal", "license_url": CC0_URL, "attribution": "none required (CC0)",
                    "modified": "not used as audio: mined for isolated plucks (too few, see tools/koto_music.py mine) and "
                                "measured for partial decay rates and inharmonicity, which tune the koto model",
                    "date_retrieved": VERIFIED,
                    "notes": f"HQ preview {s['preview']} (sha256 {sha}); pack {PACK}; page shows Creative Commons 0 "
                             f"({VERIFIED}); no audio from it is in any track"})
    for slug, c in catalog().items():
        name = f"yuzu_{slug.replace('-', '_')}.mp3"
        p = f"{out_dir.relative_to(ROOT).as_posix()}/{name}"
        if p in have:
            continue
        new.append({"path": p, "kind": "music (Colored pencil on black paper: silly friends on snowy nights playlist, "
                                       "made by tools/koto_music.py)",
                    "title": c["title"], "author": f"{ARTIST} (this repo, tools/koto_music.py)", "source_url": "",
                    "license": OWN, "license_url": "", "attribution": "none",
                    "modified": "original performance in code (modeled koto, synthetic room)", "date_retrieved": VERIFIED,
                    "notes": f"composition: {c['composition']}; {c['pd']} Sidecar {p}.json; no AI-generated audio"})
    if new:
        with open(LEDGER, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
            for r in new:
                w.writerow(ledger_row(r))
    print(f"  {len(new)} rows added to {LEDGER.relative_to(ROOT)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--force", action="store_true")
    sub.add_parser("mine")
    sub.add_parser("ledger")
    r = sub.add_parser("render")
    r.add_argument("--only", help="comma-separated piece names (default: all)")
    r.add_argument("--out", default=str(OUT))
    r.add_argument("--jobs", type=int, default=3)
    a = ap.parse_args()
    if a.cmd == "fetch":
        fetch(a.force)
    elif a.cmd == "mine":
        mine()
    elif a.cmd == "ledger":
        ledger()
    else:
        render(set(a.only.split(",")) if a.only else None, pathlib.Path(a.out).resolve(), a.jobs)


if __name__ == "__main__":
    main()
