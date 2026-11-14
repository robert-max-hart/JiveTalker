"""Singing (experimental): a melody in ABC notation with a lyric line, or a MusicXML score -> a sung line.

MusicXML (.musicxml, .xml, or compressed .mxl: what MuseScore, Finale, Sibelius, Dorico export) is read with
load(): one part and one voice (the first with lyrics, unless chosen), its notes, rests, ties and tempo marks,
and one verse of its lyric syllables. Of a chord only the first written note is sung (keep the melody in a
voice of its own); grace notes are skipped. Lyric syllables can be /phonemes/ as below.

    X:1
    L:1/4                 default note length
    Q:1/4=96              tempo
    K:G                   key (major or minor: G, Em, Bb, F#m ...)
    G G d d | e e d2 | z c c B B | A A G2 |
    w: Twin-kle twin-kle lit-tle star, _ how I won-der what you are

Notes: C D E F G A B (the octave from middle C), c d e ... (one up), ' and , raise or lower an octave;
^ sharp, _ flat, = natural (until the bar line); a number after the note multiplies its length (2, 3/2, /2, /);
z is a rest; - after a note ties it to the next (one longer note); | bar lines are only for reading. Lyrics (w:): one syllable per note; - splits a word's syllables,
_ holds the syllable before over one more note (a melisma), * leaves a note unsung (held, like _).
A syllable can be written as phonemes between slashes, in misaki's notation (the one `jivetalker preview -v`
prints): /fˈIəɹ/ for a whole word, or Twin/twˈɪŋ/-kle for one syllable: with its spelling before the slashes,
the word is phonemized whole from its spelling (so "kle" is said as in "twinkle") and only that syllable is
replaced. Without spellings, a word's other syllables are phonemized one by one.

Pitch beyond the voice: Kokoro's decoder follows a pitch only over a band around the voice's speaking pitch
(probe_range measures it per voice, and caches it). Notes outside the band are sung at the band's edge and then
moved to their real pitch with PSOLA (psola()), which keeps the vowels' sound but can sound synthetic.

How it is sung: the words are phonemized whole (so they sound as spoken), split into syllables at their vowels,
and timed so each syllable's vowel starts on its note: the consonants before the vowel come just before the beat,
the ones after it at the end of the note. Pitch is set to the notes inside the model (as for speech marks), with
a short glide between notes and vibrato on long ones. Every phrase between rests is rendered on its own.

Untuned by ear: the constants below are first guesses.
"""
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import dsp, lang as languages

FPS = 40.0                  # model duration frames per second (600 samples at 24 kHz; F0 runs at 2 per frame)
CONSONANT_MAX = 0.15        # seconds: longest a single consonant may last
CONSONANT_SHARE = 0.5       # at most this share of a note goes to consonants (the vowel needs the rest)
PITCH_LEAD = 0.02           # seconds: pitch changes this much before the beat (measured: without it pitch
                            # changes arrived +20 ms late, median; with it, 0)
GLIDE = 0.03                # seconds: pitch glide between notes (gaussian sigma)
VIBRATO = dict(rate=5.5, depth=0.3, after=0.25, fade=0.25)  # Hz, semitones, seconds into a note, fade-in
SUSTAIN_ENERGY = -2.0       # held vowels' energy (N) is kept at least at the phrase's loud level (90th percentile)
                            # minus this: a held vowel fades to silence at speech levels (2026-11-14, measured)
HOLD_LEVEL = dict(attack=0.08, max_gain=4.0)   # then each vowel is held at the loudness of its first `attack` s
OPEN_VOWELS = True          # held vowels are voiced from an open, long version of the syllable (see _sing_phrase)
OPEN_LONG = True            # ... with a length mark after the vowel
OPEN_HOLD = 0.3             # seconds: a vowel held at least this long counts as held
OPEN_RETURN = 3             # frames at the end of a held vowel that blend back to its real context (into the coda)
# Measured 2026-11-14 (sustained notes, pitch-tracked): voices follow the notes within a few cents over a band of
# roughly an octave and a half around their speaking pitch, and not above ~300 Hz for any voice (af_bella F3-D4,
# am_adam C2-E4, af_nicole D3-A3); above it the decoder drops an octave or the voice turns to noise.
CEILING_HZ = 300.0
PROBE = dict(low=36, high=76, words=('far', 'see'), length=0.8, cents=50, voiced=0.7)   # C2..E5
BAND_MARGIN = (2, 5)        # semitones kept inside the measured band (bottom, top): sustained test notes hold
                            # higher than notes inside a phrase do (am_adam's G4 failed in a line; D4 held)
PROBE_VERSION = 1           # bump when singing changes in a way that moves the voices' bands
ONSET_BIAS_MS = 35.0        # the pitch tracker's wide window hears voicing start ~35 ms early after silence
                            # (calibrated on the guide tones; on pitch changes it is within ~10 ms)
UNVOICED_STEP = 0.005       # seconds: PSOLA grain spacing where there is no pitch (copied unchanged)
LEAD_IN = 0.3               # seconds of silence before the first note
TAIL = 0.4                  # seconds after the last note

NOTE_STEPS = dict(C=0, D=2, E=4, F=5, G=7, A=9, B=11)
SHARPS = 'FCGDAEB'          # order of sharps (and, reversed, of flats) in key signatures
MAJOR_KEYS = {'C': 0, 'G': 1, 'D': 2, 'A': 3, 'E': 4, 'B': 5, 'F#': 6, 'C#': 7,
              'F': -1, 'Bb': -2, 'Eb': -3, 'Ab': -4, 'Db': -5, 'Gb': -6, 'Cb': -7}
MINOR_KEYS = {'A': 0, 'E': 1, 'B': 2, 'F#': 3, 'C#': 4, 'G#': 5, 'D#': 6, 'A#': 7,
              'D': -1, 'G': -2, 'C': -3, 'F': -4, 'Bb': -5, 'Eb': -6, 'Ab': -7}


