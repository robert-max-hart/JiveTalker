"""Smoke tests that need no model, no voice files and no audio: the script format, word marks, clip names,
cache keys and recipes. Run from the repo root: python -m unittest discover -s tests"""
import json
import tempfile
import unittest
from pathlib import Path

from jivetalker import marks, render, styles, voicelab
from jivetalker.script import Script

SCRIPT = """\
# Voice script: test.
@cast narrator = af_nicole
@cast Mara = af_bella | ??? {pitch -1}
@cast Mara (thought) = af_bella {internal}
@defaults speed 0.95, human 1.0
@pronounce Mara = /mˈɑɹə/

== Chapter 1 ==
c1.e1    narrator: Mara sat on the bench.
# a comment that belongs to the next line
c1.e3    Mara (thought): But what if nobody comes back?
c1.e4    ??? {whisper}: Who's there?

@ramp trance 0.2 -> 1.0
c1.e10   Mara: Close your [eyes](+~)...
c1.e11   narrator: She did.
c1.e12   Mara {pause 2}: Deeper... [now](++||).
@end
c1.e20   Mara {deep, take 2}: yes… yes…
c1.e21   Mara {deep}: yes… yes…
"""


def parse():
    return Script.parse(SCRIPT)


class ScriptFormat(unittest.TestCase):
    def test_parses_without_errors(self):
        jobs, errors = parse().jobs()
        self.assertEqual(errors, [])
        self.assertEqual([j.id for j in jobs], ['c1.e1', 'c1.e3', 'c1.e4', 'c1.e10', 'c1.e11', 'c1.e12',
                                                'c1.e20', 'c1.e21'])

    def test_aliases_and_cast_directions(self):
        jobs = {j.id: j for j in parse().jobs()[0]}
        self.assertEqual(jobs['c1.e4'].speaker, 'Mara')
        self.assertEqual(styles.resolve(jobs['c1.e4'].direction)['style'], 'whisper')
        self.assertIn('internal', styles.resolve(jobs['c1.e3'].direction)['effects'])

    def test_ramp_applies_to_its_speaker_only(self):
        jobs = {j.id: j for j in parse().jobs()[0]}
        d10, d12 = (styles.resolve(jobs[i].direction) for i in ('c1.e10', 'c1.e12'))
        self.assertEqual(d10['style'], 'trance')
        self.assertEqual(d12['style'], 'trance')         # settings-only direction keeps the ramp's style
        self.assertNotEqual(styles.resolve(jobs['c1.e11'].direction)['style'], 'trance')

    def test_pronounce_is_applied(self):
        jobs = {j.id: j for j in parse().jobs()[0]}
        self.assertIn('[Mara](/mˈɑɹə/)', jobs['c1.e1'].text)

    def test_repeated_text_gets_different_seeds(self):
        jobs = {j.id: j for j in parse().jobs()[0]}
        self.assertNotEqual(jobs['c1.e20'].seed, jobs['c1.e21'].seed)

    def test_dump_round_trips(self):
        sc = parse()
        again = Script.parse(sc.dump())
        self.assertEqual([(l.id, l.speaker, l.direction, l.text) for l in sc.lines],
                         [(l.id, l.speaker, l.direction, l.text) for l in again.lines])
        self.assertEqual(again.lines[1].comments, ['# a comment that belongs to the next line'])

    def test_errors_are_reported(self):
        bad = SCRIPT + 'c1.e1    Nobody: hello\nc1.e30   Mara {bogus 3}: hi\n'
        lines = sorted(n for n, _ in Script.parse(bad).jobs()[1])
        self.assertEqual(len(lines), 3)                   # duplicate ID, unknown speaker, bad direction


class WordMarks(unittest.TestCase):
    def test_marks_leave_plain_text(self):
        m = marks.parse('Close your [eyes](+~||) and [Dr.](=Doctor) [Siobhan](/ʃɪvˈɔn/) [very slowly](^2>-1)')
        self.assertEqual(m.plain, 'Close your eyes and Dr. Siobhan very slowly')
        eyes, shaped = m.marks
        self.assertEqual((eyes.stress, eyes.stretch, eyes.pause), (1, 1, 2))
        self.assertEqual(shaped.shape, (2.0, -1.0))

    def test_stacking_limits(self):
        self.assertEqual(marks.parse('[a](+++++)').marks[0].stress, 5)
        for bad in ('[a](++++++)', '[a](~~~~~~)', '[a](----)'):
            with self.assertRaises(ValueError, msg=bad):
                marks.parse(bad)


