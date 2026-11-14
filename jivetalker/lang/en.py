"""English (misaki's American G2P, Kokoro lang_code 'a'). Every voice speaks through it, British ones included.

The tuning here was set in the 2026-11 listening rounds (dates and round labels in the comments)."""
import re

from . import Language, Token, register


class English(Language):
    code = 'en'
    kokoro = 'a'
    name = 'English'

    PUNCT = frozenset(',.;:!?—…')
    SENTENCE_END = frozenset('.!?…')
    # vowels (misaki's capitals are diphthongs), voiced sonorants, the flap, and stress/length marks
    VOWELS = frozenset('aeiouæɑɐɒɔəɚɛɜɪʊʌᵊᵻAIOWY')
    SONORANT = VOWELS | frozenset('lɹwjmnŋɫTˈˌː')
    WEAK_NUCLEI = frozenset('əᵊɪᵻ')     # reduced vowels ("fire" = fI + əɹ on one note)

    # ---- stress marks -> per-word edits
    # Stress is relative: the word's peak is lifted to `over` semitones above the peaks of the words around it
    # (at least `pitch`, at most STRESS_MAX), then eases down `fall` semitones across the word; `gain` dB louder;
    # `dur` = length factor. (2026-11-12 round 1: a flat +1.5 st was inaudible on "have you ever WANTED", where
    # the model already peaks on "ever"; ++ on "finally" was too high and didn't ease down enough; round 2: ++
    # start lower and end below the unstressed "finally" before it.)
    STRESS = {1: dict(over=1.5, pitch=1.5, fall=2.0, gain=2.0, dur=1.15),
              2: dict(over=2.0, pitch=2.0, fall=4.0, gain=3.0, dur=1.25),
              -1: dict(pitch=-1.0, dur=0.9, gain=-1.5)}
    STRESS_MAX = 6.0
    # Levels 3-5 (+++ to +++++) and de-stress -- / ---, for when ++ / - isn't enough. Untuned by ear: they may
    # sound bad. Each raises its own limit (`max` instead of STRESS_MAX), or the limit would flatten it into
    # level 2. A line's clip depends only on the levels it uses (render.tuning).
    STRESS_MORE = {3: dict(over=3.0, pitch=3.0, fall=5.0, gain=4.0, dur=1.35, max=7.5),
                   4: dict(over=4.0, pitch=4.0, fall=6.0, gain=5.0, dur=1.45, max=9.0),
                   5: dict(over=5.0, pitch=5.0, fall=7.0, gain=6.0, dur=1.55, max=10.5),
                   # -- and ---: stops at 3, as past ~20% shorter Kokoro swallows sounds and quieter words get lost
                   -2: dict(pitch=-2.0, dur=0.85, gain=-3.0),
                   -3: dict(pitch=-3.0, dur=0.8, gain=-4.5)}

    # ---- question rise: Kokoro says "Mara?" like a statement (a peak on the stressed syllable, then a fall), so
    # the word before a "?" gets its own contour flattened and a rise laid on top: gradual at first, then sharp.
    # auto: semitones used on one-word questions when the line doesn't set `rise`; flatten: 0..1, how much of the
    # model's own movement on that word is removed; gradual: the share of the rise that is linear (the rest
    # comes as t**power, i.e. at the end).
    # auto_multi: semitones on longer questions without a wh-word at the start of a clause (round 1: "Maybe...
    # back when I was a kid?" was said as a statement).
    QUESTION = dict(auto=5.0, auto_multi=3.0, flatten=0.9, gradual=0.3, power=4.0)
    WH_WORDS = frozenset({'who', 'whom', 'whose', 'what', 'when', 'where', 'why', 'how', 'which'})
    WORD_RE = re.compile(r"[^\W\d_][\w'’-]*")

    def spoken(self, text):
        # misaki drops a spaced hyphen ("eyes - easy") without a pause; an en/em dash it reads as one
        return re.sub(r'(?<=\s)-+(?=\s)', '—', text)

    def has_pause_after(self, rest):
        return bool(re.match(r'\s*[,.;:!?…—–]', rest))

    def tokenize(self, pipe, marked, vocab):
        _, mtoks = pipe.g2p(marked.g2p)
        out, pos = [], 0
        for t in mtoks:
            raw = t.phonemes or ''
            ps = ''.join(c for c in raw if c in vocab)
            tok = Token(t.text, ps, bool(t.whitespace), unknown='❓' in raw)
            if t.text:
                i = marked.align.find(t.text, pos)
                if i >= 0 and not marked.align[pos:i].strip(' \t\n-–—'):    # a dash the phonemizer re-spelt
                    tok.span = (i, i + len(t.text)); pos = i + len(t.text)
            out.append(tok)
        return out

    def question_rises(self, settings, plain):
        """The line's `rise` applies to all. Otherwise: a one-word question gets QUESTION['auto']; a longer one
        QUESTION['auto_multi'], unless one of its clauses starts with a wh-word ("So Mara, when was...?"), since
        those fall. (`rise` is not in styles.DEFAULTS, so lines without it keep their cache keys.)"""
        out, start = [], 0
        for m in re.finditer(r'\?+', plain):
            if 'rise' in settings:
                out.append(settings['rise'])
            else:
                sentence = re.split(r'[.!?…]+(?=\s|$)', plain[start:m.start()])[-1]
                words = self.WORD_RE.findall(sentence)
                clauses = re.split(r'[,;:—–…]|\.\.\.|\s-+\s', sentence)
                firsts = {w[0].lower() for w in (self.WORD_RE.findall(c) for c in clauses) if w}
                out.append(0.0 if not words else self.QUESTION['auto'] if len(words) == 1 else
                           0.0 if firsts & self.WH_WORDS else self.QUESTION['auto_multi'])
            start = m.end()
        return out


ENGLISH = register(English, 'a', 'en-us')