@dataclass
class Note:
    midi: int               # None = rest
    start: float            # seconds
    length: float           # seconds

    @property
    def hz(self):
        return 440.0 * 2 ** ((self.midi - 69) / 12)


@dataclass
class Song:
    notes: list             # [Note], rests included
    lyrics: list            # [(syllable, word index)] per sung note, or None for a held note ('_' / '*')
    words: list             # the lyric's words, without hyphens
    title: str = ''
    parts: list = None      # each word's syllables as written ('/.../' = phonemes)


# ---------------------------------------------------------------------------------------------- ABC
def key_accidentals(key):
    """K: field -> {letter: semitone shift}"""
    k = (key or 'C').split()[0] if (key or '').strip() else 'C'
    m = re.match(r'^([A-G][b#]?)(m|min|maj)?$', k)
    if not m:
        raise ValueError(f'K:{key}: use a major or minor key such as G, Em, Bb or F#m')
    n = (MINOR_KEYS if m.group(2) in ('m', 'min') else MAJOR_KEYS).get(m.group(1))
    if n is None:
        raise ValueError(f'K:{key}: not a key signature')
    return {c: 1 for c in SHARPS[:n]} if n >= 0 else {c: -1 for c in SHARPS[::-1][:-n]}


def _length(s):
    """'2', '3/2', '/2', '/', '' -> multiplier"""
    if not s:
        return 1.0
    if '/' not in s:
        return float(s)
    a, _, b = s.partition('/')
    return (float(a) if a else 1.0) / (float(b) if b else 2.0)


NOTE_RE = re.compile(r"(\^\^|\^|__|_|=)?([A-Ga-gz])([',]*)(\d*/?\d*)")


def parse_abc(text, transpose=0):
    """ABC (one voice, the subset in the module doc) -> Song. transpose: semitones."""
    fields, body, lyric = {}, [], []
    for raw in text.splitlines():
        s = raw.split('%')[0].strip()
        if not s:
            continue
        if re.match(r'^w:', s):
            lyric.append(s[2:].strip())
        elif re.match(r'^[A-Za-z]:', s):
            fields[s[0]] = s[2:].strip()
        else:
            body.append(s)
    unit = 1 / 8
    if fields.get('L'):
        a, _, b = fields['L'].partition('/')
        unit = float(a) / float(b or 1)
    beat, bpm = 1 / 4, 120.0
    if fields.get('Q'):
        m = re.match(r'^(?:(\d+)/(\d+)\s*=\s*)?(\d+(?:\.\d+)?)$', fields['Q'].replace(' ', ''))
        if not m:
            raise ValueError(f'Q:{fields["Q"]}: write the tempo as e.g. 1/4=96')
        if m.group(1):
            beat = int(m.group(1)) / int(m.group(2))
        bpm = float(m.group(3))
    sec_per_unit = unit / beat * 60.0 / bpm
    key = key_accidentals(fields.get('K'))

    notes, t, bar, tie = [], 0.0, {}, False
    music = ' '.join(body)
    pos = 0
    while pos < len(music):
        ch = music[pos]
        if ch == '-':                           # a tie: the next note of the same pitch lengthens this one
            tie = True; pos += 1; continue
        if ch in ' |:[]':
            if ch == '|':
                bar = {}
            pos += 1; continue
        m = NOTE_RE.match(music, pos)
        if not m:
            raise ValueError(f'not understood in the notes: "{music[pos:pos + 10]}"')
        acc, letter, octs, ln = m.groups()
        length = _length(ln) * sec_per_unit
        if letter == 'z':
            notes.append(Note(None, t, length))
        else:
            up = letter.upper()
            octave = 5 if letter.islower() else 4
            octave += octs.count("'") - octs.count(',')
            if acc:
                shift = {'^': 1, '^^': 2, '_': -1, '__': -2, '=': 0}[acc]
                bar[(up, octave)] = shift
            shift = bar.get((up, octave), key.get(up, 0))
            midi = 12 * (octave + 1) + NOTE_STEPS[up] + shift + transpose
            if tie and notes and notes[-1].midi == midi:
                notes[-1].length += length
            else:
                notes.append(Note(midi, t, length))
        tie = False
        t += length
        pos = m.end()
    sung = [n for n in notes if n.midi is not None]
    syl, words, written = parse_lyrics(' '.join(lyric), len(sung))
    return Song(notes, syl, words, fields.get('T', ''), written)


def parse_lyrics(text, n_notes):
    """w: text -> ([(syllable, word index) or None per sung note], [words], [each word's syllables])"""
    out, words, written = [], [], []
    for tok in text.replace('|', ' ').split():
        held = 0
        while tok and tok[-1] == '_':          # "star_" = star, held one more note
            tok = tok[:-1]; held += 1
        if tok in ('', '*'):
            out += [None] * (held + (1 if tok == '*' else 0)); continue
        parts = tok.split('-')
        word = ''.join(parts)
        words.append(word)
        written.append([p for p in parts if p])
        for p in parts:
            if p == '':
                out.append(None)                # "wor--ld": an extra note on the syllable before
            else:
                out.append((p, len(words) - 1))
        out += [None] * held
    if len(out) > n_notes:
        raise ValueError(f'the lyric has {len(out)} syllables (and holds) for {n_notes} notes')
    out += [None] * (n_notes - len(out))        # a lyric shorter than the tune: the last syllable is held
    return out, words, written


# ---------------------------------------------------------------------------------------------- MusicXML
STEPS = dict(C=0, D=2, E=4, F=5, G=7, A=9, B=11)