class Files(unittest.TestCase):
    def test_clip_names_are_safe_everywhere(self):
        self.assertEqual(render.clip_name('c1.e174', 'abcdef0123456789', 'ogg'), 'c001_e174_abcdef0123.ogg')
        name = render.clip_name('a:b*c?<>|"\\/', 'k' * 12, 'ogg')
        self.assertFalse(set(name) & set('<>:"/\\|?*'))

    def test_cache_key_is_stable(self):
        # A fixed key: if this fails, every existing clip would re-render. That's right only when the sound
        # really changed (then update the key here); never for a refactor or on another platform.
        job = {j.id: j for j in parse().jobs()[0]}['c1.e10']
        self.assertEqual(render.cache_key(job), GOLDEN_KEY)

    def test_recipes_old_and_new_marker(self):
        with tempfile.TemporaryDirectory() as d:
            for marker in ('jivetalker_recipe', 'voicegen_recipe'):
                p = Path(d) / f'{marker}.recipe.json'
                p.write_text(json.dumps({marker: 1, 'timbre': {'mix': {'af_bella': 1}, 'axes': {}},
                                         'delivery': {'mix': {'af_bella': 1}, 'axes': {}}}), encoding='utf-8')
                self.assertEqual(voicelab.load_recipe(p)['timbre']['mix'], {'af_bella': 1})
            p = Path(d) / 'other.json'
            p.write_text('{"something": 1}', encoding='utf-8')
            with self.assertRaises(ValueError):
                voicelab.load_recipe(p)
        self.assertIn('jivetalker_recipe', voicelab.clean({}))


class Editor(unittest.TestCase):
    """the toolkit's Script tab: line rewrites and file edits (no model needed)"""

    def test_rewrite_keeps_layout(self):
        from jivetalker.toolkit import rewrite_line
        raw = 'c1.e10   Mara: Close your [eyes](+~)...'
        self.assertEqual(rewrite_line(raw, text='Close your eyes...'), 'c1.e10   Mara: Close your eyes...')
        self.assertEqual(rewrite_line(raw, direction='trance 0.6, take 2'),
                         'c1.e10   Mara {trance 0.6, take 2}: Close your [eyes](+~)...')
        self.assertEqual(rewrite_line('c1.e20   !changed Mara {deep}: yes', flags=[], direction=''), 'c1.e20   Mara: yes')
        self.assertEqual(rewrite_line('c1.e4    ??? {whisper}: Who?', flags=['check']), 'c1.e4    !check ??? {whisper}: Who?')
        for bad in (dict(direction='a}b'), dict(text='two\nlines'), dict(flags=['no spaces'])):
            with self.assertRaises(ValueError, msg=bad):
                rewrite_line(raw, **bad)

    def test_edits_and_conflicts(self):
        from jivetalker.toolkit import Conflict, ScriptDoc
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'voice_script.txt'
            p.write_bytes(SCRIPT.replace('\n', '\r\n').encode('utf-8'))     # Windows line endings survive
            doc = ScriptDoc(p)
            m = doc.model()
            self.assertEqual((m['summary']['lines'], m['summary']['errors']), (8, 0))
            line = next(i for i in m['items'] if i.get('id') == 'c1.e11')
            self.assertEqual(line['ramp']['value'], None)               # the ramp is Mara's, not the narrator's
            e10 = next(i for i in m['items'] if i.get('id') == 'c1.e10')
            self.assertEqual((e10['style'], e10['style_src']), ('trance', '@ramp'))
            m2 = doc.edit({'base': m['version'], 'lineno': e10['lineno'], 'expect': e10['raw'],
                           'text': 'Close your [eyes](++|)...'})
            self.assertIn('c1.e10   Mara: Close your [eyes](++|)...\r\n', p.read_bytes().decode('utf-8'))
            self.assertTrue((Path(d) / 'voice_script.txt.bak').exists())
            with self.assertRaises(Conflict):                           # made on the old version
                doc.edit({'base': m['version'], 'lineno': e10['lineno'], 'expect': e10['raw'], 'text': 'x'})
            doc.save_text({'base': m2['version'], 'text': SCRIPT})
            self.assertEqual(p.read_bytes().decode('utf-8'), SCRIPT.replace('\n', '\r\n'))


