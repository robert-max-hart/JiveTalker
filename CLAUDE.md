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
- **Seeds** use hashlib, never `hash()` (it varies per process).
- **Stay generic and cross-platform**: no game- or story-specific names, paths or defaults; Linux and
  Windows (use `pathlib`, no shell-outs). Ogg Opus via soundfile, with a `.wav` fallback.
- **Sound is judged by ear, by the user.** Tuning constants (whisper, `dsp.MUFFLED` 700 Hz, stress levels)
  were set in listening rounds; keep them unless asked. For sound changes, render variants and ask the user
  to listen; never call a sound good yourself. Headless browsers here can't play audio, so the mixer can
  only be smoke-tested (page, `/api/info`, `/api/load`).
- **The editor (`toolkit.py`, `toolkit.html`)** never reformats the script: a Visual edit rewrites one line
  (`rewrite_line`), and every edit carries the file version it was made on (`Conflict` if it is stale). The
  page is plain JS with no build step or CDN, so it works offline; the mixer stays its own page in a frame.
  Smoke-test it on a copy of a script, never on a game's real one.

## Running

- Tests (no model or audio needed): `python -m unittest discover -s tests`.
- Long renders (minutes on CPU) go in the background.
- Commit only when asked.