def load(path, transpose=0, part=None, voice=None, verse=1):
    """a song file -> Song: ABC (.abc) or MusicXML (.musicxml, .xml, .mxl)"""
    path = Path(path)
    if path.suffix.lower() in ('.musicxml', '.xml', '.mxl'):
        return parse_musicxml(path.read_bytes(), transpose, part, voice, verse)
    if part is not None or voice is not None or verse != 1:
        raise ValueError('--part, --voice and --verse are for MusicXML scores')
    return parse_abc(path.read_text(encoding='utf-8'), transpose)


def _musicxml_root(data):
    import io
    import xml.etree.ElementTree as ET
    import zipfile
    if data[:2] == b'PK':                       # .mxl: a zip; META-INF/container.xml names the score
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            name = None
            try:
                c = ET.fromstring(z.read('META-INF/container.xml'))
                name = next((e.get('full-path') for e in c.iter() if e.tag.endswith('rootfile')), None)
            except KeyError:
                pass
            name = name or next(n for n in z.namelist() if not n.startswith('META-INF') and n.endswith('ml'))
            data = z.read(name)
    root = ET.fromstring(data)
    for e in root.iter():                       # drop any namespace
        if '}' in e.tag:
            e.tag = e.tag.split('}', 1)[1]
    if root.tag == 'score-timewise':
        raise ValueError('this MusicXML is "timewise"; export it as a normal (partwise) MusicXML file')
    if root.tag != 'score-partwise':
        raise ValueError('not a MusicXML score')
    return root


def musicxml_parts(data):
    """[(id, name, voices with lyrics)] of a MusicXML score, to choose --part / --voice"""
    root = _musicxml_root(data)
    names = {sp.get('id'): (sp.findtext('part-name') or '').strip() for sp in root.iter('score-part')}
    out = []
    for p in root.findall('part'):
        voices = sorted({n.findtext('voice') or '1' for n in p.iter('note') if n.find('lyric') is not None})
        out.append((p.get('id'), names.get(p.get('id'), ''), voices))
    return out


def parse_musicxml(data, transpose=0, part=None, voice=None, verse=1):
    """MusicXML bytes -> Song. part: id, name or 1-based number (default: the first part with lyrics);
    voice: the voice number (default: the first with lyrics in that part); verse: the lyric line (number)."""
    root = _musicxml_root(data)
    parts = root.findall('part')
    info = musicxml_parts(data)
    if not parts:
        raise ValueError('the score has no parts')
    if part is None:
        k = next((i for i, (_, _, vs) in enumerate(info) if vs), 0)
    else:
        sel = str(part)
        k = next((i for i, (pid, name, _) in enumerate(info) if sel in (pid, name) or sel == str(i + 1)), None)
        if k is None:
            raise ValueError(f'no part "{part}": the parts are '
                             + ', '.join(f'{i + 1} ({pid} {name})'.strip() for i, (pid, name, _) in enumerate(info)))
    p = parts[k]
    if voice is None:
        voice = info[k][2][0] if info[k][2] else (p.findtext('measure/note/voice') or '1')
    voice = str(voice)
    numbers = [ly.get('number') or '1' for n in p.iter('note') if (n.findtext('voice') or '1') == voice
               for ly in n.findall('lyric')]
    if str(verse) not in numbers and verse == 1 and numbers:
        verse = numbers[0]                          # lyric lines numbered otherwise ("verse1", "2"...): the first

    divisions, cur, measure_q = 1.0, 0.0, 0.0       # cursor in divisions inside the measure; measure start in quarters
    tempo = [(0.0, 120.0)]                          # (quarter position, quarters per minute)
    events = []                                     # (start q, length q, midi or None, lyric, tie start, tie stop)
    for m in p.findall('measure'):
        cur, longest = 0.0, 0.0
        for e in m:
            if e.tag == 'attributes' and e.findtext('divisions'):
                divisions = float(e.findtext('divisions'))
            elif e.tag in ('direction', 'sound'):
                snd = e if e.tag == 'sound' else e.find('sound')
                if snd is not None and snd.get('tempo'):
                    tempo.append((measure_q + cur / divisions, float(snd.get('tempo'))))
            elif e.tag == 'backup':
                cur -= float(e.findtext('duration') or 0)
            elif e.tag == 'forward':
                cur += float(e.findtext('duration') or 0)
            elif e.tag == 'note':
                if e.find('grace') is not None or e.find('cue') is not None:
                    continue
                dur = float(e.findtext('duration') or 0)
                if e.find('chord') is not None:     # a further note of a chord: same time, not sung
                    continue
                if (e.findtext('voice') or '1') == voice:
                    midi = None
                    if e.find('rest') is None and e.find('pitch') is not None:
                        pt = e.find('pitch')
                        midi = (12 * (int(pt.findtext('octave')) + 1) + STEPS[pt.findtext('step').strip()]
                                + int(round(float(pt.findtext('alter') or 0))) + transpose)
                    lyr = None
                    for ly in e.findall('lyric'):
                        if (ly.get('number') or '1') == str(verse) and ly.findtext('text') is not None:
                            lyr = (''.join((t.text or '') for t in ly.findall('text')).strip(),
                                   (ly.findtext('syllabic') or 'single').strip())
                    ties = {t.get('type') for t in e.findall('tie')}
                    events.append((measure_q + cur / divisions, dur / divisions, midi, lyr,
                                   'start' in ties, 'stop' in ties))
                cur += dur
            longest = max(longest, cur)
        measure_q += longest / divisions

    tempo.sort(key=lambda x: x[0])                # stable: at the same place, the mark written later wins
    def seconds(q):                                 # quarter position -> seconds, through the tempo changes
        t, last_q, bpm = 0.0, 0.0, tempo[0][1]
        for tq, tb in tempo[1:]:
            if tq >= q:
                break
            t += (tq - last_q) * 60.0 / bpm; last_q, bpm = tq, tb
        return t + (q - last_q) * 60.0 / bpm

    notes, lyric_of, tie_open = [], [], False
    for q, ln, midi, lyr, t_start, t_stop in events:
        if midi is not None and t_stop and tie_open and notes and notes[-1].midi == midi:
            end = seconds(q + ln)
            notes[-1].length = end - notes[-1].start
            tie_open = t_start
            continue
        start = seconds(q)
        notes.append(Note(midi, start, seconds(q + ln) - start))
        if midi is not None:
            lyric_of.append(lyr)
        tie_open = t_start and midi is not None
    if not any(lyric_of):
        raise ValueError(f'part {info[k][0]} voice {voice} has no lyrics (verse {verse})')
    out, words, written, open_word = [], [], [], False
    for lyr in lyric_of:
        if lyr is None or not lyr[0]:
            out.append(None); continue
        text, syllabic = lyr
        if syllabic in ('single', 'begin') or not open_word:
            words.append(''); written.append([])
        words[-1] += text
        written[-1].append(text)
        out.append((text, len(words) - 1))
        open_word = syllabic in ('begin', 'middle')
    title = (root.findtext('work/work-title') or root.findtext('movement-title') or '').strip()
    return Song(notes, out, words, title, written)


