# Guided session (three lessons in a row) and album covers — design

## Originating requirement

Operator requirement, 2026-10-07, spoken in Russian, quoted verbatim from the pinned task:

> «И, возможно, нужно какой-то такой режим, который вот типа я начинаю петь. У меня сначала 3 урока вот этих идут
> последовательных. Просто, ну, типа, я могу пропустить урок, но они как бы включаются один за одним. То есть какой-то
> такой режим, и это с анимациями, с переходами между этими... между уроками. И потом выбираем песни. Кстати, говоря к
> песням, желательно добавить картинки сейчас вот, которые у нас сейчас есть. Картинки альбомов, там, или чего.
> Чтобы... чтобы было видно.»

Read as five obligations:

1. A mode I start when I sit down to sing.
2. The three lessons play one after another; any of them can be skipped.
3. Animated transitions between the lessons.
4. Then I choose a song.
5. Songs show the album pictures we already have, so they are easy to see.

Everything below is checked against these five points in [Validation against the quote](#validation-against-the-quote).

## Ground truth (observed 2026-10-07)

| Fact | Where / how observed |
|---|---|
| Studio is one static page (`studio/studio.html`, 140 lines) polling `GET /status` every 2–15 s; it renders «Уроки» from `songs/lessons.index.html` and the library from `/status.songs`. Every trainer link opens a **new tab** (`target=_blank`). | `studio/studio.html:104-137` |
| The server serves `/`, `/demo`, `/status`, `/song/<name>.html` and nothing else over GET; `send()` writes only Content-Type and Content-Length. | `studio/studio_server.py:118-143` |
| Three built-in lessons, ordered by `order` 1-2-3: `Luma_Lesson_1_Novachok.html` (2:13, 6 MB), `Luma_Lesson_2_Seredniy.html` (3:19, 9 MB), `Luma_Lesson_3_Ekspert.html` (2:46, 8 MB). The catalogue carries `order, html, title, level, summary, description, duration, repetitions`. | `lessons/definitions.py:70-100`; `build_lessons.py --songs <scratch>` build log |
| A sung attempt ends in `onFinished(m)` and is stored by `storeTake(meta, m)`; `m.reason==='end'` means the transport ran to its planned end. Without a selected fragment the planned end is `song.duration`. `take.endSong = meta.a + m.duration*meta.speed`. | `app/app.js:300-302, 323, 765-772, 781-791` |
| The test hooks `Luma.test.fakeSing / fakeTick / fakeFinish` drive a whole attempt without a microphone, and `fakeFinish` goes through `storeTake` with `reason:'end'`. | `app/app.js:1458-1461` |
| The trainer's only link out (`#studioLink`) is shown for `file:` pages only, so an embedded trainer never navigates itself away. Its `beforeunload` guard fires on `s.unsaved || singing`. | `app/head.html:388`, `app/app.js:31, 1404` |
| A song package is `songs/<slug>/` and its trainer is `songs/Luma_<slug>.html`, for both `prepare_song.py` and the Studio worker (`slugify` is the same function in both). Imported trainers are `Luma_<slug>_<8 hex>.html` and have no package. | `studio/prepare_song.py:223-224`, `studio/studio_server.py:38, 97, 166` |
| The upload is kept as `songs/<slug>/original.<ext>` (`prepare_song.py:234-238`). In the operator's library all **27** songs have one, all `.m4a`, every one with an `attached_pic` video stream: 16 carry a single MJPEG (13 at 544×544, one each at 480×480, 1280×720 and 480×252); 11 carry a 1280×720 **PNG first** and a 544×544 MJPEG after it (one of them two MJPEGs). | `ffprobe` over `songs/*/original.*`; 30 trainers = 27 songs + 3 lessons, every song trainer maps to its package by slug |
| The 1280×720 PNG is the same artwork letterboxed with coloured bars; the square MJPEG is the album cover itself. Taking stream 0 would give the wrong picture for 11 of 27 songs. | one sample extracted to a scratch dir and viewed, then deleted |
| Extracting all 27 covers (ffprobe + ffmpeg, ≤512 px JPEG, `-q:v 3`) takes **4.4 s** wall and **1.8 MB** in total. | timed loop into a scratch dir, deleted afterwards |
| `tests/studio_test.py` builds the server with `threading.Thread.start` patched out, so background threads started at import do not run in those tests. | `tests/studio_test.py:21-22` |
| Two other lanes are editing now: a lives mode (`app/app.js`, `app/head.html`) and activity logging (an endpoint in `studio_server.py`, thin hooks in `studio.html` and `app.js`). | pinned task |

Prior work: searches of transcripts and memory for guided sessions, lessons in a row and album covers found nothing on
these topics (only the earlier lessons and progress-tab lanes, whose code is cited above).

## Decision 1 — how the flow moves between Studio and the lesson trainers

### Options

| | A. Studio hosts the session; trainer in a same-origin `<iframe>` (**chosen**) | B. Same-tab navigation with `?session=` in the URL | C. New tab per lesson, trainer reports to `window.opener` |
|---|---|---|---|
| Where the session UI lives (dots, skip, leave, intro cards, transitions) | `studio/studio.html` only | Inside the trainer (`app.js` + `head.html`) **and** in Studio | Studio tab, while the singer is in another tab |
| `app/app.js` change | 2 lines: post one message when a whole lesson is sung | Session bar, skip/leave controls, URL handling, navigation on finish: tens of lines in both contested files | 2 lines, like A |
| Animated transitions between lessons | Studio animates its own overlay; the next trainer preloads behind the intro card | A full page load between every step; any "transition" is a blank flash | Tabs switching; no transition is possible |
| Conflict with the lives lane (`app.js`, `head.html`) | Minimal | High | Minimal |
| Mic, IndexedDB history, prefs | Same origin as today (`/song/*.html` on the Studio port), so the same history store and the same remembered mic permission | Same | Same |

B fails the "keep `app/app.js` small" constraint and puts UI into the file the lives lane owns. C cannot show
transitions at all, which is half of the requirement. **A** keeps every visual of the session in Studio.

Rejected variant of A: Studio polls `frame.contentWindow.Luma.diagnostics()` to notice a finished attempt and needs zero
lines in `app.js`. `diagnostics().takes` carries no start or end time, so "reached the end of the lesson" cannot be read
from it, and polling a diagnostics object couples Studio to a debug surface. Two explicit lines are cheaper to keep correct.

### What "finished" means

A lesson is finished when **a sung attempt runs to the end of the lesson**: the attempt stops with `reason==='end'` and
`take.endSong >= song.duration - 0.25`. Consequences:

- An attempt over a selected fragment, a loop pass, a stopped attempt, listening without singing: none of them finish.
- An attempt started midway that sings through to the end does finish. The singer chose to start there; skipping was
  available anyway.
- A lives-mode attempt that ends early (the other lane) ends with a reason other than `'end'`, so it does not count.

### The `app/app.js` change (the whole of it)

One function and one call, inside `storeTake` right after `saveRun(take)`:

```js
// A trainer embedded by a Studio session tells it when a whole lesson has been sung; on its own it does nothing.
function tellHost(t){if(window.parent===window||t.endSong<song.duration-.25)return;parent.postMessage({type:'luma:finished',file:decodeURIComponent(location.pathname.split('/').pop()),match:scorePct(t.score)},location.origin);}
```

```js
 s.trace={take,points:take.points,score:take.score};s.current=null;saveRun(take);if(m.reason==='end')tellHost(take);markUnsaved();renderTakes();
```

`storeTake` is the one place both the real path (`onFinished`) and the test path (`fakeFinish`) pass through, which is
why the call sits there and not in `onFinished`. A top-level trainer (`window.parent===window`) returns before touching
`location.origin`, so `file:` trainers are unaffected. Lessons pick the change up automatically: `luma-studio.sh` runs
`build_lessons.py`, which re-wraps the three lesson trainers whenever `app/` changed. Song trainers need no rebuild,
because Studio ignores the message for them.

### Studio side of the protocol

```
Studio (studio.html)                               trainer in <iframe src="/song/Luma_Lesson_N_….html">
  ── creates iframe, preloads behind intro card ─▶ loads like a normal trainer
                                                    singer presses «Співати», sings to the end
  ◀── postMessage {type:'luma:finished', file, match}  (origin = Studio origin)
  accept only if  e.origin === location.origin
              and e.source === current iframe's contentWindow
              and e.data.type === 'luma:finished'
              and e.data.file === current step's html
  → step marked done with match %, advance
```

Skip and leave **remove** the iframe element (a new iframe is created per step). Removing a document stops its audio and
releases the microphone, and it does not run a `beforeunload` prompt, so «Пропустити урок» always responds at once. An
attempt in progress at that moment is dropped. That is the explicit meaning of the button; a finished attempt is
already in IndexedDB by then.

## Decision 2 — screens, states and transitions

### State machine

```
            «Почати заняття»
 HOME ───────────────────────▶ INTRO(1) ──(5 s or «Почати зараз»)──▶ LESSON(1)
  ▲                              │  ▲                                   │ finished → done(1, match)
  │ × «Завершити» / Back          │  └──────────── «Ще раз» ─────────────┤ «Пропустити урок» → skipped(1)
  │ from any state               ▼                                      ▼
  │                           INTRO(2) ─▶ LESSON(2) ─▶ INTRO(3) ─▶ LESSON(3) ─▶ PICKER ──card──▶ SONG(frame)
  └──────────────────────────────────────────────────────────────────────────────▲    «До пісень» ◀─┘
```

- Steps come from the catalogue Studio already loads (`lessons`, sorted by `order`), filtered to the trainers present in
  `/status`. Today that is three; the code takes N (dots = N + 1).
- «Пропустити урок» in the bar works on an intro and on a lesson; after the last lesson it leads to the picker.
- `INTRO(n)` after a finished lesson carries the result line «✓ Урок n−1 пройдено · збіг 78 %» (match from the
  message, «—» when null) and a secondary «Ще раз» that reloads the lesson just finished.
- `INTRO(n)` opens the trainer by itself after 5 s; «Почати урок» does it at once. The next trainer's iframe is created
  hidden (`opacity:0`) as soon as the intro appears, so its 6–9 MB load overlaps the countdown; if it is still loading
  when the countdown ends, the button reads «Завантажуємо урок…» until the frame's `load` event. Opening a trainer
  starts no sound; the singer still presses «Співати», which is also the user gesture the trainer's AudioContext needs.
- `PICKER` shows the run summary (per lesson: «✓ 78 %», «пропущено») and the song library with covers; a card opens that
  song in the session frame, and «До пісень» in the bar returns to the picker. Lesson trainers do not appear in the picker.
- Leaving: the × «Завершити» button in every state, and the browser's Back button (session start does one
  `history.pushState({lumaSession:1}, '')`; `popstate` closes the session; × calls `history.back()` when that state is
  on top). Focus returns to «Почати заняття». The session is held in memory only; a reload returns to HOME.

