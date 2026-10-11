# Design: estimate the microphone offset from every recorded attempt

## Originating requirement

Operator, 2026-10-11, Russian voice transcript, verbatim. "SUV" is a speech-to-text slip for the latency value.

> «Нужно ещё, чтобы оно, эм, скажем так, какой-то такой механизм, который автоматически анализирует, как часто я не
> успеваю, или наоборот, слишком поздно я стартую, который может индикацировать, как, блядь, указывать, короче, на то,
> что у нас неправильная задержка микрофона, то есть если я в целом форму правильную делаю, но, ну, плюс-минус, но при
> этом запаздываю регулярно на какую-то величину, оно должно автоматически рассчитать. Может быть, нужно кнопочку там
> добавить, которая это просчитает, и предложит новый SUV, только это нужно, ну, как-то делать быстро, автоматически, по
> всем записям, которые у меня были.»

What this asks for, point by point:

| # | Requirement | Where this design answers it |
|---|---|---|
| R1 | Detect when the sung shape is right but consistently shifted in time | §3, estimator |
| R2 | Tell "early / late on starts" apart from a wrong microphone offset | §3.4, onsets; §4.3 |
| R3 | Compute it automatically, over **all** past attempts | §2, §4, §5 |
| R4 | A button that computes it and proposes a new value | §6 |
| R5 | Fast | §4.6: whole history in 0.55 s, the newest 60 takes in 0.18 s, in Edge's V8 engine |

## Operator decisions (prototype review `pr_5e183880`, 2026-10-11)

| question | decision |
|---|---|
| D1 `apply-mode` | **suggest, apply with one tap**: «Застосувати N мс» under the result; nothing is applied without it |
| D2 `auto-hint` | **yes, at most once a day**: after a saved attempt, from Studio only, under the strict conditions in §6 (variant 2) |
| D3 `window` | **the newest 30 usable takes**, with their date range in the result |

The sections below are written to these decisions. The implementation notes after §8 record where the build differs in
detail from the prototype.

## 1. Answer first

The estimator was run on the operator's real history (Microsoft Edge, Studio origin `http://127.0.0.1:8792`, 189
attempts with 182 stored traces over 29 songs and lessons, 2026-09-16 … 2026-10-11).

- **Suggested offset: 55 ms** (newest 30 usable takes, 2026-10-09 … 10-11; 90 % interval 48–68 ms).
- **Current setting: 120 ms** (`luma.trainer.settings`, read from the same profile). The settings used in recent
  attempts were 0 → 150 → 100 → 180 → 120 ms; today alone saw four values.
- At 120 ms the trace is drawn **≈ 65 ms too early**. Before 2026-10-09 the setting was 0 ms, and the trace was drawn
  ≈ 50–58 ms too late. That earlier lag is what the operator noticed ("запаздываю регулярно").
- **Phrase starts carry no extra lateness of their own.** Measured against the constant part, voice onsets in songs fall at
  −12 … +4 ms (median per take, over 30–113 takes depending on the window). The whole lag is constant, so fixing the offset
  is the right remedy. No "start earlier" coaching is needed.
- Every usable take in the whole history together gives 58.6 ms (51–62). Takes recorded at 0 ms give 51 ms (48–58).
  Both agree with the recent figure.

## 2. Where takes live and how the offset is applied today

### 2.1 Stores

- **Practice history**: IndexedDB `luma` v1 in the trainer page's own origin, stores `songs`, `runs` and `traces`
  ([HISTORY_SCHEMA.md](../HISTORY_SCHEMA.md)). Every run carries `latency` (the offset it was recorded with), `a`
  (song second where the take started), `speed`, `view`, `octave`, `punches`, `startedAt` and `songHash`.
  `traces` holds the compact per-frame pitch: `{hop≈0.02133 s, segments:[{t0, cents:Int16, conf:Uint8, db:Int8}]}`,
  kept for the last 20 takes of each song plus every record holder.
- **Target**: each trainer embeds `window.LUMA_SONG`. `song.points` is the contour of the original vocal on a 20 ms grid
  (`[t, midi|null, periodicity, ok]`), and `song.notes` holds the notes, including the `ignored` and `manual` flags.
  `songHash` = `song.sourceId`, so every run maps to its trainer file in the library (29 of 29 mapped here).
- **Setting**: `prefs.latency`, clamped to −500…1000 ms on load and on change (`app/app.js:13`, `app/app.js:1489`), saved
  in `localStorage['luma.trainer.settings']` of the origin. Every trainer that Studio serves therefore shares one value.
  The field is «Зсув мікрофона, мс» in the settings dialog (`app/head.html:434`). The text under it currently says that
  no automatic measurement exists (`app/head.html:435`).
- **Activity log** (`songs/logs/activity/*.jsonl`): attempt summaries only, with no per-frame pitch. It cannot support this
  estimate.