# ---------------------------------------------------------------------------------------------- syllables
@dataclass
class Syllable:
    onset: str
    nucleus: str
    coda: str
    word: int
    notes: list = field(default_factory=list)   # indices into the sung notes


ONSETS2 = {'st', 'sp', 'sk', 'sm', 'sn', 'sl', 'sw'} | {a + b for a in 'pbtdkɡfθʃ' for b in 'ɹlwj'}


def split_word(ph, n, L):
    """a word's phonemes -> n (onset, nucleus, coda) syllables, split at the vowels.
    Too many vowels: of the closest pair (reduced vowels first), the weaker one is sung as part of the other's
    syllable. Too few: the caller holds the last one."""
    stress = set('ˈˌ')
    nuclei = []                                 # [start, end) of each vowel (with a length mark after it)
    i = 0
    while i < len(ph):
        if ph[i] in L.VOWELS:
            j = i + 1
            while j < len(ph) and ph[j] == 'ː':
                j += 1
            nuclei.append([i, j]); i = j
        else:
            i += 1
    if not nuclei:
        return [('', ph, '')]
    reduced = set('əᵊɪᵻ')
    while len(nuclei) > max(n, 1):
        def cost(k):
            gap = nuclei[k + 1][0] - nuclei[k][1]
            red = ph[nuclei[k][0]] in reduced or ph[nuclei[k + 1][0]] in reduced
            return gap * 2 + (0 if red else 1)
        k = min(range(len(nuclei) - 1), key=cost)
        # the weaker vowel of the pair stops being a syllable of its own: it is sung at its natural length,
        # next to the vowel that holds the note ("fire" = fI + əɹ)
        drop = k if ph[nuclei[k][0]] in reduced and ph[nuclei[k + 1][0]] not in reduced else k + 1
        del nuclei[drop]
    out, prev_end = [], 0
    for k, (a, b) in enumerate(nuclei):
        # the consonants between this vowel and the last: the next syllable takes one (two if a usual onset)
        if k == 0:
            onset = ph[:a]
        else:
            cl = ph[prev_end:a]
            core = cl.replace('ˈ', '').replace('ˌ', '')
            take = 2 if core[-2:] in ONSETS2 and len(core) >= 2 else (1 if core else 0)
            cut = len(cl)
            while take and cut > 0:
                cut -= 1
                if cl[cut] not in stress:
                    take -= 1
            while cut > 0 and cl[cut - 1] in stress:    # a stress mark stays with its syllable
                cut -= 1
            out[-1][2] = cl[:cut]
            onset = cl[cut:]
        out.append([onset, ph[a:b], ''])
        prev_end = b
    out[-1][2] = ph[prev_end:]
    return [tuple(x) for x in out]


PHONEMIC_RE = re.compile(r'^([^/]*)/([^/]+)/([,.;:!?]*)$')    # spelling, phonemes, punctuation


def is_phonemes(part):
    return bool(PHONEMIC_RE.match(part))


def spelling(part):
    """what a lyric syllable spells: its text, or a phonemic syllable's spelling ('' if none was given)"""
    m = PHONEMIC_RE.match(part)
    return (m.group(1) + m.group(3)) if m else part


def syllables(song, phonemes_of_words, L):
    """Song + each word's phonemes -> [Syllable] in order, with the sung notes each one spans.
    A word's phonemes are a string (split here at its vowels) or a list, one string per syllable as written."""
    by_word = {}
    for k, s in enumerate(song.lyrics):
        if s:
            by_word.setdefault(s[1], []).append(k)
    out, first_note = [], {}
    for w, ph in enumerate(phonemes_of_words):
        ks = by_word.get(w, [])
        if not ks:
            continue
        parts = split_word(ph, len(ks), L) if isinstance(ph, str) else [split_word(x, 1, L)[0] for x in ph]
        for i, (on, nu, co) in enumerate(parts):
            k = ks[i] if i < len(ks) else ks[-1]
            out.append(Syllable(on, nu, co, w, [k]))
            first_note[k] = out[-1]
        for k in ks[len(parts):]:               # more sung syllables than vowels: the last vowel holds
            out[-1].notes.append(k)
    by_note = {}
    for syl in out:
        for k in syl.notes:
            by_note[k] = syl
    last = None
    for k, s in enumerate(song.lyrics):         # held notes (_ and *) join the syllable sung before them
        if k in by_note:
            last = by_note[k]
        elif last is not None:
            last.notes.append(k)
    return out


