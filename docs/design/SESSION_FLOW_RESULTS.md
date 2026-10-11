# Session flow: early finish, result vs median, 3-2-1 auto-advance — implementation brief

## Originating requirement

Operator requirements, 2026-10-11, Russian voice transcripts quoted verbatim from the pinned task, in order:

> (1) «Смотри, что нужно подправить: нужно, чтобы уроки, ну, эти, во-первых, после окончания... ну, это в конце, короче,
> урока, там большая пауза, долгая, пока, типа, дождёшься, пока оно там закончит. Хотя звук уже закончился. Там после
> того, как закончилась последняя вот эта дорожка звука, ну, как по тайм-темпу, то можно и, в принципе, и завершать
> урок. Переход к следующему уроку нужно делать автомати... э-э, автоматически, там, через... чтобы таймер появлялся,
> там, типа, 3, 2, 1. Если хочешь повторить, то только тогда нажимаешь ещё раз. Если вдруг хочешь повторить. И чтобы
> автоматический запуск следующего урока спеваты тоже запускался.»
>
> (2) «Кстати, должно, после того как я прошёл, показывать мне «Congratulations». Кстати, сейчас оно переключилось само.
> Короче, должно показывать «Congratulations», должно показывать график изменений того, как я в среднем учил и
> сегодняшний, типа, лучше-хуже. Чем среднее? Или медиана лучше?» (The orchestrator recommended the median, and it was
> adopted.)
>
> (3) «И после того как я сыграл, вот у меня показывает после этого песню, я сыграл её, опять же, она закончилась,
> слишком долго после последнего обрыва закончилась, то есть на песнях тоже нужно обрывать раньше. И нужно, чтобы сразу
> переходило бы, ну, показывало, опять же, результат то же самое, и типа следующую песню. Всё, когда делаешь, сразу же
> перезагружай, деплой перезагружай.»

