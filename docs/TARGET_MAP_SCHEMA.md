# Song package and target-map schema

A trainer is one HTML file. All song data lives on a single line:

```html
<script>window.LUMA_SONG={…};window.LUMA_ASSETS={…};</script>
```

`studio/build_html.py` writes that line from a **package directory** (`target.json` + four MP3 files) and wraps it with the
app parts. `--rebuild` re-wraps an existing trainer with newer app code and keeps its data line byte-for-byte. Every wrap
(a build, `--rebuild`, `reassets` and Studio's import) writes one more line right after it, derived from the lyrics, which
the head of the «Голова» panel reads (see [`LUMA_PHONES`](#luma_phones)).

## `LUMA_SONG` (schema `luma.song.v1`)

| key | type | meaning |
|---|---|---|
| `schema` | `"luma.song.v1"` | required literal |
| `title`, `artist` | string | shown in the top bar and `document.title` |
| `duration` | number, s | must match the embedded audio within 0.1 s; 1..2400 (40 minutes, `MAX_SECONDS` in `studio/prepare_song.py`) |
| `a4` | 440 | tuning reference |
| `hop` | 0.02 | contour hop in seconds |
| `status` | string | `"unverified_draft"` for automatic maps |
| `neuralSeparation` | bool | whether a neural separator produced the stems |
| `method` | string | free text shown in the "Наскільки точна ціль" dialog |
| `warning` | string | shown to the user; keep it truthful |
| `createdBy` | string | provenance |
| `id` | string | 20 hex chars; `localStorage` key `luma.target.<id>` stores note edits and verified ranges. A new map for the same song gets a new id, so old edits stay untouched and do not apply. |
| `sourceId` | string | sha256 of the source audio; importing a bare target requires a match |
| `initialTime` | number | where the playhead starts |
| `metrics` | object | `{notes, candidateSeconds, comparableSeconds, comparablePercentOfTrack}` |
| `waveform` | number[1000] | 0..1 envelope for the timeline |
| `points` | array | pitch contour, below |
| `notes` | array | segmented notes, below |
| `unpitched` | array | optional scream/noise intervals, below; absent means none |
| `phrases` | array | optional practice fragments `{id ≥ 1, a, b, label, verified:false}` |
| `lyrics` | array | optional word timings, below |
| `lyricsSource` | string | provenance of the lyrics |

### `points`
`[t, midi|null, confidence, ok]` on the `hop` grid, sorted by `t`. `midi` is a float in 24..108 or `null` (no melody candidate).
`ok` = 1 when the frame passed the strict reliability mask (drawn solid in contour view), 0 for draft (dashed).

### `notes`
`{id, a, b, m, n, q, ok, ignored}` — `a`/`b` seconds, non-overlapping, sorted by `a`; `m` float MIDI centre, `n = round(m)`,
`q` confidence 0..1, `ok` confident note (solid) vs draft (dashed), `ignored` excluded from comparison and drawing.
User edits add `manual: true` and `originalM`.

### `unpitched`

Optional top-level list `[{"a": 1.2, "b": 2.4, "kind": "scream"}]`. Times are finite
seconds with `0 <= a < b <= duration`. Kinds are `scream` and `noise`. Entries are
sorted by start and do not overlap; adjacent entries of the same kind may merge.
An absent list and an empty list both mean no annotated spans.

These intervals carry no pitch: contour points inside them have `midi: null`, and
notes do not intersect them. They mark audible unpitched voice/noise for a chart
renderer. They supply no target notes or scoring credit. Existing targets remain
valid without this optional key.

`tools/song_qa/apply_edits.py` writes the list for an explicit melody edit
`{"op":"clear","a":1.2,"b":2.4,"kind":"scream"}` (or `noise`). A plain `clear`
removes contour without inventing a reason. Candidates require visual confirmation
before a reviewer assigns a kind. Subsequent edits replace the annotations inside
their time span while preserving the rest. See [SONG_QA.md](SONG_QA.md).

### `lyrics`
`[{a, b, words: [{a, b, w, c}]}]` — lines of words with start/end seconds and a confidence `c` 0..1. Words are drawn above the
melody at their own moment; the current line is shown at the top of the stage.
The aligner rounds line endpoints to two decimals and words to three, so their
corresponding endpoints may differ by up to 0.005 s.

## `LUMA_ASSETS`
`{"1": {backing, foreground}, "0.8": {backing, foreground}}` — base64 MP3 (22.05 kHz, 128 kb/s). The 0.8× pair is
time-stretched with FFmpeg `atempo` so pitch is preserved; both pairs are padded/trimmed to exactly `duration / speed`.

## `LUMA_PHONES`
```html
<script>window.LUMA_PHONES={"v":1,"words":{"time":"t a+ɪ m","ма":"m a"}};</script>
```
The sounds of the song's distinct lyric words, written by `studio/phonemes.py` at every wrap and never edited: keys are the
words normalised (NFC, no stress marks, one apostrophe `'`, lower case, no punctuation at the ends; `app/tract3d.js`
normalises the same way), values IPA symbols separated by spaces, `+` joining a diphthong's glide to its first vowel and
`ʲ` marking a soft consonant. English words come from CMUdict (first pronunciation; `studio/data/`, with its licence),
Ukrainian words from spelling rules. A word read by neither is left out; the trainer then reads it with letter rules and
marks it «приблизно». `<` is written as `\u003c`. The line repeats words the data line already holds and adds nothing else.

## How the app uses the map
- `targetAt(t)`: in notes view, the note containing `t`; in contour view, the `points` entry within 0.75 hop of `t`. The user's
  octave setting shifts the target.
- In a song with lyric words, `targetAt(t)` is null outside scored time: chains of notes (gap ≤ 0.85 s) that come within
  0.5 s of a lyric line, plus the lines widened by 0.5 s. A wordless chain is drawn dimmed and never scored; lessons and
  songs with no lyrics score every target. Computed in the trainer, so nothing in `target.json` changes
  ([SCORING.md](SCORING.md#wordless-target-без-слів--не-рахується)).
- The live match score and per-note ✓/× use every non-ignored, scored note regardless of `ok`. The strict statistics on attempt cards
  ("У коридорі", "Покриття") use only `ok` frames inside ranges the user has explicitly verified.
- Validation on import: points ≤ 300 000, notes ≤ 20 000, ranges inside `duration`, MIDI 24..108, non-overlapping notes.