### Entry on the Studio page

A hero card at the top of `<main>`, replacing the current `.lead` line, shown only when the lesson catalogue loaded:
title «Заняття», one sentence «Три уроки поспіль, потім пісня з бібліотеки. Будь-який урок можна пропустити.», the path
«Новачок → Середній → Експерт → Пісня» as pills, and the primary «Почати заняття» (46 px tall; full width at 390 px).
It sits in the first screen at 390×844 and at 1440×900 (prototype frames below). The «Уроки» cards stay as they are,
«Відкрити урок» included, for opening one lesson directly (`tests/e2e/lessons.mjs:59` reads that `a.primary`).

### Session overlay layout

```
┌──────────────────────────────────────────────────────────────────────┐
│ [× Завершити]          ●  ━━━  ●  ●   Урок 2 з 3        [Пропустити урок] │  52 px bar, #0c1018, 1 px border
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│     iframe (trainer)  — or —  intro card (max 460 px, centred)       │  flex:1
│                       — or —  picker (scrolls, max 960 px)           │
└──────────────────────────────────────────────────────────────────────┘
```

- `<section id="session" role="dialog" aria-modal="true" aria-label="Заняття" hidden>`, `position:fixed; inset:0`,
  `background:var(--bg)`, and `body` scrolling locked while it is open.
