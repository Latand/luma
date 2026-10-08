# Activity log: what the operator does in Luma, for UX and singing analysis

Luma Studio and every trainer it serves record what the operator does: clicks on controls, tab and mode switches,
settings, play / record / stop / seek / loop / range choices, song and lesson opens and closes, time spent, toasts and
errors shown, and a summary of every finished attempt. The point is to let an analysis agent, run now and then, tune the
UX to how Luma is really used and follow how the singing changes over time.

Everything stays on this computer. Luma Studio writes the events into the library folder; nothing is sent anywhere
else.

## Where the files live

```
songs/logs/activity/2026-10-07.jsonl     one file per local calendar day of the Studio machine, append-only
```

`songs/` is the library folder Studio was started with (`--songs`, default `songs/` in the repository; it is
gitignored). Each line is one event in JSON. A file is never rewritten; deleting files is the way to forget.

`studio/activity_report.py [--days 30 | --since YYYY-MM-DD] [--songs DIR]` prints a compact Markdown digest of the
chosen days (time per page, most used controls and keys, setting and state switches, toasts and errors, every song's
attempts with the match trend and the weakest phrases). Read it first, then go to the raw lines for detail.

## What logs and what does not

- **Logs:** pages Luma Studio serves: Studio itself (`/`), trainers under `/song/<file>.html`, and `/demo`.
- **Silent:** a trainer opened from `file://` or from any other server. The logger is in the trainer file, but it never
  sends from those pages.
- **Off switch:** the line «Записувати мої дії» at the bottom of Studio. It is stored in `localStorage['luma.activity']`
  (`'off'` / `'on'`, on by default) of the Studio origin, so it switches every trainer of that Studio too, open tabs
  included. Switching off writes one last `logging_off` event; switching on writes `logging_on`.
- **Failures never show:** each logger entry point swallows its own errors. A batch the server refuses or cannot write
  is dropped. A tab keeps at most 400 events waiting while the server is away.
- **Old trainers:** a trainer built before the logger existed logs nothing until it is rebuilt with
  `studio/build_html.py --rebuild songs/Luma_*.html`. Built-in lessons are rebuilt by `studio/luma-studio.sh` on its next
  start, because their fingerprint includes `app/activity.js`.

## Transport

`app/activity.js` is one script shared by Studio (served at `GET /activity.js`) and the trainers (embedded by
`studio/build_html.py` in front of `app/app.js`). It queues events and sends them as `POST /activity` with the body
`{"events":[…]}`: after 10 s, at 40 events or 24 KB, when the tab is hidden, and on `pagehide`. It uses
`navigator.sendBeacon`, which outlives the page, and falls back to `fetch(…, {keepalive: true})`.

The server (`studio/studio_server.py`) refuses:

| status | when |
|---|---|
| 413 | the body is over 64 KiB (it is not read) |
| 400 | an empty body, broken JSON, no `events` list, more than 200 events, any event that is malformed or over 16 KiB as a line |
| 403 | an `Origin` header from another site; requests without `Origin` (local scripts, tests) are accepted |

A batch is all-or-nothing: either every event of it is appended, or none. A good batch gets `204`.

## Event schema

```json
{"v":1,"ts":"2026-10-07T10:47:35.622Z","session":"a9c3…","page":"demo","seq":3,"type":"click",
 "data":{"id":"lyricsBtn","label":"Показувати слова пісні","area":"chartWrap"}}
```

| field | meaning |
|---|---|
| `v` | schema version, `1` |
| `ts` | ISO 8601 time in UTC, from the browser clock |
| `session` | random id of one page load; a reload or a new tab is a new session |
| `page` | `studio`, `demo`, or the trainer's file name without `.html` (`Luma_<slug>`, `Luma_Lesson_01_…`) |
| `seq` | 1, 2, 3 … within the session, so ties in `ts` keep their order |
| `type` | event type, below |
| `data` | the event's payload, below |

Lines from one session can land in different batches and, past midnight, in two day files; sort by `session`, `seq`.

### Events on every page

| type | data |
|---|---|
| `page_open` | `kind` (`studio` / `trainer`); for a trainer `songHash`, `songId`, `lessonId`, `duration` s, `notes`; `from` (`studio` when opened from the Studio page), `restored` (back/forward cache), `viewport` [w, h], `coarse` (touch screen) |
| `page_close` | `openMs`, `visibleMs` (time the tab was in front), `persisted` |
| `visibility` | `state` (`visible` / `hidden`), `visibleMs` so far |
| `click` | `id`: the control's element id, else its first `data-*` attribute (`level:strict`, `view:notes`, `close:settingsDialog`), else tag and class inside the nearest element with an id (`takesList button.play`); `label`: aria-label, label, title or text, ≤ 60 characters; `area`: the dialog, section or region it sits in; `href` for links (`song:Luma_<slug>`, `/demo`, `external`); `noPointer` when the click came from Enter/Space or a script. Never coordinates. |
| `change` | `id`, `label`, `area`, `kind` (input type); `value` for checkboxes, ranges, numbers and short select values (`#index` for long ones); for files `files`, `ext`, `mb`; typed text is only `filled: true/false` |
| `key` | `key` (`KeyboardEvent.code`), `mods` (`ctrl+shift`…); keys typed into fields are not logged |
| `details` | a `<details>` opened or closed: `id` (or its summary text), `open` |
| `dialog` | a dialog closed (button, Esc or backdrop): `id`, `open: false` |
| `js_error` | an uncaught script error or rejection: `message`, `source`, `line` |
| `logging_off` / `logging_on` | the Studio switch |

