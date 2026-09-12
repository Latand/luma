# Built-in singing lessons

Three warm-ups ship with Luma and need no audio file, no separation and no network. `studio/luma-studio.sh` generates
them into the library on start when they are missing or stale (about nine seconds for all three, a no-op afterwards), so
a fresh clone opens Studio with an **«Уроки»** section above the library and three trainers ready to sing.

```sh
.venv/bin/python lessons/build_lessons.py                 # build what is missing or stale, into songs/
.venv/bin/python lessons/build_lessons.py --songs DIR      # into another library
.venv/bin/python lessons/build_lessons.py --force          # rebuild everything
.venv/bin/python lessons/build_lessons.py --definitions    # the definitions as JSON (tests/e2e/lessons.mjs reads this)
```

## The lessons

Every lesson is a classic warm-up: a pattern sung in one key, a breath rest, the same pattern a semitone higher, up to
the top key and back down. The guide voice sings the exact target melody; a struck piano chord opens each repetition, a
quiet root-and-fifth pad sits under it and a click marks every beat with the downbeat accented. One syllable per note
rides the melody in the lyric lane.

| | Урок 1 · Новачок | Урок 2 · Середній | Урок 3 · Експерт |
|---|---|---|---|
| suggested level | Легко (±80 ¢) | Звично (±50 ¢) | Точно (±35 ¢) |
| tempo | 70 BPM | 84 BPM | 110 BPM |
| length | 2:14 | 3:20 | 2:47 |
| range | C4–B4 | A3–D5 | G3–F♯5 |
| keys per exercise | 5 up and back (9 repetitions) | 6 up and back (11) | 5 up and back (9); 3 on the long note (5) |
| patterns | one held note on «ма»; scale 1-2-3-4-5-4-3-2-1 on «ма» | arpeggio 1-3-5-8-5-3-1 on «но»; thirds 1-3-2-4-3-5-4-2-1 on «лі»; octave leap 1-8-1 on «а» | scale 1…9…1 in sixteenths on «а»; arpeggio 1-5-8-12-8-5-1 on «но»; chromatic run on «мі»; eight-beat note on the octave on «а» |

The ranges sit in a comfortable middle where most voices meet. A lower or higher voice sings the same exercise with
**«Вокальна октава»** set an octave down or up in the trainer's settings — that transposes the target only, so the
backing stays where it is. Each lesson description in Studio says so.

## Why the scoring is strict here

An automatic map from a real recording is a draft: `ok` frames cover a fraction of the track and octave errors happen.
A lesson has no estimator in its path at all. The melody is written first, the guide voice is synthesized from it, and
the map is that same melody — so every note is `ok` with confidence 0.99, every contour frame is confident, and the map
carries `status: "exact_synthetic"` instead of `"unverified_draft"`. Nothing is drawn dashed and the ±35 ¢ corridor
measures your voice rather than the estimator's doubts. `tests/e2e/lessons.mjs` checks this from the built file: it
recomputes the timeline from the definitions, and it measures the guide voice out of the embedded MP3 — the sung pitch
stays within a few cents of the target on every note (worst case 3.5 ¢ across the three lessons).

## Adding a lesson

Append one `Lesson` to `lessons/definitions.py`. A pattern is a list of semitones above the key root, `Section.keys` is
the key sweep, and the two Ukrainian strings (`summary`, `description`) are what Studio shows on the card: the goal, the
syllable, a breathing cue, the suggested level, what to watch on screen and the octave note. Nothing else has to change
— the audio, the map, the lyrics, the practice fragments and the Studio card all follow from that definition.

Each practice fragment carries `exercise` — the pattern's name, without the key. One exercise is one skill sung through
nine keys, so the trainer's Прогрес tab groups the fragments by it and keeps a record per exercise and per difficulty
level instead of nine unrelated rows (see [SCORING.md](SCORING.md) and [HISTORY_SCHEMA.md](HISTORY_SCHEMA.md)).

Two invariants are checked before anything is built, and the generator stops with the reason when one breaks: each
repetition has to fill a whole number of beats, because the click rides the same beat grid, and `Lesson.file` has to be
`Luma_*.html`, because the library server lists exactly that glob and a trainer outside it would be generated into
`songs/` and then be invisible everywhere.

## Generation, determinism and staleness

`lessons/build_lessons.py` uses numpy, soundfile and FFmpeg only. There is no randomness anywhere: the same definitions
always produce byte-identical trainers, which is what makes "rebuild when stale" cheap and safe.

Two fingerprints are stored next to the lessons. When only `app/` moved, the existing trainers are re-wrapped with the
current app code (`build_html --rebuild`) and the embedded data line is kept byte-for-byte. When the lesson data itself
moved, the audio and the map are synthesized again. When neither moved, the command returns in milliseconds.

The catalogue Studio reads lives in `songs/lessons.index.html` next to the trainers: a JSON payload in a
`<script type="application/json">` tag. It has that extension because the library server serves `*.html` only; serving a
plain `lessons.json` would be a change in `studio/studio_server.py`. If the catalogue is missing or unreadable, Studio
simply lists the lessons as ordinary library entries.

## Known gaps

All four of these are one missing idea — the trainer does not read the lesson fields the map carries — and all four need
a change in `app/`, which this work does not own.

- **The suggested level is advice, not a setting.** `target.json` carries `lesson: {id, level, bpm}`, and the Studio card
  names the level, but nothing applies it: the trainer opens at whatever level the browser remembers, «Звично» (±50 ¢) on
  a fresh profile. So «Урок 3 · Експерт» is scored at ±50 ¢ until you press «Точно» yourself.
- **The header pill reads «Чернетка мелодії»** until you confirm a fragment by ear, and the live readout appends
  « · чернетка». The simplest fix is honouring a `verified` range carried in the embedded song, which `importFile`
  already accepts but `loadEdits` ignores at load.
- **Attempt cards show no strict statistics.** «У коридорі», «Покриття» and «Медіана |Δ|» are counted only inside
  confirmed ranges, and a lesson has none, so the card falls back to the «Попередня оцінка за чернеткою» badge whose
  tooltip asks you to check that the estimator found the lead vocal — meaningless for a synthesized lesson.
- **«Наскільки точна ціль» explains Demucs separation** and automatic markup that a lesson never used;
  `status: "exact_synthetic"` deserves its own paragraph there.
