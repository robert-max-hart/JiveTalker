"""jivetalker command line.

    jivetalker preview "Close your [eyes](+)..." --voice voices/lee.pt --style "trance 0.6" -o x.ogg
    jivetalker preview --script voice_script.txt --line c1.e174 -o x.ogg
    jivetalker check voice_script.txt
    jivetalker render voice_script.txt --out voice/ [--dry-run] [--only "c1.e1*"] [--prune]
    jivetalker edit voice_script.txt                  edit a script in the browser (Script + Voices tabs)
    jivetalker edit [--demo]                          no script: create or open one in the page (or try the demo)
    jivetalker mixer --voices-dir voices/ [--script voice_script.txt]     blend and tune voices in the browser
    jivetalker voice recipe voices/mara.pt           print (and with --write, save) the stock blend it is made of
    jivetalker voice build voices/mara.recipe.json   rebuild a .pt from its recipe
    jivetalker sing song.abc|song.musicxml --voice af_bella -o song.wav [--check] [--json r.json]   (experimental)
"""
import argparse
import sys
import time
from pathlib import Path

from .common import FORMAT_CHOICES


def report(errors, label):
    for n, msg in errors:
        print(f'  {label}:{n}: {msg}' if n else f'  {label}: {msg}')


def cmd_preview(a):
    from .engine import Engine, write
    job = None
    if a.script:
        from .script import Script
        jobs, errors = Script.load(a.script).jobs(a.voices_dir)
        job = next((j for j in jobs if j.id == a.line), None)
        if not job:
            report(errors, a.script)
            sys.exit(f'jivetalker: no usable line "{a.line}" in {a.script}')
        if a.style:
            from . import styles
            job.direction = styles.merge(job.direction, styles.parse_direction(a.style))
        text, voice, direction, seed = job.text, job.voice, job.direction, job.seed
        print(f'{job.id}  {job.speaker} {{{job.direction}}}: {job.text}')
    else:
        if not a.text or not a.voice:
            sys.exit('jivetalker preview: give TEXT and --voice, or --script and --line')
        text, voice, direction, seed = a.text, a.voice, a.style, a.seed
        if a.voices_dir and not Path(voice).suffix and not Path(voice).exists():
            voice = str(Path(a.voices_dir) / f'{voice}.pt')
    t0 = time.time()
    eng = Engine(model_dir=a.model_dir)
    t1 = time.time()
    r = eng.render_job(job) if a.script else eng.render(text, voice, direction, seed=seed)
    out = write(a.output, r.audio, a.format)
    print(f'{out}: {len(r.audio) / 24000:.1f} s  (model load {t1 - t0:.0f} s, render {time.time() - t1:.1f} s)')
    if a.verbose:
        print('phonemes:', r.phonemes)
    for w in r.unknown_words:
        print(f'  ! the phonemizer could not read "{w}": respell it, e.g. [{w}](/.../)')
    for w in r.unplaced_marks:
        print(f'  ! the mark on "{w}" did not land on a word')


