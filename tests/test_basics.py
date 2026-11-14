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


GOLDEN_KEY ="871ac1f61f37b41a38624d547580d285de26851030d7ac1c8e93c66eb9175ae9"

if __name__ == '__main__':
    unittest.main()