- 390 px: × becomes a 40×36 icon button with `aria-label="Завершити заняття"`, the step label beside the dots is hidden
  (the dots carry `role="progressbar"`, `aria-valuenow`, `aria-valuetext="Урок 2 з 3"`), «Пропустити урок» stays as
  text (36 px, 12.5 px type). In the picker the right-hand button is absent; in SONG it reads «До пісень».
- The trainer gets the full width and `100vh − 52 px`; at 390×844 that is 390×792, which the trainer already handles
  (rendered: see variant 1, frame "lesson 390").
- Dots: 8 px circles, the current one a 28 px mint pill; done = mint at 63 % alpha, skipped = `#95a3b855`. Use the state
  class name `skipped`, never `skip`: the prototype showed `.sbar .skip` (the bar button) restyling a `.dot.skip`.
- Intro card eyebrow «Урок 2 з 3» in sentence case. The upper-cased version renders «З» like the digit «3».
- All text Ukrainian; tokens, buttons and chips are the existing `.primary`, `.secondary`, `.chip.easy/normal/strict`.
- A polite live region announces each step: «Урок 1 пройдено, збіг 78 %. Далі урок 2.» / «Урок 2 пропущено.» /
  «Розспівку завершено, обери пісню.». Focus moves to the intro card's primary button, then into the iframe
  (`frame.focus()`) when the trainer opens, so Space and the trainer's own keys work without a click.

