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
jivetalker edit   voice_script.txt                                  # edit the script in the browser
jivetalker edit                                                     # ... or create/open one in the page
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

**Japanese** (optional): `pip install -e "$HOME/git/JiveTalker[ja]"`, then `python -m unidic download` (the
dictionary, about 800 MB). See [Languages](VOICE_SCRIPT.md#languages).

Tests (no model or audio needed): `python -m unittest discover -s tests`.

## Editing scripts: `jivetalker edit`

`jivetalker edit voice_script.txt` opens a local page (127.0.0.1 only) with two tabs: **Script**, an editor for
the voice script, and **Voices**, the mixer below. With no script, `jivetalker edit` (or `jivetalker.sh` /
`jivetalker.bat` with no arguments) opens on a start page:

- **New script**: a file name (relative to the folder you started in, or a full path) and a first cast of
  stock or saved voices. Then build it in the Visual view: **Add a speaker** under Cast, and the **New line**
  box under the lines (it suggests the next ID). Marks and directions go on afterwards, as for any line.
- **Open a script**: the scripts found in that folder and the ones below it, or any path.
- **Try the demo**: a short scene that shows off the styles, marks and ramps with Kokoro's stock voices. The
  first time, it is copied to `jivetalker_demo/voice_script.txt` in the current folder; after that your copy
  opens, edits and all (delete the folder to start over). `jivetalker edit --demo` opens it directly.

**New or open…** next to the file name comes back to this page later. You don't need to remember the mark
syntax:

- **Visual** shows every line with its speaker, its direction and its marks. Marked words show how they'll
  sound: bold for stress, spaced out for drawn out, faded for de-stress, and a gap label for a pause. Settings
  a line inherits from `@cast`, `@defaults` or a ramp are shown with dashed borders.
- **Click a word** (Shift-click to take in more words) and the inspector sets its stress, draw-out, pause,
  pronunciation or replacement words. Its pitch has a curve you shape by dragging the points. From the keyboard:
  `+` `-` stress, `~` draw out, `|` pause, `^` pitch shapes, `0` clear, arrow keys to move, Space to play.
- **The line** part of the inspector sets the style, effects, settings and take. It shows where each value
  comes from (`@defaults`, `@cast`, `@ramp`, the line itself, or the style) and what the line ends up with.
- **Play** plays the line's clip if it is up to date, or renders a preview. **Render** renders the lines that
  changed into the clip folder (`--out`, default `voice/` next to the script), like `jivetalker render`.
- **Source** is the file itself, with colours and a list of what fits at the cursor: marks after `[word](`,
  directions after `{`, header lines after `@`. Ctrl+S saves.
- The **Check** panel lists problems, words the phonemizer can't read, and lines flagged for review.

The text file stays the master copy, so you can still edit it by hand or keep it in git. A change in Visual
rewrites only the line it touches. A change made to the file elsewhere is picked up within seconds, and an
edit made on an outdated copy is refused rather than overwriting the other change. Undo works across both
views. Before its first change, each session copies the file to `voice_script.txt.bak`.

## Designing voices: `jivetalker mixer`

The Voices tab of `jivetalker edit` (or `jivetalker mixer` on its own, which opens on that tab; with
`--script` the Script tab is there too). *Tune … in Voices* in the Script tab opens a line's voice with that
line as test text.


Blending and tuning voice packs by ear. A pack's first 128 numbers set the
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

## Singing (experimental): `jivetalker sing`

```
jivetalker sing song.musicxml --voice af_bella -o song.wav --check --guide
jivetalker sing song.abc --voice af_bella -o song.wav
```

The melody comes from a MusicXML score (`.musicxml`, `.xml` or compressed `.mxl`, as MuseScore, Finale,
Sibelius or Dorico export it: write the tune with its lyric syllables there), or from ABC notation with a `w:`
lyric line (`-` splits syllables, `_` holds one over the next note); `jivetalker/sing.py` lists what is read.
Japanese lyrics sing with `--lang ja` (one kana per note; ん and long vowels can take notes of their own).
For scores with several parts, voices or verses: `--part`, `--voice-number`, `--verse` (the choices are listed
when there are any). Each voice sings by itself only over a band of notes
(Kokoro's decoder was trained on speech and can't go much above middle C); the band is measured once per voice
(about a minute, cached), and notes outside it are moved to their pitch with PSOLA, which can sound synthetic.
Syllables can be written as phonemes: `/fˈIəɹ/`, or `Twin/twˈɪŋ/-kle` to keep the spelling.
`--dry-run` shows which syllable goes on which note (no model, instant). `--check` pitch-tracks the result and
reports each note's pitch and when it arrives against its beat; `--json report.json` writes all of that (files,
band, phonemes, per-note results) for scripts and AI agents; `--guide` also writes the melody as plain tones.

## Notes

- Voices are Kokoro voice packs (`.pt`, shape [510, 1, 256]) or stock names such as `af_nicole`.
- Output is Ogg Opus by default, with an automatic fallback to `.wav`; `--format wav|flac` is also available.
- Tested on Linux. Windows is intended to work but not yet tested: first check that `jivetalker preview`
  writes an `.ogg` (not a `.wav` fallback with a warning).
- Recipes written before the rename (marked `voicegen_recipe`) still load.

Layout: `engine.py` (the model with duration/pitch editing), `styles.py` (styles and how directions
resolve), `marks.py` (word marks), `lang/` (what depends on the language: the phonemizer, phoneme classes, pauses, stress and question rules; `en.py`, `ja.py`), `dsp.py` (loudness, whisper, the `internal` echo, `muffled`), `script.py`
(the voice script), `render.py` (caching and the manifest), `voicelab.py` (recipes and axes), `mixer.py` +
`mixer.html` (the voice mixer), `toolkit.py` + `toolkit.html` (the page with both tabs, and the script editor), `cli.py`.

Bump `ENGINE_VERSION` in `__init__.py` when a change alters the sound in a way the cache key can't see
(for example a change inside `engine.py`). Every clip is then rebuilt on the next render.
