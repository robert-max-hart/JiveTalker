"""The JiveTalker toolkit: one local page with a tab per tool.

    jivetalker edit voice_script.txt [--voices-dir voices/] [--out clips/] [--port 8765]
    jivetalker mixer --voices-dir voices/ [--script voice_script.txt]

Tabs: **Script** (edit a voice script by hand: word marks, directions, previews, render) and **Voices** (the
mixer, mixer.py). Serves on 127.0.0.1 only.

The script file stays the source of truth. A change in the Visual view rewrites only the line it touches; the
Source view saves the whole text. Every edit names the version of the file it was made on, and an edit made
on an older version (the file changed elsewhere meanwhile) is refused, and the page reloads, instead of
overwriting the other change. Before the first change of a session the file is copied to <name>.bak.
"""
import base64
import hashlib
import io
import json
import os
import re
import shutil
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import marks as marks_mod, render as render_mod, styles
from .common import STOCK_PREFIXES
from .script import LINE_RE, Script

PAGE = Path(__file__).with_name('toolkit.html')
# a script line split into the parts an edit may change: indent, ID, gap, !flags, speaker, {direction}, text
EDIT_RE = re.compile(r'^(\s*)(\S+)(\s+)((?:![\w-]+\s+)*)([^{:]+?)\s*(?:\{([^}]*)\})?\s*:\s?(.*)$')
FLAG_RE = re.compile(r'^[\w-]+$')
AUDIO_TYPES = {'ogg': 'audio/ogg', 'wav': 'audio/wav', 'flac': 'audio/flac'}


class Conflict(Exception):
    """the edit was made on an older version of the file"""


def version(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]


def rewrite_line(raw, text=None, direction=None, flags=None):
    """`raw` (one script line) with its text, direction and/or flags replaced; None keeps that part as is.
    Everything else (the ID column, spacing) is kept."""
    m = EDIT_RE.match(raw)
    if not m:
        raise ValueError('not a script line')
    for name, v in (('text', text), ('direction', direction)):
        if v is not None and ('\n' in v or '\r' in v):
            raise ValueError(f'{name}: one line only')
    if direction is not None and ('{' in direction or '}' in direction):
        raise ValueError('direction: no braces')
    if flags is not None and not all(FLAG_RE.match(f) for f in flags):
        raise ValueError('flags: letters, digits, _ and - only')
    indent, lid, gap, old_flags, speaker, old_dir, old_text = m.groups()
    if direction is None and flags is None:
        new = raw if text is None else raw[:m.start(7)] + text
    else:
        f = old_flags if flags is None else ''.join(f'!{x} ' for x in flags)
        d = (old_dir or '') if direction is None else direction
        t = old_text if text is None else text
        new = f'{indent}{lid}{gap}{f}{speaker.strip()}' + (f' {{{d.strip()}}}' if d.strip() else '') + f': {t}'
    check = LINE_RE.match(new.strip())
    if not check or check.group(1) != lid or check.group(3).strip() != speaker.strip():
        raise ValueError('that change would break the line (a ":" or "{" in the wrong place?)')
    return new


def _num(v):
    return round(v, 3) if isinstance(v, float) else v