### 2.2 How the offset is applied (pre- or post-correction)

The offset is applied **when recording starts**: the capture window opens `latency` ms after the music starts.

```
startTransport:  worker.postMessage({type:'record', start: when + lag, …})          app/app.js:403
worker:          point.t = (end - win/2) − rec.start      (window centre)         app/workers.html:116,126
analyzeTake:     songT  = meta.a + p.t × meta.speed                                 app/app.js:432
live view:       st = offset + (m.t − when − latency/1000) × speed                  app/app.js:296
```

So **stored traces are post-correction**: `t` is measured from `when + latency`. A singer who is exactly on time, with an
audio round trip `R` (output + input), lands at `songT = s + (R − latency) × speed`. The estimator measures the residual
`d` in song time, and the corrected setting for that take is

```
implied = run.latency + d / run.speed          (ms)
```

The run's own `latency` comes from the run record, so takes recorded under different settings can be pooled. That
also gives a built-in self-check, used in §4.3. The detector timestamps each frame at its window centre, so the analysis
itself adds no fixed offset. The value being calibrated is "everything constant between the music and the trace":
output and input latency plus any steady habit of the singer. That is the quantity scoring and the drawn trace need.

Punch-ins splice the new points into the old take, and the run keeps the newest `latency` (`app/app.js:368-370`). If
the setting changed between a take and its punch, the older part would be judged against the wrong value. Here 23 of
189 runs are punched; dropping them changes the result by 3 ms (58 vs 55), so they stay in.

## 3. Estimator

The full working prototype is in the appendix (pure functions, ~110 lines). Per take:

1. **Sung frames.** These are trace frames the trainer itself would trust: pitch present, periodicity ≥ .8 (`conf ≥ 204`),
   level ≥ −48 dBFS. Each lands at `songT = a + t × speed`.
2. **Target.** Only `ok` contour frames, with `ignored` notes removed and `manual` note shifts applied, so wordless or
   uncertain fragments of the map never vote. The target is resampled once per song to a 10 ms grid, which turns every
   candidate offset into an index shift.
3. **Pitch bias.** At offset 0, the circular mode of the octave-folded difference is removed. A take sung a semitone flat
   or a fifth down still aligns on its shape.
4. **Offset search.** Candidate offsets run from −300 to +700 ms of song time in 10 ms steps. The score is
   `Σ max(0, 1 − (e/100¢)²)` over pairs of sung frame and target at `songT − d`, where `e` is folded into ±600 ¢. This
   makes it **octave-insensitive** and caps the vote of a wrong note at zero, so screams, garbage and off-target
   singing add nothing. Only **phrase interiors** count: target frames ≥ 0.30 s after a target onset, where an onset means
   voice after ≥ 0.25 s of no target. A late *start* therefore cannot pull the constant. The peak gets parabolic
   refinement.
5. **Per-take uncertainty.** The same sums are kept per 15 s block of the song. Each block with ≥ 1.5 s of match has its
   own peak, and `se = 1.4826 · MAD(block peaks) / √blocks + 5 ms`.
6. **Gates (gross failures only).** A take is rejected if it has < 50 voiced frames, < 6 s of matched singing, < 3
   blocks, a flat peak (contrast < 0.12), a peak at the edge of the search range, or `se > 60 ms`. Inside the gates,
   each take is weighted by its `se`. An earlier version cut at `se ≤ 35 ms`, and the set of accepted takes then flipped
   under a 10 ms grid change, moving the result by 8 ms. Weighting removed that knife edge.
7. **Onsets (R2).** At each target onset, the first sung frame within −0.25…+0.8 s that follows ≥ 0.15 s of silence and
   starts a run of ≥ 4 voiced frames. Its lag **minus the take's constant** is the onset lateness. The median is
   reported per take.

**Aggregate.** The newest 30 usable takes are used, in time order (§4.4 explains why recency matters). Takes with
`|implied − median| > max(3·MADn, 60 ms)` are dropped. The estimate is the weighted median with weight
`1/(se² + 15²)`, and the 90 % interval comes from a 500-draw bootstrap over takes. A suggestion needs **≥ 12 usable takes**;
below that the result says how many more are needed. The onset figure is the median over takes with ≥ 3 onsets.

## 4. Results on the real history

Read-only method. The Edge profile's `IndexedDB/http_127.0.0.1_8792.indexeddb.leveldb` and `Local Storage/leveldb` were
copied to a scratch directory. A headless Edge (`/opt/microsoft/msedge/msedge` 155) opened that copy with every request
to `http://127.0.0.1:8792/*` answered locally by Playwright, so the live Studio and the live profile were never
touched. All three stores were read with `getAll()`. Targets were taken from `songs/Luma_*.html` (the `LUMA_SONG` JSON;
no map edits exist in localStorage). Song names below are anonymous ids in the order the songs were first sung; the
three lessons keep their level names.

