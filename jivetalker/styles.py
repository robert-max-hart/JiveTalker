"""Styles, settings and how a direction such as "trance 0.6, internal, pause 2" resolves to engine settings.

Resolution order: DEFAULTS -> the style -> the line's own settings.
- `speed` in a direction sets the speaker's base speed; the style's speed then scales it
  (so `{deep, speed 0.9}` = 0.9 x 0.75).
- `pitch` and `volume` in a direction add to the style's; every other setting replaces the style's value.
"""
import re
from dataclasses import dataclass, field

from . import lang as languages
from .lang.en import ENGLISH as _en

DEFAULTS = dict(speed=0.95, pitch=0.0, range_=1.0, drift=0.0, pause=1.0, floor=0.0, human=1.0,
                volume=0.0, take=0)

# ---- approved styles (2026-11-11 listening rounds; names in quotes are the round labels)
# pause values were 1.2 / 2.5 / 2.0 (deep) when `pause` stretched the model's own (tiny) punctuation; now it
# scales real inserted silence (PAUSES), so they're gentler.
TRANCE_LIGHT = dict(speed=0.85, pitch=-1.5, range_=0.45, pause=1.15, drift=0.0)  # "t02", depth 0
TRANCE_DEEP = dict(speed=0.75, pitch=-3.5, range_=0.20, pause=1.8, drift=1.0)    # "t04", depth 1


def trance(depth):
    depth = min(1.0, max(0.0, depth))
    return {k: TRANCE_LIGHT[k] + (TRANCE_DEEP[k] - TRANCE_LIGHT[k]) * depth for k in TRANCE_LIGHT}


STYLES = {
    'normal': dict(),
    'deep': dict(speed=0.75, pitch=-3.0, range_=0.0, pause=1.6),               # "m05": dead-flat monotone
    'shout': dict(pitch=4.0, range_=1.4, floor=0.55),                             # "s06/s07"
    'soft': dict(speed=0.9, pitch=-2.0, range_=0.6, floor=0.55, breath=0.15),   # own voice, a trace of whisper
    'whisper': dict(speed=0.88, range_=0.6),                                      # "w65", whisper renderer
}
STYLE_LEVEL_DB = {'soft': -8.0, 'whisper': -12.0}    # ear-weighted, relative to a normal line
# (soft used to borrow af_nicole's delivery, which made e141 sound like another person; 2026-11-12 it became
# the speaker's own voice with breath mixed in. `breath` works on any style except whisper.)
EFFECTS = ('internal', 'muffled')                    # post effects that combine with any style (applied in order)

# ---- word marks -> per-word edits
# What stress (+ / -) does depends on the language: see lang/ (English: lang/en.py). These names are the
# English tables, kept for older code.
STRESS, STRESS_MORE, STRESS_MAX = _en.STRESS, _en.STRESS_MORE, _en.STRESS_MAX
STRETCH = {1: 1.25, 2: 1.5}     # 2026-11-13: was 1.5 / 2.0 (too long); every level now adds 0.25 up to ~~~~
# Levels 3-5 (~~~ to ~~~~~), for when ~~ isn't enough. Untuned by ear: they may sound bad. Each also raises
# its own limit (`cap` instead of STRETCH_CAP), or the limit would flatten it into level 2. A line's clip
# depends only on the levels it uses (render.tuning), so tuning one level rebuilds only the lines that use it.
STRETCH_MORE = {3: dict(factor=1.75, cap=0.5), 4: dict(factor=2.0, cap=0.65), 5: dict(factor=2.5, cap=0.8)}
MARK_LEVELS = 5         # most + or ~ a mark may stack
DESTRESS_LEVELS = 3     # most - a mark may stack


# Pitch shape (^): semitones, spread evenly across the word(s), on top of everything else (stress included).
SHAPE_MAX = 12.0
SHAPE_SOFTEN = 3         # F0 samples (12.5 ms each) of smoothing on a shape's edges (odd)
# Pause marks (|): seconds held after the word, 0.2 per bar, at `pause 1` (`pause` scales them, like PAUSES);
# |seconds is exact. No random variation (`human`) on either: they are set on purpose. (The comma they're held
# on also lengthens the word before it a little, ~0.06 s.)
PAUSE_MARKS = {n: round(0.2 * n, 2) for n in range(1, 6)}
PAUSE_MAX = 5.0