### Transitions

| Moment | Motion (default) | `prefers-reduced-motion: reduce` |
|---|---|---|
| HOME → session | overlay fades in 200 ms; intro card rises 10 px and fades in, 320 ms ease-out | appears at once |
| INTRO → LESSON | card fades out 180 ms while the preloaded iframe fades 0 → 1 over 250 ms | swap at once |
| LESSON → next INTRO (finish or skip) | after a finish, a 1.2 s hold so the trainer's own result shows; iframe fades out 200 ms and is removed; the next card rises in; the current pill slides to the next dot (width/colour, 300 ms) | no hold animation; swap at once (the 1.2 s hold stays, it is timing) |
| → PICKER | picker content rises in 320 ms | appears at once |
| Leave | overlay fades out 200 ms, then is hidden | hidden at once |

`studio.html:37` already zeroes every animation and transition under reduced motion. The session JS must therefore
never wait for `transitionend`/`animationend`; it uses timeouts whose length is 0 when
`matchMedia('(prefers-reduced-motion: reduce)').matches`. The 5 s intro countdown is a timer and stays.

### Prototype and operator review

A throw-away prototype (Studio's own `<style>` plus the additions above, invented titles, generated art in place of
covers, the real lesson 2 trainer inside the frame) was rendered with Playwright at 390×844 and 1440×900 and
published as a prototype review on this task (`pr_f1975e920590c3d1e452dd0f6656be4f`):

- **Variant 1 — thumbnail beside the text**: 88 px cover left (76 px at 390), title, artist, length, button right. All
  session screens: home, intro 1, intro 2 after a finish, lesson in the frame, picker.
- **Variant 2 — cover on top**: full-width square cover per tile; 4 columns at 1440, 2 at 390; home and picker.

Measured on every frame: `scrollWidth == clientWidth` (no horizontal overflow), no control under 24 px, no clipped
button or title text, no page errors. The first render had a 412 px overflow at 390 (the row layout leaked into the
lesson cards) and the dot/class collision above; both are fixed in the published frames, and both are listed here
because the implementation can hit them the same way.

**Recommendation: variant 2** for the library and the picker. "Чтобы было видно" asks for covers that are visible, and
a picker is chosen by recognising artwork. In variant 2 clamp the title to two lines and the artist to one
(`-webkit-line-clamp`, full text in `title=`), because real titles in this library run long. If the operator picks
variant 1 in the review, only the `.song` card CSS changes; nothing else in this design depends on the choice.

## Decision 3 — album covers

### Extraction

New module **`studio/covers.py`** (standard library + the `ffprobe`/`ffmpeg` binaries the pipeline already needs):

