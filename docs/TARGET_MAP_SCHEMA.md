# Song package and target-map schema

A trainer is one HTML file. All song data lives on a single line:

```html
<script>window.LUMA_SONG={…};window.LUMA_ASSETS={…};</script>
```

`studio/build_html.py` writes that line from a **package directory** (`target.json` + four MP3 files) and wraps it with the
app parts. `--rebuild` re-wraps an existing trainer with newer app code and keeps its data line byte-for-byte.

## `LUMA_SONG` (schema `luma.song.v1`)

| key | type | meaning |
|---|---|---|
| `schema` | `"luma.song.v1"` | required literal |
| `title`, `artist` | string | shown in the top bar and `document.title` |
| `duration` | number, s | must match the embedded audio within 0.1 s; 1..600 |
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

### `lyrics`
`[{a, b, words: [{a, b, w, c}]}]` — lines of words with start/end seconds and a confidence `c` 0..1. Words are drawn above the
melody at their own moment; the current line is shown at the top of the stage.

## `LUMA_ASSETS`
`{"1": {backing, foreground}, "0.8": {backing, foreground}}` — base64 MP3 (22.05 kHz, 128 kb/s). The 0.8× pair is
time-stretched with FFmpeg `atempo` so pitch is preserved; both pairs are padded/trimmed to exactly `duration / speed`.

## How the app uses the map
- `targetAt(t)`: in notes view, the note containing `t`; in contour view, the `points` entry within 0.75 hop of `t`. The user's
  octave setting shifts the target.
- The live match score and per-note ✓/× use every non-ignored note regardless of `ok`. The strict statistics on attempt cards
  ("У коридорі", "Покриття") use only `ok` frames inside ranges the user has explicitly verified.
- Validation on import: points ≤ 300 000, notes ≤ 20 000, ranges inside `duration`, MIDI 24..108, non-overlapping notes.
