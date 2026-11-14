"""Languages: the rules that depend on the language being spoken.

The script format, the mark syntax and the engine's edits (durations, pitch offsets, energy, pauses, `human`)
are shared. A Language says what they mean for its words and sounds:

- text -> tokens: the phonemizer (G2P), how words are found, fix-ups to the text before it is phonemized
- phoneme classes: punctuation, sentence ends, vowels, voiced sonorants (as the phonemizer writes them)
- how a run of punctuation pauses (comma, clause, dash, sentence, ellipsis)
- what stress (+ / -) does: the STRESS tables
- question intonation: which questions rise, and by how much

Each language is a subclass in its own module, registered with `register`; `get(code)` returns it.
Only light imports here: scripts and the editor load this without torch.
"""
from dataclasses import dataclass

DEFAULT = 'en'
LANGUAGES = {}
ALIASES = {}


@dataclass
class Token:
    text: str
    phonemes: str       # already filtered to the model's vocabulary
    whitespace: bool
    span: tuple = None  # character span in the plain text, if it could be aligned
    unknown: bool = False

    @property
    def is_word(self):
        return any(c.isalpha() for c in self.phonemes)


class Language:
    """Base class. Subclasses fill in the constants and the methods marked as such."""
    code = None                 # jivetalker's name for it, e.g. 'en'
    kokoro = None               # Kokoro's lang_code (KPipeline), e.g. 'a'
    name = None

    PUNCT = frozenset()         # punctuation as it appears in the phoneme string
    SENTENCE_END = frozenset()
    VOWELS = frozenset()        # vowel phonemes: a stretched word's extra length goes to these
    SONORANT = frozenset()      # voiced sounds: pitch dropouts over these are bridged, drawn-out words held
    QUESTION_MARKS = '?'        # a token holding one of these ends a question

    PAUSE_MARK = ','            # added after a word with a | mark, so the model has something to hold

    STRESS = {}                 # level (1, 2, -1) -> per-word edit, see styles.word_edit
    STRESS_MORE = {}            # levels 3-5 and -2, -3
    STRESS_MAX = 0.0            # semitones: the most a stressed word is lifted (levels 1-2)
    QUESTION = {}               # question rise tuning, see Engine._synth_chunk

    def stress(self, level):
        """the per-word edit for a stress level (empty for 0)"""
        return dict(self.STRESS.get(level) or self.STRESS_MORE.get(level) or {})

    def spoken(self, text):
        """fix-ups to the spoken text before it is phonemized"""
        return text

    def has_pause_after(self, rest):
        """True if `rest` (the text after a | mark) already starts with a mark the model can hold"""
        raise NotImplementedError

    def tokenize(self, pipe, marked, vocab):
        """MarkedText -> [Token], with character spans aligned to marked.plain. pipe: Kokoro's KPipeline for
        this language; vocab: the model's phoneme vocabulary"""
        raise NotImplementedError

    def pause_kind(self, run):
        """a run of punctuation (with spaces) in the phoneme string -> a styles.PAUSES kind"""
        raise NotImplementedError

    def question_rises(self, settings, plain):
        """semitones of rise for each question in the plain text, in order"""
        raise NotImplementedError

    def __repr__(self):
        return f'<Language {self.code}>'


def register(cls, *aliases):
    lang = cls()
    LANGUAGES[lang.code] = lang
    for a in aliases:
        ALIASES[a] = lang.code
    return lang


def get(code=None):
    """a Language by its code (or alias); None = the default (English). A Language passes through."""
    if isinstance(code, Language):
        return code
    code = DEFAULT if code is None else str(code).lower()
    code = ALIASES.get(code, code)
    if code not in LANGUAGES:
        raise ValueError(f'unknown language "{code}": known are {", ".join(sorted(LANGUAGES))}')
    return LANGUAGES[code]


from . import en  # noqa: E402,F401  (registers English)
