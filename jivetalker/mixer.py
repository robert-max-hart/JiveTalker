"""The voice mixer behind the toolkit's Voices tab: blending and tuning voice packs by ear.

    jivetalker mixer --voices-dir voices/ [--script voice_script.txt] [--port 8765]

The page and server live in toolkit.py (this module is the mixer's API). Saving writes <name>.pt and
<name>.recipe.json to --save-dir (default: the first --voices-dir); an existing file is kept as
<name>.pt.bak-<time> before it is replaced.
"""
import base64
import io
import re
import threading
import time
from pathlib import Path

from . import voicelab

PAGE = Path(__file__).with_name('mixer.html')
NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')


class Mixer:
    def __init__(self, voices_dirs, save_dir, script=None, model_dir=None, engine=None, lock=None):
        """engine/lock: share an Engine (and the lock that guards it, as it is not thread-safe) with other tools"""
        if engine is None:
            from .engine import Engine
            print('jivetalker: loading Kokoro...')
            engine = Engine(model_dir=model_dir)
        self.eng = engine
        self.lab = voicelab.Lab(self.eng, voices_dirs)
        self.lab.axes()
        self.save_dir = Path(save_dir) if save_dir else None
        self.lock = lock or threading.Lock()
        self.script = script
        self.script_voices = voices_dirs[0] if voices_dirs else None

    @property
    def lines(self):
        """the script's lines as test text (read afresh, so edits made in the Script tab show up)"""
        if not self.script:
            return []
        from .script import Script
        jobs, _ = Script.load(self.script).jobs(self.script_voices)
        return [{'id': j.id, 'speaker': j.speaker, 'direction': str(j.direction), 'text': j.text} for j in jobs]

    def source_for(self, voice_path):
        """the mixer's name for a voice (a stock name, or a .pt file in the voices folders), or None"""
        if voice_path in self.lab.stock:
            return voice_path
        try:
            want = Path(voice_path).resolve()
        except OSError:
            return None
        return next((n for n, p in self.lab.user.items() if Path(p) == want), None)

    # ------------------------------------------------------------------ API
    def info(self, _):
        return {'sources': self.lab.sources(), 'axes': self.lab.axes_info(), 'lines': self.lines,
                'save_dir': str(self.save_dir) if self.save_dir else None, 'halves': list(voicelab.HALVES)}

    def load(self, q):
        src = q['source']
        with self.lock:
            path = self.lab.user.get(src)
            if path and voicelab.recipe_path(path).exists():
                r = self.lab.local(voicelab.load_recipe(voicelab.recipe_path(path)), Path(path).parent)
                return {'recipe': r, 'how': f'its recipe file ({voicelab.recipe_path(path).name})'}
            r, fits = self.lab.decompose(src)
            exact = [h for h, f in fits.items() if f < 1e-4]
            how = ('found the stock blend it was made from' if len(exact) == 2 else
                   f'found the stock blend for its {exact[0]}; the rest is the file itself' if exact else
                   'the file itself (not a blend of stock voices)')
            return {'recipe': r, 'how': how}

    def render(self, q):
        with self.lock:
            pack = self.lab.build(q['recipe'])
            t = time.time()
            r = self.eng.render(q.get('text') or 'Hello.', pack, q.get('direction') or '', seed=int(q.get('seed', 0)))
            took = time.time() - t
            pos = self.lab.position(pack)
        import soundfile as sf
        buf = io.BytesIO()
        sf.write(buf, r.audio, 24000, format='WAV', subtype='PCM_16')
        return {'audio': base64.b64encode(buf.getvalue()).decode('ascii'), 'seconds': round(len(r.audio) / 24000, 2),
                'took': round(took, 1), 'position': pos,
                'warnings': [f'could not read "{w}"' for w in r.unknown_words] +
                            [f'mark on "{w}" did not land' for w in r.unplaced_marks]}

    def position(self, q):
        with self.lock:
            return {'position': self.lab.position(self.lab.build(q['recipe']))}

    def variants(self, q):
        halves = [h for h in q.get('halves', voicelab.HALVES) if h in voicelab.HALVES]
        return {'recipes': self.lab.variations(q['recipe'], int(q.get('n', 6)), float(q.get('step', 0.5)), halves)}

    def save(self, q):
        if not self.save_dir:
            raise ValueError('no --save-dir (or --voices-dir) to save into')
        name = str(q.get('name', '')).strip()
        if name.endswith('.pt'):
            name = name[:-3]
        if not NAME_RE.match(name):
            raise ValueError('name: letters, digits, _ - . only')
        pt = self.save_dir / f'{name}.pt'
        backup = None
        if pt.exists():
            if not q.get('overwrite'):
                return {'exists': True, 'path': str(pt)}
            stamp = time.strftime('%Y%m%d-%H%M%S')
            backup = pt.with_name(f'{pt.name}.bak-{stamp}')
            pt.rename(backup)
            rp = voicelab.recipe_path(pt)
            if rp.exists():
                rp.rename(rp.with_name(f'{rp.name}.bak-{stamp}'))
        with self.lock:
            self.lab.save(q['recipe'], pt)
        return {'path': str(pt), 'backup': str(backup) if backup else None, 'sources': self.lab.sources()}


