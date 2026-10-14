# Past takes as a soft cloud behind the target — design

Prototypes and research by lane a97b2f5c (§ Ground truth to § What the frames show are its measurements, unchanged).
The operator chose in prototype review `pr_f9d4c805` on 2026-10-11; § [Operator decisions](#operator-decisions-pinned-2026-10-11)
pins that choice and overrides the recommendation further down wherever the two differ. The build is in `app/app.js`
and `app/workers.html` (§ [Build](#build)).

## Originating requirement

Operator requirement, 2026-10-11, Russian voice transcript, quoted verbatim from the pinned task:

> «нужно, чтобы визуально придумать прототипы того, как отобразить предыдущие мои записи, только чтобы они не мешали мне
> петь, а они просто немножко, очень, так, знаешь, как расплывчато показывали, как я играл в целом, как, знаешь, как
> разнос как я играл до этого, при этом чтобы это было как-то blurred, или, знаешь, как то, что просто цветом оно
> приблизительно как шумом, как облака, вот, не знаю, как вот чтобы, чтобы такое было показывало.»

Read as four obligations:

1. Show my previous takes of this song on the stage.
2. They must not get in the way of singing.
3. Show the spread (разнос) of how I sang, roughly and blurred.
4. Colour only, like noise or clouds.

The prototype lane delivered prototypes and this document and changed no product file. Section [Validation against the quote](#validation-against-the-quote) checks the result against these four points.

## Operator decisions (pinned, 2026-10-11)

Answers in prototype review `pr_f9d4c8052d5579f8289f2721c620f5f4`, no comment attached:

| Question | Recommended in the review | Operator's choice |
|---|---|---|
| Look | 1 · Туман | **3 · Пил** (dust specks) |
| The record shadow | one button, three states | **The cloud fully replaces the shadow. There is no record line any more.** |
| Intensity | two levels in the settings | **One fixed level, no setting** |
| Source | the last 20 takes of this song, any level or view | **The last 20 takes of this song, any level or view** (as recommended) |

What follows from them:

- The «Рекорд» stage button (`#shadowBtn`), its legend entry «твій рекорд», the shadow line, its IndexedDB read and its
  `shadow` key in the activity `state` are removed. The legend entry becomes «твої спроби», drawn as a few specks.
- **Migration of the old pref.** `prefs.shadow` (boolean, on by default) is dropped and nothing replaces it. With no
  button and no setting, carrying `shadow: false` over as «cloud off» would hide the cloud for good, with no way to
  turn it back on. Carrying `true` over changes nothing. The stale key leaves `luma.trainer.settings` at the next save.
- Dust colour, speck size and alpha are the prototype's (variant 3 frames), fixed: `#c3d3f2`, 1.9 px on a stage at
  least 720 px wide and 1.6 px below that, two alpha tiers of 0.22 and 0.26.
- The take being sung, the take on screen in review, and a take being re-recorded (punch-in) never feed the cloud.

## Ground truth (observed 2026-10-11)

| Fact | Where / how observed |
|---|---|
| The stage is one 2D canvas. `draw()` paints, in this order: background, pitch rail, piano-roll rows, time grid, past-of-playhead dim, loop region, then (clipped to the plot) target notes or contour, the **shadow**, the live/review trace, and the words. | `app/app.js:1316-1386` |
| The insertion point for anything that must sit *behind* the target is right after `const tolH=…,barH=…` inside the plot clip, before the notes loop. | `app/app.js:1324` |
| The existing **shadow** is the personal best of the current fragment, in the same comparison group as the numbers above the graph (`cmpKey` = song · map · level · view · speed). It is one 1 px line, `#95a3b899`, with no halo, frames with confidence < 0.8 are skipped, and it follows the vocal octave. One trace is read from IndexedDB per change of scope. | `refreshShadow()` `app/app.js:753-774`, drawn at `app/app.js:1362-1367` |
| Its switch is the stage button «Рекорд» (`#shadowBtn`, legend «твій рекорд»), stored as the boolean `prefs.shadow`, on by default, and logged in the activity `state`. | `app/head.html:419`, `app/app.js:11, 228, 1456` |
| The tab already holds **up to 20 attempts with their full pitch points** (`TRACE_TAKES=20`, `TRACE_POINTS=400000`): the session's own takes plus the newest ones `restoreTakes()` brings back from the history on open. Every point has `songT` and `m`. | `app/app.js:308, 650-668` |
| History keeps the trace of every standing record plus the last 20 attempts; summaries forever. | `app/app.js:447, 697`; `docs/HISTORY_SCHEMA.md` |
| Workers are built from `<script>` text in `app/workers.html` through a Blob URL; there is one pitch worker today. | `app/app.js:281-283` |
| The operator's real history lives in IndexedDB of the Studio origin (`http://127.0.0.1:8792`) in the Microsoft Edge profile: **29 songs, 188 attempts, 181 kept traces**. They sing at Легко in the Контур view. | read from a copy of that store in a scratch dir (below); activity log |
| Lane f81c2c96 (PR #16) is changing `app/app.js` and `studio/studio.html` now. | pinned task |

Prior work: searches of transcripts and memory for a take cloud, heat map, density or spread of past takes found nothing. The closest existing feature is the shadow line from the progress lane, cited above.

### How the prototypes were made

- The Edge store was **copied** into a private scratch directory under `/var/tmp`. Edge and the running Studio were not touched. A headless Edge opened the copy on the Studio origin, with every request to that origin answered locally, so the live Studio received nothing and no activity was logged.
- The song with the most history was chosen: **song A**, songHash `f491ef01…`, 4:30, a draft note map. It has 27 attempts between 18.09 and 11.10 and 20 kept traces. Its title, artist, lyrics and phrase labels were replaced in the prototype copy, and lyrics were off in every frame.
- The trainer was this worktree's `app/` code at 77e116d plus **one injected line** at `app/app.js:1324` that calls the prototype layer. Nothing else in the drawing changed.
- **During singing:** the newest real attempt (11.10, from 2:19.9) is replayed through the live pitch path (`Luma.test.fakeSing` + `livePush` + `fakeTick`), so the live line, the readout and the live score are real. The cloud is built only from the **18 traces that came before it**, as it would be at that moment.
- Frames are at 1440×900 and 390×844, in Контур (the operator's view) and Ноти, at 03:46 and at 03:04 (the "octave" moment). Each frame is paired with today's stage at the same moment (shadow on) as its "before".

Prototype review: **`pr_f9d4c8052d5579f8289f2721c620f5f4`** (4 variants, 19 frames, 4 questions).

## The variants

All four are drawn at the insertion point above, so the target bars, the contour, the shadow, the live line and the readout always paint over them. All four use the same source: past points with confidence ≥ 0.5, shifted by the difference between the current vocal octave and the octave of the take.

| # | Name | What it draws | What it says to the singer | Cost per frame (measured) |
|---|---|---|---|---|
| 1 | **Туман** (density fog) | One blurred density map, time × pitch: a 40 ms × ¼-semitone grid, normalised by how many past takes ran through each moment, faded where fewer than three did, gaussian blur σ ≈ 120 ms × 0.8 semitone, pale blue-white `#9db8e6` at ≤ 34 % alpha. Built once per song into a bitmap, then **one `drawImage` per frame**. | "My voice usually sits here." It shows habits across the whole stage, ahead of the playhead too, including singing an octave up. At 03:04 the fog lies on G4 over a G3 target. | +0.0 ms median (no change against today) |
| 2 | **Смуги розкиду** (per-note bands) | For each target note, the 10th–90th percentile of where past takes were, brightest at the median, as a soft band under the bar. The octave is folded (Легко forgives it). | "On this note I am usually flat or sharp by this much." Clean and per note. | +0.0 ms |
| 3 | **Пил** (dust) | Every past frame is one 1.6–1.9 px speck, slightly scattered in time and pitch, in three alpha tiers. | Literally "noise". Individual takes stay faintly traceable. | +0.3 ms median at DPR 2; p95 9.7 → 19.2 ms with 4× CPU throttle |
| 4 | **Туман з кольором влучань** (hit/miss tint) | Variant 1, coloured mint where past frames were inside the current tolerance and rose where they were not; frames without a target drop out. | "Here I usually hit; here I usually miss." | +0.0 ms |

Performance was measured in headless Edge 155 at 1440×900, DPR 2, over 240 `draw()` calls during singing. Whole-frame `draw()` cost, median / p95, in ms:

| CPU | today | 1 Туман | 2 Смуги | 3 Пил | 4 Колір |
|---|---|---|---|---|---|
| 1× | 0.8 / 3.1 | 0.8 / 2.7 | 0.8 / 2.7 | 1.1 / 3.8 | 0.9 / 2.8 |
| 4× throttled | 5.0 / 9.7 | 4.0 / 10.4 | 4.4 / 8.6 | 6.2 / 19.2 | 5.0 / 9.5 |

Build cost for the whole 4:30 song from 18 takes (41 400 points), on the main thread in the prototype: 1 = 0.22–0.30 s, 2 = 0.14–0.18 s, 3 = 0.01–0.06 s, 4 = 0.47–0.56 s. With 4× throttling: 1.1 s, 0.6 s, 0.16 s and 2.4 s. The production build therefore runs in a worker (below), so no pause of that length reaches singing or the «Співати» press. The bitmap is 25 columns per second × 4 rows per semitone: 6757 × 264 px, 7.1 MB RGBA for this song.

### What the frames show

- **Туман** reads as weather behind the line. At «тихо» it is easy to ignore while singing, and at «помітно» it plainly shows where the voice goes. At 03:04 it reveals a real habit: on the sustained G3 the operator sings G4. At 390 px the vertical blur stretches into soft columns, because a semitone is ~24 px tall there. It stays readable and does not cover the bars.
- **Смуги** is the cleanest in the Ноти view, and it shows a steady flat or sharp tendency per note well. It cannot show the octave habit: the folded band sits exactly under the target, where the target hides it. It also says nothing between notes, where the operator spends a lot of voice in this draft map.
- **Пил** is closest to the word «шумом». On a phone the specks become sparse grain and say less. It is the only variant whose cost grows with the number of points on screen.
- **Колір** carries the most information, but it reuses mint and rose, the colours that already mean "hit now" and "miss now" on the live line and the bars. A past miss in rose next to a present hit in mint makes the singer read two states at once, which works against obligation 2.

## Recommendation (prototype stage — superseded by the operator decisions above)

**Variant 1, Туман.** It is the only one that answers obligations 3 and 4 as spoken ("blurred", "like clouds", "the spread of how I sang"). It shows the habit the bands lose, costs nothing per frame, and stays out of the live colour language. Variant 2 is the fallback if the operator wants a per-note number-like reading over a cloud.

### Relation to the existing shadow («Рекорд»)

The two answer different questions. The shadow is *one* line: my best take of this fragment, at this level, view and speed. The cloud is *all* recent takes: where I usually go, whatever the level. A crisp line pulls the eye, which is what the operator asked to avoid. A blur only hints.

**Recommended: extend the same switch.** `#shadowBtn` keeps its place and becomes a three-state control: **хмара** (default) → **хмара + рекорд** → **вимк**. One button, no new stage chrome, and the old line stays one tap away for anyone who uses it. The `prefs.shadow: true` saved today migrates to «хмара + рекорд», so nobody loses what they had, and `false` migrates to «вимк». The alternatives (replace the shadow outright; two separate buttons) are in the review as options.

### Toggle and intensity

- Stage: the three-state button above. The title says what each state shows; the legend entry «твій рекорд» gains «твої спроби» while the cloud is on.
- Settings dialog: **Хмара спроб: тихо · помітно**. «Тихо» is the default; «помітно» multiplies alpha by 1.9 (frame «Інтенсивність» in variant 1). Two steps are enough to tell "barely there" from "I want to study it". A slider would invite tuning that the prototype showed is unnecessary.
- No cloud when fewer than two takes cover a moment: it fades in as takes accumulate (normalised by coverage, full strength from three takes on).

### Source of the cloud

**The takes already in the tab** (`s.takes`, ≤ 20, the session's plus the newest restored), whatever their level, view or speed, minus the one being sung or reviewed. Level and view change only how a take is scored; where the voice went stays the same. Speed is already undone in `songT`. This reads nothing new from IndexedDB, and it matches the history's own retention (the last 20 attempts), with no record-only older traces to bias it toward good days.

## Build

The outline the prototype lane wrote for Туман (a worker-built density bitmap, a three-state button, an intensity
setting) is replaced by this one for Пил.

1. **Source.** The takes in the tab (`s.takes`, at most `TRACE_TAKES` = 20: the session's plus the newest ones
   `restoreTakes()` brings back), whatever their level, view or speed. Left out: the take on screen in review, and a
   take being re-recorded by a punch-in. The take being sung is not in `s.takes` until it ends. Nothing new is read
   from IndexedDB.
2. **Packing (main thread, once per take).** Each take's confident frames (pitch present, confidence ≥ 0.5) are packed
   once into a `Float32Array` of `songT, m − octave` pairs, cached against the take's points array, so a re-scored or
   punched take is packed again and nothing else is.
3. **Build (worker).** `refreshCloud()` runs from `sync()` and posts the packed takes to the `cloud-source` worker in
   `app/workers.html` when the set of takes changes. The worker scatters every frame a little in time (± 25 ms) and
   pitch (triangular, ± 0.32 semitone) with a seed per take, so one new take never reshuffles the others. It assigns
   each speck one of two alpha tiers, sorts all specks by time and transfers three typed arrays back. An answer that
   arrives after the take set has moved on is dropped.
4. **Drawing.** Specks never go straight onto the stage. They are drawn once into an offscreen layer that covers the
   plot's height and 1.6 view spans of song time from just behind the visible window, at the stage's own pixel ratio,
   using the current pitch scale and the current vocal octave. Each frame then costs one `drawImage` of the visible
   part, at the insertion point behind the target (after the grid, before the notes), inside the plot clip. The layer
   is redrawn when the window walks off it, when the plot size, pixel ratio or octave changes, and when the pitch scale
   settles somewhere new. While the scale eases, the old layer is stretched to the moving scale and redrawn at most
   every 150 ms.
5. **Prefs and log.** `prefs.shadow` and the activity `state` key `shadow` go (see the decisions above).
6. **Tests.** `tests/e2e/cloud.mjs`: seeded takes put specks on the plot behind the target and the live line; target-bar
   and live-trace pixels are the same with and without the cloud; the take under review is left out; a punch-in leaves
   its own take out; the old `#shadowBtn` and «твій рекорд» are gone and a saved `shadow` pref is dropped; wordless
   notes keep their alpha and their unscored state; the build runs in the worker; frame time with the cloud during
   singing, at 1× and 4× CPU throttle, stays within budget at 390 px and on desktop.

## Questions for the operator (asked in the review, each with a recommendation)

1. **Look:** Туман · Смуги · Пил · Колір. Recommended **Туман**.
2. **Shadow:** one «Рекорд» button with three states (хмара · хмара + рекорд · вимк, default хмара) · the cloud replaces the shadow outright · two separate buttons. Recommended **three states on one button**.
3. **Intensity:** two levels in settings (тихо default, помітно) · one fixed level · a 0–100 % slider. Recommended **two levels**.
4. **Source:** the last 20 takes of this song, any level or view · only the shadow's comparison group · only the last 7 days. Recommended **last 20, any level**.

None of these blocks the design. The recommended set is buildable as written.

## Validation against the quote

| Obligation | How the recommended design meets it | Evidence |
|---|---|---|
| 1. Show my previous takes | Every take in the tab, up to 20, feeds the cloud over the whole stage, ahead of the playhead too. | all variant-1 frames |
| 2. Do not disturb singing | Drawn under the target, the shadow and the live line. Pale blue outside the live colour language. ≤ 34 % alpha at «тихо». Zero measured frame cost. Built in a worker, off the «Співати» path. One tap turns it off. | perf table; «до/після» pairs |
| 3. The spread, blurred | Density normalised by coverage, blur σ ≈ 120 ms × 0.8 semitone. Shows where the voice usually is, including octave habits. | frame «03:04 … октавою вище» |
| 4. Colour only, like clouds | No lines, glyphs or labels; one soft hue. | variant 1 frames |

## Deferred — not currently justified

- **Hit/miss colouring of the cloud** (variant 4): it reuses the live mint and rose and competes with the present take. Revisit only if the operator picks it.
- **Per-note bands** (variant 2) as a second layer on top of the fog: two encodings of the same data.
- **Dust / animated drifting noise**: the only option whose cost grows with points on screen. Motion behind a moving target distracts.
- **Cloud on the timeline strip or in the Прогрес tab**: the requirement is about the stage while singing.
- **Weighting recent takes higher, or a 7-day window**: the 20-take window already tracks the present. Add it only if the cloud is seen lagging behind real progress.
- **A cross-song "my range" cloud**: answers a separate question about vocal range across songs.
- **Reading traces beyond the 20 in the tab from IndexedDB**: more data, a slower build, and a bias toward record takes.

## Notes

- The real data shows the operator often sings an octave above the target on this song (the readout says «інша октава»). Легко forgives it, so the score hides it, and the fog shows it at once. This is the strongest argument for variant 1.
- The prototype scripts and frames are in `/var/tmp/luma-take-cloud-a97b2f5c/` (`scripts/`, `frames/`). The copied store and the decoded history were deleted after rendering; `scripts/dump.mjs` rebuilds them from a fresh copy. The frames carry no titles, artists or lyrics.
