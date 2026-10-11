# «Обери за мене»: a progressive song pick — design

## Originating requirement

Operator requirement, 2026-10-11, Russian voice transcript quoted verbatim from the pinned task:

> «Я бы хотел, чтобы ещё, знаешь что, чтобы выбирал рандомную песню, ну типа можно было рандомно взять так, э-э, такой
> режим и оно вместо меня выбирает. И желательно, чтобы оно выбирало те, которые я хуже всего пою, эм, и. Наверное. Нет.
> Нужно, чтобы прогрессивно, как-то, оно сначала лёгкие, а потом сложнее и сложнее, типа, и что-то такое, не знаю.»

Obligations, checked in [Validation against the quote](#validation-against-the-quote):

1. A mode in which the app picks the song instead of the operator.
2. Some randomness: the order differs from one time to the next.
3. Progressive: easy songs first, then harder and harder.
4. Aware of how the operator actually sings each song. The operator first asked for "the ones I sing worst", then
   withdrew it («Наверное. Нет.») in favour of progression. Personal results therefore
   **adjust** an order that stays easy-to-hard.

This design sits on top of the session flow in `docs/design/SESSION_FLOW_RESULTS.md` (merged in PR #16): the result card with today vs the
median, the «Далі» section with a 3-2-1 ring, auto-sing in the next frame, and "next song = picker order". Autopick
changes only **which** song the «Далі» section names. Everything else in that flow stays as specified there.

Prior work: transcript and memory searches ("song difficulty random pick progressive", "adaptive difficulty next song
picker") found nothing earlier on this topic.

## Operator decisions (prototype review `pr_ce9a8dbf`, 2026-10-11)

| question | decision |
|---|---|
| `entry` | **both**: the tile in the song picker after the lessons, and «Одразу пісні: обери за мене» on the «Заняття» card of the Studio home (variants 1 and 2) |
| `personal-weight` | **half**: k = 0.5, so a song sung 10 points below the usual counts 5 points harder; the shift is capped at ±10 |
| `session-start` | **one step below** where the last session ended |
| `chain-end` | **never by itself**: only × or «До пісень» end it; with nobody singing it waits without a countdown |

The sections below are written to these decisions.

## Measured: difficulty of the real library (2026-10-11)

Read from the 31 trainers in the operator's `songs/` (28 songs and 3 built-in lessons): the embedded `LUMA_SONG.notes`,
non-ignored notes only, the same notes the score counts in notes view. Songs are named by the first 8 hex characters of
`songHash` (`sourceId`, the sha256 of the source audio). No titles, artists or lyrics appear in this document.

Five features, each chosen because it is something a singer feels and the target map already holds:

| feature | definition | why |
|---|---|---|
| `span` | P90 − P10 of note pitch in semitones, weighted by note duration | how wide the melody moves; the percentiles shrug off the map's stray octave errors |
| `out` | share of sung time outside the comfort band **A3–D5 (MIDI 57–74)** | notes the voice has to reach for. The band is the range of built-in lesson 2, which the operator sings at 71 % on Легко |
| `rate` | notes per second of sung time | how busy the line is |
| `leaps` | share of connected note changes (gap < 0.3 s) of ≥ 5 semitones | jumps are where pitch is lost |
| `sung` | seconds of target (sum of note lengths) | stamina; a long song is a longer test |

Each feature is mapped linearly onto 0…1 between fixed anchors and clipped. **D** = 100 × the mean of the five. The
anchors are constants, so adding a song never moves another song's D.

| feature | 0 at | 1 at |
|---|---|---|
| `span` | 7 st | 20 st |
| `out` | 0 % | 40 % |
| `rate` | 2.5 /s | 4.8 /s |
| `leaps` | 3 % | 20 % |
| `sung` | 75 s | 270 s |

Rejected features:

- **Sustained notes:** lesson 1 is built from sustained notes and is the easiest lesson. In a frame-counted score a long
  note gives time to settle, so it does not make a song harder in any one direction.
- **Draft share:** it describes the map's quality, and the personal adjustment absorbs whatever it does to the score.

The features are nearly independent (Spearman |ρ| ≤ 0.40 for every pair across the 28 songs; the largest is `leaps` with
`sung`, 0.40). Equal weights are therefore a fair default, and no feature is counted twice.

**Sanity check on the lessons**, whose difficulty is known by construction: lesson 1 → **D 0**, lesson 2 → **35**,
lesson 3 → **41**. The measure orders them correctly. Lessons are never autopicked; they only check the scale.

### The library

Sorted by D. "Personal" is the pooled match (Σ hit ÷ Σ target, Легко, 1×, attempts with ≥ 4 s of target) from today's
activity log, the only songs the operator has sung so far. D′ is D after the personal adjustment below, with a baseline
of 48.3 % (the median of those attempts). "Step" is the quarter of the library by D′.

| # | song | span st | out % | notes/s | leaps % | sung s | **D** | personal % | D′ | step |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `e60a7b76` | 7.1 | 11 | 3.61 | 4 | 93 | **18** | | 18 | 1 |
| 2 | `63fbf3bd` | 7.1 | 22 | 3.49 | 8 | 96 | **27** | | 27 | 1 |
| 3 | `f6836496` | 11.8 | 2 | 3.18 | 9 | 128 | **27** | | 27 | 1 |
| 4 | `3ac24ad7` | 11.1 | 7 | 3.74 | 8 | 97 | **28** | | 28 | 1 |
| 5 | `cf0174f5` | 10.1 | 29 | 3.63 | 3 | 93 | **31** | | 31 | 1 |
| 6 | `5ef6808b` | 13.0 | 17 | 3.27 | 8 | 106 | **33** | | 33 | 1 |
| 7 | `c3fc8d19` | 16.3 | 20 | 2.67 | 7 | 120 | **35** | | 35 | 1 |
| 8 | `b88a083c` | 12.2 | 32 | 3.04 | 9 | 74 | **36** | | 36 | 2 |
| 9 | `0f75fe0f` | 12.1 | 6 | 3.41 | 18 | 85 | **37** | | 37 | 2 |
| 10 | `80df0785` | 12.1 | 2 | 4.54 | 8 | 115 | **37** | | 37 | 2 |
| 11 | `07513e2f` | 12.0 | 27 | 2.91 | 10 | 137 | **39** | | 39 | 2 |
| 12 | `0aff8715` | 11.9 | 16 | 4.42 | 8 | 77 | **39** | | 39 | 2 |
| 13 | `41238459` | 12.9 | 9 | 3.69 | 10 | 142 | **39** | | 39 | 2 |
| 14 | `3f0f6b50` | 14.3 | 9 | 3.73 | 10 | 129 | **41** | | 41 | 2 |
| 15 | `4077c84e` | 13.0 | 25 | 3.90 | 7 | 117 | **43** | | 43 | 3 |
| 16 | `627bd898` | 12.0 | 12 | 3.11 | 17 | 153 | **43** | 50.5 | 41.9 | 3 |
| 17 | `98e4b826` | 11.2 | 11 | 2.81 | 11 | 266 | **44** | | 44 | 3 |
| 18 | `cf53d492` | 16.0 | 16 | 4.35 | 7 | 109 | **46** | | 46 | 3 |
| 19 | `a0c92420` | 14.0 | 11 | 2.76 | 15 | 212 | **47** | | 47 | 3 |
| 20 | `e463af74` | 13.9 | 23 | 4.37 | 10 | 113 | **50** | | 50 | 3 |
| 21 | `ca612566` | 21.2 | 23 | 3.10 | 11 | 115 | **51** | | 51 | 3 |
| 22 | `1119a8ab` | 13.8 | 10 | 4.75 | 17 | 101 | **54** | | 54 | 4 |
| 23 | `fda50534` | 15.0 | 17 | 3.84 | 17 | 118 | **54** | | 54 | 4 |
| 24 | `62a3148b` | 17.9 | 37 | 3.91 | 10 | 90 | **57** | 47.6 | 57.3 | 4 |
| 25 | `d1287cc2` | 19.1 | 28 | 4.49 | 7 | 107 | **58** | | 58 | 4 |
| 26 | `f491ef01` | 10.9 | 55 | 4.41 | 17 | 119 | **64** | 45.8 | 65.2 | 4 |
| 27 | `fdb47014` | 15.6 | 45 | 4.23 | 12 | 168 | **68** | | 68 | 4 |
| 28 | `fecdce02` | 18.8 | 35 | 3.29 | 15 | 229 | **73** | 54.0 | 70.2 | 4 |

D runs from 18 to 73 (median 42). The steps hold 7 songs each, with these D′ ranges: 18–35, 36–41, 42–51 and 54–70.

What the operator's own numbers say:

- **Four songs, one day, mostly lives-mode chunks.** Today's 11 song attempts with ≥ 4 s of target include only one full
  pass. The rest are 33–180 s pieces that lives rewinds cut. A personal signal that needs full passes would see almost
  nothing, so the design pools every attempt by its target frames.
- **The static measure and the operator disagree at the top.** `fecdce02` has the highest D (73), yet it is the operator's
  best-sung song (54.0 %). `f491ef01` (D 64, low tessitura, 55 % of its time under A3) is the worst (45.8 %). Four songs
  cannot validate or refute the measure. This is the case the personal adjustment exists for.
- The pooled values sit within 6 points of the baseline, so today the adjustment moves D by at most 2.9. It grows as
  the history does.

Cost: parsing all 31 trainers takes 4.6 s wall time (about 0.15 s each). `sourceId` sits after the `points` array,
about 550 KB into the `LUMA_SONG` line of a typical song, far past the 4 KB head window `song_meta()` reads, so the
difficulty pass has to parse the whole line.

## Decision 1 — where D is computed: the Studio server

| | A. Server, from the trainer file, cached (**chosen**) | B. Written into `LUMA_SONG` at build time | C. Studio fetches each trainer |
|---|---|---|---|
| Existing songs | covered on the next server start | needs a data migration; `--rebuild` keeps the data line byte for byte | covered |
| Imported trainers | covered | not covered | covered |
| Cost | 0.15 s per file, once per (size, mtime) | none at run time | 6–40 MB per song, per page load |

- New module `studio/difficulty.py`, about 40 lines: `measure(song) -> {D, span, out, rate, leaps, sung}` with the
  anchors above as named constants, plus `of_file(path)`, which reads `window.LUMA_SONG=` with `json.JSONDecoder().raw_decode`.
- `studio_server.py`: the `/status` song entries gain `songHash` (`sourceId`, else `id`) and `difficulty` (integer D,
  or `null`). Results are cached by `(size, mtime)` like `song_meta`. On a cache miss, the file goes to a
  single-worker `ThreadPoolExecutor` and the entry says `null` until it is done. The next poll (2–15 s) carries the
  number, and `/status` never blocks. A parse error caches `null`, and that song is never autopicked.
- Lessons get a D too; Studio does not autopick them.
- Note edits a singer made in a trainer (`localStorage luma.target.<id>`) are not seen. D describes the map as built.

## Decision 2 — personal adjustment

Studio and the trainers share an origin, so Studio reads the practice history (`IndexedDB luma`, store `runs`)
directly, read-only.

- **Opening the base safely:** `indexedDB.open('luma', 1)` with an `onupgradeneeded` that calls
  `e.target.transaction.abort()`. If the base does not exist yet, the open fails and nothing is created. A bare
  `open('luma')` would create an empty version-1 base without stores, and the trainer's first write would then fail,
  because its own `onupgradeneeded` would never run. Any failure (including a future version 2 → `VersionError`)
  means "no history", and autopick runs on D alone.
- **Population:** runs whose `songHash` is a library song (lessons excluded), `level` = the level in
  `localStorage['luma.trainer.settings']` (default `normal`), `speed === 1`, `match !== null`, `target ≥ 200` frames
  (the existing `HIST.minSongFrames`). Partial attempts count, by their own frames; that is what lives mode produces.
  The map version and the view are not filtered. Autopick uses this only as a rough tuning signal and never displays it, so the full
  `cmpKey` ruler the result card needs (SESSION_FLOW Decision 2) would only make the sample smaller.
- **Baseline b:** the median `match / 100` of the last 10 such runs across all library songs. With fewer than 3 runs,
  b = 50. Today's measured value is 48.3.
- **Song result p:** pooled Σ `hit` ÷ Σ `target` over that song's last 10 such runs, used when Σ `target` ≥ 1500 frames
  (30 s). Otherwise the song has no personal value.
- **D′ = D + k × clamp(b − p, −20, 20)**, with **k = 0.5** (decided: `personal-weight`). A song sung 10 points
  under the operator's usual counts 5 points harder, and the shift is never more than ±10, about one step's width.
- Lives rewinds are not counted separately. A rewind ends a stored attempt that holds the failed passage, so a song
  that keeps costing lives already pools lower.

## Decision 3 — the progression rule

- **Steps:** library songs with a D, sorted by (D′, `songHash`), split into four equal quarters. Song at rank r of n is
  in step ⌊4r / n⌋ + 1, so n = 28 gives 7 per step. With n < 4, each song is its own step.
- **State:** `step` (1–4) and `recent` (the last picked `songHash`es, at most min(8, n − 1)).
- **Session start:** step = max(1, stored step − 1), one step easier than the last session ended (decided:
  `session-start`). The very first time, step 1. A second start inside the same open session (after «До пісень», the tile
  again) keeps the stored step, so leaving and coming back cannot ratchet the ladder down.
- **Pick:** a uniformly random song of the current step that is not in `recent` and not the song just sung. If none is
  left, the step's song picked longest ago. The pick is pushed onto `recent`.
- **After a result** (the `luma:finished` `result` from SESSION_FLOW Decision 2), with s = `result.score`:

| condition | step | why |
|---|---|---|
| s < 5 (or no score) | unchanged, and **no countdown**: the «Далі» section names the pick with «Почати» and no ring | nobody sang; never walk an empty room through the library (decided: `chain-end`) |
| `result.full === false` | −1 | in a session the song auto-sings from 0, so a pass that did not start at 0 followed a lives rewind (or a seek) |
| s ≥ b | +1 | at or above the operator's usual |
| s < b − 10 | −1 | clearly below |
| otherwise | unchanged | |

- Steps clamp to 1…4. At step 4 a good result stays at 4 and keeps picking at random within it.
- Only the **first** result of a picked song moves the step. «Повторити» shows the result card as usual, without a second
  move, and «Далі» names the same pick as before, so repeating a song cannot climb the ladder. A silent result is not a
  first result: a repeat after it moves the step as usual.
- b is the library-wide baseline from Decision 2, recomputed after each result (the run is in the history by then:
  SESSION_FLOW posts after the save). The result card's own comparison uses that song's median; the two can differ, and
  the autopick line names its own reason (below).

On today's data: b = 48.3. Starting at step 1 means a pick from songs #1–7. A pass at ≥ 48 % climbs to step 2. The
operator's four songs sit in steps 3–4, which matches their 46–54 % hovering around the baseline.

## Decision 4 — where the mode lives

**Entry (decided: `entry` = both).** The session picker that SESSION_FLOW opens after the last lesson gets one tile above
the song grid:

- «Обери за мене», a short line («Studio сам підбере пісню: спершу легші, далі складніші — з огляду на те, як ти їх
  співаєш.»), a four-bar step meter with «Почнемо зі ступеня N з 4», and «минулого разу — ступінь M» when there is a
  stored state.
- The primary button (`#autopickStart`) picks and opens the song exactly as a picker card's «Співати» does, auto-sing
  included. The grid below is headed «Або обери сам».
- While no library song has a D yet, the button is disabled and reads «Оцінюємо складність…». With no library songs,
  the tile is hidden.

The «Заняття» card on the Studio home also gets «Одразу пісні: обери за мене» (`#autopickHome`, a secondary button next to
«Почати заняття») and one line above it: the meter and «Обери за мене: ступінь N з 4 · без розспівки», N being the step a
start would use. The button opens the session overlay straight at the picked song: no lessons, one dot in the bar, and
«До пісень» leads to the same picker (without the lesson summary). It is hidden with no library songs and disabled with
«Оцінюємо складність…» while none has a D, like the tile. The card itself still appears only with the built-in lessons
present, as before.

**While autopick is on (`S.auto = true`, session memory only):**

- The «Далі» section of the song result card names `autopick.next(result)` instead of `S.songs[index + 1]`. It keeps
  the ring, cover, «Почати зараз» and «Повторити».
- One extra line under the next song: a chip «↑ складніша» / «= той самий ступінь» / «↓ легша» (from the step's actual
  move, so a good result at step 4 reads «=»), the meter, and the reason after «ступінь N з 4 ·»: «57 % ≥ твоїх звичних
  48 %», «57 % — біля твоїх звичних 48 %», «нижче звичних 48 % більш ніж на 10», «спроба з перемотуванням життів»,
  «голосу майже не було, ступінь той самий» or «повтор не змінює ступінь».
- The eyebrow ends with «· обрано за тебе».
- There is no "last song". The chain runs until × or «До пісень», which also ends autopick (`S.auto = false`) and shows
  the picker. The s < 5 rule stops the countdown when nobody sang.
- Autopick never jumps from the last lesson straight into a song. The picker with the tile is one click, and that click
  (or the one on the home button) is also the user gesture the audio needs (SESSION_FLOW Decision 4). The history is read
  between the click and the frame; `autopick.mjs` checks under the real autoplay policy that the song still starts.

Layout, measured on the prototype frames (Studio CSS, Playwright, reduced motion): at 390×844 and 1440×900 every frame
has `scrollWidth == clientWidth`, no button under 36 px or clipped, text ≥ 11 px apart from Studio's existing 10 px
status chip, and the result card's bottom at 626 px (390) and 526 px (1440), inside the first screen.

## What is stored, and where

| what | where | shape |
|---|---|---|
| difficulty | Studio server memory, rebuilt on start | `{(size, mtime): D}` per file; nothing on disk |
| progression | Studio origin `localStorage['luma.autopick']` | `{v:1, step:1..4, recent:[songHash…], at:ISO}`; unreadable or a different `v` → start fresh |
| session flag | `S.auto` in Studio memory | as `S.songs` in SESSION_FLOW: a reload returns to the library |

The practice history is read and never written.

## Activity log

One Studio event, documented in `docs/ACTIVITY_LOG.md` → Studio:

| type | data |
|---|---|
| `autopick` | `why` (`start`/`up`/`down`/`stay`/`silent`/`lives`), `from`, `to` step, `songHash` picked, `D`, `Dp` (D′), `baseline`, `score` (null on start), `pool` (how many songs the step offered after exclusions), `origin` on start (`picker`/`home`) |

A repeat logs no `autopick` event: it moves nothing and picks nothing. The clicks are logged through their ids
(`autopickStart`, `autopickHome`), and opening the picked song is a `session_next` with `how: 'autopick'`.

## Files

| File | Change |
|---|---|
| `studio/difficulty.py` (new) | `measure()`, `of_file()`, anchors; ~40 lines |
| `studio/studio_server.py` | `songHash` + `difficulty` in `/status`, cached, computed off the request thread |
| `studio/studio.html` | `autopick` (history read, D′, steps, pick, next) ~70 lines; the picker tile and the home button; the «Далі» line and eyebrow when `S.auto`; the `autopick` event |
| `tests/studio_test.py` | `difficulty.measure` cases and the `/status` contract below |
| `tests/e2e/autopick.mjs` (new), `tests/e2e/run.sh` | the autopick checks below, run after `session.mjs` |
| `README.md` («Заняття», tests, layout), `docs/ACTIVITY_LOG.md` | one paragraph; the event |

### Do not touch

- `app/app.js`, `app/head.html`, `app/workers.html`: the trainer already reports everything autopick needs through
  SESSION_FLOW's `luma:finished` result.
- The history schema, its stores and the scoring. Autopick only reads.
- `studio/build_html.py`, `studio/prepare_song.py`, song packages, `LUMA_SONG` and `lessons/`.
- SESSION_FLOW's result card, chart, countdown and auto-start protocol, except the «Далі» target and the extra line.
- The library order on the home page: autopick never reorders it.

## Dependency and order

Built on SESSION_FLOW (PR #16): its result card, `result.score`/`full` and the picker auto-sing. `app/app.js` is not
changed. The baseline and the pooled match read the trainer's stored `match`, `hit` and `target`, so a change to the
trainer's scoring (the parallel lane «Не рахувати промахи там, де немає слів») flows into them with no change here;
D reads only the notes.

## E2E checks

`tests/studio_test.py` (Python suite, run by `tests/e2e/run.sh`):

1. `measure()` on a synthetic map: notes 60, 62, 64 (1 s each, connected) give span 4 → 0, out 0, rate 1/s → 0,
   leaps 0, sung 3 s → 0, so D = 0. Ten 0.2 s notes with jumps 60→72→60 and 60→76, 30 % of the time at MIDI 76 and
   5 notes/s give the hand-computed D = 69. Ignored notes are skipped; a gap of 0.3 s breaks a jump.
2. The three built-in lessons satisfy D(lesson 1) < D(lesson 2) < D(lesson 3), measured on the note plan
   `lessons/build_lessons.py` builds their trainers from (0, 35, 41), so the check takes milliseconds instead of a build.
3. `/status` lists `songHash` and an integer `difficulty` for every fixture within 5 s of the server start, a trainer
   whose `LUMA_SONG` is truncated gets `null` for both while the others still have numbers, and a rewritten trainer is
   measured again.

`tests/e2e/autopick.mjs`, at 390×844 and 1440×900, with the fake-media flags SESSION_FLOW uses. It is its own suite,
run after `session.mjs`, because that suite's picker expects exactly its two songs:

4. **Fixtures:** seven copies of the demo trainer, each with its own `sourceId` and its melody spread and transposed so
   that D is 4, 13, 18, 20, 25, 31 and 44 (steps of 2, 2, 2 and 1), and one with its `LUMA_SONG` cut short. `/status`
   gives each its hash and D, and the cut one `null`.
5. **Fresh state:** the home card reads «Обери за мене: ступінь 1 з 4 · без розспівки»; the tile shows «Почнемо зі
   ступеня 1 з 4» and no "last time" line, and the grid is headed «Або обери сам». With `Math.random` fixed by
   `addInitScript` (no product hook), «Обери за мене» opens the easiest fixture, `luma:autostart ok:true` arrives, and
   `localStorage['luma.autopick'].recent[0]` is its `songHash`.
6. **Up:** seed the history with 3 runs at 40 %, finish the picked song with an exact pass. b = 40; the result card's
   eyebrow ends «· обрано за тебе», «Далі» names a step-2 fixture with a running 3-2-1, the chip reads «↑ складніша»,
   the reason «ступінь 2 з 4 · 100 % ≥ твоїх звичних 40 %», and the stored step is 2. After 3 s that song sings.
7. **Down / lives:** a pass sung from 0:05 to the end (`full:false`, the signal a lives rewind leaves; `session.mjs`
   already checks that a rewind itself shows no card) gives «↓ легша», step 1 and the step-1 song not picked lately.
8. **Silent:** a pass with no voice shows the pick with «Почати» and no ring, and 4 s later nothing has started. The
   stored step is unchanged.
9. **Repeat does not climb:** «Повторити» after the silent pass and a good result climb to step 2; «Повторити» again and
   another good result leave the step, the recent list and «Далі» as they were, reading «повтор не змінює ступінь».
10. **Randomness and repeats:** on a 24-song ladder, six picks inside one step (stubbed random sequence) never repeat,
    the seventh is the one picked longest ago, and two different random sequences start on different songs. D′ follows
    the personal weight: 20 under the usual → +10, 40 under → +10 (capped), 10 over → −5.
11. **History safety:** in a fresh browser profile, reading the history returns nothing and `indexedDB.databases()` has
    no `luma`. The trainer opened afterwards still creates the base and stores its runs.
12. **Session start:** with a stored step 3, the home card says step 2, and a new session's tile says «Почнемо зі
    ступеня 2 з 4 · минулого разу — ступінь 3».
13. **Home button:** «Одразу пісні» opens a song of step 2 (read from the page's own ladder, since by then the
    operator's results have shifted D′) that sings, with one dot and «До пісень» in the bar.
14. **Leaving:** «До пісень» shows the picker and sets `S.auto` off. The next finished song counts into the picker order
    again, without the reason line or «обрано за тебе».
15. **Layout:** the home card, the tile and every result card with the reason line stay within the viewport, buttons
    ≥ 36 px and unclipped, text ≥ 11 px; «Почати заняття» stays in the first screen.
16. **Activity:** the test library's `logs/activity` holds `autopick` events with `why` `start`, `up`, `lives` and
    `silent`, the `up` one with its steps, song, D, D′, baseline 40, score 100 and pool, and the clicks on both entries.
17. The console stays clean in Studio and in every frame.
18. **Real autoplay policy:** without the autoplay flag, one real click on «Одразу пісні» and no other input; the picked
    song still starts by itself.

Required checks: `tests/e2e/run.sh` in full (it runs every Python suite too). Rollout: Studio reads `studio.html` per
request, but `/status` changes, so **restart `luma-studio`** after the merge. The trainers do not change (`app/` is
untouched); the usual post-merge rebuild of lessons and trainers is harmless.

## Prototype review

Published on this task as `pr_ce9a8dbfcacd8818d09435da7765c17a`. Frames were rendered with Playwright from Studio's
own CSS at 390×844 and 1440×900, with invented titles and generated placeholder covers.

- **Variant 1 — tile in the song picker (recommended):** the picker after the lessons with the «Обери за мене» tile,
  a result card stepping up, and a result card after a lives rewind stepping down.
- **Variant 2 — plus a button on the home page:** the same, plus «Одразу пісні: обери за мене» on the «Заняття» card.

Questions as asked; the operator's answers are in [Operator decisions](#operator-decisions-prototype-review-pr_ce9a8dbf-2026-10-11)
(variants 1 and 2 chosen, every other recommendation taken):

| id | question | options | recommended |
|---|---|---|---|
| `entry` | where the mode's entry lives | picker tile · tile + home button · home button only | **picker tile** |
| `personal-weight` | how strongly personal results shift a song's difficulty | k = 0.5, capped ±10 · none (k = 0) · personal result replaces D after 3 attempts | **k = 0.5** |
| `session-start` | which step a new session starts at | one below last time · where it stopped · always step 1 | **one below** |
| `chain-end` | when the chain stops | never by itself (× or «До пісень»; stops if nobody sang) · after 3 songs · after 5 | **never by itself** |

## Deferred — not currently justified

- **Learning the comfort band from the operator's own traces** in place of the lesson-2 range A3–D5. The traces hold
  pitch per frame, so it is possible, but it is new analysis code. The personal adjustment already corrects songs that
  sit badly for the voice.
- **"Worst-sung first"** as a mode or a weight. The operator withdrew it in the same sentence.
- **Per-phrase difficulty, or picking a phrase to drill.** The quote is about songs.
- **A reroll button («Іншу»)** next to the picked song. «До пісень» already gives a free choice.
- **Autopick outside «Заняття»** (in the library grid, or in a standalone trainer). The home button opens the same
  session overlay.
- **Persisting difficulty to disk.** 4.6 s once per server start, off the request thread.
- **Tuning the weights or anchors from data.** Four sung songs on one day are not enough. The `autopick` events log
  D, D′, the baseline and the score, so the tuning can come later from evidence.
- **Showing D or the step on library cards.** It was not asked for, and a number on every card invites gaming it.
- **Counting lives rewinds as a separate penalty.** That needs a new field in the trainer's result payload; pooled
  frames already carry the failure.

## Validation against the quote

| Quote | Design |
|---|---|
| «чтобы выбирал рандомную песню… такой режим и оно вместо меня выбирает» | «Обери за мене» in the «Заняття» song picker, or «Одразу пісні: обери за мене» on the home card, opens a song Studio chose. The next song after each result is chosen too. |
| «рандомно» | Uniform random choice within the current step, excluding the last picks. Two sessions do not repeat the same order. |
| «желательно… те, которые я хуже всего пою… Наверное. Нет.» | Left out as a mode. Personal results shift a song's difficulty by up to ±10, so a song sung badly counts as harder and comes later. |
| «прогрессивно… сначала лёгкие, а потом сложнее и сложнее» | Four steps by measured difficulty. A new session starts one step easier than the last. Each result at or above the operator's usual moves one step up; a clearly worse one or a lives rewind moves one down. |
| (aware of how the operator sings — pinned goal) | Baseline and per-song pooled match from the practice history, at the operator's current level, partial lives attempts included. |

Privacy: no song titles, artists or lyrics appear in this document or the prototype. Songs are named by an 8-character
prefix of their audio hash.