def word_edit(mark, lang=None):
    """a word Mark -> the engine's per-word edit: {'over', 'pitch', 'fall', 'gain', 'dur', 'max', 'sustain',
    'cap', 'shape', 'pause_after', 'pause_exact'} (only what applies). lang: a code or Language (default English)"""
    stress, stretch = mark.stress, mark.stretch
    e = languages.get(lang).stress(stress)
    if stretch:
        more = STRETCH_MORE.get(stretch)
        e['dur'] = e.get('dur', 1.0) * (more['factor'] if more else STRETCH[stretch])
        e['sustain'] = True
        if more:
            e['cap'] = more['cap']
    if mark.shape:
        e['shape'] = list(mark.shape)
    if mark.pause_s:
        e['pause_after'], e['pause_exact'] = mark.pause_s, True
    elif mark.pause:
        e['pause_after'] = PAUSE_MARKS[mark.pause]
    return e

SUSTAIN_SMOOTH = 4.0    # F0 samples (12.5 ms): pitch smoothing inside drawn-out words
SUSTAIN_ENERGY = 1.5    # drawn-out words keep their energy at least this far below the line's median (N units)
STRETCH_CAP = 0.35      # seconds at speed 1: a drawn-out word stretches no single sound past this (e209)

# ---- pauses: Kokoro holds punctuation inside a line for only 30-50 ms (it only pauses properly at the end
# of the line), so the engine lengthens the mark to these totals (seconds at `pause 1`, including the spaces
# after it; `pause` scales them) with voicing and energy off over it (see QUIET_*).
PAUSES = dict(comma=0.18, clause=0.28, dash=0.28, sentence=0.42, ellipsis=0.55)
PAUSE_HUMAN = 0.12      # lognormal sigma of each pause, times `human`

# ---- quiet: on punctuation and the line's pads the model keeps humming (pitch) and breathing (energy N);
# both are switched off there. N around -5 is what the model itself predicts for silence.
QUIET_ENERGY = -5.0
QUIET_EASE = 1.5       # F0 samples (12.5 ms each): how softly energy eases into and out of the quiet

# ---- length cap: the model now and then holds a sound far too long (the "r" of "sweater" for 0.95 s).
# Seconds at speed 1 (divided by speed): inner = inside a phrase, phrase_end = before mid-line punctuation,
# gap = a space between words. The last sound of the line isn't capped.
LENGTH_CAP = dict(inner=0.30, phrase_end=0.50, gap=0.15)

# ---- pitch bridge: the predicted F0 sometimes drops out (or by about an octave) over sounds that should be
# voiced, and the decoder goes nearly silent there ("thorough" lost its second syllable). Drops below `ratio`
# x the local median (window `win` F0 samples each side, 80 per second), at most `max_len` samples long,
# voiced on both sides and only over vowels/sonorants, are filled in.
PITCH_BRIDGE = dict(ratio=0.7, win=12, max_len=24)

# ---- question rise: which questions rise and by how much depends on the language (lang/; English: lang/en.py).
QUESTION = _en.QUESTION     # the English tuning, kept for older code

SETTING_NAMES = {'speed': 'speed', 'pitch': 'pitch', 'range': 'range_', 'drift': 'drift', 'pause': 'pause',
                 'floor': 'floor', 'human': 'human', 'volume': 'volume', 'take': 'take', 'rise': 'rise',
                 'breath': 'breath', 'lang': 'lang', 'sing': 'sing'}
ADDITIVE = ('pitch', 'volume')
TEXT_SETTINGS = ('lang', 'sing')    # settings that hold words, not a number (and can't be ramped)
SONG_FILES = ('.abc', '.musicxml', '.xml', '.mxl')
SING_OPTIONS = ('part', 'voice', 'verse', 'transpose', 'band')


def parse_sing(value):
    """'songs/x.musicxml verse=2 transpose=-12' -> (path, {option: value}); see SING_OPTIONS"""
    words = (value or '').split()
    if not words:
        raise ValueError('"sing" needs a song file, e.g. "sing songs/lullaby.musicxml"')
    path, opts = words[0], {}
    if not path.lower().endswith(SONG_FILES):
        raise ValueError(f'sing: "{path}" is not a song file ({", ".join(SONG_FILES)})')
    for w in words[1:]:
        k, eq, v = w.partition('=')
        if not eq or k not in SING_OPTIONS or not v:
            raise ValueError(f'sing: "{w}" is not an option (' + ', '.join(f'{o}=' for o in SING_OPTIONS) + ')')
        if k in ('verse', 'transpose'):
            try:
                int(v)
            except ValueError:
                raise ValueError(f'sing: {k}= takes a whole number') from None
        if k == 'band' and v not in ('auto', 'off') and not re.match(r'^\d+-\d+$', v):
            raise ValueError('sing: band= is auto, off, or two MIDI notes such as 50-62')
        opts[k] = v
    return path, opts