class ScriptDoc:
    """A voice script file being edited: reads it, describes it for the page, applies edits."""

    def __init__(self, path, voices_dir=None, out=None, fmt='ogg', source_for=None):
        self.path = Path(path).resolve()
        self.voices_override = voices_dir
        self.out = Path(out).resolve() if out else self.path.parent / 'voice'
        self.fmt = fmt
        self.source_for = source_for or (lambda p: None)     # voice path -> mixer name
        self.lock = threading.Lock()
        self.backed_up = False

    # ------------------------------------------------------------------ the file
    def read(self):
        with open(self.path, encoding='utf-8', newline='') as f:
            return f.read()

    def _write(self, text):
        if not self.backed_up:
            shutil.copy2(self.path, self.path.with_name(self.path.name + '.bak'))
            self.backed_up = True
        tmp = self.path.with_name(self.path.name + '.tmp')
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            f.write(text)
        os.replace(tmp, self.path)

    def script(self, text=None):
        return Script.parse(self.read() if text is None else text, self.path)

    # ------------------------------------------------------------------ edits
    def edit(self, q):
        """{base, lineno, expect, text?, direction?, flags?}: change one line"""
        with self.lock:
            text = self.read()
            if q.get('base') != version(text):
                raise Conflict()
            lines = text.splitlines(keepends=True)
            n = int(q['lineno'])
            if not 1 <= n <= len(lines):
                raise Conflict()
            body = lines[n - 1].rstrip('\r\n')
            if body != q.get('expect'):
                raise Conflict()
            new = rewrite_line(body, q.get('text'), q.get('direction'), q.get('flags'))
            if new != body:
                lines[n - 1] = new + lines[n - 1][len(body):]
                self._write(''.join(lines))
        return self.model()

    def save_text(self, q):
        """{base, text}: replace the whole file (the Source view, undo)"""
        new = q['text']
        if not isinstance(new, str):
            raise ValueError('text must be a string')
        with self.lock:
            text = self.read()
            if q.get('base') != version(text):
                raise Conflict()
            new = new.replace('\r\n', '\n')
            if '\r\n' in text:                   # keep the file's own line endings
                new = new.replace('\n', '\r\n')
            if new != text:
                self._write(new)
        return self.model()

    # ------------------------------------------------------------------ the page's view of the script
    def model(self):
        text = self.read()
        sc = self.script(text)
        jobs, errors = sc.jobs(self.voices_override)
        physical = text.splitlines()

        def parse(s, where):
            try:
                return styles.parse_direction(s)
            except ValueError as e:
                errs.append(f'{where}: {e}')
                return None

        errs = []
        defaults = parse(sc.defaults, '@defaults')
        cast_dirs = {c.name: parse(c.direction, f'@cast {c.name}') for c in sc.cast.values()}
        ramps = sc.ramp_info()
        by_id = {}
        for j in jobs:
            by_id.setdefault(j.id, j)
        plan = {j.id: (key, action, src) for j, key, action, src in
                render_mod.make_plan(list(by_id.values()), self.out, self.fmt)} if by_id else {}
        line_errors = {}
        for n, msg in errors:
            line_errors.setdefault(n, []).append(msg)

        items, line_n = [], 0
        for kind, x in sc.items:
            if kind == 'line':
                items.append(self._line(x, sc, physical, defaults, cast_dirs, ramps, by_id, plan, line_errors))
                line_n += 1
            elif kind == 'section':
                items.append({'kind': 'section', 'title': x})
            elif kind == 'ramp':
                who = sc.ramp_speaker(x)
                items.append({'kind': 'ramp', 'header': x.header(), 'what': x.what, 'a': x.a, 'b': x.b,
                              'lineno': x.lineno, 'speaker': who,
                              'count': sum(1 for ln in x.lines if sc.aliases.get(ln.speaker) == who)})
            elif kind == 'end':
                items.append({'kind': 'end'})
            else:
                items.append({'kind': kind, 'text': x})

        counts = {}
        for ln in sc.lines:
            who = sc.aliases.get(ln.speaker)
            counts[who] = counts.get(who, 0) + 1
        cast = []
        for c in sc.cast.values():
            vp = sc.voice_path(c.voice, self.voices_override)
            stock = vp.startswith(STOCK_PREFIXES) and not Path(vp).suffix
            cast.append({'name': c.name, 'voice': c.voice, 'aliases': c.aliases, 'direction': c.direction,
                         'lines': counts.get(c.name, 0), 'stock': stock,
                         'found': stock or Path(vp).exists(), 'source': self.source_for(vp)})

        todo = [by_id[i] for i, (_, a, _) in plan.items() if a == 'render']
        est = sum(render_mod.estimate_seconds(j) for j in todo)
        problems = [{'lineno': n, 'msg': m} for n, m in errors if not any(
            n == it.get('lineno') for it in items if it['kind'] == 'line')]
        return {
            'version': version(text), 'text': text, 'path': str(self.path), 'name': self.path.name,
            'folder': self.path.parent.name, 'out': str(self.out), 'out_rel': self._rel(self.out), 'format': self.fmt,
            'defaults': sc.defaults, 'pronounce': sc.pronounce, 'voices': str(sc.voices_dir(self.voices_override)),
            'cast': cast, 'items': items, 'problems': problems,
            'summary': {'lines': len(sc.lines), 'ready': len(jobs), 'errors': len(errors),
                        'render': len(todo), 'reuse': sum(1 for _, a, _ in plan.values() if a == 'reuse'),
                        'cached': sum(1 for _, a, _ in plan.values() if a == 'cached'),
                        'flagged': sum(1 for ln in sc.lines if ln.flags),
                        'estimate_s': round(est * render_mod.RENDER_FACTOR)},   # the model is already loaded
        }

    def _rel(self, p):
        try:
            return Path(os.path.relpath(p, self.path.parent)).as_posix() + '/'
        except ValueError:                  # another drive (Windows)
            return str(p)

    def _line(self, ln, sc, physical, defaults, cast_dirs, ramps, by_id, plan, line_errors):
        who = sc.aliases.get(ln.speaker)
        out = {'kind': 'line', 'lineno': ln.lineno, 'raw': physical[ln.lineno - 1], 'id': ln.id, 'flags': ln.flags,
               'speaker': ln.speaker, 'who': who, 'direction': ln.direction, 'text': ln.text,
               'comments': ln.comments, 'errors': line_errors.get(ln.lineno, []), 'status': 'error'}
        ramp, rv, rd = ramps.get(id(ln), (None, None, None))
        if ramp:
            out['ramp'] = {'what': ramp.what, 'value': _num(rv) if rv is not None else None,
                           'a': ramp.a, 'b': ramp.b, 'for': sc.ramp_speaker(ramp)}
        try:
            own = styles.parse_direction(ln.direction)
        except ValueError:
            return out
        layers = [('@defaults', defaults), ('@cast', cast_dirs.get(who)), ('@ramp', rd), ('line', own)]
        try:
            merged = styles.merge(*[d for _, d in layers])
            res = styles.resolve(merged)
        except (ValueError, KeyError):
            return out
        style = merged.style or 'normal'
        style_src = next((k for k, d in reversed(layers) if d and d.style), 'default')
        effects = []
        for k, d in layers:
            for e in (d.effects if d else []):
                if e not in [x['name'] for x in effects]:
                    effects.append({'name': e, 'src': k})
        style_vals = styles.trance(merged.depth if merged.depth is not None else 0.5) if style == 'trance' \
            else styles.STYLES.get(style, {})
        settings = {}
        inv = {v: k for k, v in styles.SETTING_NAMES.items()}
        for k_eng, name in inv.items():
            srcs = [(k, d.settings[k_eng]) for k, d in layers if d and k_eng in d.settings]
            if name == 'volume':
                value = sum(v for _, v in srcs)
            elif name == 'rise':
                value = srcs[-1][1] if srcs else None
            else:
                value = res.get(k_eng, styles.DEFAULTS.get(k_eng, 0.0))
            if srcs:
                src = ' + '.join(k for k, _ in srcs) if k_eng in styles.ADDITIVE else srcs[-1][0]
                if k_eng in styles.ADDITIVE and style_vals.get(k_eng):
                    src += ' + style'           # pitch: the style's own shift adds to these
            elif name == 'rise':
                src = 'auto'
            else:
                src = 'style' if k_eng in style_vals else 'default'
            settings[name] = {'value': _num(value), 'src': src}
        plain = marks_mod.parse(ln.text).plain if not out['errors'] else ln.text
        out.update({
            'style': style, 'depth': _num(merged.depth) if merged.depth is not None else None,
            'style_src': style_src, 'own_style': own.style, 'own_depth': own.depth,
            'own_effects': own.effects, 'own_settings': {inv[k]: _num(v) for k, v in own.settings.items()},
            'effects': effects, 'settings': settings, 'level_db': _num(res['level_db']),
            'rises': [_num(r) for r in styles.question_rises(res, plain)],
            'layers': {k: (str(d) if d else '') for k, d in layers},
        })
        job = by_id.get(ln.id)
        if job and not out['errors'] and job.lineno == ln.lineno:
            key, action, src = plan[ln.id]
            out.update({'status': action, 'key': key, 'resolved': str(job.direction), 'spoken': job.text,
                        'clip': render_mod.clip_name(ln.id, key, self.fmt) if action == 'cached' else None})
        return out


