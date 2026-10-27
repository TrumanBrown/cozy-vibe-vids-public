"""ffmpeg and ffprobe for every tool (TASKS.md T11): one way to run them and one error when they fail.

  run_ffmpeg(args)                   ffmpeg <args>; each caller keeps its own log level and options
  probe(path, entries, streams=...)  ffprobe -show_entries <entries> for a file, parsed: {"format": {...}, "streams": [...]}
  grab_frame(video, ss, ...)         decoded frames as raw bytes: ffmpeg -v error [-ss] [-t] -i <video> [-frames:v] [-vf]
                                     -f rawvideo [-pix_fmt] -, always in that order, so a QA number made from a grab (the
                                     seam check, the motion maps, the hour join) is the same to the bit as before

A failure raises MediaError, a subprocess.CalledProcessError (an `except CalledProcessError` still catches it) whose
message is the program, its exit code, the command and the last lines it printed. check=False hands back what ffmpeg
gave instead, for the callers that make do without (a missing frame drawn grey, a duration of 0).
"""
import json
import subprocess


class MediaError(subprocess.CalledProcessError):
    def __str__(self):
        err = self.stderr.decode("utf-8", "replace") if isinstance(self.stderr, bytes) else (self.stderr or "")
        tail = "".join(f"\n  {x}" for x in err.strip().splitlines()[-8:])
        return f"{self.cmd[0]} exited {self.returncode}: {' '.join(str(c) for c in self.cmd)}{tail}"


def _run(cmd, check, capture, **kw):
    r = subprocess.run(cmd, capture_output=capture, **kw)
    if check and r.returncode:
        raise MediaError(r.returncode, cmd, r.stdout, r.stderr)
    return r


def run_ffmpeg(args, *, check=True, capture=True, **kw):
    """ffmpeg <args>, its CompletedProcess. capture: stdout and stderr come back (bytes, or str with text=True) and
    stderr's last lines go in the error; capture=False leaves both on the console (an encode's progress and errors)."""
    return _run(["ffmpeg", *args], check, capture, **kw)


def probe(path, entries, *, streams=None, args=(), check=True):
    """ffprobe's JSON for a file with the entries asked for ("stream=width,height:format=duration"): the sections
    "format" and "streams" (a list). streams selects them ("v:0"); args go first (-count_packets, -show_data_hash
    sha256). check=False: {} when ffprobe gave nothing."""
    cmd = ["ffprobe", "-v", "error", *args, *(["-select_streams", streams] if streams else []), "-show_entries", entries,
           "-of", "json", str(path)]
    r = _run(cmd, check, True, text=True)
    return json.loads(r.stdout) if r.stdout.strip() else {}


def grab_frame(video, ss=None, *, t=None, frames=None, vf=None, pix_fmt=None, check=True):
    """Raw decoded frames (rawvideo) from a video: from ss (a string, so each caller keeps its own precision) for t
    seconds of input or `frames` frames, through the filter vf, in pix_fmt (else what vf ends in)."""
    cmd = ["-v", "error", *(["-ss", ss] if ss is not None else []), *(["-t", t] if t is not None else []), "-i", str(video),
           *(["-frames:v", str(frames)] if frames is not None else []), *(["-vf", vf] if vf else []), "-f", "rawvideo",
           *(["-pix_fmt", pix_fmt] if pix_fmt else []), "-"]
    return run_ffmpeg(cmd, check=check).stdout