def cmd_sing(a):
    import numpy as np
    from . import __version__, sing
    from .engine import Engine, write
    song = sing.load(a.song, transpose=a.transpose, part=a.part, voice=a.voice_number, verse=a.verse)
    if Path(a.song).suffix.lower() in ('.musicxml', '.xml', '.mxl'):
        parts = sing.musicxml_parts(Path(a.song).read_bytes())
        if len(parts) > 1 or any(len(v) > 1 for _, _, v in parts):
            print('parts: ' + '; '.join(f'{i + 1} = {pid} {name} (voices with lyrics: {", ".join(v) or "none"})'
                                        for i, (pid, name, v) in enumerate(parts)))
    sung = [n for n in song.notes if n.midi is not None]
    lo, hi = min(n.hz for n in sung), max(n.hz for n in sung)
    print(f'{len(sung)} notes, {lo:.0f}-{hi:.0f} Hz, {sum(1 for x in song.lyrics if x)} syllables')
    if a.dry_run:                               # no model: which syllable goes on which note
        notes, last = [], None
        for k, n in enumerate(sung):
            syl = song.lyrics[k][0] if song.lyrics[k] else None
            last = syl or last
            notes.append({'index': k, 'note': sing.note_name(n.midi), 'midi': n.midi, 'start': round(n.start, 3),
                          'length': round(n.length, 3), 'syllable': syl, 'held': syl is None})
            print(f'  {sing.note_name(n.midi):4s} at {n.start:6.2f} s, {n.length:.2f} s: '
                  + (syl if syl else f'(holds {last})' if last else '(unsung)'))
        if a.json:
            import json
            Path(a.json).write_text(json.dumps({'jivetalker': __version__, 'song': str(a.song), 'dry_run': True,
                                                'words': song.words, 'notes': notes}, ensure_ascii=False, indent=1),
                                    encoding='utf-8')
        return
    eng = Engine(model_dir=a.model_dir)
    band = None
    if a.band == 'auto':
        band = sing.safe_band(sing.probe_range(eng, a.voice))
    elif a.band != 'off':
        try:
            band = tuple(int(x) for x in a.band.split('-'))
        except ValueError:
            sys.exit('jivetalker sing: --band is auto, off, or two MIDI notes such as 50-62')
    if band:
        out_of = [n for n in sung if not band[0] <= n.midi <= band[1]]
        print(f'{a.voice} sings {sing.note_name(band[0])}-{sing.note_name(band[1])} by itself'
              + (f'; {len(out_of)} notes outside it are shifted (PSOLA)' if out_of else ''))
    elif hi > sing.CEILING_HZ:
        print(f'  ! notes above ~{sing.CEILING_HZ:.0f} Hz tend to drop an octave or lose their voice (try --band auto)')
    t0 = time.time()
    audio, phrases = sing.sing(eng, song, a.voice, lang=a.lang, seed=a.seed, band=band)
    out = write(a.output, audio, a.format)
    print(f'{out}: {len(audio) / 24000:.1f} s  (render {time.time() - t0:.1f} s)')
    if a.verbose:
        for ps in phrases:
            print('phrase:', ps)
    report = {'jivetalker': __version__, 'song': str(a.song), 'voice': a.voice, 'output': str(out),
              'seconds': round(len(audio) / 24000, 2), 'transpose': a.transpose,
              'band': {'low': band[0], 'high': band[1], 'low_name': sing.note_name(band[0]),
                       'high_name': sing.note_name(band[1])} if band else None,
              'shifted_notes': sum(1 for n in sung if band and not band[0] <= n.midi <= band[1]),
              'phrases': phrases}
    if a.check or a.json:
        res = sing.measure(audio, song)
        notes = []
        for k, (n, m) in enumerate(zip(sung, res)):
            c, on = m['cents'], m['onset_ms']
            bad = c is None or abs(c) > 50 or (on is not None and abs(on) > 60 and not m['after_rest'])
            notes.append({'index': k, 'note': sing.note_name(n.midi), 'midi': n.midi, 'start': round(n.start, 3),
                          'length': round(n.length, 3), 'syllable': song.lyrics[k][0] if song.lyrics[k] else None,
                          'cents': None if c is None else round(c, 1), 'voiced': round(m['voiced'], 3),
                          'onset_ms': None if on is None else round(on, 1), 'after_rest': m['after_rest'],
                          'ok': not bad})
            if not a.check:
                continue
            when = ('arrives   ?   ' if on is None else f'starts  {on:+4.0f} ms (after a rest)' if m['after_rest']
                    else f'arrives {on:+4.0f} ms')
            print(f'  {sing.note_name(n.midi):4s} at {n.start:6.2f} s: '
                  + (f'{c:+5.0f} cents' if c is not None else 'unvoiced   ') + f', voiced {m["voiced"]:4.0%}, '
                  + when + ('   <-' if bad else ''))
        ok = [abs(m['cents']) for m in res if m['cents'] is not None]
        ons = [abs(m['onset_ms']) for m in res if m['onset_ms'] is not None and not m['after_rest']]
        off = sum(m['cents'] is None or abs(m['cents']) > 50 for m in res)
        report['notes'] = notes
        report['summary'] = {
            'notes': len(res), 'notes_off_pitch': off, 'bad_notes': [x['index'] for x in notes if not x['ok']],
            'pitch_median_cents': round(float(np.median(ok)), 1) if ok else None,
            'timing_median_ms': round(float(np.median(ons)), 1) if ons else None,
            'timing_worst_ms': round(float(max(ons)), 1) if ons else None,
            'ok': all(x['ok'] for x in notes)}
        if ok and a.check:
            print(f'  pitch: median {np.median(ok):.0f} cents off; '
                  f'{sum(m["cents"] is None or abs(m["cents"]) > 50 for m in res)} of {len(res)} notes off by more '
                  f'than 50 cents or unvoiced')
        if ons and a.check:
            print(f'  timing of pitch changes: median {np.median(ons):.0f} ms from the beat, worst {max(ons):.0f} ms '
                  f'({len(ons)} notes; the measure is good to ~10 ms, less next to consonants)')
    if a.guide:
        g = sing.guide(song)
        gp = write(Path(out).with_name(Path(out).stem + '_guide' + Path(out).suffix), g, a.format)
        n = max(len(g), len(audio))
        mix = np.zeros(n, np.float32)
        mix[:len(audio)] += audio; mix[:len(g)] += 0.5 * g
        mp = write(Path(out).with_name(Path(out).stem + '_mix' + Path(out).suffix), mix / max(1.0, np.abs(mix).max()),
                   a.format)
        print(f'{gp}, {mp}: the melody as tones, and mixed under the voice')
        report['guide'], report['mix'] = str(gp), str(mp)
    if a.json:
        import json
        Path(a.json).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
        print(f'{a.json}: report (per note: pitch in cents, voicing, arrival vs the beat)')