# ---------------------------------------------------------------------------------------------- singing
def word_phonemes(eng, song, L):
    """each lyric word's phonemes: the words without written phonemes are phonemized together, as one sentence
    (so they sound as spoken); a word with phonemic syllables -> a list, one string per syllable"""
    from . import marks as marks_mod

    def say(text):
        return ''.join(t.phonemes for t in eng.tokenize(marks_mod.parse(text, L), L) if t.is_word)
    parts = song.parts or [[w] for w in song.words]
    out = [None] * len(parts)
    plain = [i for i, ps in enumerate(parts) if not any(is_phonemes(p) for p in ps)]
    for i, ps in enumerate(parts):
        if i in plain:
            continue
        given = [PHONEMIC_RE.match(p).group(2) if is_phonemes(p) else None for p in ps]
        whole = None
        if all(spelling(p).strip(',.;:!?') for p in ps):     # spelt throughout: say the word, swap in the given
            split = split_word(say(''.join(spelling(p) for p in ps)), len(ps), L)
            if len(split) == len(ps):
                whole = [''.join(x) for x in split]
        out[i] = [g if g is not None else whole[k] if whole else say(p) for k, (g, p) in enumerate(zip(given, ps))]
    toks = [t for t in eng.tokenize(marks_mod.parse(' '.join(song.words[i] for i in plain), L), L) if t.is_word]
    if len(toks) == len(plain):
        for i, t in zip(plain, toks):
            out[i] = t.phonemes
    else:                                       # the phonemizer split or joined words: one at a time
        for i in plain:
            out[i] = say(song.words[i])
    bad = sorted({c for ph in out for c in (ph if isinstance(ph, str) else ''.join(ph)) if c not in eng.vocab})
    if bad:
        raise ValueError(f'phonemes the model doesn\'t know: {" ".join(bad)} (write them in misaki\'s notation, '
                         f'e.g. A for eɪ, I for aɪ, O for oʊ, ɹ for r, ɡ for g)')
    return out


def sing(eng, song, voice, lang=None, seed=0, band=None):
    """Engine + Song -> (audio, info). Phrases between rests are rendered separately and laid on the timeline.
    band: (lowest, highest) MIDI note the voice sings itself (see probe_range); notes outside it are sung at its
    edge and shifted with PSOLA. None = the model sings every note itself."""
    import torch
    L = languages.get(lang)
    sung = [n for n in song.notes if n.midi is not None]
    words = word_phonemes(eng, song, L)
    syls = syllables(song, words, L)
    pack = eng.voice(voice)
    end = max((n.start + n.length for n in song.notes), default=0.0)
    out = np.zeros(int((LEAD_IN + end + TAIL + 2.0) * dsp.SR), np.float32)
    phrases, cur = [], []
    for syl in syls:                            # a rest between two syllables' notes starts a new phrase
        if cur:
            prev_end = sung[cur[-1].notes[-1]].start + sung[cur[-1].notes[-1]].length
            if sung[syl.notes[0]].start - prev_end > 1e-6:
                phrases.append(cur); cur = []
        cur.append(syl)
    if cur:
        phrases.append(cur)
    torch.manual_seed(seed)
    info = []
    for ph in phrases:
        audio, lead, ps, f_sung, shift = _sing_phrase(eng, ph, sung, pack, L, band)
        if np.any(np.abs(shift[f_sung > 0]) > 1e-4):
            audio = psola(audio, f_sung, np.exp(shift))
        t0 = LEAD_IN + sung[ph[0].notes[0]].start
        at = int(round((t0 - lead) * dsp.SR))
        if at < 0:
            audio, at = audio[-at:], 0
        out[at:at + len(audio)] += audio[:len(out) - at]
        info.append(ps)
    last = np.nonzero(np.abs(out) > 1e-4)[0]
    out = out[:last[-1] + int(0.05 * dsp.SR)] if len(last) else out
    return dsp.level(out, 0.0), info


