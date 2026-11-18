"""Small helpers with no heavy imports (safe for script parsing and adapters)."""
import hashlib

# Kokoro stock voices: <language><f|m>_name (a = US, b = UK, e, f, h, i, j, p, z)
STOCK_PREFIXES = tuple(f'{l}{g}_' for l in 'abefhijpz' for g in 'fm')


def make_seed(*parts):
    """stable across runs and platforms (Python's hash() is salted per process)"""
    h = hashlib.sha256('\x1f'.join(str(p) for p in parts).encode('utf-8')).digest()
    return int.from_bytes(h[:8], 'little')


# Audio formats: name -> (soundfile format, subtype, file extension). 'ogg' is Ogg Opus (small, the default; web
# browsers play it). Many game engines and audio tools only read Ogg Vorbis from an .ogg: use 'vorbis' for
# those. Both write .ogg files.
FORMATS = {'ogg': ('OGG', 'OPUS', 'ogg'), 'vorbis': ('OGG', 'VORBIS', 'ogg'),
           'wav': ('WAV', 'PCM_16', 'wav'), 'flac': ('FLAC', 'PCM_16', 'flac')}
FORMAT_ALIASES = {'opus': 'ogg'}
FORMAT_CHOICES = ('ogg', 'opus', 'vorbis', 'wav', 'flac')


def format_name(fmt):
    """'ogg' | 'vorbis' | 'wav' | 'flac' for a name as written (case, a leading dot and 'opus' allowed)"""
    f = str(fmt).lower().lstrip('.')
    f = FORMAT_ALIASES.get(f, f)
    if f not in FORMATS:
        raise ValueError(f'unknown audio format "{fmt}": use ogg (Opus), vorbis, wav or flac')
    return f


def codec_available(fmt):
    """can this machine's soundfile/libsndfile write `fmt`?"""
    try:
        import soundfile as sf
        container, subtype, _ = FORMATS[format_name(fmt)]
        return subtype in sf.available_subtypes(container)
    except Exception:
        return False


def resolve_format(fmt='ogg', warn=print):
    """the format a render will write: `fmt`, or 'wav' when this machine can't write Ogg (Opus or Vorbis)"""
    fmt = format_name(fmt)
    if FORMATS[fmt][0] == 'OGG' and not codec_available(fmt):
        if warn:
            warn(f'jivetalker: this soundfile/libsndfile cannot write Ogg {FORMATS[fmt][1].title()}; '
                 'writing .wav instead')
        return 'wav'
    return fmt