def cmd_check(a):
    from collections import Counter
    from .script import Script
    sc = Script.load(a.script)
    jobs, errors = sc.jobs(a.voices_dir)
    flagged = [ln for ln in sc.lines if ln.flags]
    print(f'{a.script}: {len(sc.lines)} lines, {len(jobs)} ready')
    for who, n in Counter(j.speaker for j in jobs).most_common():
        print(f'  {n:5}  {who}')
    styled = Counter('sung' if j.song else (j.direction.style or 'normal') for j in jobs)
    print('  styles: ' + ', '.join(f'{k} {v}' for k, v in styled.most_common()))
    if flagged:
        print(f'{len(flagged)} flagged for review:')
        for ln in flagged:
            print(f'  {a.script}:{ln.lineno}: {ln.id} !{" !".join(ln.flags)}')
    if errors:
        print(f'{len(errors)} problems:')
        report(errors, a.script)
        sys.exit(1)


def cmd_render(a):
    from .script import Script
    from .render import render, print_summary
    sc = Script.load(a.script)
    jobs, errors = sc.jobs(a.voices_dir)
    if errors:
        print(f'{len(errors)} problems in the script (fix them, or they are skipped):')
        report(errors, a.script)
        if not a.keep_going:
            sys.exit('jivetalker: nothing rendered (use --keep-going to render the good lines anyway)')
    out = Path(a.out) if a.out else Path(a.script).parent / 'voice'
    s = render(jobs, out, a.format or sc.audio_format or 'ogg', a.dry_run, a.prune, a.only, a.model_dir)
    print_summary(s, dry_run=a.dry_run)
    print(f'clips: {out}')


def start_toolkit(a, script, start):
    from .mixer import Mixer
    from .toolkit import ScriptDoc, Toolkit, serve
    dirs = list(a.voices_dir or [])
    doc = None
    if script:
        if not Path(script).is_file():
            sys.exit(f'jivetalker: no such script: {script}')
        from .script import Script
        own = Script.load(script).voices_dir()        # the script's own @voices folder comes first
        if own.is_dir() and own.resolve() not in [Path(d).resolve() for d in dirs]:
            dirs.insert(0, str(own))
    m = Mixer(dirs, a.save_dir or (dirs[0] if dirs else None), script, a.model_dir)
    if script:
        doc = ScriptDoc(script, None, getattr(a, 'out', None), getattr(a, 'format', None), m.source_for)
    serve(Toolkit(m, doc, start, Path.cwd(), getattr(a, 'format', None), bool(a.save_dir)),
          a.port, not a.no_browser)