@dataclass
class Direction:
    style: str = None                    # None = not set here (inherits; 'normal' in the end)
    depth: float = None                  # trance depth
    effects: list = field(default_factory=list)
    settings: dict = field(default_factory=dict)    # engine names (range_, ...)

    def __str__(self):
        parts = []
        if self.style:
            parts.append(self.style if self.depth is None else f'{self.style} {self.depth:g}')
        parts += self.effects
        inv = {v: k for k, v in SETTING_NAMES.items()}
        parts += [f'{inv[k]} {v}' if isinstance(v, str) else f'{inv[k]} {v:g}' for k, v in self.settings.items()]
        return ', '.join(parts)


def parse_direction(text):
    """'trance 0.6, internal, pause 2' -> Direction. An empty string is 'normal'."""
    d = Direction()
    styled = False
    for part in filter(None, (p.strip() for p in (text or '').split(','))):
        words = part.split()
        name = words[0].lower()
        if name in STYLES or name == 'trance':
            if styled:
                raise ValueError(f'two styles in "{text}"')
            styled = True
            d.style = name
            if name == 'trance':
                d.depth = float(words[1]) if len(words) > 1 else 0.5
            elif len(words) > 1:
                raise ValueError(f'"{name}" takes no value')
        elif name in EFFECTS:
            d.effects.append(name)
        elif name in SETTING_NAMES:
            if name == 'sing':
                path, opts = parse_sing(' '.join(words[1:]))
                d.settings[name] = ' '.join([path] + [f'{k}={opts[k]}' for k in SING_OPTIONS if k in opts])
                continue
            if name in TEXT_SETTINGS:
                if len(words) != 2:
                    raise ValueError(f'"{name}" needs one value: {", ".join(languages.codes())}')
                d.settings[name] = languages.get(words[1]).code      # unknown languages raise ValueError
                continue
            if len(words) != 2:
                raise ValueError(f'"{name}" needs one number, e.g. "{name} 1.2"')
            v = float(words[1])
            d.settings[SETTING_NAMES[name]] = int(v) if name == 'take' else v
        else:
            raise ValueError(f'unknown direction "{part}"')
    return d


def merge(*directions):
    """later directions win: a set style replaces the earlier one; effects add up; settings replace, except
    pitch and volume, which add up (so a speaker's `@cast ... {pitch 1}` survives a line's own `pitch -1`)"""
    out = Direction()
    for d in directions:
        if d is None:
            continue
        if d.style:
            out.style, out.depth = d.style, d.depth
        out.effects += [e for e in d.effects if e not in out.effects]
        for k, v in d.settings.items():
            out.settings[k] = out.settings.get(k, 0) + v if k in ADDITIVE else v
    return out


def resolve(direction):
    """Direction -> flat engine settings (plus 'style', 'effects', 'level_db')."""
    s = dict(DEFAULTS)
    base_speed = direction.settings.get('speed', s['speed'])
    name = direction.style or 'normal'
    style = trance(direction.depth) if name == 'trance' else STYLES[name]
    s.update(style)
    s['speed'] = base_speed * style.get('speed', 1.0)
    for k, v in direction.settings.items():
        if k == 'speed':
            continue
        s[k] = s[k] + v if k in ADDITIVE else v
    if s.get('lang') == languages.DEFAULT:     # English is the default: its lines keep their cache keys
        del s['lang']
    s['style'] = name
    s['effects'] = list(direction.effects)
    s['level_db'] = STYLE_LEVEL_DB.get(name, 0.0) + s.pop('volume')
    return s


def question_rises(settings, plain, lang=None):
    """semitones of rise for each question in the line, in order; the line's `rise` setting applies to all.
    lang: a code or Language (default English), which decides the rest"""
    return languages.get(lang).question_rises(settings, plain)
