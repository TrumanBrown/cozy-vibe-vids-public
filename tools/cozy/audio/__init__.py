"""The procedural ambience (TASKS.md T17), moved verbatim from tools/audio.py, which stays the command line. Other
tools import what they need from the modules here. Its docstring has the design.

  dsp        signal helpers: FIR design, FFT convolution, noise, the bubble, pan, a peak limiter, WAV writing
  kernels    the impact kernels the grains play: rain drops, drips, fire crackles and pops, cup clinks
  events     the event sounds: boat wash and wake laps, lantern gutter, fish, creak, car, train, log settle, neon
  ambience   the beds and defaults, and class Ambience: the bed in 15 s blocks, the thunder, the events in place

Import the modules by their full name (`from cozy.audio.dsp import ...`). cozy.code follows that form to the file,
which keeps the stem cache and the render fingerprint current; it doesn't follow `from cozy.audio import dsp`, and
it doesn't read this file, so keep code out of it.
"""