### 4.1 Take yield

182 traced takes, **114 usable**. Rejections can overlap: 47 blocks disagree, 43 too few blocks, 41 too little match,
16 almost silent, 8 flat peak, 3 at the edge. Of the rejected takes, 43 are shorter than 30 s (aborted starts, short
loops).

### 4.2 Per song (median implied offset of usable takes)

| song | takes | usable | implied, ms | onset vs constant, ms | | song | takes | usable | implied, ms | onset, ms |
|---|---|---|---|---|---|---|---|---|---|---|
| S01 | 6 | 4 | 60 | 12 | | S15 | 8 | 2 | 108 | 106 |
| S02 | 2 | 0 | — | — | | S16 | 4 | 2 | 88 | 3 |
| S03 | 10 | 10 | 76 | 12 | | S17 | 1 | 1 | 59 | 7 |
| S04 | 10 | 3 | 52 | 3 | | S18 | 5 | 5 | 57 | 34 |
| S05 | 10 | 4 | 82 | 38 | | S19 | 5 | 4 | 40 | 46 |
| S06 | 20 | 6 | 61 | 6 | | S20 | 4 | 3 | 45 | −12 |
| S07 | 3 | 2 | 93 | 22 | | S21 | 8 | 5 | 87 | −46 |
| S08 | 7 | 5 | 79 | 19 | | S22 | 4 | 3 | 59 | 30 |
| S09 | 1 | 1 | 80 | −49 | | S23 | 1 | 1 | 11 | 6 |
| S10 | 8 | 5 | 62 | −28 | | S24 | 5 | 4 | 68 | −19 |
| S11 | 3 | 3 | 23 | 11 | | S25 | 9 | 6 | 61 | 0 |
| S12 | 3 | 3 | 68 | −23 | | S26 | 4 | 1 | 69 | 169 |
| S13 | 12 | 8 | 49 | 43 | | lesson-beginner | 11 | 6 | 83 | −111 |
| S14 | 2 | 2 | 70 | 18 | | lesson-intermediate | 9 | 8 | 51 | −90 |
| | | | | | | lesson-expert | 7 | 7 | 54 | −78 |

One song alone does not settle the value: song medians spread from 11 to 108 ms, and between takes the spread is
MADn ≈ 20–28 ms. Only the pooled figure is stable (§4.5).

### 4.3 Checks

| check | result |
|---|---|
| **Linearity.** Every take shifted by +150 ms; does its residual move by 150? | error median 0.0 ms, p10 −1.2, p90 +1.0 (109 takes) |
| **Recovery.** Whole history shifted +80 ms | aggregate 51 → 131 (exact search), 59 → 137 (10 ms grid) |
| **Two independent cues.** Pitch contour vs voice-onset timing, songs at setting 0 | 58 ms vs 53 ms |
| **Exact interpolation vs the 10 ms grid**, per take | median +3 ms, p10 −8, p90 +15 (77 takes) |
| **Exact targets.** Lessons, synthetic and precise | 48 ms (41–55), 21 takes; songs 61 ms (58–68) |

### 4.4 The setting at the time of recording matters a little

If the estimator were the whole story, takes recorded at 0 ms and at 150 ms would imply the same value. They do not:

| takes | usable | implied, ms (90 %) |
|---|---|---|
| recorded at 0 ms (09-30 … 10-09) | 59 | 51 (48–58) |
| recorded at 150 ms, September | 36 | 88 (70–94) |
| recorded at 150 ms, October | 15 | 61 (48–83) |
| same song at 150 vs 0, paired, 18 songs | — | +29 ms median difference |

The linearity check rules out the estimator as the cause. Two causes fit, and this data cannot separate them. The first
is a different audio setup in September: most 150 ms takes are from September, and October's 150 ms takes sit close to
the 0 ms ones. The second is that the singer partly follows the drawn trace: with the trace shown 100 ms early, the
singer may sing a little later. Either way the design must use **recent** takes and treat calibration as **iterative**.
After applying a value, the next check runs on takes recorded with it, and the estimate settles where the implied value
equals the setting. That is why the window is the newest 30 usable takes and why the result names its date range.

### 4.5 How many takes are needed

Random draws of n usable takes, 400 draws each, range of the estimate (p5…p95):

| n | 5 | 8 | 12 | 20 | 30 |
|---|---|---|---|---|---|
| range, ms | 33–94 | 38–87 | 45–83 | 48–72 | 50–69 |

12 usable takes (≈ 12 songs sung through, ~25 min of singing) give ±18 ms, and 30 give ±10 ms. The between-take
spread dominates the error. A single take can be usable from about 6 s of matched singing, but one take should never
set the value.