class Languages(unittest.TestCase):
    """per-language rules (lang/): no model needed; the Japanese phonemizer test needs misaki[ja] and UniDic"""

    def test_lang_setting(self):
        d = styles.parse_direction('deep, lang ja')
        self.assertEqual(styles.resolve(d)['lang'], 'ja')
        self.assertEqual(str(d), 'deep, lang ja')
        self.assertNotIn('lang', styles.resolve(styles.parse_direction('lang en')))   # English: keys unchanged
        for bad in ('lang xx', 'lang'):
            with self.assertRaises(ValueError, msg=bad):
                styles.parse_direction(bad)
        errs = Script.parse(SCRIPT + '@ramp lang 0 -> 1\nc9.e1 Mara: hi\n@end\n').jobs()[1]
        self.assertTrue(any('@ramp' in e for _, e in errs))

    def test_english_keys_ignore_lang_en(self):
        jobs = {j.id: j for j in parse().jobs()[0]}
        job = jobs['c1.e10']
        en = render.cache_key(job)
        job.direction = styles.merge(job.direction, styles.parse_direction('lang en'))
        self.assertEqual(render.cache_key(job), en)
        job.direction = styles.merge(job.direction, styles.parse_direction('lang ja'))
        self.assertNotEqual(render.cache_key(job), en)

    def test_japanese_rules(self):
        from jivetalker import lang
        ja = lang.get('ja')
        self.assertEqual(ja.question_rises({}, '何ですか？はい。本当？'), [ja.QUESTION['auto']] * 2)
        self.assertEqual(ja.question_rises({'rise': 2.0}, 'そう？'), [2.0])
        self.assertEqual(ja.stress(1)['dur'], 1.0)          # vowel length is meaning in Japanese
        self.assertEqual(marks.parse('[目](|)を', ja).g2p, '目、を')

    def test_unspaced_words(self):
        self.assertEqual(marks.apply_marks('今日は目を閉じて', marks.marked_words('今日は[目](+)を閉じて'))[0],
                         '今日は[目](+)を閉じて')
        self.assertEqual(marks.apply_pronounce('ミラは来た', {'ミラ': '/miɾa/'}), '[ミラ](/miɾa/)は来た')
        self.assertEqual(marks.apply_pronounce('Maraschino', {'Mara': '/x/'}), 'Maraschino')

    def test_japanese_words_match_kokoro(self):
        try:
            from misaki import ja as misaki_ja
            g2p = misaki_ja.JAG2P()
        except Exception as e:                              # optional: misaki[ja] + UniDic
            self.skipTest(f'Japanese phonemizer not installed ({e})')
        from types import SimpleNamespace
        from jivetalker import lang
        ja, pipe = lang.get('ja'), SimpleNamespace(g2p=g2p)
        vocab = set(' !"(),.:;?abdehijkmnoprstuvwzçŋɕɡɨɯɲɴɸɾʔʣʥʦʨʲβᵝː—“”…')
        mt = marks.parse('さあ、[目](+)を閉じて…[深く](++)息を吸って。それは本当ですか？', ja)
        with _no_warnings(self):
            toks = ja.tokenize(pipe, mt, vocab)
        said = ' '.join(t.text for t in toks if t.span and any(t.span[0] < m.end and t.span[1] > m.start for m in mt.marks))
        self.assertEqual(said, '目 深く')
        ps = ''.join(t.phonemes + (' ' if t.whitespace else '') for t in toks)
        self.assertIn('saː, me', ps)                       # the 、 cutlet drops is back
        self.assertIn('sɨʔte. soɾe', ps)                   # and the 。


