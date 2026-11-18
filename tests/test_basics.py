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

    def test_demo_script(self):
        from jivetalker.toolkit import demo_script
        with tempfile.TemporaryDirectory() as d:
            path = Path(demo_script(d))
            jobs, errors = Script.load(path).jobs()
            self.assertEqual(errors, [])
            self.assertGreater(len(jobs), 10)
            path.write_text('# my edits\n', encoding='utf-8')
            self.assertEqual(Path(demo_script(d)).read_text(encoding='utf-8'), '# my edits\n')   # copy kept


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

    def test_shorten(self):
        m = marks.parse('the [blurry](<<|) ceiling')
        self.assertEqual((m.plain, m.marks[0].shorten, m.marks[0].pause), ('the blurry ceiling', 2, 1))
        self.assertEqual(styles.word_edit(m.marks[0])['shorten'], styles.SHORTEN[2])
        for bad in ('[a](<<<<)', '[a](~<)'):
            with self.assertRaises(ValueError, msg=bad):
                marks.parse(bad)

    def test_shorten_keys_only_its_lines(self):
        # lines without < keep their keys (GOLDEN_KEY); a line with it depends on the levels it uses
        job = {j.id: j for j in parse().jobs()[0]}['c1.e10']
        s = styles.resolve(job.direction)
        self.assertNotIn('shorten', render.tuning(job, s))
        job.text = job.text.replace('Close', '[Close](<<)')
        self.assertEqual(render.tuning(job, s)['shorten'], {2: styles.SHORTEN[2]})


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

    def test_audio_formats(self):
        sc = Script.parse(SCRIPT.replace('@defaults', '@format Vorbis\n@defaults', 1))
        self.assertEqual((sc.audio_format, sc.errors), ('vorbis', []))
        self.assertEqual(Script.parse(SCRIPT).audio_format, None)             # no @format: Ogg Opus
        self.assertTrue(Script.parse('@format mp3\n').errors)
        key = 'ab' * 32
        self.assertEqual(render.clip_name('c1.e1', key, 'ogg'), 'c001_e001_ababababab.ogg')    # names unchanged
        self.assertEqual(render.clip_name('c1.e1', key, 'opus'), 'c001_e001_ababababab.ogg')
        vorbis = render.clip_name('c1.e1', key, 'vorbis')
        self.assertTrue(vorbis.endswith('.ogg') and vorbis != render.clip_name('c1.e1', key, 'ogg'))
        with self.assertRaises(ValueError):
            render.clip_name('c1.e1', key, 'mp3')

    def test_renamed_style_keeps_its_clips(self):
        # 'monotone' was called 'deep': scripts that say deep still read, and both names give the same clip
        jobs = {j.id: j for j in parse().jobs()[0]}
        old = jobs['c1.e21']
        self.assertEqual(old.direction.style, 'monotone')
        new = Script.parse(SCRIPT.replace('c1.e21   Mara {deep}', 'c1.e21   Mara {monotone}')).jobs()[0]
        self.assertEqual(render.cache_key(old), render.cache_key({j.id: j for j in new}['c1.e21']))

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

    def test_voices_in_subfolders(self):
        from types import SimpleNamespace
        from jivetalker.toolkit import DEMO, Toolkit, find_scripts
        with tempfile.TemporaryDirectory() as d:
            v = Path(d) / 'voices'
            for f in ('mara.pt', 'villagers/bob.pt', 'guards/captain.pt', 'a/b/too_deep.pt'):
                (v / f).parent.mkdir(parents=True, exist_ok=True); (v / f).write_bytes(b'')
            lab = voicelab.Lab(SimpleNamespace(torch=None), [v])
            self.assertEqual(sorted(lab.user), ['guards/captain', 'mara', 'villagers/bob'])   # one level down
            tk = Toolkit(SimpleNamespace(lab=lab, eng=None, lock=None), home=d)
            # names are relative to the script's @voices folder, the way voice_path() reads them back
            self.assertEqual(tk.voice_ref('villagers/bob', v), 'villagers/bob')
            self.assertEqual(tk.voice_ref('mara', v), 'mara')
            self.assertEqual(tk.voice_ref('mara', v / 'villagers'), '../mara.pt')
            self.assertEqual(tk.voice_ref('af_heart', v), 'af_heart')
            sc = Script.parse('@voices voices\n@cast Bob = villagers/bob\n', Path(d) / 's.txt')
            self.assertEqual(Path(sc.voice_path('villagers/bob')), v / 'villagers' / 'bob.pt')
        self.assertNotIn(DEMO.relative_to(DEMO.parents[2]).as_posix(), find_scripts(DEMO.parents[2]))

    def test_change_id_and_speaker(self):
        from jivetalker.toolkit import rewrite_line
        self.assertEqual(rewrite_line('c1.e10   Mara: Close your [eyes](+~)...', line_id='c1.e9'),
                         'c1.e9    Mara: Close your [eyes](+~)...')           # the speaker column stays put
        self.assertEqual(rewrite_line('c1.e4    !check ??? {whisper}: Who?', speaker='narrator'),
                         'c1.e4    !check narrator {whisper}: Who?')
        for bad in (dict(line_id='two words'), dict(line_id=''), dict(speaker='a: b')):
            with self.assertRaises(ValueError, msg=bad):
                rewrite_line('c1.e1    narrator: hi', **bad)

    def test_edit_and_delete_lines_and_cast(self):
        from jivetalker.toolkit import ScriptDoc
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'voice_script.txt'
            p.write_bytes(SCRIPT.replace('\n', '\r\n').encode('utf-8'))
            doc = ScriptDoc(p)
            m = doc.model()
            line = lambda i: next(x for x in m['items'] if x.get('id') == i)
            e1 = line('c1.e1')
            with self.assertRaises(ValueError):                                 # IDs stay unique
                doc.edit({'base': m['version'], 'lineno': e1['lineno'], 'expect': e1['raw'], 'id': 'c1.e3'})
            with self.assertRaises(ValueError):                                 # speakers come from the cast
                doc.edit({'base': m['version'], 'lineno': e1['lineno'], 'expect': e1['raw'], 'speaker': 'Nobody'})
            m = doc.edit({'base': m['version'], 'lineno': e1['lineno'], 'expect': e1['raw'], 'id': 'c1.e2',
                          'speaker': 'Mara'})
            self.assertEqual(line('c1.e2')['raw'], 'c1.e2    Mara: Mara sat on the bench.')
            # rename: the @cast line, the lines that use the name, and the ramp's "for"; not the alias's lines
            text = SCRIPT.replace('@ramp trance 0.2 -> 1.0', '@ramp trance 0.2 -> 1.0 for Mara')
            p.write_bytes(text.replace('\n', '\r\n').encode('utf-8'))
            m = doc.edit_cast({'base': doc.model()['version'], 'name': 'Mara', 'new_name': 'Mira',
                               'direction': 'pitch -2'}, 'af_sky')
            out = p.read_bytes().decode('utf-8')
            self.assertIn('@cast Mira = af_sky | ??? {pitch -2}\r\n', out)
            self.assertIn('@cast Mara (thought) = af_bella {internal}\r\n', out)
            self.assertIn('c1.e10   Mira: Close', out)
            self.assertIn('c1.e4    ??? {whisper}', out)
            self.assertIn('@ramp trance 0.2 -> 1.0 for Mira\r\n', out)
            self.assertEqual(m['summary']['errors'], 0)
            with self.assertRaises(ValueError):                                 # Mira still has lines
                doc.delete_cast({'base': m['version'], 'name': 'Mira'})
            th = line('c1.e3')
            m = doc.delete_line({'base': m['version'], 'lineno': th['lineno'], 'expect': th['raw']})
            self.assertNotIn('c1.e3', p.read_text(encoding='utf-8'))
            self.assertIn('# a comment that belongs to the next line', p.read_text(encoding='utf-8'))
            m = doc.delete_cast({'base': m['version'], 'name': 'Mara (thought)'})
            self.assertNotIn('Mara (thought)', p.read_text(encoding='utf-8'))
            self.assertEqual(m['summary']['errors'], 0)

    def test_build_a_script_from_scratch(self):
        from jivetalker.toolkit import Conflict, ScriptDoc, find_scripts, new_script_text
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'scenes' / 'act1.txt'
            p.parent.mkdir()
            p.write_bytes(new_script_text('act1', [('Narrator', 'af_heart')]).replace('\n', '\r\n').encode('utf-8'))
            doc = ScriptDoc(p)
            m = doc.add_cast({'base': doc.model()['version'], 'name': 'Sam', 'direction': 'pitch -1'}, 'am_michael')
            m = doc.add_line({'base': m['version'], 'id': 'a.01', 'speaker': 'Sam', 'text': 'Hello [there](+).'})
            m = doc.add_line({'base': m['version'], 'id': 'a.02', 'speaker': 'Narrator', 'text': 'And so.'})
            m = doc.add_line({'base': m['version'], 'id': 'a.0', 'speaker': 'Sam', 'text': 'First!', 'after': 5})
            self.assertEqual(p.read_bytes().decode('utf-8').split('\r\n')[2:], [
                '@cast Narrator = af_heart', '@cast Sam = am_michael {pitch -1}', '',
                'a.0  Sam: First!', 'a.01  Sam: Hello [there](+).', 'a.02  Narrator: And so.', ''])
            self.assertEqual((m['summary']['lines'], m['summary']['errors']), (3, 0))
            for bad in ({'id': 'a.01', 'speaker': 'Sam', 'text': 'x'},              # the ID is taken
                        {'id': 'a.9', 'speaker': 'Nobody', 'text': 'x'},
                        {'id': 'two words', 'speaker': 'Sam', 'text': 'x'}):
                with self.assertRaises(ValueError, msg=bad):
                    doc.add_line(dict(bad, base=m['version']))
            with self.assertRaises(ValueError):
                doc.add_cast({'base': m['version'], 'name': 'Sam'}, 'af_bella')
            with self.assertRaises(Conflict):
                doc.add_line({'base': 'stale', 'id': 'a.9', 'speaker': 'Sam', 'text': 'x'})
            (Path(d) / 'notes.txt').write_text('no cast here', encoding='utf-8')
            self.assertEqual(find_scripts(d), ['scenes/act1.txt'])

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
        self.assertEqual(str(d), 'monotone, lang ja')                                 # deep: the old name
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

    def test_sung_script_lines(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / 'songs').mkdir()
            (d / 'songs' / 'tune.abc').write_text('L:1/4\nK:C\nC D E2\nw: la la la\n', encoding='utf-8')
            sc = d / 'voice_script.txt'
            sc.write_text('@cast Mara = af_bella\n'
                          'a.1 Mara: spoken\n'
                          'a.2 Mara {sing songs/tune.abc transpose=-12, internal}: la la la\n'
                          'a.3 Mara {sing songs/missing.abc}: x\n'
                          'a.4 Mara {sing songs/tune.abc verse=x}: x\n', encoding='utf-8')
            jobs, errors = Script.load(sc).jobs()
            self.assertEqual([j.id for j in jobs], ['a.1', 'a.2'])
            self.assertEqual(sorted(n for n, _ in errors), [4, 5])                    # missing file, bad option
            sung = jobs[1]
            self.assertEqual(Path(sung.song).name, 'tune.abc')
            self.assertEqual(styles.resolve(sung.direction)['sing'], 'songs/tune.abc transpose=-12')
            k1 = render.cache_key(sung)
            (d / 'songs' / 'tune.abc').write_text('L:1/4\nK:C\nC D F2\nw: la la la\n', encoding='utf-8')
            self.assertNotEqual(render.cache_key(sung), k1)                           # the score is in the key
        with self.assertRaises(ValueError):
            styles.parse_direction('sing songs/tune.mp3')

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