### 4.6 Speed

Measured in headless Edge 155 (V8) on a Ryzen 7 3700X, with typed arrays as IndexedDB returns them:

| scope | time |
|---|---|
| all 182 takes + 29 targets + aggregate | 547–657 ms (first run 657) |
| newest 60 takes (enough to find 30 usable) | 175–298 ms |
| the first version, linear interpolation per offset | 1.5–1.7 s, too slow; replaced by the 10 ms index grid |

Reading the traces out of IndexedDB and fetching the targets come on top (§5). The product scans **newest-first and stops
after 30 usable takes**, so the cost stays flat as the history grows.

## 5. Where it runs

The estimate needs the traces (IndexedDB of the Studio origin) and the target of **every** song in them. A trainer only
carries its own target.

| option | what it takes | verdict |
|---|---|---|
| **A. Trainer settings button; targets from Studio** | `GET /targets?ids=<songHash,…>` in `studio/studio_server.py`: for each library trainer, the `LUMA_SONG` JSON up to `;window.LUMA_ASSETS=` (31 files, 10 MB of JSON, 0.09 s cold), cached by size and mtime like `song_meta`, answered as `{sourceId: {hop, cents: base64 Int16 (−32768 = none or not ok), notes: [{a,b,ignored,manual,m,originalM}]}}`. The trainer reads `runs`/`traces` newest-first, fetches the targets it needs, and runs the estimator in its existing worker or a small inline one. | **Recommended.** The button sits next to the field it changes, and the history schema stays as it is. |
| B. A Studio panel | Same endpoint; the button lives on the Studio page and writes `luma.trainer.settings.latency` | Works, but the value would be set away from where it is read and explained |
| C. Estimate each take when it is saved, stored on the run | New run field, a schema note, import validation, and a backfill that can only reach a song when that song is opened | Fails "по всем записям" for the existing history; deferred |

Details for A:

- Runs whose `mapVersion` does not start with the current `song.id` of that `sourceId` were recorded against an older
  map, so they are skipped. Map edits stored in `localStorage['luma.target.<song.id>']` are applied in the browser, the
  same way the trainer applies them.
- On `file://` there is no Studio, so the trainer uses its own song's takes only and says so («лише ця пісня»). The
  ≥ 12 rule still holds.
- Applying writes `prefs.latency` through the existing `savePrefs()`. Every trainer of that Studio reads it on the next
  load. Tabs already open keep their value until reload, as they do today.
- Nothing leaves the computer: the endpoint serves maps that are already on disk, and traces never leave the page.

