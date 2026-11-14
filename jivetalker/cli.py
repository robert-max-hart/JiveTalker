"""jivetalker command line.

    jivetalker preview "Close your [eyes](+)..." --voice voices/lee.pt --style "trance 0.6" -o x.ogg
    jivetalker preview --script voice_script.txt --line c1.e174 -o x.ogg
    jivetalker check voice_script.txt
    jivetalker render voice_script.txt --out voice/ [--dry-run] [--only "c1.e1*"] [--prune]
    jivetalker edit voice_script.txt                  edit a script in the browser (Script + Voices tabs)
    jivetalker mixer --voices-dir voices/ [--script voice_script.txt]     blend and tune voices in the browser
    jivetalker voice recipe voices/mara.pt           print (and with --write, save) the stock blend it is made of
    jivetalker voice build voices/mara.recipe.json   rebuild a .pt from its recipe
    jivetalker sing song.abc --voice af_bella -o song.wav [--transpose -12] [--guide]   (experimental)
"""
import argparse
import sys
import time
from pathlib import Path


def report(errors, label):
    for n, msg in errors:
        print(f'  {label}:{n}: {msg}' if n else f'  {label}: {msg}')


def cmd_preview(a):
    from .engine import Engine, write
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
    r = eng.render(text, voice, direction, seed=seed)
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
    from . import sing
    from .engine import Engine, write
    song = sing.parse_abc(Path(a.song).read_text(encoding='utf-8'), transpose=a.transpose)
    sung = [n for n in song.notes if n.midi is not None]
    lo, hi = min(n.hz for n in sung), max(n.hz for n in sung)
    print(f'{len(sung)} notes, {lo:.0f}-{hi:.0f} Hz, {sum(1 for x in song.lyrics if x)} syllables')
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
    if a.check:
        res = sing.measure(audio, song)
        for n, (c, share) in zip(sung, res):
            mark = '' if c is not None and abs(c) <= 50 else '   <-'
            print(f'  {sing.note_name(n.midi):4s} at {n.start:6.2f} s: '
                  + (f'{c:+5.0f} cents' if c is not None else 'unvoiced   ') + f', voiced {share:4.0%}{mark}')
        ok = [abs(c) for c, _ in res if c is not None]
        if ok:
            print(f'  median {np.median(ok):.0f} cents off; {sum(c is None or abs(c) > 50 for c, _ in res)} of '
                  f'{len(res)} notes off by more than 50 cents or unvoiced')
    if a.guide:
        g = sing.guide(song)
        gp = write(Path(out).with_name(Path(out).stem + '_guide' + Path(out).suffix), g, a.format)
        n = max(len(g), len(audio))
        mix = np.zeros(n, np.float32)
        mix[:len(audio)] += audio; mix[:len(g)] += 0.5 * g
        mp = write(Path(out).with_name(Path(out).stem + '_mix' + Path(out).suffix), mix / max(1.0, np.abs(mix).max()),
                   a.format)
        print(f'{gp}, {mp}: the melody as tones, and mixed under the voice')


def cmd_check(a):
    from collections import Counter
    from .script import Script
    sc = Script.load(a.script)
    jobs, errors = sc.jobs(a.voices_dir)
    flagged = [ln for ln in sc.lines if ln.flags]
    print(f'{a.script}: {len(sc.lines)} lines, {len(jobs)} ready')
    for who, n in Counter(j.speaker for j in jobs).most_common():
        print(f'  {n:5}  {who}')
    styled = Counter(j.direction.style or 'normal' for j in jobs)
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
    s = render(jobs, out, a.format, a.dry_run, a.prune, a.only, a.model_dir)
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
        doc = ScriptDoc(script, None, getattr(a, 'out', None), getattr(a, 'format', None) or 'ogg', m.source_for)
    serve(Toolkit(m, doc, start), a.port, not a.no_browser)


def cmd_mixer(a):
    start_toolkit(a, a.script, 'voices')


def cmd_edit(a):
    start_toolkit(a, a.script, 'script')


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
    pv.add_argument('--format', choices=('ogg', 'wav', 'flac'),
                    help='audio format (default: from -o; ogg falls back to wav if Opus is unavailable)')
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
    rd.add_argument('--format', default='ogg', choices=('ogg', 'wav', 'flac'))
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
    ed.add_argument('script')
    ed.add_argument('--voices-dir', action='append', help='more folders of .pt voices for the mixer (repeatable; '
                                                          'the script\'s @voices folder is always included)')
    ed.add_argument('--save-dir', help='where the mixer saves (default: the script\'s @voices folder)')
    ed.add_argument('--out', help='clip folder for Render (default: voice/ next to the script)')
    ed.add_argument('--format', default='ogg', choices=('ogg', 'wav', 'flac'))
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
    sg.add_argument('song', help='an .abc file: see jivetalker/sing.py for the subset understood')
    sg.add_argument('--voice', required=True, help='.pt file or a stock voice')
    sg.add_argument('--lang', help='the lyric\'s language (default en)')
    sg.add_argument('--transpose', type=int, default=0, help='semitones (e.g. -12 for a low voice)')
    sg.add_argument('--band', default='auto', help='notes the voice sings by itself; outside them PSOLA shifts: '
                                                   'auto (measured once per voice, cached, with a safety margin), off, or MIDI LOW-HIGH')
    sg.add_argument('--check', action='store_true', help='pitch-track the result and report each note')
    sg.add_argument('--seed', type=int, default=0)
    sg.add_argument('--guide', action='store_true', help='also write the melody as tones, alone and mixed')
    sg.add_argument('-o', '--output', default='song.wav')
    sg.add_argument('--format', choices=('ogg', 'wav', 'flac'))
    sg.add_argument('-v', '--verbose', action='store_true')
    sg.set_defaults(func=cmd_sing)
    a = p.parse_args(argv)
    try:
        a.func(a)
    except (ValueError, FileNotFoundError) as e:
        sys.exit(f'jivetalker: {e}')


if __name__ == '__main__':
    main()
