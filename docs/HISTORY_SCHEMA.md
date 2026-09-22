# Practice history: schema, retention and the export file

Every finished attempt is written to IndexedDB in the trainer page's own origin, automatically and without a WAV. The
trainer makes no network requests; nothing here leaves the computer it was sung on. Luma Studio serves its own page and
the trainers from the same origin (`http://127.0.0.1:8792` by default), so a Studio panel can read this base directly,
with no change to `studio/studio_server.py`.

Database `luma`, version 1.

## Stores

```
songs   keyPath 'songHash'
  { songHash, title, artist, duration, lessonId|null,
    maps: [{mapVersion, firstSeen, notes, draftShare}],
    firstRunAt, lastRunAt, runCount }

runs    keyPath 'id'                                  // ≈ 0.5–2 KB per attempt
  { id, songHash, mapVersion, cmpKey, startedAt, endedAt, localDay,
    a, b, speed, level, tolerance, view, octave, latency, hasAudio, clipped, punches,
    target, hit, sung, draftFrames, medianCents, match, songTarget,
    strict: {targetTime, compared, inside, median},
    phraseIds: Int32Array, phraseStats: Int32Array,   // four numbers per phrase: target, hit, sung, median |Δ|
    hasTrace: boolean }
  index 'bySong' ['songHash', 'startedAt']
  index 'byKey'  ['cmpKey', 'match']
  index 'byDay'  'localDay'

traces  keyPath 'runId'
  { runId, songHash, hop, segments: [{t0, cents: Int16Array, conf: Uint8Array, db: Int8Array}] }
```

IndexedDB stores structured clones, so the typed arrays go in as they are — no JSON, no base64.

- `match` is hundredths of a percent (`round(10000 × hit ÷ target)`), so a tie really is a tie and the tie-break can look
  at the median instead of at a rounding artefact. `null` means the attempt covered no drawn target at all.
- `medianCents` and `strict.median` are whole cents; `-1` means "no frame to measure".
- `songTarget` is how many frames of the whole song carried a target under this attempt's view. It rides along so that
  the "full pass" rule can be applied later without walking the map again.
- `target`, `hit`, `sung`, `draftFrames` count 20 ms frames, the same grid `docs/SCORING.md` describes.
- `localDay` is the local date with its boundary at **04:00**, so singing at half past midnight belongs to the evening
  that just passed.

Opening another song ("Інша пісня") swaps `songHash` under the tab, so the in-memory view of the history is reset and
read again for the new song before anything else happens. Otherwise the next attempt would write the previous song's
runs into the new song's row and thin the previous song's traces against a list it does not belong to.

## Keys

```
songHash   = song.sourceId  (sha256 of the source audio; for a lesson, of its synthesized mix), else song.id
mapVersion = song.id + ':' + hash16([id, a, b, m, ignored] for every note)
cmpKey     = songHash · mapVersion · level · view · speed
```

- Re-preparing the same audio changes `song.id` but not `sourceId`: the song keeps its history and opens a new
  `mapVersion` group inside it. `build_html.py --rebuild` changes neither.
- Editing a note changes `mapVersion` — the ruler changed, so the old scores stand apart. Confirming a fragment by ear
  does **not**: `verified` never reaches `targetAt().m`, so a confirmation would otherwise wipe every record.
- `level` is `easy` / `normal` / `strict` or `custom:<cents>`. The vocal octave is deliberately outside the key: it
  moves the target and leaves the difficulty where it was.
- `hash16` is two FNV-1a accumulators, 16 hex characters. It fingerprints a local map; it is not a security hash.

## Records

Inside one `cmpKey`:

- **Song record** — the best `match` among attempts that covered ≥ 95 % of `songTarget` and at least 200 frames (4 s) of
  target. Until there is such a pass the panel says so instead of showing a number.