class LockedEngine:
    """an Engine whose render() takes the shared lock, so a long render and previews can take turns"""

    def __init__(self, eng, lock):
        self._eng, self._lock = eng, lock

    def render(self, *a, **k):
        with self._lock:
            return self._eng.render(*a, **k)

    def __getattr__(self, name):
        return getattr(self._eng, name)


class Stopped(KeyboardInterrupt):
    """raised from the render log to stop between clips (render() saves its work on KeyboardInterrupt)"""


class Toolkit:
    def __init__(self, mixer, doc=None, start='script'):
        self.mixer = mixer
        self.doc = doc
        self.start = start if doc else 'voices'
        self.eng = mixer.eng
        self.lock = mixer.lock
        self.words_cache = {}
        self.job = {'running': False, 'log': [], 'done': 0, 'total': 0}
        self.stop = False

    def info(self, _):
        return {'start': self.start, 'script': self.doc.path.name if self.doc else None,
                'folder': self.doc.path.parent.name if self.doc else None}

    def need_doc(self):
        if not self.doc:
            raise ValueError('no script open (start with: jivetalker edit voice_script.txt)')
        return self.doc

    def _job(self, line_id):
        jobs, errors = self.need_doc().script().jobs(self.doc.voices_override)
        job = next((j for j in jobs if j.id == line_id), None)
        if not job:
            raise ValueError(f'{line_id} can\'t be rendered; fix its problems first')
        return job

    def preview(self, q):
        job = self._job(q['id'])
        with self.lock:
            t = time.time()
            r = self.eng.render(job.text, job.voice, job.direction, seed=job.seed)
            took = time.time() - t
        import soundfile as sf
        buf = io.BytesIO()
        sf.write(buf, r.audio, 24000, format='WAV', subtype='PCM_16')
        return {'audio': base64.b64encode(buf.getvalue()).decode('ascii'), 'seconds': round(len(r.audio) / 24000, 2),
                'took': round(took, 1),
                'unknown': r.unknown_words, 'unplaced': r.unplaced_marks}

    def words(self, q):
        """{ids: [...]} -> {id: [words the phonemizer can't read]} (cached by text)"""
        jobs, _ = self.need_doc().script().jobs(self.doc.voices_override)
        want = set(q.get('ids') or [])
        out = {}
        for j in jobs:
            if want and j.id not in want:
                continue
            if j.text not in self.words_cache:
                with self.lock:
                    toks = self.eng.tokenize(marks_mod.parse(j.text))
                self.words_cache[j.text] = [t.text for t in toks if t.unknown]
            out[j.id] = self.words_cache[j.text]
        return out

    # ------------------------------------------------------------------ rendering the script
    def render_start(self, q):
        doc = self.need_doc()
        if self.job['running']:
            raise ValueError('a render is already running')
        jobs, errors = doc.script().jobs(doc.voices_override)
        if errors:
            raise ValueError(f'{len(errors)} problem{"s" if len(errors) > 1 else ""} in the script: fix '
                             f'{"them" if len(errors) > 1 else "it"} first, so no line loses its clip')
        self.stop = False
        self.job = {'running': True, 'log': [], 'done': 0, 'total': 0, 'started': time.time()}

        def log(msg):
            self.job['log'] = (self.job['log'] + [msg])[-50:]
            m = re.match(r'\[(\d+)/(\d+)\]', msg)
            if m:
                self.job['done'], self.job['total'] = int(m.group(1)), int(m.group(2))
                if self.stop:
                    raise Stopped()
            elif msg.startswith('rendering '):
                m = re.match(r'rendering (\d+)', msg)
                self.job['total'] = int(m.group(1)) if m else 0

        def run():
            try:
                s = render_mod.render(jobs, doc.out, doc.fmt, engine=LockedEngine(self.eng, self.lock), log=log)
                s['by_speaker'] = dict(s['by_speaker'])
                self.job['summary'] = s
            except Exception as e:          # report it on the page; the server keeps running
                self.job['error'] = str(e)
            finally:
                self.job['running'] = False
                self.job['finished'] = time.time()

        threading.Thread(target=run, daemon=True).start()
        return self.job

    def render_status(self, _):
        return self.job

    def render_stop(self, _):
        self.stop = True
        return self.job

    def clip(self, name):
        doc = self.need_doc()
        m = render_mod.CLIP_RE.match(name)
        p = doc.out / name
        if not m or not p.is_file():
            return None, None
        return p.read_bytes(), AUDIO_TYPES[m.group(3)]


