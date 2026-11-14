"""Japanese (misaki's cutlet G2P, Kokoro lang_code 'j'; stock voices jf_* and jm_*).

Needs misaki's Japanese extras and the UniDic dictionary (about 800 MB):
    pip install "misaki[ja]==0.9.4"
    python -m unidic download

Tuning: NOT set by ear yet. The stress and question values below are first guesses; listen before relying on them.

Japanese has pitch accent and phonemic vowel length, so stress here is a pitch lift and a little loudness that
keeps the word's own accent shape (no `fall` across the word) and does not lengthen the word (a longer vowel can
be a different word). Drawing a word out (~) is still allowed: there it is asked for.
"""
import re
import unicodedata
import warnings

from . import Language, Token, register

MARK_RE = re.compile(r'\[([^\]]+)\]\(([^)]*)\)')       # as marks.MARK_RE (only /ipa/ links are left in g2p text)
# kokoro runs cutlet with these; a space next to a glottal stop (small tsu) is removed unless punctuation is there
GLOTTAL_BEFORE_OK = set('!",.:;?»—…”')
GLOTTAL_AFTER_OK = set('"«“')
INSTALL = ('Japanese needs misaki\'s Japanese extras and UniDic: pip install "misaki[ja]==0.9.4", then '
           'python -m unidic download')