Implementation goes after lane f81c2c96 (PR #16) lands, because that lane is changing `app/app.js` and
`studio/studio.html`. This design touches `app/app.js`, `app/head.html`, `studio/studio_server.py` and docs (the build
added `app/latency.js`, and `studio/build_html.py` and `lessons/build_lessons.py` list it). It does not touch
`studio/studio.html`.

## 6. UX

Mock-ups were published for review as two variants at 1440 px and 390 px. The controls are injected into a copy of a
built lesson trainer. No overflow at either width; at 390 px the buttons are 44–48 px tall.

**Variant 1: button in the settings (recommended core).** Under «Зсув мікрофона, мс»:

- The text under the field changes to: «Плюсовий зсув пересуває твій слід раніше. «Розрахувати затримку» порівнює твої
  записані спроби з мелодією і пропонує зсув; спершу заспівай кілька пісень цілком.»
- Button «Розрахувати затримку» (secondary). While it runs, the label reads «Рахую…» and the button is disabled. Like the
  latency field, the button is disabled while singing.
- Result (`role="status"`):
  - «Голос приходить на **65 мс** раніше за мелодію. Пропоную зсув **55 мс** (зараз 120 мс), точність ±10 мс.» When the
    residual is positive, the first sentence says «пізніше».
  - Small line: «30 останніх спроб, 9–11 жовтня · початок фраз — вчасно, без окремого запізнення.» When the median
    onset lag is beyond ±60 ms, the line instead says «на початку фраз ти вступаєш ще на ~N мс пізніше (раніше)» and that
    the offset does not fix it.
  - «Застосувати 55 мс» (primary) and «Розрахувати знову». Applying sets the field, saves, and announces «Зсув 55 мс
    збережено».
  - When the suggestion is within 10 ms of the current value: «Зсув уже правильний (±10 мс)», with no Apply button.
- **Too few takes**: «Поки замало даних: **4** придатні спроби з 12 потрібних. Заспівай ще кілька пісень від початку до
  кінця…», with no Apply button.
- The suggested value is rounded to 5 ms, the field's step.

**Variant 2: Variant 1 plus an automatic hint.** After a take is saved, the trainer reruns the same computation in the
background, at most once per day and only from Studio. The hint shows only when all of these hold:

- ≥ 12 usable takes, at least 8 of them recorded **at the current setting**;
- |suggestion − current| ≥ 30 ms;
- the 90 % interval excludes the current value.

The hint is one dismissible line above the transport bar: «Схоже, зсув мікрофона завеликий (замалий): голос у слідах на
~65 мс раніше (пізніше) за мелодію.» with «Перевірити», which opens the settings and shows the result, and «Не зараз»,
which keeps it quiet for the day. It is never shown during singing or a countdown, and never inside a «Заняття» frame.

Applying the value without asking is not recommended (§9, D1): by §4.4 the singer's own behaviour moves with the
setting, so the operator should see the change and its date range.

The activity log gains two events: `latency_estimate` {latency, ci90, n, current, onset} and `latency_apply` {from, to}.
They are the minimum needed to follow later whether calibration settles.

## 7. End-to-end checks to add

All checks run on the demo trainer and the test Studio that `tests/e2e/run.sh` already starts. Traces are seeded through
`__lumaTest.seedMany`, extended with a `trace` option that synthesizes a voice from the trainer's own contour, shifted by
a chosen number of milliseconds, with optional noise frames.

1. **Recovery** (`latency.mjs`): 15 takes at `latency: 0` with voice +60 ms late. The suggestion is 60 ± 10. Apply sets
   the field and `prefs.latency`, survives a reload, and the console stays clean.
2. **Pooling across settings**: 8 takes at `latency: 0` with +60, and 8 at `latency: 150` with −90. The suggestion is
   60 ± 10, which proves `implied = latency + d/speed`.
3. **Speed**: 12 takes at `speed: 0.8` with a +48 ms song-time shift (60 ms wall clock). The suggestion is 60 ± 10.
4. **Robustness**: add 10 takes of random pitch and 5 of silence, plus 5 sung an octave down. The suggestion is
   unchanged within 5 ms, and the octave-down takes count as usable.
5. **Onset lateness**: takes on time inside phrases but starting 200 ms late at every phrase onset. The suggestion
   stays at the true offset ±10, and the onset line reports ~200 ms.
6. **Too few**: 5 usable takes show the «замало даних» state and no Apply. A run whose `mapVersion` belongs to another
   map is not counted.
7. **Performance**: 200 seeded takes of 4 minutes each. The estimate is reported in under 1.5 s, measured in page
   script and read from a console message, never through `page.evaluate`.
8. **Hint**: shown once when its conditions hold and absent when they do not. «Не зараз» suppresses it for the day. It
   is absent during singing and inside a «Заняття» frame.
9. **Layout** at 390 × 844 and 1440 × 900: the settings result has no horizontal overflow, buttons are ≥ 44 px at
   390 px, and nothing is clipped. Screenshots go to `tests/e2e/shot_latency*.png`.
10. **`studio_test.py`**: `/targets` returns compact targets by `sourceId` for library trainers and lessons, an unknown id
    is omitted, the cache follows mtime, the response never contains audio, and malformed `ids` give 400.
11. **file://**: the trainer computes from its own song only and says so.

## 8. Docs to update with the implementation

- `app/head.html:435`: the "no automatic measurement" sentence is replaced by the text in §6.
- `docs/SCORING.md:130` and `docs/PROGRESS_DESIGN.md:303,347,645` say the end-to-end latency is not measured. They
  should say it is estimated from the attempts, with a link here, and keep "rhythm is not scored", which stays true.
- `docs/ACTIVITY_LOG.md`: the two new events.
- `docs/HISTORY_SCHEMA.md`: no change (option A reads only).
- README "What the trainer does": one line.

## 9. Operator decisions (recommendation first; all three were decided as recommended, see the top)

- **D1. Apply mode.** (a) **Suggest, apply with one tap (recommended):** matches «предложит новый», and §4.4 shows the
  value interacts with the singer, so a visible step is safer. (b) Apply automatically with an undo. (c) Show the number
  only.
- **D2. Automatic hint.** (a) **Yes, at most once a day, only under the strict conditions in §6 (recommended):** covers
  «автоматически… индикацировать». (b) Button only.
- **D3. Window.** (a) **Newest 30 usable takes, with the date range shown (recommended):** the setup can change, and the
  data shows a September/October difference. (b) The whole history.

These are published in the prototype review as questions with the recommended answers marked. The design proceeds on
the recommendations.

## Implementation notes (2026-10-12)

- **Code.** The estimator is `app/latency.js` (`window.LumaLatency`: `CAL`, `prepareTarget`, `estimateTake`, `aggregate`),
  embedded in every trainer by `studio/build_html.py` between the activity logger and the app. It is the appendix code
  with three changes: `prepareTarget` takes the contour as Int16 cents on the song's hop grid (the same form `/targets`
  sends), it takes optional scored spans, and the bootstrap draws from a fixed seed, so the same takes always give the
  same interval. The scan, the result and the hint live in `app/app.js` (`latencyEstimate`, `renderLatency`,
  `latencyAuto`); `GET /targets` is in `studio/studio_server.py`.
