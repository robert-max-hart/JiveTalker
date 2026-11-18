# Voice scripts

A voice script is a plain text file with one line per voice clip. You direct the delivery by hand: a style
and settings in `{…}` after the speaker, and marks on single words. Write the script from scratch, or
have your game's own tooling generate it (IDs are any text, so they can point back at your game's events).

```
# Voice script: Demo story.
@voices ../voices
@cast narrator = base_narrator
@cast Mara = mara
@cast Mara (thought) = mara {internal}
@cast Doctor Lee = lee | ???
@defaults speed 0.95, human 1.0

== Chapter 1: The Visit ==

c1.e3    Mara (thought): But what if nobody comes back?
c1.e62   Doctor Lee {pause 1.5}: And have you ever [wanted](+) to leave, or start over?
# she hesitates here
c1.e117  Mara {deep, take 2}: It... it does feel calm, but I don’t know if it’s really [more](+) calm…

@ramp trance 0.2 -> 1.0
c1.e170  Doctor Lee: Let everything else fade away…
c1.e174  Doctor Lee {pause 2.2}: Now... Mara... close your [eyes](+~)...
@end
```

## Lines

`ID  [!flags]  Speaker {direction}: text`

- **ID**: any text without spaces, unique in the file. Clips are named after it.
- **!flags**: notes for review, such as `!changed`. They don't change the sound; delete them once you've
  checked the line.
- **Speaker**: a name from a `@cast` line, or one of its aliases.
- **{direction}**: optional; see below.
- **text**: what is spoken, with optional word marks.
- `#` starts a comment. A comment directly above a line belongs to that line. `== Title ==` is a heading
  for reading only.

## Header

| Line | Meaning |
|---|---|
| `@voices ../voices` | the folder that voice names are looked up in, relative to the script |
| `@cast Name = voice` | which voice a speaker uses: a name in `@voices` (`mara` → `mara.pt`), a path to a `.pt`, or a Kokoro stock voice (`af_nicole`) |
| `@cast Name = voice {direction}` | a default direction for everything this speaker says |
| `@defaults direction` | a default direction for every line |
| `@pronounce Mara = /mˈɑɹə/` | say this word this way in every line, unless that occurrence already has a mark (a mark holds either a stress or a respelling). Possessives ("Mara’s") aren't touched |

Other names for the same speaker go after the voice, separated by bars, so lines spoken by `???` use
Doctor Lee's voice:

    @cast Doctor Lee = lee | ??? {pitch 1}

**To change a voice**, replace its `.pt` file or point the `@cast` line at a new one. A rebuild then
redoes that speaker's lines.

## Directions

A direction is a comma-separated list: at most one **style**, any **effects**, and any **settings**.

| Style | Sound |
|---|---|
| `normal` | the voice as it is |
| `trance 0.6` | slower, lower and flatter, with longer pauses. Depth 0 is light, 1 is deepest |
| `deep` | dead-flat, slow monotone, for very deep trance and mantras |
| `shout` | higher and livelier |
| `soft` | quiet and gentle: the speaker's own voice, a little lower, with a trace of whisper mixed in (`breath 0.15`) |
| `whisper` | breathy whisper, modelled on a real one |

| Effect | Sound |
|---|---|
| `internal` | a light echo, for thoughts |
| `muffled` | heard through a door or wall: the highs cut away, a little room. It keeps normal loudness, so add `volume` for distance |