class Japanese(Language):
    code = 'ja'
    kokoro = 'j'
    name = 'Japanese'

    PUNCT = frozenset(',.;:!?—…')                      # cutlet writes Japanese punctuation as ASCII
    SENTENCE_END = frozenset('.!?…')
    VOWELS = frozenset('aiɯɨeo')
    # nasals (n, ɲ, ŋ, ɴ, m), the flap ɾ, the glides j and β (the particle wa), palatalisation and length
    SONORANT = VOWELS | frozenset('mnɲŋɴɾjβwᵝʲː')
    QUESTION_MARKS = '?？'
    MORA_NASALS = frozenset('ɴŋmnɲ')     # ん before a consonant or at the end (げんき = ge + ŋ + kʲi)
    LONG_MORA = True
    WEAK_NUCLEI = frozenset('ɴŋmnɲː')    # with fewer notes, ん and ー join the beat before them
    PAUSE_MARK = '、'
    CHARS_PER_SECOND = 8.0

    STRESS = {1: dict(over=1.5, pitch=1.5, fall=0.0, gain=2.0, dur=1.0),
              2: dict(over=2.5, pitch=2.5, fall=0.0, gain=3.0, dur=1.0),
              -1: dict(pitch=-1.0, dur=1.0, gain=-1.5)}
    STRESS_MAX = 6.0
    STRESS_MORE = {3: dict(over=3.5, pitch=3.5, fall=0.0, gain=4.0, dur=1.0, max=7.5),
                   4: dict(over=4.5, pitch=4.5, fall=0.0, gain=5.0, dur=1.0, max=9.0),
                   5: dict(over=5.5, pitch=5.5, fall=0.0, gain=6.0, dur=1.0, max=10.5),
                   -2: dict(pitch=-2.0, dur=1.0, gain=-3.0),
                   -3: dict(pitch=-3.0, dur=1.0, gain=-4.5)}
    # Every question rises (か questions and wh-questions alike); the rise lands on the word before the ？,
    # usually the particle.
    QUESTION = dict(auto=4.0, flatten=0.6, gradual=0.2, power=3.0)

    def has_pause_after(self, rest):
        return bool(re.match(r'\s*[,.;:!?…—–、。，．！？：；～〜]', rest))

    def question_rises(self, settings, plain):
        out, start = [], 0
        for m in re.finditer(r'[?？]+', plain):
            if 'rise' in settings:
                out.append(settings['rise'])
            else:
                said = re.split(r'[.!?…。！？]+', plain[start:m.start()])[-1]
                out.append(self.QUESTION['auto'] if any(c.isalnum() for c in said) else 0.0)
            start = m.end()
        return out

    # ------------------------------------------------------------------ text -> tokens
    def tokenize(self, pipe, marked, vocab):
        """Kokoro's own Japanese G2P (cutlet) returns a phoneme string only. Its word list is rebuilt here, and
        checked against that string: if the two ever differ (another misaki), the line is spoken from the string
        alone and its marks are reported as not placed."""
        cut = getattr(pipe.g2p, 'cutlet', None)
        if cut is None:
            raise RuntimeError(INSTALL)
        out, pos, g = [], 0, marked.g2p
        for m in MARK_RE.finditer(g):                  # [word](/ipa/): the phonemes as written
            out += self._words(pipe, cut, g[pos:m.start()], vocab)
            ipa = m.group(2).strip().strip('/')
            out.append(Token(m.group(1), ''.join(c for c in ipa if c in vocab), True))
            pos = m.end()
        out += self._words(pipe, cut, g[pos:], vocab)
        self._align(out, cut, marked.align)
        return out

    def _words(self, pipe, cut, text, vocab):
        if not text.strip():
            return []
        ref, _ = pipe.g2p(text)
        words, punct = self._cutlet_words(cut, text)
        said = re.sub(r'\s+', ' ', ''.join(w.phonemes + (' ' if w.whitespace else '') for w in words)).strip()
        if said != ref:
            warnings.warn('jivetalker: could not follow cutlet\'s words for this text (another misaki version?); '
                          'its marks will not be placed')
            words = [Token('', p, True) for p in ref.split(' ') if p]
        else:
            self._restore_punct(words, punct)
        for w in words:
            w.phonemes = ''.join(c for c in w.phonemes if c in vocab)
        return words

    @staticmethod
    def _cutlet_words(cut, text):
        """cutlet's __call__ (misaki 0.9.4), keeping each word's surface: [Token] with unfiltered phonemes"""
        import jaconv
        from misaki import cutlet as C
        text = cut._normalize_text(text)
        words = [C.Word(w.surface, jaconv.kata2hira(w.feature.pron or w.feature.kana or w.surface),
                        6 if w.char_type == 7 or not w.is_unk else w.char_type) for w in cut.tagger(text)]
        groups, i = [], 0                               # as Cutlet._romaji_tokens: dictionary words grouped
        while i < len(words):
            z = next((z for z in range(i + 1, len(words)) if words[z].char_type != words[i].char_type), len(words))
            j = next((j for j in range(z, i, -1) if ''.join(w.surface for w in words[i:j]) in C.JA_WORDS), None)
            if j is None:
                groups.append(words[i:i + 1]); i += 1
            else:
                groups.append(words[i:j]); i = j
        words = [C.Word(''.join(w.surface for w in g), ''.join(w.hira for w in g), g[0].char_type) for g in groups]
        roma = cut._romaji_tokens(words)
        if len(roma) != len(words):
            return []
        toks, punct = [], {}
        for w, r in zip(words, roma):
            ph = r.surface.replace('(', '«').replace(')', '»')
            if not ph and C.HEPBURN.get(w.surface, '').strip():
                # 、。「」: the dictionary knows them but gives no reading, so cutlet says nothing for them.
                # Kept as empty words here (to check against cutlet's string) and filled in afterwards.
                t = Token(w.surface, '', r.space)
                punct[id(t)] = C.HEPBURN[w.surface]
                toks.append(t); continue
            if not ph.strip():                          # a space (・ and the like)
                if toks and ph:
                    toks[-1].whitespace = True
                continue
            if toks and not toks[-1].whitespace and ph.startswith(' '):
                toks[-1].whitespace = True
            unknown = not ph.strip() and any(unicodedata.category(c)[0] in 'LN' for c in w.surface)
            toks.append(Token(w.surface, ph.strip(), r.space or ph.endswith(' '), unknown=unknown))
        # a glottal stop (small tsu) joins the words around it
        spoken = [t for t in toks if t.phonemes]
        for a, b in zip(spoken, spoken[1:]):
            if a.whitespace and ((b.phonemes[:1] == 'ʔ' and a.phonemes[-1:] not in GLOTTAL_BEFORE_OK) or
                                 (a.phonemes[-1:] == 'ʔ' and b.phonemes[:1] not in GLOTTAL_AFTER_OK)):
                a.whitespace = False
        return toks, punct

    @staticmethod
    def _restore_punct(toks, punct):
        """fill in the punctuation cutlet dropped, spaced as cutlet spaces the punctuation it keeps"""
        for i, t in enumerate(toks):
            mark = punct.get(id(t))
            if not mark:
                continue
            t.phonemes = mark
            prev = next((u for u in reversed(toks[:i]) if u.phonemes), None)
            if mark in '“«(':
                t.whitespace = False
                if prev:
                    prev.whitespace = True
            else:
                t.whitespace = True
                if prev:
                    prev.whitespace = False

    @staticmethod
    def _align(tokens, cut, align):
        """character spans in the plain text. cutlet normalises the text first (full-width letters and
        punctuation, half-width kana), so the plain text is normalised the same way, character by character."""
        norm, where = [], []
        for i, ch in enumerate(align):
            n = unicodedata.normalize('NFKC', ch) if ch.isdigit() else cut._normalize_text(ch)
            norm.append(n); where += [i] * len(n)
        norm = ''.join(norm)
        pos = 0
        for t in tokens:
            if not t.text:
                continue
            i = norm.find(t.text, pos)
            # skip only what no word stands for: spaces, punctuation, digits (spoken as kana), =substituted text
            if i >= 0 and all(unicodedata.category(c)[0] in 'PZSN' for c in norm[pos:i]):
                t.span = (where[i], where[i + len(t.text) - 1] + 1); pos = i + len(t.text)


JAPANESE = register(Japanese, 'j', 'jp')
