# Build brief: camera video of an attempt, composed with the game and the instrumental

For one builder. Written 2026-10-19 against `main` at `473879b` (after #17–#21). The design is
`docs/design/CAMERA_VIDEO.md` from the design lane (commit `6138fe4`). Where this brief and the design disagree, this
brief wins: it applies the operator's 2026-10-14 decisions and today's code. Line numbers below are for `473879b`.

## Originating requirement

Operator, 2026-10-11, Russian voice message, verbatim («сув» is a speech-to-text slip for the microphone latency):

> «очень важная штука... возможность вывести камеру на меня, чтобы записывать автоматически... меня на камеру, как я
> пою... Чтобы писался, соответственно, мой голос, камера, как оно обычно делается, но потом подставлялся правильно в с
> учётом сува и всего. Правильно подставлялся именно минус этой песни, и мне показывалось потом в видео, где мой минус и
> плюс наложены, и я посмотрю, как я пою.»

Addendum, same day:

> «очень важно, чтобы снималось то, как я играю, без лишнего интерфейса... чтобы меня было видно, линию, как я пою.
> Также слова... жизни, чтобы было видно. ...когда жизнь сгорает, чтобы оно более эффектно сгорало... И это чтобы было
> тоже на камере... красивое видео.»

Operator decisions, 2026-10-14 (binding; they replace the design's §7 recommendations). The design lane's prototype
review was answered the same day with variant 3, landscape only, one continuous video, ≥ 30 s automatic, and the same
burn in the trainer and the video:

1. The game fills the frame (target notes, live pitch line, lyrics, lives) and the camera sits in a circle. No buttons,
   menus or other chrome in the video.
2. Landscape only.
3. One continuous video per attempt at a song, with the lives-mode rewinds inside it.
4. Every attempt of 30 s or longer is composed automatically. The oldest videos are deleted automatically to stay
   within 5 GB.
5. The life burn looks the same in the trainer and in the video: reuse the one canvas draw function in `app/burn.js`.
   The past-takes dust (#21) appears as it does in the trainer.

Audio: the voice, shifted by the microphone latency (`prefs.latency`), over the song's instrumental stem (минус).

## 1. What to build, in one paragraph

With «Знімати мене на камеру» on, a trainer served by Studio opens the camera together with the microphone. It records
one `MediaRecorder` webm for the whole sitting, from «Співати» until the sitting ends, lives rewinds included, and
streams the webm to Studio while the singer sings. Each attempt in the sitting also records its microphone WAV, which
already sits on the song timeline with the latency applied. At the end of the sitting the trainer uploads one take
record. Studio cross-correlates the webm's own audio with the WAVs to place the camera, runs the trainer in a headless
render mode that draws the game layer frame by frame with the trainer's own drawing code (WebCodecs H.264), and has
ffmpeg overlay the camera in a circle, mix the voice with the instrumental and write a 1920×1080 MP4. «Мої відео» in
Studio lists and plays the videos and deletes the oldest past 5 GB. Design option D (§5.1) stays the mechanism. What
changes is the frame, the orientation, the sitting boundary and the scope cut in §9.

## 2. What changed since the design, and what it means here

| merged | what is on `main` now | consequence for this build |
|---|---|---|
| #17 wordless chains | `scoredSpans()` / `wordlessNote()` (`app/app.js:63-90`) dim wordless notes, keep them out of the score, and `singEnd()` (`:513`) stops a pass at the last worded note | The render inherits this through `draw()`. The render page runs in a fresh browser profile, so it never sees the singer's note edits (`localStorage['luma.target.'+song.id]`, `loadEdits()` `:46`). The take record must carry `song.notes` and `s.verified` when edits exist, or the render dims and scores different notes. |
| #18 autopick | «Обери за мене» chains songs inside the Studio session frame; each song is a new frame (`studio/studio.html:406`, `:461`) | Each song in a chain is its own video. `tellHost()` (`app/app.js:917`) must wait for the video upload, because Studio drops the frame on `luma:finished` (`studio/studio.html:350-351`, `dropFrame()` `:245`). |
| #19 latency | `prefs.latency` can be applied from «Розрахувати затримку» (`latencyApply`, `app/app.js:1725`); `takeMeta()` (`:436`) records `latency` per attempt; `#latencyHint` banner | Use each attempt's own `meta.latency` (`lag`). Videos keep the latency they were recorded with. `app/latency.js` is untouched. The hint banner is chrome and never reaches the video. |
| #20 burn | `window.LumaBurn = {ms: 800, box, drawHeart}` (`app/burn.js`), DOM hearts plus a burn canvas per loss (`burnLife()` `app/app.js:171`, `renderLives()` `:183`); the last life burns through the count-in and the refill pop waits for it | The design's 1.1 s burn timing is obsolete: the burn is 800 ms. The render calls `LumaBurn.drawHeart` exactly as `docs/design/LIFE_BURN.md` §4 describes, compositing through a transparent offscreen canvas because the glow uses `'lighter'`. The trainer's DOM hearts and `burnLife` stay as they are. |
| #21 dust | The record line («Рекорд», the design's "personal-best shadow") is gone. Past takes are dust, painted by a worker into an `ImageBitmap` layer (`cloud`, `drawCloud()` `app/app.js:1387-1431`, worker `app/workers.html` `#cloud-source`) | (a) The render profile has no IndexedDB history and no `s.takes`, so the take record must carry the dust input (`packTake()` output: seed + `[songT, m]` Float32 pairs) for each segment. (b) The layer arrives asynchronously, so the render must wait for a fresh layer before encoding a frame (§5.3). (c) Drop every mention of the shadow line. |

Other facts that moved:

- **Disk.** On 2026-10-19 `/home` has 317 GB free (`df -h /home`); the design's 15 GB and its 3 GB disk floor no longer
  apply. The 5 GB cap is the operator's and stays.
- **Browser for the render and the tests.** Playwright's Chromium 153 (the bundled `chromium-1243`), headless on a
  `localhost` origin on this machine: `VideoEncoder` supports `avc1.640028` and `avc1.4D0028` (not `avc1.42E01E`), and
  encoded 150 synthetic 1920×1080 frames at 85.5 fps. `MediaRecorder` supports `video/webm;codecs=h264,opus` and
  `vp8,opus`. The fake camera opens at 1920×1080 @ 20 fps. (Probe run 2026-10-19 with an inline script; nothing was
  written.) `VideoEncoder` is undefined on a non-secure page, so the render page must be served over
  `http://127.0.0.1`.
- **The demo song** sings to 29.96 s (`singEnd()`), so one full demo pass is shorter than 30 s. The e2e suite uses that
  (§8).

## 3. Decisions, resolved against the operator's answers and the code

| # | question | resolved as | from |
|---|---|---|---|
| D1 | Frame | Landscape 1920×1080, 30 fps. The game layer fills it: plot top 26 px, lyric band 900–1060 px. The camera is a 300 px circle with its top-left corner at (72, 570), over the past part of the roll, ringed by 5 px `#a1eed8aa` with a soft shadow. This is the chosen prototype frame (variant 3 landscape, `left 72, top 570, 300×300`). Hearts sit top-right with the match % and «ЗБІГ» right of them, as in that frame. | decisions 1, 2; chosen frame |
| D2 | Portrait, «Альбомна версія», orientation buttons | None. Only landscape is ever composed. | decision 2 |
| D3 | What one video spans | One **sitting**: from the «Співати» (or session auto-start) that opens the recorder until an attempt ends without a lives rewind following it. Lives rewinds (`livesRewind` → `onFinished` → `livesResume`, `app/app.js:144-150`, `:951-962`) continue the same recorder and the same video. Anything else that ends an attempt ends the video: «Завершити» / Esc, the song reaching its end, a seek while singing (`applySeek` `:1579`, which the trainer treats as a new attempt), the tab hidden (`:1640`), a device lost, Studio's «Повторити» (a new frame). Each A–B auto-repeat pass is its own video: the trainer defines each pass as a new attempt (`scheduleLoop` comment, `app/app.js:333`), and decision 3 names only lives rewinds as staying inside a video. | decision 3; code |
| D4 | The 30 s rule | Measured on the composed output: from the first segment's music start to the last segment's stop, gaps included. Shorter sittings are deleted at once (raw files too). Nothing offers a «Змонтувати» button for them, and the trainer says so in a toast. Studio owns the threshold (`--video-min-seconds`, default 30). | decision 4 |
| D5 | Budget | `--video-budget` bytes, default 5 GiB, over everything under `songs/videos/`. After every compose, and at Studio start, the video worker deletes whole video folders, oldest `startedAt` first, until the total fits. It never deletes the folder it is composing, a sitting still recording, or the newest ready video. No pinning: the operator asked for automatic deletion. Raw sources (`camera.webm`, `voice-*.wav`, `game.h264`) are deleted as soon as the MP4 passes its checks, so a ready video is its MP4, thumbnail, `take.json` and `align.json`. | decision 4 |
| D6 | Burn | `LumaBurn.drawHeart` unchanged, seeds = heart index, `ms` = video milliseconds since the loss. The video always burns, whatever the reduced-motion preference. | decision 5; LIFE_BURN.md §4 |
| D7 | Dust | Drawn by the same worker and `drawCloud()` from packs the trainer uploads. Each segment uses the set `cloudTakes()` held when that segment started, so the attempt that ends in a rewind joins the dust for the re-sing, as it does on screen. | decision 5; code |
| D8 | Audio | Voice: each segment's WAV, gain 0.9 (the review-playback voice gain, `ensureContext()` `app/app.js:307-313`). Instrumental: `LUMA_ASSETS[String(speed)].backing` decoded from the trainer file named in the take, gain = the recorded `prefs.back`. The original vocal stem is never mixed. `amix=normalize=0`, `alimiter=limit=0.95`, AAC LC 192 kbit/s, 48 kHz stereo. | spec Audio; design §5.5 |
| D9 | Timeline | Output second `u` is AudioContext time `when₁ + u` for the instrumental and the game layer (what was heard and seen), and `when₁ + u + lag` for the voice and the camera, so the latency is applied once and the camera follows the voice. Segment *k* (music start `when_k`, stop `stop_k`, count-in start `cin_k`) sits at output `[when_k − when₁, stop_k − when₁]`. Between segments the game layer shows what the trainer showed: the frozen last frame while the last heart burns, then from `cin_{k+1}` the stage at the rewind point with «Ще раз з mm:ss», the count-in number and the refill. Voice and instrumental are silent in the gap, as they were in the room. The video starts at `u = 0` (music start of segment 1, no count-in) and ends at the last stop. | design §4.1, extended to several segments |
| D10 | Live line and note states in the video | Replayed from the stored attempt: a point appears once the playhead reaches its `songT`, and the score advances to `t − 0.18 × speed` as `tick()` does (`app/app.js:1564-1566`). The line therefore meets the playhead together with the voice you hear. (In the trainer it trails by the latency, because the voice arrives that much later.) Lives come from the trainer's own record: it stores each loss with the playhead song time it happened at, and the render burns that heart when its playhead reaches that time. Replaying `livesStep()` on stored points could lose lives on other frames than the live run did, since live frames are scored before late points arrive. | decision 1 "live pitch line"; code |
| D11 | Mirror | The video is not mirrored, so the singer sees themselves as others do. The framing preview in the settings dialog is mirrored, like a mirror. | convention; no operator word, reversible in one filter |
| D12 | Punch-in | Off while camera mode is on: `punchTarget()` (`app/app.js:400`) returns null, so «Співати» always records a new attempt. Splicing video is out of proportion to the need (design §3.3). | design |
| D13 | WAV | Forced on for an attempt only when a recorder is actually running (`meta.hasAudio = true`). The tab then keeps it under the usual `AUDIO_TAKES` / `AUDIO_BYTES` rules (`:355`). With the camera refused or absent, `prefs.audio` decides as before. | design §3.2; "works exactly as before" |
| D14 | Camera capture | `video: {width: {ideal: 1280}, height: {ideal: 720}, frameRate: {ideal: 30}}`, `video/webm;codecs=h264,opus` (fallback `vp8,opus`), `videoBitsPerSecond: 2.5e6`, `audioBitsPerSecond: 128e3`, `start(1000)`. The circle shows a 300 px crop of the centre square, so 720p is enough; the design's 1080p costs CPU while singing and buys no visible detail. | D1; design §2.3 |
| D15 | Where the camera is offered | Only on Studio-served pages (`studioPage`, `app/app.js:1650`: `/song/*.html` and `/demo`). On `file://` and on any other server the switch is disabled with its reason. | design §3.1 |

There are no open operator questions. D3 (each A–B pass is its own video) and D4 (a sitting under 30 s is deleted)
follow from the trainer's own attempt definition and decision 4. Their consequence goes into the PR so the operator
sees it: fragment loops shorter than 30 s never produce a video. If the operator wants loop passes joined, that is one
predicate (`continuesVideo()` in §5.1).

## 4. Files

### Add

| file | what |
|---|---|
| `docs/design/CAMERA_VIDEO.md` | The design verbatim from `6138fe4` (`git show 6138fe4:docs/design/CAMERA_VIDEO.md`), with a short status block on top: "Built per `CAMERA_VIDEO_BUILD_BRIEF.md`; the operator's 2026-10-14 decisions replace §7's recommendations; §2.1 disk and the shadow line are out of date." Do not rewrite its body. |
| `app/camera.js` | Recorder and uploader, no DOM: `LumaCamera.open(stream, {id, base})`, `.chunk` streaming with `seq`, a bounded send queue (more than 8 unsent chunks: stop and report `slow`), `.voice(k, blob)`, `.finish(take) → Promise<{ok, composed, reason}>`, `.abort()`, and the stamps `ctxAtStart` / `ctxAtOnstart`. Embedded before `app.js` by `studio/build_html.py`. |
| `app/render.js` | The render mode (§5.3): reads `GET /video/<id>/take`, builds the timeline, drives `Luma.render` hooks, draws the overlays (hearts with `LumaBurn`, % + «ЗБІГ», lyric band, the camera ring and dark disc, the count-in in gaps), encodes with `VideoEncoder`, streams `PUT /video/<id>/game?seq=n`, then `POST /video/<id>/rendered`. Idle on every page whose path is not `/video/<id>/render`. |
| `studio/video.py` | Store, alignment (numpy FFT cross-correlation, as `studio/stems.py` does), the render supervisor (start, deadline, kill by the recorded process group), ffmpeg compose, thumbnail, budget and eviction, the `/videos` listing (cached per folder by `take.json` mtime). One worker thread owns the queue and the eviction. |
| `tests/e2e/video.mjs` | The new suite (§8). |
| `tests/video_test.py` | Unit tests for alignment, the budget, eviction order, the render deadline and the ffmpeg graph on synthetic inputs (§8). |

### Change

| file | change |
|---|---|
| `app/app.js` | `prefs.camera` (boolean, default false, read like `lives`). In `ensureMic()` (`:322-337`), one `getUserMedia({audio: {…as now}, video: {…D14}})` when camera mode is on; on `NotAllowedError` / `NotFoundError` / `NotReadableError` / `OverconstrainedError` / `AbortError` retry audio-only and remember the reason. Reuse an open stream only when it has the video track camera mode wants. **Attach `onended` to the audio track only** (today `:334` puts it on every track, so a lost camera would report «Мікрофон від’єднався» and stop the attempt); the video track's `onended` ends the recording and leaves singing alone. Sitting lifecycle in `startTransport()` (`:442`), `onFinished()` (`:951`), `stopTransport()` (`:474`), `releaseMic()` (`:321`). Per-segment record: `when`, `cin`, `stop`, `a`, `endSong`, `speed`, `latency`, `runId`, the take's `takePayload()` (`:888`), lives total, losses, `retryFrom`, dust pack ids. Lives losses recorded in `livesStep()` (`:122-136`) as `{i, at: now(), left}` on `s.lives`. `punchTarget()` returns null with camera mode on. `tellHost()` waits for `LumaCamera.finish` (at most 10 s). The settings field, the badge and the takes-card button (§6). Render-mode hooks (§5.3) on `window.Luma.render`, defined only in render mode. |
| `app/head.html` | The settings field after «Записувати голос у WAV» (`:435`), with a circular preview and a state line; `#camBadge` in `.bar` after `#status` (`:410`); an `i-camera` symbol; render-mode CSS under `html[data-render]` that hides everything except `#chartWrap`, pinned `position: fixed; inset: 0`. |
| `studio/build_html.py` | `parts()` (`:21-25`) embeds `camera.js` and `render.js`, in the order `activity, latency, burn, camera, app, render`. |
| `studio/studio_server.py` | The `/video…` and `/videos` routes (§5.4), delegating to `video.py`. Origin check on every write, as `activity()` does (`:333-336`). `--video-budget`, `--video-min-seconds`, `--render-deadline-factor` (default 3, deadline = factor × duration + 60 s). Start the video worker and requeue unfinished videos at startup. |
| `studio/studio.html` | «Мої відео» section and player (§6.3). `#video/<id>` opens the player. `makeFrame()` (`:249`): `f.allow = 'microphone; camera; autoplay; fullscreen'`. |
| `tests/e2e/run.sh` | Add `video` to the suite loop and `"$PY" tests/video_test.py` before `audio_stems_test.py` (which must stay last). |
| `README.md` | A «Відео з камерою» bullet under "What the trainer does", a «Мої відео» paragraph under the Studio section, `video.mjs` and `video_test.py` in Tests, `camera.js` / `render.js` / `video.py` in Layout, one Privacy paragraph: what is filmed, where it lies (`songs/videos/`), the 5 GB cap, «Видалити», off by default, never leaves the computer. |
| `docs/ACTIVITY_LOG.md` | The events in §6.4. |
| `docs/design/LIFE_BURN.md` | Only the sentence that says CAMERA_VIDEO.md is "not on main yet". |

## 5. Mechanics

### 5.1 Trainer: one sitting, one recorder

- `startTransport(sing)`: when camera mode is on, the stream has a live video track and no sitting is open, open one:
  `id = crypto.randomUUID()`, `LumaCamera.open(stream, …)`, stamp `s.ctx.currentTime` at the `start()` call and in
  `onstart`. Set `meta.hasAudio = true`. Record `cin = s.ctx.currentTime` at the call and `when` from the transport.
- `onFinished(m)`: if `storeTake()` stored the attempt, upload its WAV as segment *k* and push the segment record. Its
  stop time is `when + lag + m.duration`, the worker's own end, taken from the `when` the segment recorded at its start,
  because `onFinished` has already cleared `s.transport`. All segments of one sitting share one `latency`: settings are
  locked while singing, and the rewind gap is too short to change them. Assert it, and close the sitting if it differs. Then decide `continuesVideo()`.
  That is true exactly when `livesResume(m)` is about to restart (`s.livesRetry` matched `m.id`). If false, close the
  sitting: `recorder.stop()`, wait for the last chunk, `PUT /video/<id>/take`, read Studio's answer. An attempt that
  `onFinished` discards (≤ 0.15 s) is simply left out of the segments. A sitting with no segments sends
  `DELETE /video/<id>`.
- A continuation that never starts (the singer pressed Stop during the re-sing count-in, so `startTransport` exits
  through `s.busy`) closes the sitting with the segments it has.
- `releaseMic()`, `visibilitychange`, a lost microphone, a lost camera, a refused chunk: stop the recorder first, then
  close the sitting with what is complete. After a lost camera or a refused chunk the attempt sings on and the sitting is
  closed with the footage so far. Studio holds the last camera frame (`tpad=stop_mode=clone`) to the end.
- The tick loop never waits on an upload: chunks go out through `LumaCamera`'s own promise chain.

### 5.2 Take record (`PUT /video/<id>/take`, JSON)

`{v: 1, id, trainer: hostFile(), songId, songHash, title, startedAt, ctxAtStart, ctxAtOnstart, mime, view, octave,
scaleZoom, back, speed, notes?, verified?, dust: {<packId>: {seed, buf: base64 Float32}}, segments: [{k, runId, when,
cin, stop, a, endSong, latency, history: takePayload(take), lives: {total, losses: [{i, at, left}], retryFrom}|null,
dust: [packIds]}]}`

`notes` and `verified` are sent only when this browser has edits for the song. Studio validates sizes (refuse over
32 MiB) and every number, and resolves `trainer` to `examples/demo/Luma_Demo.html` for `demo`, else to `SONGS/<name>`
(basename only).

### 5.3 Render mode

- Active when `location.pathname` matches `^/video/[0-9a-f-]{36}/render$`. `activity.js` and the latency estimate are
  already silent on that path. In render mode `historyAvailable()` returns false, `loadHistory()`, the microphone,
  autoplay, the audio notice toast and every dialog stay off, `html` gets `data-render`, the canvas is 1920×1080 at DPR 1
  (force it in `resize()`), `s.headH = 0`, `s.railH = 180`, `s.dense = false`, and `measureStage()` / `fitStage()` are
  skipped.
- **Virtual clock.** `followRange()` (`app/app.js:258`) reads `performance.now()` and `easeScale()` takes a frame `dt`.
  In render mode both read `s.vclock` (output seconds) and `dt = 1/30`. This is the only change to the existing drawing
  path.
- `Luma.render` hooks (render mode only): `load(take)` applies `notes` / `verified`, view, octave, zoom, rebuilds each
  segment's points and score with `unpackTrace()` + `analyzeTake()` (as `restoreTakes()` does, `:710-728`), and posts
  each segment's dust packs to the cloud worker. `frame(u)` sets the state for output time `u` (§3 D9, D10), calls
  `draw(t)`, and resolves once `cloud.fit` is true for that frame, or at once when there is no dust (re-draw after the
  layer arrives). It returns `{t, segment, gap, left, total, lossMs, notice, count, pct}` for the overlays and the tests.
- Overlays drawn by `render.js` after `draw(t)`:
  - Hearts: size 36 px, centres on y = 92 px, the row right-aligned so that the last heart's centre is ≤ 1700 px. The
    burn's glow reaches 2.4 sizes (86 px) and must stay inside the frame. Draw the row into a transparent canvas the
    size of its `LumaBurn.box`, then `drawImage` it onto the frame (LIFE_BURN.md §4, Compositing). Refill: after the
    burn ends, each heart pops back over 0.45 s with a 45 ms stagger, the `lifeRefill` curve (`app/head.html:297`).
  - Match %: right of the hearts, `500 60px` sans, tabular, with the trainer's good/low colours; «ЗБІГ» under it,
    12 px, letter-spacing 1.3 px. Live % = `scorePct(s.live)`.
  - Lyric band: centred in 900–1060 px. Current line 44 px in `.lyric-line.now` colours (sung word `#f2f8ff` 600 with a
    mint underline, past and coming `#98a6bc`); next line 30 px `#96a4ba`. Shrink the current line to fit 1700 px, down
    to 30 px, then wrap it onto two lines and drop the next line. Never ellipsize.
  - Camera seat: a dark disc and the ring around (222, 720) r 150 / 155, drawn every frame, so the circle reads even
    where the camera has ended.
  - Gap: the trainer's countdown look scaled for 1080p. A radial dark wash, «Ще раз з mm:ss» 30 px rose and «Забагато
    промахів поспіль · життя відновлено» 17 px, then the count number 96 px mono 300 mint.
- Encoding: `VideoEncoder({codec: 'avc1.640028', avc: {format: 'annexb'}, width: 1920, height: 1080, bitrate: 6e6,
  framerate: 30})`, a key frame every 60 frames, back-pressure on `encodeQueueSize > 8`. Chunks are sent in order. Any
  error posts `POST /video/<id>/render-failed` with the message, and the page logs nothing to the console in the normal
  case.
- `?hold=1` loads and builds the timeline but does not encode, so the e2e suite can call `Luma.render.frame(u)`.

### 5.4 Studio

```
PUT    /video/<id>/camera?seq=n       append a webm chunk; 409 unless n is the next seq; 507 when the write fails
PUT    /video/<id>/voice?seg=k        one segment's WAV (≤ 700 MB, streamed to disk in 1 MiB pieces like upload())
PUT    /video/<id>/take               the take record → {composed: true} | {composed: false, reason: 'short'|'invalid'}
DELETE /video/<id>                    discard (a sitting with no segments, or «Видалити»)
GET    /videos                        {videos: [{id, title, startedAt, duration, segments, state, progress, bytes, error?}], used, budget}
GET    /video/<id>/take               the take record (for the render page)
GET    /video/<id>/render             the trainer file bytes; the path itself switches render mode on
PUT    /video/<id>/game?seq=n         H.264 Annex B from the render;  POST …/rendered;  POST …/render-failed
GET    /video/<id>/video.mp4          with Range → 206 (send() returns whole files today, :225-226)
GET    /video/<id>/thumb.jpg
```

States: `recording` → `queued` → `aligning` → `rendering` (progress = frames / expected) → `composing` → `ready`, or
`failed` with a reason. `id` must match the UUID pattern.

Pipeline per video, in the one video worker, under `nice -n 19`:

1. **Align.** Decode the webm audio and each WAV to 48 kHz mono. Find `W0`, the AudioContext time of webm t = 0, by
   correlating the longest segment's WAV inside ±0.3 s of the stamp estimate `ctxAtStart + 0.018`. Accept a peak only
   when it is ≥ 0.5 and the runner-up more than 50 ms away is below 0.7 × the best. Otherwise use the stamp and set
   `approximateSync`. Write `align.json` with `W0`, the peak, the runner-up, the fallback flag and the per-segment
   residuals (they must agree within one frame, 33 ms; report the spread).
2. **Render.** The browser is `LUMA_BROWSER`, else the first of `msedge`, `/opt/microsoft/msedge/msedge`,
   `google-chrome`, `chromium` found on PATH. Run it with `--headless=new --user-data-dir=<songs/videos/<id>/.profile>
   --disable-gpu --mute-audio --no-first-run --no-default-browser-check --force-device-scale-factor=1
   --window-size=1920,1080 http://127.0.0.1:<port>/video/<id>/render`, `start_new_session=True`. Record the PID. On
   `rendered`, on `render-failed` or at the deadline, end that process group (`os.killpg` of the PID Studio started),
   wait for it, and remove the profile dir. With no browser, mark the video `failed` with «Для монтажу потрібен Edge або
   Chrome» (nothing ships without the game layer, which decision 1 requires).
3. **Compose.** One ffmpeg run: the game H.264 at 30 fps is the base. The camera is `setpts` by `W0 − when₁ − lag₁`
   (trim when negative), `fps=30`, centre-square crop, `scale=300:300`, a soft circular alpha (`geq`, a 1 px edge),
   `tpad=stop_mode=clone`, and `overlay=72:570`. Each voice WAV is `adelay` by `when_k − when₁` (sample units), each
   instrumental piece `atrim=start=a_k/speed:duration=stop_k−when_k` and `adelay` by `when_k − when₁`, all into
   `amix=normalize=0` and `alimiter`. Encode `libx264 -preset veryfast -crf 22 -maxrate 5M -bufsize 10M -profile:v high
   -pix_fmt yuv420p`, AAC 192k 48 kHz stereo, `-movflags +faststart`, `-t <duration>`, written to `video.mp4.part` and
   renamed after `ffprobe` passes. Then `thumb.jpg` (one frame at 40 %), delete the raw sources, run eviction.
4. The instrumental is decoded from the trainer's `LUMA_ASSETS` once per (trainer mtime, speed) into
   `songs/videos/.stems/` and counted in the budget.
5. At startup: requeue folders that have `take.json` but no `video.mp4`. Delete folders with no `take.json` and no write
   for an hour (a closed or crashed tab).

## 6. Trainer and Studio surfaces

### 6.1 States the trainer must handle

| state | what happens | what the singer reads |
|---|---|---|
| Switch off (default) | Nothing changes: `getUserMedia` with `video: false`, no `/video` request | — |
| Not a Studio page (`file://`, another server) | Switch disabled | «Відео працює, коли пісню відкрито з бібліотеки Studio.» |
| Switch turned on | The camera opens for the preview while the dialog is open (this is where the browser asks first), and closes when the dialog closes unless singing | Hint: «Типово вимкнено. Кожна спроба від 30 с стає відео: ти в кружечку поверх нот, твоя лінія, слова й життя, голос — із затримкою мікрофона — поверх мінусу. Відео в Studio, «Мої відео»: до 5 ГБ, найстаріші видаляються самі. Поки камера ввімкнена, «Перезаписати з …» вимкнено.» |
| Camera denied | Singing runs audio-only, exactly as with the switch off; `video_capture {ok: false, reason: 'denied'}` | State line: «Доступ до камери заборонено. Дозволь камеру для цієї сторінки біля адреси; поки що спроби йдуть без відео.» Toast once per page at «Співати»: «Камера недоступна: спроба без відео.» |
| Camera absent / overconstrained | Same, `reason: 'absent'` | «Камеру не знайдено. Підключи її; поки що спроби йдуть без відео.» |
| Camera busy (another tab or app) | Same, `reason: 'busy'` | «Камера зайнята іншою програмою або вкладкою; спроби йдуть без відео.» |
| Microphone refused too | The existing microphone error path, unchanged | the existing `MIC_ERRORS` text |
| Recording | `#camBadge` shown | «● ВІДЕО» |
| Lives rewind mid-attempt | The same recorder continues, a new segment starts after the count-in, the badge stays on | — |
| Camera unplugged mid-take | The attempt continues; the video ends its footage there and holds the last frame | Toast: «Камера від’єдналась: відео цієї спроби закінчується тут, спів триває.» |
| Studio refuses a chunk (write failed, server gone) or the send queue overflows | The recorder stops, singing goes on, the sitting closes with what Studio has | Toast: «Studio не приймає відео: спроба триває без відео.» |
| Sitting < 30 s | Studio deletes it, answers `short` | Toast: «Спроба коротша за 30 с: відео не змонтовано.» |
| Sitting ≥ 30 s | Studio queues it; the attempt cards of the sitting get a «Відео» button that opens `/#video/<id>` in a new tab | Toast: «Відео монтується в Studio, «Мої відео».» |
| Session frame (Заняття, «Обери за мене») | `luma:finished` is posted after the take upload settles (≤ 10 s; on timeout it posts anyway and logs `video_upload {ok: false}`) | — |
| Evicted video, link opened later | Studio player | «Цього відео вже немає: найстаріші видаляються самі, щоб відео займали не більше 5 ГБ.» |

### 6.2 New trainer controls at 390 px and desktop

- **Settings field** (dialog, after the WAV field). At 1440×900 the dialog keeps its width. The preview is a 120 px
  mirrored circle beside the hint, and the state line sits under it. At 390×844 the field stacks: checkbox row
  (≥ 44 px target), hint, preview centred, state line. Nothing scrolls sideways, and the dialog body scrolls as it does
  today.
- **`#camBadge`** in the top bar, shown only while a sitting records. Its style is `.status.rec` (rose dot, blinking).
  At ≤ 720 px `.status` is hidden (`app/head.html:316`), and the badge must stay visible on the bar's first row next to
  the icon buttons, without pushing them onto a new row and without covering the song title row. At 1440 it sits after
  `#status`.
- **Takes card «Відео»** in `.take-actions`, before the ↓ button, with `i-camera` and the label; the same size as the
  card's other buttons (≥ 40 px at 390 px, where `.take-actions` already wraps).
- Check at 390, 900 and 1440 px wide (900 is the width between the two named ones), each state above whose text shows
  in the dialog, with a real song title in the bar.

### 6.3 «Мої відео» in Studio

A section after «Бібліотека», hidden while there are no videos: «Мої відео · N», then «Займають 1,2 з 5 ГБ · найстаріші
видаляються самі». Cards newest first: thumbnail (16:9), song title, date and time, duration, and a state badge with
distinct words per state («Записується», «Чекає на монтаж», «Монтую · 40 %», «Не вдалося: …»). A ready card opens a
`<dialog>` player: `<video controls playsinline preload="metadata">`, «Завантажити» (`<a download>`, file name
`Luma_<title>_<YYYY-MM-DD_HH-MM>.mp4`), «Видалити» (with a confirm), close. The dialog is modal (background inert). At
390 px cards are one column, the video is full width, buttons ≥ 44 px. At 1440 the grid matches the library's.

### 6.4 Activity events

`video_capture {ok, reason?}` when a sitting opens or fails to; `video_upload {ok, ms, bytes, segments}` when it
closes; `video_open {id}` and `video_download {id}` from Studio. Document them in `docs/ACTIVITY_LOG.md`.

## 7. Do not touch

- `app/burn.js`: call `drawHeart`, change nothing in it. The trainer's DOM hearts, `burnLife()` and `renderLives()`,
  except recording the loss in `livesStep()`, which changes no rule.
- The lives rule and constants (`LIVES`), the scoring engine (`scoreAdvance`, `newScore`, `LEVELS`), the wordless rule
  (`WORDLESS`, `wordedSpans`), `singEnd()`, the history schema and store (`docs/HISTORY_SCHEMA.md` does not change;
  videos are not history), `app/latency.js`, the dust worker and `DUST` constants, `measureStage()` / `fitStage()` /
  `bounds()` on normal pages.
- The song pipeline, the song-prep `worker()`, `/import`, `/status`, `/targets`, covers, difficulty, autopick and the
  session state machine in `studio/studio.html`, beyond the `allow` attribute and the new section.
- Every existing suite in `tests/e2e/run.sh` must pass unchanged, `lives.mjs`, `audio.mjs`, `session.mjs` and `cloud.mjs`
  above all.
- The operator's running Studio, browser profile and `songs/`: the suite uses its own library and processes.

No other open lane touches these files: there are no open pull requests or open pipelines on 2026-10-19, and the
unmerged local branches are design-only or older lyric work that does not touch `app/` or `studio/studio_server.py`.

## 8. Checks to add

`tests/e2e/video.mjs` starts its own Studio processes on free ports (bind port 0 to find one), each with its own
temporary library, records their PIDs and stops only those. It gives them `LUMA_BROWSER` =
`chromium.executablePath()` for the render. It launches Chromium with `--use-fake-device-for-media-stream`,
`--use-fake-ui-for-media-stream`, `--use-file-for-fake-audio-capture=<noise bursts WAV>` and
`--use-file-for-fake-video-capture=<MJPEG>`. Both files are generated by the suite with ffmpeg into its own temp dir:
non-periodic bursts with a fixed seed, never Chrome's periodic beep, and a `testsrc2` clip. Unless a check says
otherwise it uses `--video-min-seconds 3` and the demo at `/demo`.

1. **Off by default.** The switch is unchecked. A sung attempt calls `getUserMedia` once with `video: false` (an init
   script records the constraints), sends no `/video` request, and the existing cards look the same.
2. **Not Studio.** On the plain demo server (`LUMA_URL`) and on `file://`, the switch is disabled with its reason.
3. **One prompt, one recorder.** With the switch on, a sitting makes exactly one `getUserMedia` call with audio and
   video. Turning the switch on after an audio-only attempt makes one more call and then none. «● ВІДЕО» is visible while
   singing and gone after.
4. **Capture.** One folder per sitting: `camera.webm` (ffprobe: video + Opus, duration ≥ the sitting), one
   `voice-k.wav` per segment, `take.json` whose `runId`s match the tab's attempts. A repeated or skipped `seq` gets 409.
   A write from another `Origin` gets 403.
5. **Alignment.** `align.json` has a peak ≥ 0.5, `approximateSync: false`, and a segment spread ≤ 33 ms. A silent fake
   microphone (a zero WAV) gives `approximateSync: true` and a `W0` within 40 ms of the stamp.
6. **Latency once.** Two sittings at latency 0 and 150 ms: in each MP4, correlate the audio with that sitting's voice WAV
   and with the instrumental from `a/speed`. The voice-to-instrumental offset differs by 150 ± 2 ms.
7. **Composed file.** ffprobe: H.264 High, 1920×1080, 30 fps, yuv420p; AAC LC 48 kHz stereo; `moov` before `mdat`;
   duration = expected ± 0.1 s.
8. **Frame content.** With `?hold=1`: `html[data-render]`, the canvas is 1920×1080 at DPR 1, `.bar`, `.transport`,
   `.stage-head`, `.stage-rail`, `.takes`, `#countdown` and dialogs are not rendered. `frame(u)` at five times reports
   the note states and lives the take implies. From the MP4, extract frames: the circle's interior differs from the
   game background (camera present), and the pixels at the transport's and rail's trainer positions match the plot
   background (no chrome). The render page's console stays clean and every request goes to `127.0.0.1`.
9. **Lives sitting.** Lives on, 3 hearts. The noise voice misses, so lives go and the song rewinds. After two rewinds
   the suite presses «Завершити». The result is one folder, 3 segments, one MP4 of `stop₃ − when₁ ± 0.1 s`. Frames
   extracted 0.2 s after each recorded loss show fire colours (`#ff9a3c` range) at that heart. A frame inside the gap
   shows «Ще раз з» (read through `frame(u).notice`), and the voice is silent there (RMS).
10. **Dust.** With 3 seeded past attempts in the tab, `frame(u)` reports the dust drawn (`cloud.fit`) on every
    sampled frame, and the re-sing segment's dust set includes the attempt that ended in the rewind.
11. **Short.** Against a Studio with the default 30 s: a full demo pass (29.96 s) gets `{composed: false, reason:
    'short'}`, the folder is gone and the toast reads «Спроба коротша за 30 с: відео не змонтовано.»
12. **Budget and eviction.** With `--video-budget` set to fit two videos of this length: after the third compose the
    oldest folder is gone, `/videos` lists the two newest, `used ≤ budget`, and `/#video/<oldest>` shows the
    «Цього відео вже немає…» text.
13. **Camera denied / absent / busy.** Denied: a context that grants only `microphone` and runs without the fake-UI
    flag. Absent and busy: an init script that throws `NotFoundError` / `NotReadableError` for video constraints. Each
    sings audio-only with the state line, the toast and `video_capture {ok: false, reason}`. No `/video` request goes
    out. Scores equal those of the same attempt with the switch off.
14. **Camera lost mid-take.** Stopping the video track through a test hook leaves the attempt singing, shows the toast,
    and the video composes with the last camera frame held.
15. **Session.** In «Заняття» with camera mode on, `take.json` exists by the time `luma:finished` reaches Studio. The
    next step opens a new folder. The frame's `allow` includes `camera`.
16. **Range and player.** `Range: bytes=1000-1999` → 206 with exactly those bytes. The Studio player seeks to 75 % and
    `currentTime` advances.
17. **Layout** at 390×844, 900×900 and 1440×900: the settings field in each state, the badge while singing, a card with
    «Відео», Studio's section and open player. No horizontal overflow; no control overlaps foreign text (measured from
    text ranges) or leaves the viewport; targets ≥ 44 px at 390 px (≥ 40 px for card buttons, as today).
    Screenshots `tests/e2e/shot_video_*.png`.
18. **Process hygiene.** After the suite no process's `/proc/<pid>/cmdline` contains the suite's library paths, and the
    render profile dirs are gone.

`tests/video_test.py`: the correlation recovers known offsets (−400…+50 ms) on synthetic bursts through Opus within
1 ms, and refuses a periodic signal (fallback). Eviction order: oldest first; never the recording, composing or newest
ready one; a stale incomplete folder goes first. The size accounting includes `.stems/`. A stub browser that sleeps is
killed at its deadline by its process group, the video is `failed`, and the stub's PID is gone. The ffmpeg graph on
synthetic camera, game and audio produces the expected duration and an audio offset equal to the requested `adelay`.

The project's own check is `tests/e2e/run.sh` in full (README "Tests"). Run it with `LUMA_PY` set to the main
checkout's `.venv/bin/python` and with free ports.

## 9. Deferred — not currently justified

- Portrait output, a landscape/portrait switch, both orientations (operator chose landscape only).
- Layout variants 1 (split) and 2 (camera full frame with a transparent game layer); the matte stream for variant 2.
- Pinning videos («Зберегти назавжди»): the operator chose automatic deletion.
- «Змонтувати» for sittings under 30 s, and keeping their raw footage.
- One video spanning A–B auto-repeat passes or a whole practice session; concatenating videos.
- `videoOffset`, «Зсув відео» and the clap test (design §4.3–4.4). `W0` comes from the microphone itself; the camera's
  own lag behind its microphone is unmeasured on the real camera. If the operator sees lips late, measure it once and add
  a constant.
- A camera picker (`prefs.cam`): the system default camera is used.
- Disk floor and 507 on low space (317 GB free); a failed write already answers 507 and the trainer goes on without
  video.
- NVENC; HEVC/AV1; 1080p+ camera capture; loudness normalization; per-video mix sliders; a quiet guide vocal.
- Recovering a crashed tab's partial sitting (a stale incomplete folder is deleted after an hour).
- Live compositing during the take, muxing in the browser (design §5.1 A and B).
- Sharing to messengers; video in the history export; video on `file://`.
- An ADR: every choice here is reversible within this feature.

## 10. Validation against the requirement

| requirement | where |
|---|---|
| «вывести камеру на меня, чтобы записывать автоматически» | one switch; every sitting records with no extra step (§5.1, §6.1) |
| «писался … мой голос, камера» | one camera + microphone stream, one webm per sitting, a WAV per attempt (§5.1) |
| «подставлялся правильно с учётом сува» | D9: voice and camera shifted by each attempt's `latency`, camera placed by correlation (§5.4 step 1), check 6 |
| «именно минус этой песни» | D8: the trainer's own backing stem at the attempt's speed and start; check 6 |
| «показывалось потом в видео … я посмотрю, как я пою» | composed automatically, «Мої відео» player, link from the attempt card (§6.3), checks 7, 16 |
| «без лишнего интерфейса … линию, как я пою … слова … жизни» | D1, D10, §5.3 overlays, check 8 |
| «жизнь сгорает … эффектно … и это на камере» | D6: the same `drawHeart`, check 9 |
| «красивое видео» | the chosen frame, game layer at native 1920×1080, H.264 High + AAC (§5.3, §5.4) |
| decision 3: rewinds inside one video | D3, D9, check 9 |
| decision 4: ≥ 30 s automatic, 5 GB oldest-first | D4, D5, checks 11, 12 |
| decision 5: dust as in the trainer | D7, check 10 |
| "camera denied or absent: works exactly as before, clear message" | §6.1, check 13 |