def cmd_mixer(a):
    start_toolkit(a, a.script, 'voices')


def cmd_edit(a):
    script = a.script
    if a.demo:
        from .toolkit import demo_script
        script = str(demo_script())
    start_toolkit(a, script, 'script')


def cmd_voice(a):
    import json
    from .engine import Engine
    from . import voicelab
    lab = voicelab.Lab(Engine(model_dir=a.model_dir))
    if a.action == 'recipe':
        r, fits = lab.decompose(a.file)
        print(json.dumps(voicelab.clean(r), indent=2))
        for h, f in fits.items():
            print(f'  {h}: ' + ('exact stock blend' if f < 1e-4 else f'not a stock blend (closest misses by {f:.0%})'))
        if a.write:
            out = voicelab.recipe_path(a.file)
            if out.exists() and not a.force:
                sys.exit(f'jivetalker: {out} exists (use --force to replace it)')
            out.write_text(json.dumps(voicelab.clean(r), indent=2) + '\n', encoding='utf-8')
            print(f'wrote {out}')
    else:
        src = Path(a.file)
        out = Path(a.output) if a.output else src.with_name(src.name.replace('.recipe.json', '') + '.pt')
        if out.exists() and not a.force:
            sys.exit(f'jivetalker: {out} exists (use -o for another name, or --force)')
        pack = lab.build(voicelab.load_recipe(src), base=src.parent)
        lab.torch.save(pack, str(out))
        print(f'wrote {out}')


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')     # Windows consoles default to a legacy code page
    p = argparse.ArgumentParser(prog='jivetalker', description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--model-dir', help='local Kokoro model folder (config.json + .pth) for offline use')
    sub = p.add_subparsers(dest='cmd', required=True)
    pv = sub.add_parser('preview', help='render one line')
    pv.add_argument('text', nargs='?')
    pv.add_argument('--voice', help='.pt file, a name in --voices-dir, or a stock voice (af_nicole)')
    pv.add_argument('--voices-dir')
    pv.add_argument('--style', default='', help='direction, e.g. "trance 0.6, internal, pause 2" '
                                                '(with --script: added on top of the line\'s own)')
    pv.add_argument('--script', help='voice script to take the line from')
    pv.add_argument('--line', help='ID of the line in --script')
    pv.add_argument('--seed', type=int, default=0)
    pv.add_argument('-o', '--output', default='preview.ogg')
    pv.add_argument('--format', choices=FORMAT_CHOICES,
                    help='audio format: ogg (Ogg Opus), vorbis (Ogg Vorbis), wav, flac (default: from -o, where .ogg '
                         'is Opus; Ogg falls back to wav if this machine can\'t write it)')
    pv.add_argument('-v', '--verbose', action='store_true')
    pv.set_defaults(func=cmd_preview)
    ck = sub.add_parser('check', help='parse a voice script and report problems')
    ck.add_argument('script')
    ck.add_argument('--voices-dir', help='overrides the script\'s @voices')
    ck.set_defaults(func=cmd_check)
    rd = sub.add_parser('render', help='render every line of a voice script (cached)')
    rd.add_argument('script')
    rd.add_argument('--out', help='clip folder (default: voice/ next to the script)')
    rd.add_argument('--voices-dir', help='overrides the script\'s @voices')
    rd.add_argument('--format', choices=FORMAT_CHOICES, help='audio format: ogg (Ogg Opus), vorbis (Ogg Vorbis, for game engines that need it), wav, flac (default: the script\'s @format, else ogg)')
    rd.add_argument('--only', action='append', help='IDs or patterns, e.g. "c1.e1*" (repeatable, comma-separated)')
    rd.add_argument('--dry-run', action='store_true', help='show what would be rendered and how long it would take')
    rd.add_argument('--prune', action='store_true', help='delete clips no line uses any more')
    rd.add_argument('--keep-going', action='store_true', help='render the good lines even if some have errors')
    rd.set_defaults(func=cmd_render)
    mx = sub.add_parser('mixer', help='blend and tune voices in the browser')
    mx.add_argument('--voices-dir', action='append', help='a folder of your .pt voices (repeatable)')
    mx.add_argument('--save-dir', help='where Save writes (default: the first --voices-dir)')
    mx.add_argument('--script', help='a voice script whose lines can be picked as test text')
    mx.add_argument('--port', type=int, default=8765)
    mx.add_argument('--no-browser', action='store_true')
    mx.set_defaults(func=cmd_mixer)
    ed = sub.add_parser('edit', help='edit a voice script in the browser (with the voice mixer in another tab)')
    ed.add_argument('script', nargs='?', help='the voice script (none: create or open one in the page)')
    ed.add_argument('--demo', action='store_true', help='open your copy of the demo script (made in '
                                                        'jivetalker_demo/ under the current folder on first use)')
    ed.add_argument('--voices-dir', action='append', help='more folders of .pt voices for the mixer (repeatable; '
                                                          'the script\'s @voices folder is always included)')
    ed.add_argument('--save-dir', help='where the mixer saves (default: the script\'s @voices folder)')
    ed.add_argument('--out', help='clip folder for Render (default: voice/ next to the script)')
    ed.add_argument('--format', choices=FORMAT_CHOICES, help='audio format: ogg (Ogg Opus), vorbis (Ogg Vorbis, for game engines that need it), wav, flac for Render (default: the script\'s @format, else ogg)')
    ed.add_argument('--port', type=int, default=8765)
    ed.add_argument('--no-browser', action='store_true')
    ed.set_defaults(func=cmd_edit)
    vo = sub.add_parser('voice', help='voice recipes: recover one from a .pt, or build a .pt from one')
    vo.add_argument('action', choices=('recipe', 'build'))
    vo.add_argument('file', help='recipe: a .pt file; build: a .recipe.json file')
    vo.add_argument('-o', '--output', help='build: the .pt to write (default: next to the recipe)')
    vo.add_argument('--write', action='store_true', help='recipe: save it as <name>.recipe.json next to the .pt')
    vo.add_argument('--force', action='store_true', help='replace an existing output file')
    vo.set_defaults(func=cmd_voice)
    sg = sub.add_parser('sing', help='sing a melody (ABC notation with a w: lyric line); experimental')
    sg.add_argument('song', help='an .abc file (see jivetalker/sing.py for the subset understood), or a MusicXML '
                                 'score (.musicxml, .xml, .mxl) as notation programs export it')
    sg.add_argument('--part', help='MusicXML: the part to sing (number, id or name; default: the first with lyrics)')
    sg.add_argument('--voice-number', dest='voice_number',
                    help='MusicXML: the voice within the part (default: the first with lyrics)')
    sg.add_argument('--verse', type=int, default=1, help='MusicXML: which lyric line (default 1)')
    sg.add_argument('--voice', required=True, help='.pt file or a stock voice')
    sg.add_argument('--lang', help='the lyric\'s language (default en)')
    sg.add_argument('--transpose', type=int, default=0, help='semitones (e.g. -12 for a low voice)')
    sg.add_argument('--band', default='auto', help='notes the voice sings by itself; outside them PSOLA shifts: '
                                                   'auto (measured once per voice, cached, with a safety margin), off, or MIDI LOW-HIGH')
    sg.add_argument('--check', action='store_true', help='pitch-track the result and report each note')
    sg.add_argument('--dry-run', action='store_true', help='only show which syllable goes on which note (fast, '
                                                          'no model)')
    sg.add_argument('--json', metavar='PATH', help='write a machine-readable report (files, band, phonemes, and the '
                                                   'per-note check) to PATH, e.g. for scripts and AI agents')
    sg.add_argument('--seed', type=int, default=0)
    sg.add_argument('--guide', action='store_true', help='also write the melody as tones, alone and mixed')
    sg.add_argument('-o', '--output', default='song.wav')
    sg.add_argument('--format', choices=FORMAT_CHOICES, help='audio format: ogg (Ogg Opus), vorbis (Ogg Vorbis, for game engines that need it), wav, flac')
    sg.add_argument('-v', '--verbose', action='store_true')
    sg.set_defaults(func=cmd_sing)
    a = p.parse_args(argv)
    try:
        a.func(a)
    except (ValueError, FileNotFoundError) as e:
        sys.exit(f'jivetalker: {e}')


if __name__ == '__main__':
    main()