```
extract(package: Path) -> Path | None
  original = first of package.glob('original.*'); none → None
  cover = package/'cover.jpg'; none_marker = package/'cover.none'
  if cover exists and mtime ≥ original's → return cover            (cached)
  if none_marker exists and mtime ≥ original's → return None       (known to have no picture)
  streams = ffprobe -v error -select_streams v
              -show_entries stream=index,width,height:stream_disposition=attached_pic -of json original
  candidates = streams with attached_pic=1, or every video stream when none is flagged
  pick = min |width/height − 1|, ties → largest width×height       (square album art over 16:9 thumbnails)
  no candidate → touch cover.none, return None
  ffmpeg -hide_banner -loglevel error -y -i original -map 0:<index> -frames:v 1
         -vf "scale='min(512,iw)':-2" -q:v 3 -f mjpeg cover.jpg.part
  os.replace(cover.jpg.part, cover.jpg); return cover
  ffmpeg/ffprobe exits non-zero → remove .part, touch cover.none, return None
  FileNotFoundError (no ffmpeg) → return None, no marker (retried next start)

backfill(songs: Path) -> {'extracted': n, 'cached': n, 'none': n}
  every songs/*/ that has an original.*; prints counts only, never names

cover_for(songs: Path, html_name: str) -> Path | None
  html_name must match ^Luma_([^/\\]+)\.html$; path = songs/<group 1>/cover.jpg;
  path.resolve().parent.parent == songs.resolve() and path.is_file() → path, else None

CLI: python studio/covers.py [--songs DIR]  → runs backfill, prints the counts
```

Why these choices: the selection rule is what the 11 PNG-first files need; a JPEG of at most 512 px keeps the 27
covers at 1.8 MB and is sharp at 2× for a 200 px tile; `cover.none` keeps a song without art from being probed on every
start; `.part` + `os.replace` matches how trainers are written (`build_html.reassets`).

### When it runs

- **Backfill:** `studio_server.py` starts `covers.backfill(SONGS)` in a daemon thread at start, next to the worker
  thread. 27 songs take about 4 s; `/status` serves meanwhile and the covers appear on the next poll.
- **New songs:** `prepare_song.py` calls `covers.extract(pkg)` right after the original is copied (stage 1), inside
  `try/except Exception` with a log line, so a cover problem never fails a preparation. This covers both the Studio job
  and command-line runs. A later `original.*` replacement makes the cover stale by mtime, so it is re-extracted.
- Imported trainers and the lessons have no package and get the placeholder.

### Serving

- `GET /status`: each song gains `"cover": <int mtime>` or `"cover": null` from `cover_for` (one `stat` per song per poll).
- `GET /cover/<Luma_…html>`: the bytes of `cover_for(SONGS, basename(unquote(name)))` as `image/jpeg` with
  `Cache-Control: max-age=86400`; 404 for anything else (unknown name, a lesson, an imported trainer, `..` in any
  encoding). Studio requests `/cover/<name>?v=<mtime>`, so a new cover is a new URL. Headers are written inline in that
  branch, so `send()` keeps its current signature (the logging lane edits this file too).

### Rendering in Studio

- Song card: `<div class="cover"><img src="/cover/…?v=…" alt="" loading="lazy" decoding="async"></div>`. The image is
  decorative (the title is text right beside it). `onerror` swaps in the placeholder, which also handles a cover
  deleted between a poll and the load.
- Placeholder (`cover === null`): the same box with two radial gradients whose hues come from a hash of the file name
  (stable per song), the Luma waveform glyph from the brand mark, and the title's first letter. Pure CSS; no image file,
  no server route.
- The same card builder fills the library and the session picker (`songCard(song, {session})`; in the session the
  button reads «Співати» and opens the song in the frame).

## Files

### Touch

| File | Change | Size |
|---|---|---|
| `studio/covers.py` | new: `extract`, `backfill`, `cover_for`, CLI | ~60 lines |
| `studio/studio_server.py` | `import covers`; backfill thread; `cover` field in `/status`; `GET /cover/` branch; route list in the docstring | ~15 lines |
| `studio/prepare_song.py` | one guarded `covers.extract(pkg)` after the original is copied | ~3 lines |
| `studio/studio.html` | cover box + placeholder in song cards; hero entry; session overlay markup, CSS, and a self-contained session block in the script | the bulk |
| `app/app.js` | `tellHost` + one call in `storeTake` | 2 lines |
| `tests/studio_test.py` | cover tests (below) | |
| `tests/e2e/session.mjs` | new flow + covers suite (below) | |
| `tests/e2e/run.sh` | append `session` to the suite list (after `progress`, which also uses the test library) | 1 word |
| `README.md` | Studio section: «Заняття» and covers; Layout lists `studio/covers.py`; Tests lists `session.mjs` | |
| `docs/LESSONS.md` | new section «Заняття: three lessons in a row»: order, what "finished" means, skip, leave, picker | |