def _sing_phrase(eng, syls, sung, pack, L, band=None):
    """one phrase -> (audio, seconds before the first note's start, phoneme string, the pitch it was sung at
    (Hz per F0 sample, 0 = unvoiced), the shift still to apply (natural log of the ratio, per F0 sample))"""
    import torch
    from .engine import VOICED_HZ, Engine
    m = eng.m
    # ---- the phoneme string, and what each id is
    ps, role = '', []                           # role per character: (syllable index, part)
    for i, s in enumerate(syls):
        if i and s.word != syls[i - 1].word:
            ps += ' '; role.append((i - 1, 'space'))
        for part in ('onset', 'nucleus', 'coda'):
            for c in getattr(s, part):
                if c in eng.vocab:
                    ps += c; role.append((i, part))
    ps = ps[:510]; role = role[:510]
    ids = torch.LongTensor([[0] + [eng.vocab[c] for c in ps] + [0]])
    ref_s = pack[len(ps) - 1]
    s = ref_s[:, 128:]
    Lt = torch.full((1,), ids.shape[-1], dtype=torch.long)
    mask = torch.gt(torch.arange(Lt.max()).unsqueeze(0) + 1, Lt.unsqueeze(1))
    with torch.no_grad():
        d_en = m.bert_encoder(m.bert(ids, attention_mask=(~mask).int())).transpose(-1, -2)
        d = m.predictor.text_encoder(d_en, s, Lt, mask)
        x, _ = m.predictor.lstm(d)
        natural = torch.sigmoid(m.predictor.duration_proj(x)).sum(axis=-1).squeeze(0)

        # ---- durations: each vowel starts on its note; consonants keep their length, before/after it
        nat = natural.numpy().astype(float)
        dur = nat.copy()
        cmax = CONSONANT_MAX * FPS
        t_first = sung[syls[0].notes[0]].start
        note_at = [(sung[s.notes[0]].start - t_first) * FPS for s in syls]        # vowel starts, phrase frames
        last = sung[syls[-1].notes[-1]]
        phrase_end = (last.start + last.length - t_first) * FPS
        ids_of = {}
        for k, (i, part) in enumerate(role):
            ids_of.setdefault((i, part), []).append(k + 1)                          # +1: the leading pad
        for k in range(1, len(ps) + 1):
            dur[k] = min(nat[k], cmax) if role[k - 1][1] != 'nucleus' else nat[k]
        for k in range(1, len(ps) + 1):
            if role[k - 1][1] == 'space':
                dur[k] = 1.0
        for i in range(len(syls)):
            start = note_at[i]
            stop = note_at[i + 1] if i + 1 < len(syls) else phrase_end
            between = ids_of.get((i, 'coda'), []) + ids_of.get((i, 'space'), []) + \
                (ids_of.get((i + 1, 'onset'), []) if i + 1 < len(syls) else [])
            span = max(stop - start, 2.0)
            cons = sum(dur[k] for k in between)
            if cons > span * CONSONANT_SHARE:
                for k in between:
                    dur[k] *= span * CONSONANT_SHARE / cons
                cons = span * CONSONANT_SHARE
            vow = ids_of.get((i, 'nucleus'), [])
            tot = sum(nat[k] for k in vow) or 1.0
            for k in vow:
                dur[k] = (span - cons) * nat[k] / tot
        dur[-1] = max(dur[-1], 2.0)
        lead_frames = float(dur[0] + sum(dur[k] for k in ids_of.get((0, 'onset'), [])))
        dur_t = torch.tensor(dur, dtype=torch.float32)
        pd = Engine.frames(dur_t)
        pd_n = Engine.frames(natural)
        idx, aln = Engine.alignment(pd)
        F0, N = m.predictor.F0Ntrain(d.transpose(-1, -2) @ Engine.alignment(pd_n)[1], s)
        F0, N = Engine.retime(F0, pd_n, pd), Engine.retime(N, pd_n, pd)

        # ---- pitch: the notes, on voiced sounds
        n_s = F0.shape[-1]
        tsec = (np.arange(n_s) / 2.0 - lead_frames) / FPS + t_first                  # song time of each sample
        hz = np.full(n_s, sung[syls[0].notes[0]].hz)
        vib = np.zeros(n_s)
        for s_ in syls:
            for k in s_.notes:
                nt = sung[k]
                on = tsec >= nt.start - PITCH_LEAD
                hz[on] = nt.hz
                if nt.length > VIBRATO['after']:
                    inside = (tsec >= nt.start) & (tsec < nt.start + nt.length)
                    age = tsec[inside] - nt.start - VIBRATO['after']
                    amt = np.clip(age / VIBRATO['fade'], 0, 1)
                    vib[inside] = amt * VIBRATO['depth'] * np.sin(2 * np.pi * VIBRATO['rate'] * age)
        import scipy.ndimage as nd
        logf = nd.gaussian_filter1d(np.log(hz), GLIDE * FPS * 2) + vib * np.log(2) / 12
        sung_at = logf
        if band:                                # outside the voice's band: sing at its edge, shift afterwards
            lo, hi = (np.log(440.0 * 2 ** ((b - 69) / 12)) for b in band)
            sung_at = nd.gaussian_filter1d(np.clip(logf, lo, hi), 1.0)
        ids_at = idx.repeat_interleave(2).numpy()
        son = np.array([0 < i <= len(ps) and (ps[i - 1] in L.SONORANT) for i in ids_at])
        voiced = (F0[0].numpy() > VOICED_HZ) | son
        quiet = (ids_at == 0) | (ids_at == len(ps) + 1)
        voiced &= ~quiet
        f = torch.tensor(np.where(voiced, np.exp(sung_at), 0.0), dtype=torch.float32).view(1, -1)

        # ---- energy: held vowels don't fade
        Nv = N[0].numpy()
        # relative to the phrase's loud level, not its median: on long notes most frames *are* the fading vowel
        ref = float(np.percentile(Nv[voiced], 90)) - SUSTAIN_ENERGY if voiced.any() else None
        vowel = np.array([0 < i <= len(ps) and role[i - 1][1] == 'nucleus' for i in ids_at])
        if ref is not None:
            Nv = np.where(vowel, np.maximum(Nv, ref), Nv)
        N = torch.tensor(Nv, dtype=N.dtype).view(1, -1)

        t_en = m.text_encoder(ids, Lt, mask)
        asr = t_en @ aln
        if OPEN_VOWELS:
            asr = _open_vowels(eng, ps, role, syls, pd, asr, Lt, L)
        audio = m.decoder(asr, f, N, ref_s[:, :128]).squeeze().numpy()
    starts = np.concatenate([[0], np.cumsum(pd.numpy())])
    spf = len(audio) / int(starts[-1])                  # audio samples per frame (600)
    vowels = [(int(starts[k + 1] * spf), int(starts[k + 2] * spf)) for k, (i, part) in enumerate(role)
              if part == 'nucleus']
    audio = _hold_level(audio, vowels)
    return audio, lead_frames / FPS, ps, f[0].numpy(), np.where(voiced, logf - sung_at, 0.0)


def _hold_level(audio, vowels, sr=dsp.SR):
    """a long vowel still sags in the middle (and swells into the consonant after it): hold each vowel at the
    loudness of its start, with a smooth gain (never quieter, at most HOLD_LEVEL['max_gain'])"""
    import scipy.ndimage as nd
    env = np.sqrt(nd.gaussian_filter1d(audio.astype(float) ** 2, sr * 0.015)) + 1e-7
    gain = np.ones(len(audio))
    att = int(HOLD_LEVEL['attack'] * sr)
    for a, b in vowels:
        if b - a < 3 * att:
            continue
        want = float(np.median(env[a:a + att]))
        g = np.clip(want / env[a + att:b], 1.0, HOLD_LEVEL['max_gain'])
        gain[a + att:b] = np.maximum(gain[a + att:b], g)
    gain = nd.gaussian_filter1d(gain, sr * 0.02)
    return (audio * gain).astype(np.float32)


