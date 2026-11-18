# JiveTalker: notes for Claude

Kokoro TTS voice-line generator with markup. Read README.md (install, layout, mixer) and VOICE_SCRIPT.md
(the script format, every direction and word mark) first.

## Rules

- **Cache key.** `render.cache_key` hashes `ENGINE_VERSION`, the voice file, the resolved settings, the
  tuning constants the line uses, the text and the seed. `tests/test_basics.py` pins `GOLDEN_KEY`: if that
  test fails, every user's existing clips would re-render. Update it only for a deliberate sound change.
- **`ENGINE_VERSION`** (`__init__.py`): bump only when the sound changes in a way the key can't see (e.g.
  inside `engine.py`). It re-renders everything.
- **kokoro is pinned to 0.9.4.** `engine.py` re-implements `KModel.forward_with_tokens` in `_synth_chunk()`
  and refuses other versions. Upgrading means re-checking that code against the new kokoro.
- **Public API.** Games import `jivetalker.marks`, `jivetalker.script` (`Script`, `Line`, `Ramp`),
  `jivetalker.render` (`render`, `print_summary`) and check `jivetalker.__version__`. Keep these stable; if
  one must change, bump `__version__` and say so.
- **Recipe compatibility.** Mixer axis ids (`gender`, `accent`, `pc1`…`pc8`) never change: saved
  `.recipe.json` files refer to them. Hide an axis rather than remove it. Old `voicegen_recipe` files must
  keep loading.
- **Languages.** Language-specific rules live in `jivetalker/lang/` (one module per language, a `Language`
  subclass); the mark syntax, script format and engine edits stay shared. English is the default, and the
  cache key leaves the language out while it is English, so existing clips keep their keys.
- **Seeds** use hashlib, never `hash()` (it varies per process).
- **Stay generic and cross-platform**: no game- or story-specific names, paths or defaults; Linux and
  Windows (use `pathlib`, no shell-outs). Ogg Opus via soundfile by default (`@format vorbis` / `--format vorbis` for engines that can't read Opus), with a `.wav` fallback.
- **Sound is judged by ear, by the user.** Tuning constants (whisper, `dsp.MUFFLED` 700 Hz, stress levels)
  were set in listening rounds; keep them unless asked. For sound changes, render variants and ask the user
  to listen; never call a sound good yourself. Headless browsers here can't play audio, so the mixer can
  only be smoke-tested (page, `/api/info`, `/api/load`).
- **The editor (`toolkit.py`, `toolkit.html`)** never reformats the script: a Visual edit rewrites one line
  (`rewrite_line`), and every edit carries the file version it was made on (`Conflict` if it is stale). The
  page is plain JS with no build step or CDN, so it works offline; the mixer stays its own page in a frame.
  Smoke-test it on a copy of a script, never on a game's real one.
- **Singing (`sing.py`, experimental).** Pitch and timing are checked by measurement, not by ear:
  `jivetalker sing x.abc --voice V --json report.json` pitch-tracks every note (`summary.ok`, `bad_notes`,
  per note `cents`, `onset_ms`); keep 0 notes off by more than 50 cents on the test songs after any change.
  How it *sounds* is still the user's call. Kokoro can't sing above ~300 Hz: notes outside a voice's band
  (`probe_range`, cached per voice; bump `PROBE_VERSION` if singing changes move the bands) are shifted with
  PSOLA. The constants in `sing.py` say which were measured and which are guesses. Sung script lines
  (`{sing file}`) key on the score's contents and every constant in `sing.py`; bump `SING_VERSION` for a sound
  change inside its code. Spoken lines' keys must not move (`GOLDEN_KEY`).

## Running

- **Singing, step by step (for agents):** take a MusicXML score (`--part`/`--voice-number`/`--verse` pick the
  line) or write ABC (`sing.py`'s docstring has the subset); run
  `jivetalker sing x.abc --voice V --dry-run --json plan.json` (instant, no model) to see which syllable lands
  on which note and fix the lyric until it matches; then render with `--json report.json` and read
  `summary` (re-render or rewrite syllables as `/phonemes/` for `bad_notes`). Add `-v` (or read `phrases` in
  the report) to see the phonemes each phrase was sung with. The first render of a voice measures its band
  (about a minute). Errors exit with code 1 and one line on stderr.

- Tests (no model or audio needed): `python -m unittest discover -s tests`.
- Long renders (minutes on CPU) go in the background.
- Commit only when asked.