Keep the session code in `studio.html` as one block (state object + `startSession`, `showIntro`, `openStep`,
`finishStep`, `skipStep`, `showPicker`, `leaveSession`) after the existing render functions, so the logging lane's
hooks in the same file stay merge-friendly.

### Do not touch

- `app/head.html` (lives lane): the session needs nothing in the trainer's markup or CSS.
- `app/app.js` beyond the two lines; no session UI inside the trainer.
- `lessons/build_lessons.py`, `lessons/definitions.py`, `songs/lessons.index.html` format: the catalogue already has
  everything the intro cards need.
- `studio/build_html.py`: covers stay out of the trainer files.
- `send()` in `studio_server.py`, and the logging endpoint the other lane adds.
- Anything under `songs/` in git: covers are written there and `songs/` is already ignored (`.gitignore:3`).

## Tests

### `tests/studio_test.py` (Python, no network; skip with a reason when `ffmpeg` is missing)

Fixtures are generated in the temp library with ffmpeg: a 1 s sine in `.m4a` with a 64×36 PNG `attached_pic` first and
a 48×48 MJPEG `attached_pic` second (the command was verified on this machine), and the same audio with no picture.

1. `test_cover_prefers_square_attached_picture`: `extract` writes `cover.jpg`, a JPEG (`FF D8`) of 48×48.
2. `test_cover_is_cached_and_refreshed_by_mtime`: a second `extract` runs no subprocess (patched `subprocess.run`
   asserts not called); touching `original.m4a` newer makes it extract again.
3. `test_song_without_picture_gets_a_marker`: returns `None`, writes `cover.none`, and a second call runs no subprocess.
4. `test_backfill_counts_without_names`: two packages → `{'extracted': 1, 'none': 1, …}`; stdout holds no package name.
5. `test_status_and_cover_route`: with `songs/Fixture/cover.jpg` and a minimal `Luma_Fixture.html`, `/status` reports an
   integer `cover`; `/cover/Luma_Fixture.html` → 200, `image/jpeg`, same bytes; 404 for `Luma_Missing.html`,
   `Luma_Lesson_1_Novachok.html`, `..%2F..%2Fetc%2Fpasswd`, `%2e%2e/cover.jpg`, and `Fixture/cover.jpg`.

### `tests/e2e/session.mjs` (Playwright, run by `run.sh` against the test Studio and library)

Setup: the library already holds the lessons (built by `lessons.mjs`). Add `Luma_Cover_Fixture.html` (a copy of the
demo trainer) with `Cover_Fixture/original.m4a` (the fixture above), and `Luma_No_Cover.html` with no package; run
`studio/covers.py --songs $LUMA_TEST_LIBRARY`; remove all three at the end.

At 390×844 and 1440×900:

1. Library: the fixture card's `img` has `naturalWidth > 0` and a `/cover/Luma_Cover_Fixture.html?v=` source; the
   no-cover card shows the placeholder; `scrollWidth == clientWidth`.
2. «Почати заняття» is inside the first viewport.
3. Start: overlay visible, 4 dots with dot 1 current, the intro title equals the catalogue's lesson 1 title.
4. «Почати урок» → the iframe's `src` is `/song/Luma_Lesson_1_Novachok.html`, and the frame exposes `window.Luma`.
5. No false finish: in the frame, `fakeSing({a:d-10,b:d-5})`, tick, `fakeFinish()` → after 2 s still on lesson 1.
6. Finish: in the frame, seek to `d-2`, `fakeSing({a:d-2,b:d})`, `fakeTick` past the end, `fakeFinish()` → intro 2
   appears with «Урок 1 пройдено» and a `%`, dot 1 is `done`.