- **Wordless targets.** PR #17 (`docs/design/WORDLESS_TARGETS.md`) landed before this build. Wordless stretches are
  drawn dimmed and never scored, so they never vote here either: the trainer's own target uses `scoredSpans()`, and other
  songs get the same rule (`wordedSpans()`, factored out of `scoredSpans()`) from the notes and the lyric line times that
  `/targets` sends. `/targets` therefore also carries `lines` ([a, b] only, no text), `words` and `lesson`.
- **Where the takes come from.** With Studio, every traced run in the history, newest first, until 30 are usable.
  Without Studio (`http` from another server) only this song's runs count, and the result says «лише ця пісня». On
  `file://` the trainer keeps no history, so the attempts in the open tab are used, and the result says so too.
  `/targets` is asked only by pages Studio serves (`/song/…`, `/demo`), the same rule the activity log uses, and it also
  covers the demo Studio serves at `/demo`.
- **Hint.** It is the existing `.banner` line, placed above the transport bar, with «Перевірити» and «Не зараз». The
  check runs once per local day (`localStorage['luma.latency.check']`); a check cut short by singing does not count and
  the next saved attempt tries again. The hint hides while singing or counting in and comes back after.
- **Activity.** `latency_estimate` also carries `ms`, `auto` and `hint`; `latency_apply` is as specified.
- **The 10 ms grid.** On synthetic takes that are exactly 60 ms late the estimate reads 63–64 ms. This is the +3 ms
  grid bias of §4.3, inside the ±10 ms the checks allow; the result is rounded to the field's 5 ms step.

### Result on the real history at build time (2026-10-12)