### Studio

| type | data |
|---|---|
| `notice` | the upload notice shown (`id: uploadNotice`, `text`), or the connection lost (`id: connectionNotice`) |

Opening a song or a lesson from Studio is a `click` whose `href` is `song:<file>`; the trainer then logs its own
`page_open` with `from: "studio"` in a new session.

### Trainer

| type | data |
|---|---|
| `state` | what changed since the previous `state` of the session; the first one is the full starting state. Keys: `mode` (`idle`, `listen` = playing, `singing` = recording, `review` = playing an attempt back), `view` (`notes` / `contour`), `level` (`easy` / `normal` / `strict` / `custom`), `tolerance` ¢, `speed`, `loop`, `tab` (`takes` / `progress`), `rangeId` (phrase id; `0` whole song, `-1` own range), `range` [a, b] s, `octave`, `vocal`, `lyrics`, `shadow`, `audio` (WAV recording switch), `takesOpen`, `review` (run id of the attempt on screen or `null`) |
| `seek` | `from`, `to` s, `mode` at the time; a scrub or a run of arrow keys is one event, written 0.6 s after it settles |
| `toast` | `text` of the toast shown |
| `error` | `text` of the error banner, `kind` (`mic` for microphone trouble) |
| `song_open` | another song or target opened in the same tab («Інша пісня»): `source` (`pack` / `target`), `songHash`, `songId`, `lessonId`, `duration`, `notes` |
| `attempt` | one finished attempt, below |

Play, record and stop are `state` changes of `mode` (and the `click` on `listenBtn`, `singBtn`, `stopBtn`, or the
`key` Space / Escape that caused them). Loop and A–B ranges are `state` changes of `loop`, `rangeId` and `range`.

### `attempt`: input for the singing analysis

Written when an attempt is stored, from the same summary the practice history keeps (`summarizeRun()` and `runRecord()`
in `app/app.js`, [HISTORY_SCHEMA.md](HISTORY_SCHEMA.md)); there is no second scoring.

| field | meaning |
|---|---|
| `runId` | the history's attempt id; a punch-in re-records the same `runId` with `replaced: true` |
| `songHash`, `mapVersion`, `lessonId` | which song and which version of its note map |
| `rangeId`, `a`, `b`, `duration` | the chosen phrase (`0` whole song, `-1` own range), song seconds sung, wall seconds |
| `speed`, `level`, `tolerance`, `view`, `octave`, `latency` | the settings the attempt was scored under |
| `match` | hit ÷ target in percent, two decimals; `null` when the attempt covered no target |
| `targetSec`, `hitSec`, `sungSec`, `draftSec` | seconds of target, of hits, of voiced frames, of draft target; 20 ms frames × 0.02 |
| `songTargetSec` | seconds of target in the whole song under this view; `targetSec ÷ songTargetSec` is the coverage |
| `medianCents` | median \|Δ\| from the target over confident frames; `-1` = nothing to measure |
| `strict` | `targetTime`, `compared`, `inside` seconds and `median` ¢ at the strict reading |
| `punches`, `hasAudio`, `clipped`, `startedAt`, `endedAt` | |
| `phrases` | `[id, target, hit, sung, median]` per phrase the attempt covered ≥ 80 %, frames of 20 ms and cents (`-1` none) |
| `exercises` | lessons only: phrase id → exercise name |

The full trace of the voice is not in the log; the trainer's history keeps it (see HISTORY_SCHEMA.md), and the export in
the footer of the Прогрес tab writes it out.

## Brief for an analysis agent

Copy this to the agent, with the path of the Luma checkout:

> You are analysing how one person uses Luma, a sing-along pitch trainer, and how well they sing.
>
> 1. Run `python studio/activity_report.py --days 30` in the Luma checkout and read the digest. Then read the raw events
>    in `songs/logs/activity/*.jsonl` for detail; the schema is `docs/ACTIVITY_LOG.md`. If the operator gives you a
>    practice history export (`luma.history.v1`, `docs/HISTORY_SCHEMA.md`), read it too: it has every attempt since the
>    first, with per-phrase numbers.
> 2. **UX.** Reconstruct the real sessions: which page they start on, the path to the first «Співати», what they repeat,
>    which controls they never touch, which settings they change and change back, where they hesitate (long gaps,
>    open-and-close of a dialog, a seek right after a mode change), which toasts and errors they meet and what they do
>    next, keyboard versus mouse, phone versus desktop (`viewport`, `coarse`). Propose concrete changes to Studio and the
>    trainer for this operator, each with the events that motivate it (session id and `seq`), the expected effect and
>    the file it touches (`studio/studio.html`, `app/head.html`, `app/app.js`). Rank them by how often the friction
>    occurs. Do not propose what the log cannot support.
> 3. **Singing.** From the `attempt` events: per song and per lesson, the match trend over days at a fixed
>    level / view / speed (scores are only comparable inside one such key), the median |Δ| in cents, how much of what was
>    a target they sang at all (`sungSec ÷ targetSec`: silence versus wrong pitch), the phrases that stay weak across
>    attempts and the ones that improved, the effect of the 0.8× speed and of the levels. Name strengths and weaknesses
>    with numbers and the attempts behind them, and suggest what to practise next (phrases, lessons, level, speed).
> 4. Write the result as one Markdown report: a short summary, then UX proposals, then singing. Quote no lyrics; refer
>    to songs by their file slug and to phrases by id.