def _open_vowels(eng, ps, role, syls, pd, asr, Lt, L):
    """A vowel held on a note is heard through the text encoder's view of it in its spoken context: before a
    stop ("what", "lit-") that view already closes off (a glottal catch), and held long it turns to noise. For
    held vowels, the decoder gets the vowel as the encoder sees it in an open, long syllable (V + length mark, the
    voiceless consonants after it left out), blending back to the real context over the last OPEN_RETURN frames."""
    import torch
    m = eng.m
    pdn = pd.numpy()
    starts = np.concatenate([[0], np.cumsum(pdn)])
    held = [k for k, (i, part) in enumerate(role) if part == 'nucleus' and pdn[k + 1] >= OPEN_HOLD * FPS]
    if not held:
        return asr
    ps2, where, skip = '', {}, set()
    for k, (i, part) in enumerate(role):
        if k in skip:
            continue
        ps2 += ps[k]
        if k in held:
            where[k] = len(ps2)                 # +1 for the pad, -1 for the index: the same number
            if OPEN_LONG and 'ː' in eng.vocab:
                ps2 += 'ː'
            j = k + 1                           # leave out the voiceless consonants closing its syllable
            while j < len(role) and role[j][0] == i and role[j][1] == 'coda':
                if ps[j] not in L.SONORANT:
                    skip.add(j)
                j += 1
    ids2 = torch.LongTensor([[0] + [eng.vocab[c] for c in ps2] + [0]])
    L2 = torch.full((1,), ids2.shape[-1], dtype=torch.long)
    mask2 = torch.gt(torch.arange(L2.max()).unsqueeze(0) + 1, L2.unsqueeze(1))
    t2 = m.text_encoder(ids2, L2, mask2)
    out = asr.clone()
    for k in held:
        a, b = int(starts[k + 1]), int(starts[k + 2])          # the vowel's frames (k + 1: the pad)
        open_v, real_v = t2[0, :, where[k]], asr[0, :, b - 1]
        n_back = min(OPEN_RETURN, b - a)
        w = torch.ones(b - a)
        if n_back:
            w[-n_back:] = torch.linspace(1, 0, n_back + 1)[1:]
        out[0, :, a:b] = open_v[:, None] * w[None, :] + real_v[:, None] * (1 - w[None, :])
    return out


# ---------------------------------------------------------------------------------------------- pitch shifting
def psola(x, f0, ratio, sr=dsp.SR):
    """TD-PSOLA: move the pitch of x by `ratio`, keeping its timing and (roughly) its vowel sound.
    f0: the pitch x was made at, Hz per F0 sample (0 = unvoiced); ratio: per F0 sample. Grains two periods long
    (of the new period when shifting up), centred on pitch marks one period apart (aligned to the waveform's
    peaks), are laid out one *new* period apart; unvoiced stretches are copied through unchanged."""
    n = len(x)
    per = n / len(f0)                                   # audio samples per F0 sample (300)
    pos = (np.arange(len(f0)) + 0.5) * per
    on = f0 > 0
    if not on.any():
        return x
    filled = np.interp(np.arange(len(f0)), np.nonzero(on)[0], f0[on])        # no sag towards 0 at the edges
    fa = np.interp(np.arange(n), pos, filled)
    fa[np.interp(np.arange(n), pos, on.astype(float)) < 0.5] = 0.0
    ra = np.interp(np.arange(n), pos, ratio)
    step_u = UNVOICED_STEP * sr
    # analysis marks
    marks, periods, t, prev_voiced = [], [], 0.0, False
    while t < n:
        i = int(t)
        if fa[i] > 0:
            P = sr / fa[i]
            w = max(1, int(P / (2 if not prev_voiced else 8)))
            lo, hi = max(0, i - w), min(n, i + w + 1)
            i = lo + int(np.argmax(x[lo:hi])) if hi > lo else i
            marks.append(i); periods.append(P); prev_voiced = True
            t = i + P
        else:
            marks.append(i); periods.append(step_u); prev_voiced = False
            t = i + step_u
    marks, periods = np.array(marks), np.array(periods)
    out = np.zeros(n + 2 * int(sr * 0.05), np.float64)
    wsum = np.zeros_like(out)
    off = int(sr * 0.05)
    s = float(marks[0])
    while s < n:
        k = int(np.clip(np.searchsorted(marks, s), 1, len(marks) - 1))
        k = k if abs(marks[k] - s) < abs(marks[k - 1] - s) else k - 1
        a, P = int(marks[k]), periods[k]
        voiced = fa[a] > 0
        rr = ra[a] if voiced else 1.0
        # grains two periods long: of the old period, or of the new one when shifting up (else the old period
        # stays audible under the new one; at x3 it was what a pitch tracker heard)
        h = max(2, int(round(P / max(rr, 1.0))))
        lo, hi = a - h, a + h + 1
        win = np.hanning(2 * h + 1)
        seg = np.zeros(2 * h + 1)
        a0, a1 = max(0, lo), min(n, hi)
        seg[a0 - lo:a1 - lo] = x[a0:a1]
        c = int(round(s))
        out[off + c - h:off + c + h + 1] += seg * win
        wsum[off + c - h:off + c + h + 1] += win
        s += P / rr
    y = out[off:off + n] / np.maximum(wsum[off:off + n], 1e-3)
    y[wsum[off:off + n] < 1e-3] = 0.0
    # overlapping grains partly cancel (an octave up loses ~3 dB): match the loudness envelope of the original
    import scipy.ndimage as nd
    k = sr * 0.02
    ex = np.sqrt(nd.gaussian_filter1d(x.astype(float) ** 2, k)) + 1e-6
    ey = np.sqrt(nd.gaussian_filter1d(y ** 2, k)) + 1e-6
    y *= np.clip(ex / ey, 0.5, 2.0)
    return y.astype(np.float32)