Measured as in §4 (scratch copy of the Edge profile, headless Edge, every request answered locally, targets from the
library through this build's `/targets`), by clicking the button in a lesson trainer rebuilt with this branch. 204
traced attempts, 127 usable with the wordless rule (126 without it). The setting had meanwhile been changed to 65 ms.

| scope | estimate, ms (90 %) |
|---|---|
| newest 30 usable, 9–11 October (what the button shows) | 59.3 (47.8–74.8); onsets +6 ms |
| the same without the wordless rule | 64.0 (48.1–76.3) |
| whole history | 58.5 (51.5–61.3) |
| recorded at 0 ms | 51.5 (47.8–56.4) |

The button says «Зсув уже правильний (±15 мс)» at 65 ms, with «30 останніх спроб, 9–11 жовтня · початок фраз — вчасно,
без окремого запізнення». Time from the click to the result: 682 ms the first time (Studio reads all 31 trainers once),
179–182 ms after that.

## Deferred — not currently justified

- **Loopback measurement** (play a click, hear it in the microphone, measure the round trip). It is the only ground truth
  for hardware latency, but it needs the sound to reach the microphone through speakers, and it would not capture the singer's steady
  habit, which scoring also wants removed. The attempt-based estimate already lands within ±10 ms with 30 takes.
- **Adding `AudioContext.outputLatency` automatically.** It would change what the stored `latency` means and needs a
  migration of every run's `implied`. Revisit if the operator switches between Bluetooth and wired often.
- **One offset per device** (keyed by `prefs.mic` or the output device). The history does not record the output device,
  and there is one setup today.
- **Per-take estimates stored on runs (option C)** and a cache of results. The newest-first scan with early stop is fast
  enough without one.
- **A rhythm or entry score.** Onset lateness appears only as a sentence in the result. Scoring it is a separate decision
  ([PROGRESS_DESIGN.md](../PROGRESS_DESIGN.md)).
- **Separating the September setup from singer adaptation (§4.4).** It does not change the action: iterate on recent
  takes.

## Appendix: estimator prototype (as run on the history)

Plain ES module, no dependencies. `prepareTarget(LUMA_SONG)` once per song; `estimateTake(run, trace, target)` per
take; `aggregate(results)`. The numbers in §4 come from this code. §4.3 compares it with a variant that interpolates the
target at the exact time for every offset.

```js
export const CAL = {
  conf: 204, gate: -48, noPitch: -32768,          // the trainer's own voiced-frame rule: YIN ≥ .8, level ≥ gate
  dMin: -300, dMax: 700, step: 10,                // residual offset grid, ms of song time (positive = voice arrives late)
  kernel: 100,                                    // cents: per-pair credit max(0, 1-(e/kernel)^2), octave folded
  onsetGap: .25, onsetSkip: .30,                  // target phrase onset: voiced after ≥ .25 s of no target; skip its first .30 s
  block: 15,                                      // jackknife block, s of song time
  minSec: 6, minBlocks: 3, minContrast: .12, maxSe: 60,   // a take counts only past all four; inside them it is weighted
  seFloor: 15, recent: 30, minTakes: 12,          // weight 1/(se² + floor²); newest `recent` usable takes; fewer than minTakes → no suggestion
};
const fold = c => { c %= 1200; if (c > 600) c -= 1200; else if (c < -600) c += 1200; return c; };

// target: ok contour frames only (ignored notes removed, manual shifts applied), interior mask, onsets, 10 ms resample
export function prepareTarget(song) {
  const hop = song.hop, n = song.points.length, tm = new Float32Array(n).fill(NaN), interior = new Uint8Array(n), onsets = [];
  const notes = song.notes; let k = 0;
  for (let i = 0; i < n; i++) {
    const p = song.points[i], t = p[0];
    while (k < notes.length && notes[k].b <= t) k++;
    const note = notes[k] && notes[k].a <= t && t < notes[k].b ? notes[k] : null;
    if (note?.ignored || p[1] === null || !p[3]) continue;
    tm[i] = p[1] + (note?.manual ? note.m - (note.originalM ?? note.m) : 0);
  }
  let last = -1e9, runStart = -1e9;
  for (let i = 0; i < n; i++) {
    if (Number.isNaN(tm[i])) continue;
    const t = i * hop;
    if (t - last > CAL.onsetGap) { runStart = t; onsets.push(t); }
    last = t; interior[i] = t - runStart >= CAL.onsetSkip ? 1 : 0;
  }
  const G = .01, n10 = Math.floor((n - 1) * hop / G), tm10 = new Float32Array(n10), in10 = new Uint8Array(n10), T0 = { hop, tm };
  for (let k = 0; k < n10; k++) { tm10[k] = tgt(T0, k * G); in10[k] = interior[Math.round(k * G / hop)]; }
  return { hop, tm, interior, onsets, tm10, in10 };
}
function tgt(T, x) {             // linear between two finite neighbours a semitone apart, else nearest
  const f = x / T.hop, i = Math.floor(f); if (i < 0 || i + 1 >= T.tm.length) return NaN;
  const a = T.tm[i], b = T.tm[i + 1], r = f - i;
  if (a === a && b === b && Math.abs(a - b) < 1) return a + (b - a) * r;
  return r < .5 ? a : b;
}
export function sungFrames(run, trace) {
  const t = [], m = [];
  for (const sg of trace.segments) for (let i = 0; i < sg.cents.length; i++) {
    const c = sg.cents[i]; if (c === CAL.noPitch || sg.conf[i] < CAL.conf || sg.db[i] < CAL.gate) continue;
    t.push(run.a + (sg.t0 + i * trace.hop) * run.speed); m.push(c / 100);
  }
  return { t: Float64Array.from(t), m: Float32Array.from(m), hop: trace.hop * run.speed };
}
export function estimateTake(run, trace, T) {
  const S = sungFrames(run, trace), N = S.t.length, nd = Math.round((CAL.dMax - CAL.dMin) / CAL.step) + 1;
  if (N < 50) return { ok: false, why: 'few voiced frames' };
  // a constant pitch bias (a semitone flat, a fifth down) would blur the match: remove the circular mode at d=0
  const hist = new Float64Array(120);
  for (let j = 0; j < N; j++) { const y = tgt(T, S.t[j]); if (y === y) hist[Math.floor((fold((S.m[j] - y) * 100) + 600) / 10) % 120]++; }
  let bias = 0, bw = -1; for (let b = 0; b < 120; b++) { let w = 0; for (let k = -5; k <= 5; k++) w += hist[(b + k + 120) % 120]; if (w > bw) { bw = w; bias = b * 10 - 595; } }
  const t0 = S.t[0], nb = Math.max(1, Math.ceil((S.t[N - 1] - t0 + 1e-9) / CAL.block));
  const acc = new Float64Array(nb * nd), k2 = CAL.kernel * CAL.kernel, q0 = CAL.dMin / 10, L = T.tm10.length;
  for (let j = 0; j < N; j++) {   // offsets are whole 10 ms steps: each one is an index shift on the 10 ms target
    const blk = Math.min(nb - 1, Math.floor((S.t[j] - t0) / CAL.block)) * nd, base = Math.round(S.t[j] * 100) - q0, mj = S.m[j] * 100 - bias;
    for (let q = 0; q < nd; q++) {
      const k = base - q; if (k < 0 || k >= L || !T.in10[k]) continue; const y = T.tm10[k]; if (y !== y) continue;
      let e = mj - y * 100; e -= 1200 * Math.round(e / 1200); const w = 1 - e * e / k2; if (w > 0) acc[blk + q] += w;
    }
  }
  const tot = new Float64Array(nd); for (let b = 0; b < nb; b++) for (let q = 0; q < nd; q++) tot[q] += acc[b * nd + q];
  const peak = arr => { let q = 0; for (let i = 1; i < arr.length; i++) if (arr[i] > arr[q]) q = i;
    let d = CAL.dMin + q * CAL.step; if (q > 0 && q < arr.length - 1) { const a = arr[q - 1], b = arr[q], c = arr[q + 1], den = a - 2 * b + c; if (den < 0) d += CAL.step * .5 * (a - c) / den; }
    return { q, d }; };
  const p = peak(tot), med = Float64Array.from(tot).sort()[nd >> 1], top = tot[p.q];
  const contrast = top > 0 ? (top - med) / top : 0, matchedSec = top * S.hop;
  const bests = []; for (let b = 0; b < nb; b++) { const row = acc.subarray(b * nd, b * nd + nd); let s = 0; for (const v of row) s = Math.max(s, v);
    if (s * S.hop >= 1.5) bests.push(peak(row).d); }
  bests.sort((a, b) => a - b);
  const bmed = bests.length ? bests[bests.length >> 1] : NaN, mad = bests.length ? bests.map(v => Math.abs(v - bmed)).sort((a, b) => a - b)[bests.length >> 1] : NaN;
  const se = bests.length >= 2 ? 1.4826 * mad / Math.sqrt(bests.length) + CAL.step / 2 : Infinity, edge = p.q === 0 || p.q === nd - 1;
  const onsetLags = [];   // phrase starts: voice onset relative to the target onset, constant removed
  for (const on of T.onsets) {
    if (on < S.t[0] - .2 || on > S.t[N - 1]) continue;
    let lo = 0, hi = N; const from = on + p.d / 1000 - .25; while (lo < hi) { const mid = (lo + hi) >> 1; if (S.t[mid] < from) lo = mid + 1; else hi = mid; }
    for (let j = lo; j < N && S.t[j] <= on + p.d / 1000 + .8; j++) {
      const quietBefore = j === 0 || S.t[j] - S.t[j - 1] >= .15, run4 = j + 3 < N && S.t[j + 3] - S.t[j] <= 4 * S.hop + .01;
      if (quietBefore && run4) { onsetLags.push((S.t[j] - on) * 1000 - p.d); break; }
    }
  }
  onsetLags.sort((a, b) => a - b);
  const ok = !edge && matchedSec >= CAL.minSec && bests.length >= CAL.minBlocks && contrast >= CAL.minContrast && se <= CAL.maxSe;
  return { ok, residual: p.d, se, contrast, matchedSec, blocks: bests.length, bias, startedAt: run.startedAt,
    implied: run.latency + p.d / run.speed, onsetLag: onsetLags.length ? onsetLags[onsetLags.length >> 1] : null, onsets: onsetLags.length };
}
const median = a => { const s = [...a].sort((x, y) => x - y), n = s.length; return n ? (n % 2 ? s[n >> 1] : (s[n / 2 - 1] + s[n / 2]) / 2) : NaN; };
const wmedian = (xs, ws) => { const o = xs.map((x, i) => [x, ws[i]]).sort((a, b) => a[0] - b[0]), h = o.reduce((s, p) => s + p[1], 0) / 2; let c = 0; for (const [x, w] of o) { c += w; if (c >= h) return x; } return NaN; };
export function aggregate(takes, rng = Math.random) {
  const good = takes.filter(t => t.ok).sort((a, b) => (a.startedAt < b.startedAt ? -1 : 1)).slice(-CAL.recent);
  if (good.length < CAL.minTakes) return { ok: false, n: good.length };
  const m0 = median(good.map(t => t.implied)), madn = 1.4826 * median(good.map(t => Math.abs(t.implied - m0)));
  const kept = good.filter(t => Math.abs(t.implied - m0) <= Math.max(3 * madn, 60)), W = kept.map(t => 1 / (t.se * t.se + CAL.seFloor * CAL.seFloor));
  const est = wmedian(kept.map(t => t.implied), W), boots = [];
  for (let b = 0; b < 500; b++) { const xs = [], ws = []; for (let i = 0; i < kept.length; i++) { const j = Math.floor(rng() * kept.length); xs.push(kept[j].implied); ws.push(W[j]); } boots.push(wmedian(xs, ws)); }
  boots.sort((a, b) => a - b);
  const on = kept.filter(t => t.onsetLag !== null && t.onsets >= 3).map(t => t.onsetLag);
  return { ok: true, n: good.length, kept: kept.length, latency: est, ci90: [boots[25], boots[474]], madn,
    onsetLag: on.length ? median(on) : null, from: kept[0].startedAt, to: kept[kept.length - 1].startedAt };
}
```