- **Phrase record** — the best `match` among attempts in which the phrase was counted at all (the attempt covered ≥ 80 %
  of that phrase's frames with a target) and which held at least 75 frames (1.5 s) of it.
- Ties go to the smaller median |Δ|, then to the earlier date: a record belongs to the day it was first reached.
- A lesson also keeps records per **exercise** — `phrase.exercise`, or the label prefix before ` · ` for older files —
  because "гама 1–5" is one skill played in nine keys.

## The compact trace

Four bytes a frame instead of 96 000 a second:

| | WAV, 16 bit mono 48 kHz | packed trace |
|---|---|---|
| 1 s | 96 000 B | 188 B |
| 4 min | 22 MiB | 45 KB |

- `cents = round(midi × 100)`; `-32768` means there was no pitch in that frame.
- `conf` is the YIN periodicity 0…1 mapped onto 0…255; `db` is the frame level clipped to −120…0 dBFS, 1 dB a step.
- Time is not stored per frame. A segment carries `t0`; frame *i* sits at `t0 + i × hop`, and a new segment opens
  wherever that reconstruction would drift by more than a quarter of a hop — which is what a stream discontinuity or a
  punch-in splice does.
- Round-tripping quantizes the pitch to one cent. Re-scoring a stored trace reproduces the stored `target` and `hit`;
  `tests/e2e/history.mjs` asserts exactly that.

## Retention

- **Attempt summaries are never deleted.** Ten attempts a day is about 4 MB a year.
- **Traces** are kept for every standing record (song, each phrase, each exercise) and for the last 20 attempts of the
  song. The rest drop out as attempts leave the twenty; the summary and the score stay.
- There is no storage ceiling of its own. The retention above keeps a song's traces to about 3 MB, so a quarter of a
  gigabyte would take the history of some eighty songs, and a browser quota that does run out is caught on the write.
- A `QuotaExceededError` never loses the attempt from the tab: it stays in the list marked «не записано в історію»,
  × asks first, closing the tab warns, and the tab never drops it to make room — the one case where the trainer speaks
  up, because that line exists nowhere else. It is written again by itself after any write the store accepts, on every
  «Співати» that such attempts hold back, and after «Очистити пісню».
- `navigator.storage.persist()` is requested once, on the first write. The answer is kept for the diagnostics and never
  turned into a request to export.
- A reopened trainer puts the newest attempts whose trace is kept — up to the 20 the tab holds — back into its list,
  re-scored under the current map and without audio. Nothing has to be saved for the line to come back.

## Export and import

One file, schema `luma.history.v1`:

```json
{ "schema": "luma.history.v1", "exportedAt": "…", "app": "luma",
  "songs": [ … ], "runs": [ … ],
  "traces": [{"runId": "…", "hop": 0.021333,
              "segments": [{"t0": 12.3, "cents": "<base64 Int16>", "conf": "<base64>", "db": "<base64>"}]}] }
```

- The trainer exports the current song or everything; the same envelope with a single run is what the JSON button on an
  attempt card writes, so one attempt can travel on its own.
- Import merges by attempt `id`: importing the same file twice changes nothing. A song row this browser already has
  stays in charge: an import adds its new attempts to `runCount`, keeps the earlier `firstRunAt` and the later
  `lastRunAt`, and leaves the row untouched when the file brings no new attempt for that song.
- Validation is bounded the way `importFile()` already is — counts, string lengths, value ranges, song keys, per-phrase
  numbers — and any violation rejects the whole file with a readable message before a single record is written. What the
  validator cannot foresee (a base64 channel that will not decode, a store that refuses a key) is caught too and answered
  in the language of the interface, with the exception name kept as a hint.
- Attempts whose `songHash` is not in the library import all the same; they attach themselves the next time that song is
  prepared.

## What is not here

No audio. An attempt without the recording switch keeps pitch, confidence and level numbers, and a voice cannot be
reconstructed from them. No accounts, no sync, no leaderboards. The history is tied to this origin and this browser
profile: another port, another browser or "clear site data" gives an empty history, and export is the answer to that.