7. Spoofing: `window.postMessage({type:'luma:finished', file:…}, origin)` from the Studio page itself is ignored.
8. Auto-advance: without a click, lesson 2's trainer is in the frame within 7 s.
9. Skip: «Пропустити урок» → intro 3, dot 2 is `skipped`; open lesson 3 and skip → picker with the summary
   («✓ … %», «пропущено», «пропущено»), lesson trainers absent from the cards, the fixture cover present.
10. Picker → fixture card → its trainer in the frame; «До пісень» → picker again.
11. Leave: × → overlay hidden, focus on «Почати заняття»; start again and `page.goBack()` → overlay hidden, URL is Studio.
12. Reduced motion (`emulateMedia({reducedMotion:'reduce'})`): start → the intro card's computed `animation-name` is
    `none`, and skip → the next card is present within 100 ms.
13. Clean console in Studio and in the frames; screenshots `shot_session_<step>_<width>.png` (gitignored by
    `tests/e2e/shot_*.png`) for the rendered-evidence review.

Existing suites keep passing unchanged: lessons and progress open lesson trainers top-level, where `tellHost` returns
at its first check.

### Required checks

`tests/e2e/run.sh` (it also runs `tests/studio_test.py` and the other Python suites). The project names no linter or
CI beyond that script.

## Rollout notes for the implementer

- A running Studio picks up the backfill and the new routes on its next start (`studio/luma-studio.sh` only starts a
  server when none answers `/status`). `python studio/covers.py` backfills without a restart.
- The lesson trainers are re-wrapped with the new `app.js` by `build_lessons.py` on the next `luma-studio.sh` start;
  until then a lesson in the session can still be skipped, it just never reports a finish.
- Rebase on `origin/main` before finishing: `app/app.js` and `studio/studio.html` are both being edited in parallel.
  The two `app.js` lines sit inside `storeTake`, which neither other lane is known to change.

## Deferred — not currently justified

Kept so the cut scope stays visible; none of it is asked for by the quote.

- **Cover in the trainer header.** The spec allows it "if cheap". It is not: a trainer is a standalone file, so the
  cover would have to be embedded by `build_html.py` (a rebuild of every trainer) or fetched by `app.js`/`head.html`,
  which the lives lane is editing. Revisit after that lane lands.
- **Covers for imported trainers.** No source audio exists for them; they show the placeholder.
- **Resuming a session after a reload, or remembering today's done lessons.** The quote describes one sitting.
- **Starting singing automatically in the next lesson.** It would need a cross-frame user gesture or a new trainer API;
  opening the trainer automatically already gives "one after another".
- **Applying each lesson's suggested level in the trainer.** A known gap in `docs/LESSONS.md`; it needs `app/`.
- **Choosing which lessons or how many go into a session.** The quote fixes three.
- **Session events in the activity log.** The logging lane can hook `startSession`/`finishStep`/`skipStep`/`leaveSession`
  later; this design adds no logging of its own.
- **Fetching covers from online services** for songs without embedded art. Network, keys and privacy cost; the quote
  says "the pictures we have now".

## Validation against the quote

| Quote | Design |
|---|---|
| «режим, который вот типа я начинаю петь» | One primary «Почати заняття» at the top of Studio opens a full-screen session. |
| «сначала 3 урока… последовательных… включаются один за одним» | Lessons 1 → 2 → 3 from the catalogue order; a whole sung lesson advances by itself, and each intro opens the next trainer by itself after 5 s. |
| «я могу пропустить урок» | «Пропустити урок» on every lesson step and intro. |
| «с анимациями, с переходами между уроками» | Intro card per lesson, progress dots 1-2-3, fades and rises between steps, preloaded frames so a transition never shows a blank load; reduced motion swaps at once. |
| «И потом выбираем песни» | After lesson 3 the picker shows the run summary and the library; a song opens in the same session frame. |
| «картинки альбомов… которые у нас сейчас есть… чтобы было видно» | The embedded album art of all 27 songs, the square picture chosen over the 16:9 thumbnail, cached under `songs/`, served by Studio, shown on every library and picker card; a generated placeholder otherwise. |

Privacy: no titles, artists, lyrics or cover images are in this document, the prototype review uses invented titles and
generated art, and covers are written only under the ignored `songs/`.