Obligations, checked in [Validation against the quote](#validation-against-the-quote):

1. A lesson or a song ends when its last sung sound ends, with no long tail.
2. After every finished lesson and song: a congratulation, today's score, the median of earlier attempts, better or
   worse, and a chart of past days with today on it.
3. Then a visible 3-2-1, and the next lesson or song opens **and starts recording** by itself. «Повторити» runs only
   when pressed.
4. After a song: the result, then the next song.
5. Redeploy when done.

## Measured: where the tail comes from (2026-10-11)

Read straight from the built trainers in the operator's library: the embedded song JSON, plus both stems at 1× decoded
to 8 kHz with ffmpeg and RMS measured in 50 ms windows. "Last sung" = the latest `b` of a non-ignored note or a lyric
line. "Audio end" = the last window above −50 dBFS in backing + foreground.

| Trainer | `song.duration` | last sung | duration − last sung | audio end | what fills the tail |
|---|---|---|---|---|---|
| Lesson 1 Новачок | 133.64 s | 128.66 s | **4.98 s** | 132.15 s | 3.43 s final rest (pad + clicks), then the 1.5 s `TAIL` of silence |
| Lesson 2 Середній | 199.64 s | 196.66 s | **2.98 s** | 198.20 s | 1.43 s rest, then 1.5 s silence |
| Lesson 3 Експерт | 166.68 s | 162.95 s | **3.73 s** | 165.20 s | 2.18 s rest, then 1.5 s silence |
| Library song A | 411.43 s | 359.62 s | **51.81 s** | 411.35 s | a 52 s instrumental outro, audible to the last 0.1 s |
| Library song B | 262.13 s | 252.64 s | **9.49 s** | 258.25 s | 5.6 s fading outro, then 3.9 s of silence in the file |
| All 28 library songs | | | median **8.2 s**, max 51.8 s; > 10 s in 11 songs, > 20 s in 5 | | silence at the very end: median 3.6 s, max 9.4 s |
| Demo (`examples/demo`) | 33.50 s | 29.46 s | 4.04 s | 33.50 s | backing runs to the end |

**Cause.** A sung attempt over the whole song is planned to end at `song.duration`. `nextSegment()`
(`app/app.js:383`) returns `end: s.range.b` (= `song.duration` with no fragment selected) or `end: song.duration`.
`startTransport()` schedules the sources and the worker's `record` window to that end, and the attempt stops only there,
with `reason:'end'`. `onFinished()` (`app/app.js:879`) waits only until that same planned end plus the latency setting
(default 0), so it adds nothing of its own. The 4.1 s `endTimer` margin is a fallback that never fires on the normal
path. The tail is therefore **`song.duration` minus the last sung note**:

- **Lessons, 3–5 s:** the final rest beats and the `TAIL = 1.5` s constant in `lessons/build_lessons.py:33` (clicks
  continue until `duration − 1.5`).
- **Songs, 0–52 s (median 8 s):** the recording's instrumental outro and its trailing silence.

In a session the wait grows further. `finishStep()` holds for 1.2 s. The next intro card counts down 5 s. Then the
singer clicks «Співати», and the trainer counts in for 2.1 s. That is about 8 s plus a click on top of the tail.

Prior work: a superseded brief stage on this task (`docs/design/LESSON_AUTOADVANCE.md`, never landed) measured the same
lesson numbers. Its prototype review is the source of the pinned layout below. Memory searches found nothing else
relevant.

## Pinned: the card layout (operator decision, 2026-10-11)

On the review «Відлік 3-2-1 між уроками в «Занятті»» (`pr_eef12277424a05d993fb0ca0a25cfdf6`), published by the
superseded brief, the operator chose **variant 1 — «Відлік на картці наступного уроку»**, with no comment. Variant 2
(a panel sliding over the finished trainer) was rejected. That choice binds this design:

- The countdown sits **on the next step's intro card**, with primary «Почати зараз» and secondary «Повторити урок N».
  After the last lesson the same card leads to the song picker, and its primary reads «До пісень».
- The **result block** (headline, today vs median, delta, small chart) goes **on that same card, above the 3-2-1**.
  There is no separate result screen, overlay or second frame.
- **After a song** the same card pattern is used: the result block above a 3-2-1 into the next song, with «Почати
  зараз», «Повторити» and «До пісень».
- The prototype published by this stage (`pr_4d44e715…`, see [Prototype review](#prototype-review)) keeps this layout
  on every frame. Its two variants differ only in the chart form inside the card, and it offers no layout choice.

## Pinned: answers to this stage's review (operator decision, 2026-10-11)

On «Результат після уроку чи пісні, медіана і відлік 3-2-1» (`pr_4d44e715e7d3990c827276c494a45a17`) the operator
took every recommended option, with no comment:

| Question | Pinned answer | Where it applies |
|---|---|---|
| Chart | **Variant 1 — «Стовпчики по днях + лінія медіани»**: one column per day, today highlighted, a dashed median line | [The card, copy and chart](#the-card-copy-and-chart-pinned-layout-chart-variant-1) |
| After the last song in the library | **Stop**: the result and «До пісень», with no countdown and no wrap to the first song | Decision 3, next-song order |
| A song picked with «Співати» in the picker | **Starts recording right away** after the trainer's short count-in (0.6 s) | Decision 4 |
| Countdown on the result card | **3 seconds (3-2-1)**, with no pause on hover and no stop button | Decision 3, «Далі» section |
| What today is compared with | **The median of all earlier full passes on the same settings** (same `cmpKey`: song · note map · level · view · speed), earlier attempts today included | Decision 2 |

The variant-2 line chart is dropped. These answers and the card layout above are settled; the implementer builds them
as written.

## Decision 1 — the finish rule (every trainer, standalone too)

| | A. Trainer ends a sung pass at the last sung sound (**chosen**) | B. Shorten the audio at build time | C. Detect silence in the audio at run time |
|---|---|---|---|
| Lessons | fixed | `TAIL`/final rest cut in `build_lessons.py` | fixed (lessons end in silence) |
| Songs | fixed, outro included | re-encode 28 songs and change `duration` | **not fixed**: song A's outro is audible to the end |
| History | unchanged: no target frame lies after the last note, so the score, `target` and `songTarget` are identical | a lesson's `songHash` is the sha256 of its synthesized mix, so a new mix **orphans all lesson history** | unchanged |
| Cost | ~10 lines in `app/app.js` | a rebuild, a history migration | fragile thresholds, a decode pass |

B breaks the history, and C misses the case the operator named in (3). **A** cuts the sung attempt at the end of the
singing and leaves the files alone.

```js
// A sung pass ends with the last thing to sing: the latest note or lyric line, plus a short release, never past the
// audio. The outro and the silence after it are not part of the attempt (docs/design/SESSION_FLOW_RESULTS.md).
const RELEASE=.5;let singEndCache=0;
function singEnd(){if(singEndCache)return singEndCache;let e=0;for(const n of song.notes)if(!n.ignored&&n.b>e)e=n.b;for(const l of song.lyrics||[])if(l.b>e)e=l.b;return singEndCache=e>0?Math.min(song.duration,e+RELEASE):song.duration;}
```

- Reset `singEndCache=0` in `invalidateMap()` (`app/app.js:456`). That covers note edits, imports and «Інша пісня».
- `nextSegment(sing)`: when singing **without a selected fragment** (`!customRange()`), the end is `singEnd()` instead
  of `s.range.b` / `song.duration`. The same applies to the punch branch (`Math.max(planEnd, punch.endSong)`). The
  "back to the start" test becomes `s.pos >= (sing&&!cr ? singEnd() : song.duration) - .1 ? 0 : s.pos`. Without it, a
  second «Співати» after a finished pass would start at `singEnd()` and record nothing.
- An explicit fragment keeps its own end (`s.range.b`), and listening (`sing=false`) still plays to `song.duration`.
  Neither was asked to change.
- **Finished** = `m.reason==='end'` and `take.endSong >= singEnd() - .25`. `tellHost` uses this in place of
  `song.duration - .25`. A stopped attempt (`'user'`), a lives rewind (`'lives'`), a seek or an attempt that never
  reaches the last note still never counts. An attempt started midway that runs to the end still counts, as it does now.
- With latency 0 the attempt stops 0.5 s after the last sung sound, and it is saved and scored as before (`storeTake`
  → `saveRun`). The `record` window, `endTimer` and `onFinished` need no change: they all follow `s.transport.end`.

## Decision 2 — the result: computed by the trainer, shown by Studio

Rejected: Studio opens the `luma` IndexedDB itself. It is the same origin, but Studio would have to know `songHash`,
`cmpKey` and the full-pass rule (`HIST.songCover`, `minSongFrames`), which live only in `app.js`. The trainer already
holds `s.hist.runs` for its song.

**`tellHost` is extended** and posted once the attempt's history write has settled (`saveRun(take).then(saved=>…)`).
Studio drops the frame right after the message, and the write must not be cut off by the frame going away:

```js
parent.postMessage({type:'luma:finished', file, match /* as today */, result:{
  score,     // this attempt, Math.round(run.match/100)
  full,      // the attempt is a full pass (≥ 95 % of songTarget and ≥ 200 frames: the Progress tab's own rule)
  from,      // run.a in seconds, for the "started midway" line
  median,    // integer %, or null when nothing to compare with
  prev,      // how many earlier attempts the median is over; null when the history could not be read
  days,      // up to 6 earlier days: [{day:'2026-10-09', value: median % of that day, n}], oldest first
  ruler,     // 'Звично · Ноти · 1×': what the numbers are counted under
  saved}},   // false when the history write failed (the attempt stays in the trainer's list, as today)
  location.origin);
```

- **Population for the median:** earlier attempts in `s.hist.runs` with the same `cmpKey` (song · note map · level · view
  · speed) that are full passes, excluding this run's `id`. This is the population «Прогрес» → «Вся пісня» already uses
  (`scopeEntries`). A different level or speed is a different ruler, and mixing it in would make "better/worse" false.
  Earlier attempts **today** are included. «Медіана» means all earlier full passes.
- **Median:** the true median, averaging the two middle values for an even count. The existing `median()` helper takes
  the upper middle, so do not reuse it.
- **Days:** earlier full passes grouped by `localDay` (the history's 04:00 boundary). Each day's value is that day's
  median. Take the last 6 days before today. Today's bar is this attempt.
- `prev:null` when `!s.hist.loaded || s.hist.stale` (history unreadable), and `days:[]` when `prev===0`.

## Decision 3 — screens in Studio (`studio/studio.html`)

### State machine (changes in bold)

```
HOME ─«Почати заняття»→ NEXT(lesson 1) ─3-2-1 or «Почати урок»→ LESSON(1, auto-sing)
LESSON(n) ─finished→ **RESULT(n) + NEXT(n+1)** ─3-2-1 / «Почати зараз»→ LESSON(n+1, auto-sing)
          ─«Пропустити урок»→ NEXT(n+1) (no result section)            «Повторити урок n»→ LESSON(n, auto-sing)
LESSON(last) ─finished→ **RESULT + NEXT(picker)** ─3-2-1 / «До пісень»→ PICKER
PICKER ─card «Співати»→ **SONG(s, auto-sing)**
SONG(s) ─finished→ **RESULT(s) + NEXT(next song)** ─3-2-1 / «Почати зараз»→ SONG(next, auto-sing)
        «Повторити»→ SONG(s, auto-sing) · «До пісень»→ PICKER · last song: RESULT(s) only, no countdown
× / Back from any state → HOME
```

- One card component (the [pinned layout](#pinned-the-card-layout-operator-decision-2026-10-11)) replaces today's
  intro card: an optional **result section** above a **«Далі» section** with the countdown. A skipped lesson and lesson 1 get the «Далі» section only. That is today's intro card, with the 5 s wait
  becoming 3-2-1 and auto-sing.
- `finishStep()` loses the 1.2 s hold: Studio shows its own result now, and the trainer's in-frame result is not needed.
  On `luma:finished` the frame is dropped and the card appears at once.
- Accept `luma:finished` from the current frame when `S.phase==='lesson'` and `file===S.steps[S.i].html`, **or**
  `S.phase==='song'` and `file===S.song.name`. The origin, source and type checks stay as they are.
- **Next-song order** = the picker's order. Take a snapshot `S.songs = librarySongs.slice()` when the picker opens, so a
  15 s `/status` poll cannot reorder the queue mid-session. That order is the server's mtime-newest-first. The next song
  is `S.songs[index(S.song)+1]`. After the last one there is no countdown, and the primary is «До пісень»
  (pinned: stop, no wrap).
- **After the last lesson** the countdown leads to the picker as today. It does not jump into a song: nothing is
  "obvious" before the operator has picked one, and remembering a song across sessions would be new storage.
- **«Повторити»** reloads the same trainer in a new frame and auto-sings. That means one frame at a time, as now, at the
  cost of a 6–40 MB load from localhost.
- **Skip/close during the countdown:** the countdown is a `later()` timer, so `nextPhase()` cancels it. In RESULT(n)
  the bar is already on lesson n+1: the current dot and the label «Урок n+1 з N». «Пропустити урок» skips that lesson,
  marks it `skipped` and shows NEXT(n+2) or the picker. In RESULT(song) the bar button reads «До пісень». × leaves.
- The next frame is preloaded hidden while the card counts down, as intro cards do today. If it has not loaded at 0,
  «Почати зараз» reads «Завантажуємо…» and auto-sing follows the frame's `load`.

### The card, copy and chart (pinned layout, chart variant 1)

| Case | Headline | Line | Number cells |
|---|---|---|---|
| full pass, `score − median ≥ +2` | «Чудово!» | «Сьогодні краще за твою звичну спробу на N пунктів.» | `81 %` сьогодні · `70 %` медіана · K спроб · `+11` до медіани (mint dot) |
| full pass, within ±1 | «Готово!» | «Рівно на рівні твоєї медіани.» | delta `0` (grey dot) |
| full pass, `≤ −2` | «Готово» (no "!") | «Цього разу на N пунктів нижче за медіану. Буває — рахуються всі твої дні.» | `−6` від медіани (amber dot) |
| first attempt (`prev===0`) | «Перший прохід!» | «Історії ще немає — цей результат стане точкою відліку.» | score only; the median and delta cells are omitted |
| not a full pass (started midway, e.g. after a lives rewind) | «Готово!» | «Спроба почалася з m:ss — з повними проходами не порівнюємо.» | score and median, no delta |
| history unreadable (`prev===null`) | «Готово!» | «Історія зараз недоступна, тож порівняння не буде.» | score only |
| `saved===false` | as above | adds «Спробу не записано в історію — вона лишилась у тренажері.» | |

- Eyebrow: «Урок 1 з 3 · Новачок · пройдено» or «Пісня · «<title>» · завершено». Here the song title is the app's own
  data, rendered at run time.
- Plurals «пункт / пункти / пунктів» and «спроба / спроби / спроб» need a 3-line `plural()` in Studio, the same rule
  as the trainer's.
- **Chart:** one series. An inline SVG built with `el()`, sized to the measured width of `.rchart`, so labels stay 11–12
  px. In the prototype they shrink at 390 px because the SVG is scaled; the implementation must not scale it.
  - y runs 0–100 % with hairline grid lines at 0/50/100. One column per day, ≤ 24 px wide, with a 4 px rounded top.
    Earlier days are `#5d6a80`; today is `--mint`, with its value directly above. When that label falls within 16 px
    of the median line it is lifted above the line.
  - The median is a 1.5 px dashed `--amber` line labelled «медіана 70 %» at the left edge. Day labels read «6.10» and
    «сьогодні».
  - Each column has a `<title>` («6.10: 66 %»). The SVG has `role="img"` and an `aria-label` that lists the values.
  - Caption: «Збіг повних проходів по днях · <ruler>»; on a first attempt, «Наступні дні з’являться тут поруч».
  - The colour pair passed the dataviz validator's CVD (ΔE 32.7) and contrast checks on `--panel`. Identity is never
    colour alone: today is also labelled.
- **«Далі» section:** a 56 px ring with the number (3 → 2 → 1, one step a second, the ring empties). It shows «Далі ·
  почнеться сам за 3 с» and the next item: «Урок 2 · Середній · 3:20», the next song with its 44 px cover (the existing
  `coverBox`), or «Вибір пісні». Buttons: primary «Почати зараз» (`#resultNow`; «До пісень» after the last lesson),
  secondary «Повторити урок n» / «Повторити» (`#resultRepeat`), and on songs «До пісень» (`#resultSongs`).
- The polite live region announces the result once and «Далі урок 2 за 3 секунди». Ticks are not announced. Focus goes
  to «Почати зараз».
- Reduced motion: no rise or ring animation. The 3 s timing stays, because it is timing.

### Layouts (measured on the prototype)

| | 390×844 | 1440×900 |
|---|---|---|
| Card | full width minus 12 px margins, top-aligned, bottom at 656 px: no scroll | 520 px max, centred, bottom ≤ 755 px |
| Number cells | 3 columns, 20 px numbers; labels wrap to two lines | 3 columns, 24 px numbers |
| Buttons | primary full width; secondary buttons share the next row; all 46 px tall | one row; 46 px |
| Overflow | `scrollWidth == clientWidth` on every frame | same |

The bar stays as today: a 40 px icon × at 390, «Завершити» text at desktop, dots and the skip button.

## Decision 4 — auto-start protocol and the mic/autoplay fallback

**Fact (probed 2026-10-11, Chromium 1243 and Chrome stable, default autoplay policy, no `page.evaluate` gestures):**
with no click, a new `AudioContext` in a same-origin iframe stays `suspended` and `resume()` never settles. After one
real click in the parent page, an iframe created **3 s later** gets a `running` context at once, with or without
`allow="autoplay"`. The session's «Почати заняття» click therefore unlocks every later frame in the same tab. The frame
keeps `allow="microphone; autoplay; fullscreen"`, and the microphone grant is per origin, as today. Firefox and Safari
were not probed. The fallback below covers them.

```
Studio                                               trainer (frame)
 frame load event ──── {type:'luma:sing'} ─────────▶ autoSing()
                                                     ensureContext() raced against 1.5 s
                                                       not running → reply ok:false, reason 'audio'
                                                     closeTrace(); s.pos = song.initialTime||0
                                                     await startTransport(true, quick=true, fresh=true)
 ◀── {type:'luma:autostart', file, ok, reason} ───── ok = s.mode==='singing'; else reason 'mic' | 'busy' | 'other'
 ok:false → fallback card over the frame
 «Почати співати» (#autostartBtn, a real click in Studio) ── {type:'luma:sing'} again ──▶ (now allowed)
```

- **Trainer side** (`app/app.js`, ~15 lines):
  - A `message` listener that accepts only `e.source===parent`, `parent!==window`, `e.origin===location.origin` and
    `type==='luma:sing'`.
  - `autoSing()` replies `busy` unless the trainer is idle, not busy and not awaiting a finish. It uses `quick=true`
    (0.6 s lead-in), so the Studio 3-2-1 is the only countdown. It uses `fresh=true`, so a shown trace never turns the
    pass into a punch-in.
  - `ensureContext()` builds the gain graph **before** `await s.ctx.resume()`. A context whose resume is still pending
    is then complete, and a later call after a gesture just resumes it.
  - The reason is `mic` when `startTransport` ended in a mic error (`errorKind`).
  - Test hook: `Luma.test.autostartBlock = 'audio'` makes the next `autoSing` reply `ok:false` with that reason.
- **Studio side:** post `luma:sing` on the frame's `load` whenever the step was opened by the session: countdown, «Почати
  зараз», «Почати урок», «Повторити», or a picker card.
  - On `ok:false`, show a card over the frame: «Урок 2 готовий» / «Пісня готова».
    - audio: «Браузер не дав увімкнути звук сам. Натисни — і запис почнеться після короткого відліку.»
    - mic: «Мікрофон недоступний: дозволь доступ (значок біля адреси) і натисни ще раз.»
    - Primary «Почати співати» (`#autostartBtn`, 52 px), secondary «Сам натисну «Співати»» (`#autostartDismiss`), which
      hides the card. The trainer's own «Співати» works underneath.
  - While a mic permission prompt is open, the trainer is still awaiting `getUserMedia` and does not reply. The browser
    prompt is visible, so there is never a silent dead state.
- **Picker card «Співати» auto-sings too.** The click is the gesture, and it is what «Співати» says (pinned:
  recording starts right after the trainer's short count-in).

## Activity log

Clicks on the new buttons are logged by `activity.js` through their ids (`resultNow`, `resultRepeat`, `resultSongs`,
`autostartBtn`, `autostartDismiss`). Add three Studio events and document them in `docs/ACTIVITY_LOG.md` → Studio:

| type | data |
|---|---|
| `session_result` | `kind` (`lesson`/`song`), `file`, `score`, `median`, `prev`, `delta`, `full`, `saved`, `next` (file, `picker` or `null`) |
| `session_next` | `from`, `to`, `how` (`countdown`/`now`/`repeat`/`skip`/`songs`/`picker`) |
| `session_autostart` | `file`, `ok`, `reason`, `ms` from `luma:sing` to the reply |

## Files

| File | Change |
|---|---|
| `app/app.js` | `singEnd` + reset in `invalidateMap`; `nextSegment` end and restart rule; `tellHost` rule and payload, posted after the save; `ensureContext` order; `luma:sing` listener + `autoSing`; `Luma.song().singEnd`, `endSong` in `diagnostics().takes`, `test.autostartBlock`. ~30 lines |
| `studio/studio.html` | result + «Далі» card, chart, countdown, auto-sing protocol, fallback card, song steps and next-song queue, CSS for both widths, the three activity events |
| `tests/e2e/finish.mjs` (new), `tests/e2e/session.mjs`, `tests/e2e/run.sh` (add `finish` after `lessons`) | below |
| `docs/LESSONS.md` (Заняття section), `README.md` (Studio and Tests), `docs/ACTIVITY_LOG.md` | describe the new flow; the "finished" definition becomes "runs to the last sung note" |
| `docs/design/GUIDED_SESSION.md` | one line at the top: the finish rule, intro timing and the song step are superseded by this document |

### Do not touch

- `lessons/build_lessons.py` and `lessons/definitions.py`. A new mix changes the lessons' `songHash` and orphans their
  history, and `tests/e2e/lessons.mjs` pins the lengths.
- Song packages, `target.json`, `duration`, the MP3s, `studio/build_html.py`, `studio/prepare_song.py`.
- `app/workers.html` (recording and stop), scoring (`analyzeTake`, `summarizeRun`, `scoreAdvance`), the history schema
  and stores, the Progress tab, lives mode logic.
- `app/head.html`: the trainer needs no new UI.
- `studio/studio_server.py`: no new route; `studio.html` is read per request.
- Listening and explicit fragments keep their ends.

## E2E checks to add

`tests/e2e/finish.mjs`: standalone demo trainer, plus Lesson 1 from the test Studio library opened top-level. Launch
with `--use-fake-device-for-media-stream --use-fake-ui-for-media-stream --autoplay-policy=no-user-gesture-required`.

1. `Luma.song().singEnd` equals `min(duration, max(last non-ignored note b, last lyric b) + 0.5)`: 29.96 s on the demo.
2. **Early finish, real transport:** seek to `singEnd − 3`, press «Співати». Mode returns to `idle` within
   `3 + 0.6 + 0.8` s of the press. The take's `endSong` is within 0.05 s of `singEnd`, and there is one new take in
   `diagnostics()` and one new run in the history with `b ≈ singEnd`. Run this on the demo and on Lesson 1.
3. The next «Співати» starts again from 0: `diagnostics().time < 1` once singing.
4. The score is unchanged: two fake passes with identical pitches, `fakeSing({a, b: singEnd})` and
   `fakeSing({a, b: duration})`, give the same `pct` and the same run `target`/`hit`.
5. A fragment that ends at `song.duration`, and listening, still run to `song.duration`.

`tests/e2e/session.mjs`: extend, at 390×844 and 1440×900, launched with the fake-media flags:

6. `sing(frame, true)` sings to `Luma.song().singEnd`, and the finish arrives. Stopping short (`d − 10 … d − 5`) still
   does not finish. A user stop 1 s before `singEnd` does not finish either.
7. **Result without history** (fresh context): headline «Перший прохід!», a score cell, no median cell, a chart with
   one column marked today.
8. **Result with history:**
   - Seed IndexedDB `luma.runs` in the Studio page: clone the run just written, with new ids, `startedAt`/`localDay`
     on three earlier days, and chosen `match` values.
   - Finish lesson 1 again via «Повторити урок 1». The median equals the true median of the seeded values plus the
     first run, and the delta sign matches. There are 4 columns, the last one today. The headline is «Чудово!» or
     «Готово».
9. **Countdown → auto-start:**
   - The ring number reads 3, then 2, then 1 (sampled at 0 / 1.1 / 2.1 s), with no click.
   - Lesson 2's frame is shown, `luma:autostart ok:true` arrives, and the frame's `diagnostics().mode==='singing'`
     within 6 s of the result.
10. **Real policy:** a second browser with **no** autoplay flag (fake media only). A real `page.click('#sessionStart')`,
    then «Почати урок»: auto-start `ok:true`. No `page.evaluate` may run in the Studio page before this point, because
    Playwright marks it as a user gesture.
11. **Fallback:** set `Luma.test.autostartBlock='audio'` in the preloaded frame. The card shows `#autostartBtn` inside
    the viewport, ≥ 44 px tall. A real click on it gives `ok:true` and mode `singing`.
12. **Repeat:** «Повторити урок 1» shows the same file in the frame, singing within 6 s.
13. **Skip and close during the countdown:** «Пропустити урок» on RESULT(1) marks dot 2 `skipped` and shows NEXT(3)
    without a result section. × during that countdown hides the overlay, and after 4 s there is no frame and no new
    `luma:autostart`.
14. **Songs:**
    - Picker → first fixture card → auto-start `ok:true`. Sing to `singEnd`, and the result card names the next
      picker card. After 3 s its file is in the frame and singing.
    - «До пісень» returns to the picker.
    - The last card in picker order gives a result card with no ring, and «До пісень» is the primary.
15. **Lives:** with `luma.trainer.settings` `{lives:true}`, a lives rewind take (the `lives.mjs` drive) shows no result
    card.
16. **Layout:**
    - The card's bottom is ≤ the viewport height, and `scrollWidth == clientWidth`.
    - Every visible button is ≥ 36 px tall and unclipped.
    - The chart SVG's text has a computed font-size ≥ 11 px.
    - Reduced motion: the card is present within 100 ms, and the countdown still takes 3 s.
    - Screenshots `shot_session_result_*_<width>.png` (gitignored).
17. **Activity:** with logging on, the test library's `logs/activity` holds `session_result`, `session_next` and
    `session_autostart` for the Studio session.
18. The console stays clean in Studio and in every frame.

Required checks: `tests/e2e/run.sh` in full (it also runs every Python suite).

## Rollout

The operator asked to redeploy when this is done. Right after the merge, in the main checkout (`~/Projects/luma`), do
this without asking:

1. Re-wrap the lessons: `.venv/bin/python lessons/build_lessons.py --songs songs`.
2. Rebuild every song trainer with the new `app.js`: `.venv/bin/python studio/build_html.py --rebuild
   songs/Luma_*.html`. An old song trainer neither finishes early nor auto-sings.
3. Restart Studio through its user unit: `XDG_RUNTIME_DIR=/run/user/1000 systemctl --user restart luma-studio` (port
   8792). The unit's `ExecStartPre` also runs step 1.
   - `studio.html` is read on every request, so the restart is not strictly needed for it. It is the standard
     redeploy, and it keeps the server on the merged code.
   - Never start Studio with `nohup`/`setsid` from an agent: that process dies with the agent's session.
4. Check `curl -fsS http://127.0.0.1:8792/status`, then ask the operator to reload the Studio tab.

Note: `--rebuild` rewrites every file, and the library is ordered by mtime, so a rebuild reorders the library. That
order is also the next-song order. It already happened on today's 13:50 rebuild.

## Prototype review

Published on this task as `pr_4d44e715e7d3990c827276c494a45a17`. Frames were rendered with Playwright from Studio's own
CSS at 390×844 and 1440×900, with invented titles and generated art. Measured on every frame: 0 px horizontal overflow,
no clipped or sub-36 px button, and the card inside the first screen.

Every frame uses the [pinned layout](#pinned-the-card-layout-operator-decision-2026-10-11): one card, the result
block above the 3-2-1, then «Почати зараз» and «Повторити урок N» (or «Повторити» and «До пісень» after a song).
The two variants differ **only in the chart inside the card**:

- **Variant 1 — columns per day + median line (recommended):** lesson better than the median, song worse with the next
  song, first attempt, after the last lesson, last song (no countdown), and the autoplay fallback card.
- **Variant 2 — line per day + median line:** the same card. It is more compact, and one or two points read worse than
  columns.

One wording difference from the frames: after the last lesson the frame's primary reads «До пісень зараз». The pinned
label is «До пісень», as in the operator's chosen variant.

The review also asked four questions. The operator chose variant 1 and every recommended answer; see
[Pinned: answers to this stage's review](#pinned-answers-to-this-stages-review-operator-decision-2026-10-11).

## Deferred — not currently justified

- **Pausing the countdown** (hover, or a «Стоп» button): the quote asks for 3-2-1, and Skip, «Повторити» and × already
  stop it. The operator chose a plain 3 s countdown in the review.
- **Keeping the finished frame alive for «Повторити»** (avoids one reload): two frames and more state for a 1–2 s
  saving.
- **Jumping from the last lesson straight into a song** remembered from an earlier session: this needs new storage, and
  nothing marks a song as "obvious" yet.
- **The result card in standalone trainers:** the quote is about the session. A standalone trainer already shows the
  attempt and its record line.
- **Trimming the lesson `TAIL` or the song files:** this breaks lesson history (Decision 1).
- **Preserving mtime in `build_html.py --rebuild`**, so a rebuild does not reorder the library: worth a separate small
  change.
- **Comparing a lives-mode completion that started midway** against full passes: it shows the score and median without
  a delta. Merging the takes of one lives run is a scoring change.

## Validation against the quote

| Quote | Design |
|---|---|
| «в конце урока большая пауза… хотя звук уже закончился… после того, как закончилась последняя дорожка звука… завершать урок» | A sung pass ends 0.5 s after the last note or lyric (Decision 1). Measured tails of 3–5 s (lessons) and 0–52 s (songs) go away, and the cause is named: the planned end was `song.duration`. |
| «Переход к следующему уроку… автоматически… таймер 3, 2, 1» | The result card's «Далі» ring counts 3-2-1 and opens the next lesson. |
| «Если хочешь повторить, то только тогда нажимаешь ещё раз» | «Повторити» exists only as a button. Nothing repeats by itself. |
| «автоматический запуск следующего урока… тоже запускался» | `luma:sing` → `autoSing()` starts recording after a 0.6 s count-in. A visible «Почати співати» appears if the browser refuses. |
| «показывать «Congratulations»… график… в среднем… и сегодняшний… лучше-хуже… медиана» | «Чудово!» / «Готово», today vs the median of earlier full passes with the delta, and columns per day with today highlighted and a median line. «Перший прохід!» when there is no history. |
| «на песнях тоже нужно обрывать раньше» | The same rule in every trainer: song A stops 52 s earlier, the typical song about 8 s earlier. |
| «сразу переходило… показывало результат… и следующую песню» | The song result card, then 3-2-1 into the next song in picker order, which auto-sings. «До пісень» picks another. |
| «деплой перезагружай» | Rollout: right after the merge, re-wrap the lessons, rebuild the song trainers, restart the `luma-studio` unit, check `/status`. |

Privacy: no song titles, artists or lyrics appear in this document or the prototype. Library songs are named "A" and
"B" by their measurements only.