| Setting | Meaning | Default |
|---|---|---|
| `speed 0.9` | the speaker's base speed; a style scales it | 0.95 |
| `pitch 2` | semitones up (negative = down), added to the style's | 0 |
| `range 0.5` | pitch movement: 0 = flat, 1 = natural, above 1 = livelier | from style |
| `pause 2` | multiplies the pauses at punctuation inside a line (comma ≈ 0.18 s, `;` `:` dash ≈ 0.28 s, sentence end ≈ 0.42 s, `…` ≈ 0.55 s at `pause 1`) | from style |
| `drift 1` | semitones of slow fall across the line | from style |
| `volume -3` | dB, added to the style's level | 0 |
| `human 0.5` | natural variation in timing and pitch: 0 = none, 1 = default | 1.0 |
| `take 2` | a different variation of the same line; try takes until one sounds right | 0 |
| `floor 0.55` | ends voicing cleanly when pitch sags (cures growl at line ends) | from style |
| `rise 5` | semitones of question rise on the word before each `?`: level at first, then sharp. Kokoro says questions like statements, so they rise automatically: one-word questions ("Mara?", "Twenty?") by 5, longer ones by 3, except when a clause starts with who/what/when/where/why/how/which (those fall). Setting `rise` applies it to every question in the line; `rise 0` turns it off | auto |
| `breath 0.5` | mixes the speaker's own whisper into the voice: 0 = none, 1 = all whisper. Not for `whisper` itself | 0 (`soft`: 0.15) |
| `lang ja` | the language the line is in: `en` or `ja` (see [Languages](#languages)). Can't be ramped | `en` |
| `sing songs/x.musicxml` | the line is sung from this score (see [Sung lines](#sung-lines)). Can't be ramped | |

Directions combine in this order: `@defaults`, then the speaker's `@cast` direction, then a ramp, then the
line's own. A later style replaces an earlier one, settings replace earlier settings (except `pitch` and
`volume`, which add up, so `@cast Doctor Lee = lee {pitch 1}` shifts every Lee line), and effects add up.

## Word marks

| Mark | Effect |
|---|---|
| `[word](+)` | stress: a pitch lift that eases down across the word, a little louder and longer |
| `[word](++)` | strong stress |
| `[word](-)` | de-stress: lower, quieter and a little shorter |
| `[word](--)`, `[word](---)` | stronger de-stress (three is the limit: shorter still and Kokoro starts swallowing sounds) |
| `[word](~)`, `[word](~~)` | drawn out: ×1.25, ×1.5 the word's length (`~~~` ×1.75, `~~~~` ×2, `~~~~~` ×2.5) |
| `[word](<)`, `[word](<<)`, `[word](<<<)` | shortened: no sound of the word lasts longer than 0.15 s, 0.10 s, 0.07 s (at speed 1; slower speeds allow a little more). For a word the model drags out, usually a held last vowel that fades into silence and leaves a gap mid-phrase ("the blurry … ceiling"). `<` and `<<` only touch the over-long sound; ordinary sounds last 0.05-0.10 s, so `<<<` starts trimming those too, and three is the limit. Doesn't combine with `~`; the line's last sound isn't shortened |
| `[word](+++)` … `(+++++)`, `(~~~)` … `(~~~~~)` | more of the same: up to five of each stack (they combine too, `(+++~~~)`). Levels 3-5 are untuned extremes that may distort; each lifts the pitch more, louder and longer, and allows a bigger lift and longer sounds than levels 1-2 |
| `[word](^1.5)`, `[word](^-2)` | shift the word's pitch by that many semitones, nothing else |
| `[word](^2>-1)` | shape the pitch across the word: start 2 semitones up, glide to 1 down. Add points for more: `^0>3>0` rises in the middle and comes back. On several words (`[very carefully](^2>-1)`) the shape spans them all. It adds to the word's own melody and to any stress |
| `[word](+~)` | marks combine; all of them do (see the pause examples below) |
| `[Siobhan](/ʃɪvˈɔn/)` | pronounce it this way (IPA, Kokoro/misaki symbols) |
| `[Dr.](=Doctor)` | say different words; the text on screen stays the same. `[um](=)` makes a word silent |

**Pauses** after a word use bars (`|`) in the mark:

    [word](|)          a 0.2 s pause after the word
    [word](||)         0.4 s; each bar adds 0.2 s, up to five: [word](|||||) = 1.0 s
    [word](|0.8)       exactly 0.8 s (up to 5 s)
    [word](++^2>0||)   strong stress, gliding from 2 semitones up to level, then a 0.4 s pause

Bar pauses scale with `{pause}` and don't vary at random like punctuation pauses; `|0.8` is exact. Nothing
shows on screen. A pause after a line's last word has no effect. The word before the pause also gets
about 0.06 s longer, as it does before a comma.

Brackets can hold several words: `[you must](+)`. **Change how a line sounds with marks only**, and leave
the words themselves alone. If the plain text differs from the game's text, the line no longer matches
and is treated as changed.

Each line is checked for words the phonemizer couldn't read; respell those with `(/…/)`.

## Ramps

```
@ramp trance 0.2 -> 1.0
…lines…
@end
```

A ramp gradually changes a style or setting across the lines of one speaker: by default the first line's
speaker, or name one with `@ramp trance 0.2 -> 1.0 for Doctor Lee`. Other speakers' lines in between
are untouched. Ramps work on `trance` or any setting, for example `@ramp speed 1.0 -> 0.8`. A line's own
style wins over the ramp, but a line with only settings (such as `{pause 2.2}`) keeps the ramp's style.

## Languages

Lines are English unless a direction says otherwise. Put `lang` where it fits: `@defaults lang ja` for a
whole script, `@cast Kenji = jm_kumo {lang ja}` for one speaker, or `{lang ja}` on a single line. English
lines keep their clips: `lang` only enters the cache key when it isn't `en`.

The script format and the marks are the same in every language; what they do is the language's own rule.

**Japanese** (`lang ja`; stock voices `jf_alpha`, `jf_gongitsune`, `jf_nezumi`, `jf_tebukuro`, `jm_kumo`).
It needs an extra install (see the README). Its stress and question values are **first guesses, not yet
tuned by ear**.

- Mark words as usual: `さあ、[目](+)を閉じて…[深く](++||)息を吸って。` Brackets must be ASCII `[ ]( )`.
- `+` / `-` lift or lower the word's pitch and make it a little louder or quieter. They keep the word's own
  pitch accent, and don't make it longer: vowel length changes meaning in Japanese. `~` still draws a word
  out, since there you ask for it.
- Every question with `？` or `?` rises (4 semitones, on the word before it, usually the particle);
  `rise` overrides it as in English.
- To give a reading, substitute kana: `[明日](=あした)` (the screen keeps 明日). `[ミラ](/miɾa/)` gives the
  phonemes directly.
- `@pronounce` matches a word anywhere, even inside a longer one (there are no spaces to tell words apart):
  `@pronounce ミラ` also changes ミラー. Mark single occurrences when that matters.
- Unlike stock Kokoro, `、` and `。` and the 「」 quotes are spoken as pauses: Kokoro's Japanese phonemizer
  drops them, which leaves no pause between sentences.

## Sung lines

```
s.2   Mara {sing songs/lullaby.musicxml}: Sleep now, little one
s.3   Lee {sing songs/round.abc verse=2 transpose=-12, internal}: Night falls.
```

`sing <file>` in a line's direction makes the line sung: the melody, rhythm and lyric come from the score (a
MusicXML file as notation programs export it, or ABC; the path is relative to the script). The line's text is
only what is shown on screen. Options, written after the file: `part=` and `voice=` (which line of a score with
several), `verse=` (which lyric line), `transpose=` (semitones), `band=` (`auto`, `off`, or MIDI notes such as
`50-62`: the notes the voice sings itself; outside them the pitch is shifted). Effects (`internal`, `muffled`)
and `volume` apply as to speech, `lang ja` sings Japanese lyrics; the other settings and styles don't apply.

The clip starts 0.3 s before the song's first beat. Changing the score re-renders only the lines that sing it.
The first sung line of a voice measures its singing range (about a minute, then cached). `jivetalker sing`
renders a score on its own, with a pitch and timing report (README, Singing).

## Commands

```
jivetalker check  voice_script.txt
jivetalker preview --script voice_script.txt --line c1.e174 -o x.ogg
jivetalker preview --script … --line c1.e174 --style "take 3"       # try a direction on top of the line's
jivetalker preview "Close your [eyes](+~)..." --voice voices/lee.pt --style "trance 0.6"
jivetalker render voice_script.txt --out clips/ [--dry-run] [--only "c1.e1*"] [--prune]
```

`render` renders every line into the clip folder and writes `manifest.json` (ID → file, duration). It only
renders what changed. Each clip's file name carries a key built from everything that affects its sound:
the voice file's contents, the resolved direction, the tuning constants that line uses, the text and marks,
and the variation seed. Renumbered lines reuse their old clips, and replacing a `.pt` rebuilds only that
voice's lines. `--dry-run` shows what would be rendered and roughly how long it would take. Ctrl-C is safe:
finished clips are kept, and the next run continues. `--prune` deletes clips no line uses any more.

`--format wav` (or `flac`) writes uncompressed audio. Ogg Opus is the default and falls back to `.wav` on
machines that can't write it.