class Singing(unittest.TestCase):
    """the singing prototype's notation and syllables (no model)"""

    def test_abc(self):
        from jivetalker import sing
        song = sing.parse_abc('L:1/4\nQ:1/4=120\nK:F\nB2 z ^c/ c- c | B\nw: one two_ three\n')
        self.assertEqual([n.midi for n in song.notes], [70, None, 73, 73, 70])     # Bb (key), ^c holds in the bar
        self.assertEqual([round(n.length, 3) for n in song.notes], [1.0, 0.5, 0.25, 1.0, 0.5])   # tie: c- c
        self.assertEqual(song.lyrics, [('one', 0), ('two', 1), None, ('three', 2)])
        with self.assertRaises(ValueError):
            sing.parse_abc('K:C\nC D\nw: one two three\n')

    def test_syllables(self):
        from jivetalker import lang, sing
        en = lang.get('en')
        self.assertEqual(sing.split_word('twˈɪŋkᵊl', 2, en), [('twˈ', 'ɪ', 'ŋ'), ('k', 'ᵊ', 'l')])
        self.assertEqual(sing.split_word('fˈIəɹ', 1, en), [('fˈ', 'I', 'əɹ')])    # one sung syllable
        self.assertEqual(sing.split_word('ˈɛvəɹiθˌɪŋ', 3, en), [('ˈ', 'ɛ', 'və'), ('ɹ', 'i', ''), ('θˌ', 'ɪ', 'ŋ')])

    def test_japanese_beats(self):
        from jivetalker import lang, sing
        ja = lang.get('ja')
        self.assertEqual(sing.split_word('ɡeŋkʲi', 3, ja), [('ɡ', 'e', ''), ('', 'ŋ', ''), ('kʲ', 'i', '')])
        self.assertEqual(sing.split_word('ɡeŋkʲi', 2, ja), [('ɡ', 'e', 'ŋ'), ('kʲ', 'i', '')])     # ん joins げ
        self.assertEqual(sing.split_word('soː', 2, ja), [('s', 'o', ''), ('', 'ː', '')])
        self.assertEqual(sing.split_word('kiʔte', 2, ja), [('k', 'i', 'ʔ'), ('t', 'e', '')])

    def test_phonemic_lyrics(self):
        from jivetalker import lang, sing
        song = sing.parse_abc('K:C\nC D E F G\nw: Twin/twˈɪŋ/-kle the /fˈIəɹ/,\n')
        self.assertEqual(song.parts, [['Twin/twˈɪŋ/', 'kle'], ['the'], ['/fˈIəɹ/,']])
        self.assertEqual([sing.spelling(p) for p in song.parts[2]], [','])
        syls = sing.syllables(song, [['twˈɪŋ', 'kᵊl'], 'ðə', ['fˈIəɹ']], lang.get('en'))
        self.assertEqual([(s.onset, s.nucleus, s.coda, s.notes) for s in syls],
                         [('twˈ', 'ɪ', 'ŋ', [0]), ('k', 'ᵊ', 'l', [1]), ('ð', 'ə', '', [2]), ('fˈ', 'I', 'əɹ', [3, 4])])

    def test_musicxml(self):
        import io
        import zipfile
        from jivetalker import sing
        data = (Path(__file__).parent / 'score.musicxml').read_bytes()
        song = sing.parse_musicxml(data)          # the Voice part (the piano has no lyrics), voice 1, verse 1
        sung = [n for n in song.notes if n.midi is not None]
        self.assertEqual([n.midi for n in sung], [67, 69, 71, 72, 66, 67])            # chord: first note only
        self.assertEqual([round(n.start, 3) for n in sung], [0.0, 0.667, 1.333, 1.667, 2.0, 4.0])
        self.assertEqual(round(sung[4].length, 3), 1.333)                              # tied over the bar
        self.assertEqual(round(sung[5].length, 3), 2.0)                                # tempo 90 -> 60
        self.assertEqual(song.words, ['Morning', 'comes', '/sˈO/', 'light.'])
        self.assertEqual(song.lyrics[:4], [('Mor', 0), ('ning', 0), ('comes', 1), None])   # melisma
        self.assertEqual(sing.parse_musicxml(data, verse=2).words, ['Night', 'falls'])
        self.assertEqual(sing.parse_musicxml(data, voice=2).words, ['ooh'])
        with self.assertRaises(ValueError):
            sing.parse_musicxml(data, part=1)                                          # no lyrics there
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            z.writestr('META-INF/container.xml', '<container><rootfiles><rootfile full-path="s.xml"/></rootfiles>'
                                                 '</container>')
            z.writestr('s.xml', data)
        self.assertEqual(sing.parse_musicxml(buf.getvalue()).words, song.words)

    def test_psola_lands_on_pitch(self):
        import numpy as np
        from jivetalker import sing
        sr = 24000
        t = np.arange(sr) / sr
        x = sum(np.sin(2 * np.pi * 150 * h * t) * 0.9 ** h for h in range(1, 30)).astype(np.float32)
        f0 = np.full(sr // 300, 150.0)
        for ratio in (0.75, 2.0, 3.0):
            y = sing.psola(x, f0, np.full(len(f0), ratio))
            seg = y[sr // 4: 3 * sr // 4].astype(float)
            ac = np.correlate(seg, seg, 'full')[len(seg) - 1:]
            lag_lo = int(sr / (150 * ratio * 1.3))
            lag = lag_lo + int(np.argmax(ac[lag_lo:int(sr / (150 * ratio / 1.3))]))
            self.assertAlmostEqual(sr / lag, 150 * ratio, delta=150 * ratio * 0.03, msg=f'x{ratio}')


class _no_warnings:
    def __init__(self, test):
        self.test = test

    def __enter__(self):
        import warnings
        self.cm = warnings.catch_warnings(record=True)
        self.caught = self.cm.__enter__()
        warnings.simplefilter('always')

    def __exit__(self, *exc):
        self.cm.__exit__(*exc)
        mine = [w for w in self.caught if 'jivetalker' in str(w.message)]
        self.test.assertEqual(mine, [])


GOLDEN_KEY ="871ac1f61f37b41a38624d547580d285de26851030d7ac1c8e93c66eb9175ae9"

if __name__ == '__main__':
    unittest.main()
