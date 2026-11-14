# JiveTalker

Directed voice lines from [Kokoro](https://github.com/hexgrad/kokoro) TTS. You write a plain-text voice
script with one line per clip, giving a style (trance, deep monotone, shout, soft, whisper), effects (an echo
for thoughts, a muffled wall), settings and word marks (stress, drawn-out words, pitch shapes, pauses), and
JiveTalker renders the clips plus a manifest. It only re-renders what changed. The script format is in
[VOICE_SCRIPT.md](VOICE_SCRIPT.md).

```
jivetalker preview "Close your [eyes](+~)..." --voice voices/lee.pt --style "trance 0.6" -o x.ogg
jivetalker check  voice_script.txt
jivetalker render voice_script.txt --out voice/ --dry-run
jivetalker render voice_script.txt --out voice/
jivetalker mixer  --voices-dir voices/ --script voice_script.txt     # design voices in the browser
```

## Install

Python 3.10 or newer; a GPU isn't needed. Use a virtual environment, and install the CPU build of torch
first (it is much smaller than the default one).

Linux / macOS:

```
python3 -m venv ~/venv/kokoro
~/venv/kokoro/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
~/venv/kokoro/bin/pip install -e ~/git/JiveTalker
~/venv/kokoro/bin/jivetalker preview "Hello there." --voice af_nicole -o hello.ogg
```

Windows (PowerShell):

```
py -3 -m venv $HOME\venv\kokoro
& $HOME\venv\kokoro\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cpu
& $HOME\venv\kokoro\Scripts\pip install -e $HOME\git\JiveTalker
& $HOME\venv\kokoro\Scripts\jivetalker preview "Hello there." --voice af_nicole -o hello.ogg
```

`-e` (editable) means changes to this folder take effect at once, without reinstalling. espeak-ng comes
with the `espeakng-loader` package, so there is nothing else to install. On first use the model (about
330 MB) downloads from Hugging Face; for offline use, pass `--model-dir` (a folder with `config.json` and
the `.pth`).

Tests (no model or audio needed): `python -m unittest discover -s tests`.

## Designing voices: `jivetalker mixer`

A local page (127.0.0.1 only) for blending and tuning voice packs by ear. A pack's first 128 numbers set the
**timbre** (what the voice sounds like) and the last 128 the **delivery** (intonation, pacing, energy), and
the mixer sets each half on its own:

- **Blend**: any stock or own voices with weights. Weights are divided by their sum, so a negative weight
  pushes away from a voice (`mara 1.2, af_nicole -0.2`).
- **Adjust**: sliders along `gender`, `accent` and the eight principal axes of the 43 stock voices, in
  standard deviations. A mark on each slider shows where the current voice sits. Each slider is named for
  what it does to that half (e.g. timbre *size*, delivery *pitch*, *expression*, *tempo*; hover for details,
  `AXIS_NAMES` in `voicelab.py`); recipes store the ids (`gender`, `pc6`, ...), which never change.
- **Variations**: six random nudges along the principal axes; keep the best and repeat with a smaller step.
- **Preview** through the full engine, with any direction (`trance 0.6`, `whisper`, ...) or a line picked from
  `--script`; every take is kept so you can replay or restore it, and *Compare with* plays another voice.
- **Save** writes `<name>.pt` plus `<name>.recipe.json` (the blend and adjustments) to `--save-dir` (default:
  the first `--voices-dir`). Replacing a file keeps the old one as `.bak-<time>`.

Loading a voice uses its `.recipe.json` if there is one; otherwise the mixer works out the stock blend it was
made from (exact for plain blends), or uses the file as it is.

```
jivetalker voice recipe voices/mara.pt --write        # recover a .pt's stock blend into mara.recipe.json
jivetalker voice build voices/mara.recipe.json -o m.pt  # rebuild a .pt from a recipe
```

## Notes

- Voices are Kokoro voice packs (`.pt`, shape [510, 1, 256]) or stock names such as `af_nicole`.
- Output is Ogg Opus by default, with an automatic fallback to `.wav`; `--format wav|flac` is also available.
- Tested on Linux. Windows is intended to work but not yet tested: first check that `jivetalker preview`
  writes an `.ogg` (not a `.wav` fallback with a warning).
- Recipes written before the rename (marked `voicegen_recipe`) still load.

Layout: `engine.py` (the model with duration/pitch editing), `styles.py` (styles and how directions
resolve), `marks.py` (word marks), `dsp.py` (loudness, whisper, the `internal` echo, `muffled`), `script.py`
(the voice script), `render.py` (caching and the manifest), `voicelab.py` (recipes and axes), `mixer.py` +
`mixer.html` (the voice mixer), `cli.py`.

Bump `ENGINE_VERSION` in `__init__.py` when a change alters the sound in a way the cache key can't see
(for example a change inside `engine.py`). Every clip is then rebuilt on the next render.