def serve(toolkit, port=8765, open_browser=True):
    mx = toolkit.mixer
    doc = lambda: toolkit.need_doc()
    post = {'/api/load': mx.load, '/api/render': mx.render, '/api/position': mx.position,
            '/api/variants': mx.variants, '/api/save': mx.save,
            '/api/script/edit': lambda q: doc().edit(q), '/api/script/text': lambda q: doc().save_text(q),
            '/api/script/preview': toolkit.preview, '/api/script/words': toolkit.words,
            '/api/script/render': toolkit.render_start, '/api/script/render/stop': toolkit.render_stop}
    get = {'/api/info': mx.info, '/api/toolkit': toolkit.info,
           '/api/script': lambda q: doc().model(),
           '/api/script/version': lambda q: {'version': version(doc().read())},
           '/api/script/render': toolkit.render_status}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, body, ctype):
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ('/', '/index.html'):
                self.send(200, PAGE.read_bytes(), 'text/html; charset=utf-8')
            elif path == '/mixer':
                from .mixer import PAGE as MIXER_PAGE
                self.send(200, MIXER_PAGE.read_bytes(), 'text/html; charset=utf-8')
            elif path.startswith('/clips/'):
                try:
                    body, ctype = toolkit.clip(unquote(path[len('/clips/'):]))
                except ValueError:
                    body = None
                if body is None:
                    self.send(404, b'not found', 'text/plain')
                else:
                    self.send(200, body, ctype)
            elif path in get:
                self.api(get[path], {})
            else:
                self.send(404, b'not found', 'text/plain')

        def do_POST(self):
            fn = post.get(urlparse(self.path).path)
            if not fn:
                return self.send(404, b'not found', 'text/plain')
            n = int(self.headers.get('Content-Length') or 0)
            try:
                q = json.loads(self.rfile.read(n) or b'{}')
            except ValueError:
                return self.send(400, b'bad json', 'text/plain')
            self.api(fn, q)

        def api(self, fn, q):
            try:
                out, code = fn(q), 200
            except Conflict:
                out, code = {'error': 'the file changed meanwhile', 'conflict': True, 'model': doc().model()}, 409
            except (ValueError, KeyError, TypeError, FileNotFoundError, RuntimeError) as e:
                out, code = {'error': str(e)}, 400
            self.send(code, json.dumps(out, ensure_ascii=False).encode('utf-8'), 'application/json')

    httpd = ThreadingHTTPServer(('127.0.0.1', port), H)
    url = f'http://127.0.0.1:{port}/'
    print(f'jivetalker: {url}  (Ctrl+C to stop)', flush=True)
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        httpd.server_close()