# ---------------------------------------------------------------------------------------------- measuring
def measure(audio, song, sr=dsp.SR):
    """pitch-track a sung line: per sung note {'cents': off its note over the middle of it (10%-95%; None if
    unvoiced), 'voiced': share of it voiced, 'onset_ms': when its pitch arrived, relative to its beat (None where
    it can't be told: the same pitch as the note before, with no gap)}. Arrival = the first moment, sustained for
    30 ms, that the pitch is nearer this note than the one before (or, after silence, that it is voiced: then
    'after_rest' is True, and a voiced consonant sung before the beat counts as the arrival).
    Measured 2026-11-14 with PITCH_LEAD: pitch changes land within ~20 ms of the beat (median)."""
    import librosa
    sung = [n for n in song.notes if n.midi is not None]
    if not sung:
        return []
    lo = min(n.hz for n in sung) / 1.5
    hi = max(n.hz for n in sung) * 1.5
    f0, vf, _ = librosa.pyin(np.asarray(audio, float), fmin=max(40, lo), fmax=min(2000, hi), sr=sr,
                             frame_length=2048, hop_length=240)
    t = (np.arange(len(f0)) * 240) / sr
    out, prev, prev_end = [], None, None
    logf = np.log(np.where(vf, f0, 1.0))
    for nt in sung:
        sel = (t >= LEAD_IN + nt.start + 0.1 * nt.length) & (t < LEAD_IN + nt.start + 0.95 * nt.length)
        v = f0[sel][vf[sel]] if sel.any() else np.array([])
        share = float(vf[sel].mean()) if sel.any() else 0.0
        beat = LEAD_IN + nt.start
        win = np.nonzero((t >= beat - 0.15) & (t < beat + min(0.25, 0.6 * nt.length)))[0]
        after_gap = prev is None or nt.start - prev_end > 0.04
        if after_gap:
            hit = vf[win]
        elif prev.midi != nt.midi:
            mid = (np.log(prev.hz) + np.log(nt.hz)) / 2
            hit = vf[win] & ((logf[win] > mid) if nt.hz > prev.hz else (logf[win] < mid))
        else:
            hit = None
        onset = None
        if hit is not None:
            for j in range(len(win) - 2):
                if hit[j] and hit[j + 1] and hit[j + 2]:
                    onset = float((t[win[j]] - beat) * 1000) + (ONSET_BIAS_MS if after_gap else 0.0); break
        out.append({'cents': float(1200 * np.log2(np.median(v) / nt.hz)) if len(v) else None, 'voiced': share,
                    'onset_ms': onset, 'after_rest': after_gap})
        prev, prev_end = nt, nt.start + nt.length
    return out


def _cache_file():
    base = os.environ.get('LOCALAPPDATA') or os.environ.get('XDG_CACHE_HOME') or str(Path.home() / '.cache')
    return Path(base) / 'jivetalker' / 'voice_ranges.json'


def probe_range(eng, voice, log=print, cache=True):
    """the band of notes (lowest, highest MIDI) this voice sings on pitch by itself: sustained test notes from
    PROBE['low'] to PROBE['high'], each sung on every PROBE['words'] and pitch-tracked; the longest unbroken run
    of good notes wins. About a minute on CPU; cached per voice file (and PROBE_VERSION)."""
    key = None
    if cache and isinstance(voice, str):
        from .render import file_hash
        key = f'{file_hash(voice)}|{PROBE_VERSION}|{json.dumps(PROBE, sort_keys=True)}'
        try:
            got = json.loads(_cache_file().read_text(encoding='utf-8')).get(key)
            if got:
                return tuple(got)
        except (OSError, ValueError):
            pass
    if log:
        log(f'measuring the pitch band of {voice} (once; about a minute)...')
    good = []
    for midi in range(PROBE['low'], PROBE['high'] + 1):
        ok = True
        for w in PROBE['words']:
            song = Song([Note(midi, 0.0, PROBE['length'])], [(w, 0)], [w])
            y, _ = sing(eng, song, voice)
            m, = measure(y, song)
            ok &= m['cents'] is not None and abs(m['cents']) <= PROBE['cents'] and m['voiced'] >= PROBE['voiced']
            if not ok:
                break
        good.append(ok)
    best, run = (None, None), None
    for i, ok in enumerate(good + [False]):
        if ok and run is None:
            run = i
        elif not ok and run is not None:
            if best[0] is None or i - run > best[1] - best[0] + 1:
                best = (run, i - 1)
            run = None
    if best[0] is None:
        raise RuntimeError(f'{voice}: no note was sung on pitch; is it a voice pack?')
    band = (PROBE['low'] + best[0], PROBE['low'] + best[1])
    if key:
        f = _cache_file()
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            data = json.loads(f.read_text(encoding='utf-8')) if f.exists() else {}
            data[key] = list(band)
            f.write_text(json.dumps(data, indent=1), encoding='utf-8')
        except (OSError, ValueError):
            pass
    return band


def safe_band(band):
    """the measured band with BAND_MARGIN taken off each end (what sing() should be given)"""
    lo, hi = band[0] + BAND_MARGIN[0], band[1] - BAND_MARGIN[1]
    return (lo, hi) if hi > lo else (band[0], band[1])


NAMES = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B']


def note_name(midi):
    return f'{NAMES[midi % 12]}{midi // 12 - 1}'


def guide(song, sr=dsp.SR):
    """a plain tone track of the melody (to hear whether the voice is on pitch and on time)"""
    end = max((n.start + n.length for n in song.notes), default=0.0)
    out = np.zeros(int((LEAD_IN + end + TAIL) * sr), np.float32)
    for n in song.notes:
        if n.midi is None:
            continue
        t = np.arange(int(n.length * sr)) / sr
        env = np.minimum(1, t / 0.01) * np.minimum(1, (n.length - t) / 0.03)
        tone = sum(np.sin(2 * np.pi * n.hz * h * t) / h ** 1.5 for h in (1, 2, 3, 4))
        a = int((LEAD_IN + n.start) * sr)
        out[a:a + len(t)] += (0.2 * env * tone).astype(np.float32)[:len(out) - a]
    return out
