# Design: a camera video of the take, composed with the game layer and the backing track

> **Status (2026-10-19):** built per [CAMERA_VIDEO_BUILD_BRIEF.md](CAMERA_VIDEO_BUILD_BRIEF.md). The operator's
> 2026-10-14 decisions replace §7's recommendations (the game fills a landscape frame with the camera in a circle; one
> video per sitting, lives rewinds inside it; every sitting of 30 s or longer is composed; oldest deleted past 5 GB).
> §2.1's disk figure and the shadow line are out of date. After the visual reviews of 2026-10-22 the frame differs from
> the brief's D1 in three ways: the roll is drawn at 960×540 and DPR 2, so its type is twice the trainer's; the roll
> fills the frame above the lyric band, and the hearts, the % and a 440 px camera circle stand in one column on its past
> part (centred on x 400), where the roll fades out around them, so no note, word or line runs under any of them; the
> rewind count-in sits on an edged card in a dark halo. The body below is the design as written.

## Originating requirement

Operator, 2026-10-11, Russian voice transcript, verbatim. «сув» is a speech-to-text slip for the latency value (the
microphone offset).

> (1) «И ещё очень важная штука, которую нужно добавить тоже, это возможность вывести камеру на меня, чтобы записывать
> автоматически. Э-э, меня на камеру, как я с- как я пою, чтобы это можно было, короче, записывать. Чтобы писался,
> соответственно, мой голос, камера, как- как оно обычно делается, но потом подставлялся правильно в с учётом сува и
> всего. Правильно подставлялся именно минус этой песни, и мне показывалось потом в видео, где мой минус и плюс, э-э,
> наложены, и я посмотрю, как я пою.»
>
> (2) «Э-э, камера, кстати, я забыл: очень важно, чтобы было видно, чтобы снимался, типа, чтобы снималось то, как я играю,
> без лишнего интерфейса. То есть то, как... ну, то, как у меня линия поётся, то есть, соответственно, чтобы меня было
> видно, линию, как я пою. Также слова, чтобы было видно, вот это всё жизни, чтобы было видно. Кстати, когда жизнь
> сгорает, чтобы оно более так эффектно сгорало, нужно. И это чтобы было тоже на камере, понял? Чтобы это как
> интерактивное такое ви... ну, не интерактивное видео, но красивое видео.»

What this asks for:

| # | Requirement | Where this design answers it |
|---|---|---|
| R1 | Point a camera at the singer and record **automatically** | §3.1, §3.2 |
| R2 | Record the voice and the camera together, "as it is usually done" | §3.2, §3.3 |
| R3 | Afterwards, put the voice in place **with the latency taken into account** | §4 |
| R4 | Put the song's **instrumental (минус)** under it; the video plays voice + instrumental | §5.5 |
| R5 | The video shows the singer, the sung line, the words and the lives, **with no extra interface** | §5.3, §5.4 |
| R6 | A life that is lost **burns more spectacularly**, and that is in the video too | §5.6 |
| R7 | A **nice-looking** video, the singer watches it to see how they sing | §5.4, §6 |

Reading of «где мой минус и плюс наложены»: the pinned specification fixes the audio as the aligned voice plus the
instrumental stem. The original vocal stem is not in the mix (Deferred lists a quiet guide vocal as an option).

## 1. Answer first

- **Capture in the trainer, compose in Studio.** While camera mode is on, every sung attempt also records the camera
  with `MediaRecorder` (camera + microphone in one webm) and streams it to Studio during the take. The microphone WAV
  that the trainer already knows how to record (sample-exact on the song timeline) is forced on for these attempts.
- **Alignment by the audio itself.** Studio cross-correlates the webm's own microphone track against that WAV. On the
  operator's Edge this pins the webm onto the song timeline to the sample; the recorder's own start event is 12–77 ms
  off (§2.4). The latency setting is already applied inside the WAV, so voice, camera and game layer all land on one
  timeline with no second latency rule.
- **Game layer drawn by the trainer's own code, offline.** A render mode of the trainer replays the stored take through
  the same live path the singer saw (notes turning ✓/×, the live line, words, lives), with a virtual clock and no
  chrome, and encodes it with WebCodecs H.264. Studio runs it in a headless browser it starts itself, so no open tab is
  needed and a singing tab is never slowed. Measured: 51–81 frames per second, a 4-minute song in 1.5–2.4 minutes.
- **ffmpeg does the rest.** Studio's existing ffmpeg places the camera and the game layer into the chosen layout, mixes
  the voice with the instrumental stem taken from the trainer file itself, and writes MP4 (H.264 + AAC, faststart) that
  phones play. 60 s of output composes in 10.7 s (libx264) or 8.4 s (NVENC).
- **«Мої відео» in Studio**: a list, a player with seeking, download, an on-demand landscape version, a 5 GB budget
  that cleans up after itself. The disk holding `songs/` has **15 GB free** today (99 % full), so the budget is not optional.
- **Recommended layout: split** (camera above the game in portrait, beside it in landscape). Five operator choices are
  in the prototype review with a recommendation each; the design proceeds on the recommendations (§7).
- **Phase 1 is useful alone**: camera + aligned voice + instrumental, no game layer yet. Phase 2 adds the game layer,
  Phase 3 the burn effect and landscape (§9).

## 2. Measured on this machine (2026-10-11/12)

Probe scripts and raw results: `/var/tmp/luma-camvideo-0067b6ea/probe/` (`probe.mjs`, `align.mjs` + `align.py`,
`render.mjs`, `cpu.mjs`, `iframe.mjs`, `comp/compose_bench.sh`). Every browser probe ran in the operator's browser binary,
Microsoft Edge 155.0.4283.45 (`/opt/microsoft/msedge/msedge`), headless, with a fresh profile and pages served by
Playwright on a `localhost` origin: the operator's profile, Studio and the real camera were never touched.

### 2.1 Hardware and tools

| what | result |
|---|---|
| Camera | Logitech MX Brio on `/dev/video0` (`v4l2-ctl`): MJPG up to 1920×1080 @ 30 fps, 1280×720 @ 60; YUYV only up to 848×480 |
| CPU / GPU | Ryzen 7 3700X (8 cores, 16 threads); RTX 3060 |
| ffmpeg | n9.0.2 with libx264, h264_nvenc, libvpx, libopus, aac, librubberband, filters overlay / vstack / hstack / xstack / amix / adelay |
| Disk | `/home` 1.4 T, **15 G free (99 %)**; `songs/` is 3.7 G |

### 2.2 Edge 155: what the browser can record and encode

| capability | result |
|---|---|
| `MediaRecorder` webm | `vp8,opus` ✓ · `vp9,opus` ✓ · `av1,opus` ✓ · `h264,opus` ✓ |
| `MediaRecorder` mp4 | only with Opus (`avc1,opus` ✓, `av01,opus` ✓); **`avc1 + mp4a.40.2` (AAC) ✗**, `audio/mp4;codecs=mp4a.40.2` ✗ |
| `AudioEncoder` | `opus` ✓, **`mp4a.40.2` (AAC) ✗** |
| `VideoEncoder` | `avc1.640028` (High) and `avc1.4D0028` software ✓ at 1080×1920 and 1920×1080; `avc1.42E01E` ✗; VP8, VP9, AV1 software ✓; HEVC ✗; **no hardware encoder for any codec** |
| alpha in `VideoEncoder` (`alpha:'keep'`, VP8 / VP9) | ✗ |
| `MediaStreamTrackProcessor`, `VideoDecoder`, `OffscreenCanvas`, `requestVideoFrameCallback` | present |
| WebM from `MediaRecorder` | no duration and no cues (`duration=N/A`), so a `<video>` cannot seek in it; ffmpeg reads it fine |

The browser cannot produce AAC at all, so a phone-friendly MP4 needs ffmpeg in any design.

### 2.3 Cost of recording the camera while singing

12 s of 1920×1080 @ 30 camera (fake device fed an MJPEG file) plus microphone, CPU of the whole Edge process tree:

| | cores | bitrate asked 4 Mbit/s, got |
|---|---|---|
| camera open, not recording | 0.27 | — |
| `video/webm;codecs=h264,opus` | **0.56** | 2.6 Mbit/s |
| `video/webm;codecs=vp8,opus` | 0.92 | 4.3 Mbit/s |
| `video/webm;codecs=vp9,opus` | 1.31 | 3.7 Mbit/s |

H.264-in-webm costs a third of a core on top of an open camera. That is what the capture uses (VP8 as fallback).

### 2.4 Where the recorder's t = 0 sits on the audio clock

One `getUserMedia` stream fed an AudioWorklet stamped with `currentFrame / sampleRate` (as `app/workers.html:15` does) and
a `MediaRecorder` at once; the fake microphone played non-periodic noise bursts. Cross-correlating the webm's Opus track
against the worklet PCM:

| run | webm t = 0 vs `recorder.start()` call | vs `onstart` event | normalized correlation peak |
|---|---|---|---|
| 0 | +18.2 ms | −67.2 ms | 0.83 |
| 1 | +8.2 ms | −77.2 ms | 0.90 |
| 2 | +30.8 ms | −11.8 ms | 0.89 |
| 3 | +10.8 ms | −31.8 ms | 0.92 |

Timestamps alone are 8–31 ms off from the call and 12–77 ms off from the event, and the error moves from take to take.
The correlation is unambiguous on a non-periodic signal; with Chrome's periodic test beep it locked onto the wrong period,
which is why the fallback below refuses weak or repeating peaks. `MediaStreamTrackProcessor` frame timestamps use their
own epoch (≈ 181 370 896 ms away from `performance.now()`), so they offer no shortcut either.

### 2.5 Drawing the game layer offline with the trainer's own code

`render.mjs` pins the stage to a video panel size, hides the DOM overlays, and replays a synthetic take through
`Luma.test.fakeSing` / `livePush` / `fakeTick` (the live path with a virtual clock, `app/app.js:1606-1609`), then
encodes every canvas frame with `VideoEncoder` (`avc1.640028`, Annex B, 6 Mbit/s), headless with `--disable-gpu`:

| trainer | panel | frames per second, draw + encode | KB per frame |
|---|---|---|---|
| demo | 1080×960 | 79.8 | 14.2 |
| demo | 1080×1920 | 54.3 | 21.5 |
| demo | 1920×1080 | 54.8 | 14.2 |
| a real library song (60 s, dense notes and words) | 1080×960 | 80.9 | 19.4 |
| same | 1080×1920 | 51.1 | 22.9 |

A 4-minute song is 7 200 frames: about 1.5 minutes for a 960-pixel panel, 2.4 minutes for a full portrait frame. No
console errors. (The first attempt hid the bottom rail with `display:none`; `measureStage()` then measures the rail from
the top of the page and squashes the plot to 40 px. The render mode must hide it by collapsing it to zero height at the
stage bottom, as the probe's second run did.)

### 2.6 Composing with ffmpeg

60 s of a 1080×1920 split frame: a 1920×1080 camera (synthetic, noisy, so the worst case for size) cropped to
1080×960 above the game layer stream, voice WAV + instrumental MP3 mixed, AAC 192 k, `+faststart`:

| encoder | time | size |
|---|---|---|
| libx264 `-preset veryfast -crf 21` | 10.7 s | 39.5 MB |
| libx264 `-preset medium -crf 21` | 18.1 s | 43.8 MB |
| h264_nvenc `-preset p5 -cq 23` | 8.4 s | 65.6 MB |

Output: H.264 High 1080×1920 30 fps + AAC LC 48 kHz stereo. Uncapped CRF on a noisy camera runs to 40 MB a minute,
hence the bitrate cap in §6.3.

### 2.7 Studio's session frame and the camera

`studio/studio.html:249` creates the session frame with `allow='microphone; autoplay; fullscreen'`. A probe page with
the same attribute and a same-origin frame opened camera + microphone without asking again (the camera's default allowlist
is `'self'`). Adding `camera` to that list documents the intent and costs nothing.

### 2.8 Where the instrumental lives

- Prepared songs: `songs/<slug>/backing.mp3` (1.0×, CBR 256 k, 44.1 kHz stereo) and `backing_80.mp3` (0.8×),
  `studio/stems.py`, with `foreground*.mp3` beside them.
- **Every trainer file**, including lessons and imported trainers, which have no `songs/<slug>/` folder, embeds the same
  stems as base64: `window.LUMA_ASSETS['1'|'0.8'].backing` (`app/app.js:273` decodes them). That is the exact audio the
  singer heard, so Studio takes the instrumental from the trainer file named in the take (§5.5).

## 3. Capture

### 3.1 Camera mode, one permission flow

- A switch in the trainer settings, next to the WAV switch: **«Знімати мене на камеру»**, off by default (`prefs.camera`,
  saved in `luma.trainer.settings` like every pref, so all trainers of one Studio share it, sessions included). Under it a
  camera picker (`prefs.cam`, like `prefs.mic`) and a mirrored live preview for framing, shown only while the dialog is
  open. Hint: «Кожна спроба записується на відео разом із голосом. Відео монтуються в Studio, «Мої відео».»
- Only from Studio: on `file://` the switch is disabled with «Відео працює з бібліотеки Studio». Studio stores and
  composes the videos.
- **One prompt.** With camera mode on, `ensureMic()` (`app/app.js:278-293`) asks
  `getUserMedia({audio:{…as now}, video:{deviceId, width:{ideal:1920}, height:{ideal:1080}, frameRate:{ideal:30}}})` in a
  single call, so Edge shows one camera + microphone prompt and remembers both for the Studio origin. When the microphone
  stream is already open without video (the switch was turned on after singing), the trainer releases it and asks again
  once. The worklet keeps reading only the audio track, so pitch detection is unchanged.
- **The camera never blocks singing.** If the camera is refused, missing or busy, the attempt runs audio-only with a toast
  «Камера недоступна: спроба без відео» and the `error` activity event. If free disk on the Studio side is under 3 GB,
  Studio answers the capture request with 507 and the toast reads «Місця на диску замало: спроба без відео».
- While a camera attempt runs, the stage head shows a small red «● ВІДЕО» next to «ЗАПИС». It is chrome, so it never
  appears in the video.

### 3.2 Automatic recording, one capture per attempt

Camera mode needs no button of its own: **every attempt is filmed**. Whatever starts an attempt starts a capture: «Співати»,
R, a Studio session's auto-start (`autoSing`, `app/app.js:896`), a lives re-sing, an A–B auto-repeat pass, a seek during
singing.

Per attempt, in `startTransport(sing)` (`app/app.js:398`), when camera mode is on and the stream has a video track:

1. `meta.hasAudio = true` for this attempt whatever `prefs.audio` says: the WAV is the alignment reference and the voice
   of the video. Its usual memory budget applies (`AUDIO_TAKES`, `AUDIO_BYTES`, `app/app.js:311`).
2. A capture id (`crypto.randomUUID()`), then `new MediaRecorder(stream, {mimeType: 'video/webm;codecs=h264,opus'
   (fallback vp8,opus), videoBitsPerSecond: 4e6, audioBitsPerSecond: 128e3})`, `start(1000)`. It starts with the
   count-in, so the first sung second is never missing. `ctx.currentTime` at the call is kept as the fallback stamp.
3. Every 1 s chunk goes to Studio at once, `PUT /video/<captureId>/camera?seq=<n>`, appended in order. The tab holds no
   video in memory, and a tab that crashes leaves a playable partial webm behind.
4. In `onFinished()` (`app/app.js:925`) the recorder stops. After `storeTake()` assigns the run id, the trainer uploads the
   WAV (`PUT /video/<id>/voice`) and the take (`PUT /video/<id>/take`, §6.1), which tells Studio that the sources are
   complete. An attempt that `onFinished()` discards (shorter than 0.15 s) sends `DELETE /video/<id>`.

### 3.3 Rewinds, repeats, session auto-advance and the other edges

| event | today | with camera mode |
|---|---|---|
| Lives: the last life burns | the attempt is saved; a new attempt starts from the rewind point after the count-in (`livesRewind` / `livesResume`, `app/app.js:118-123`) | Capture 1 ends with that attempt. Its video ends on the burn and a 1.2 s tail with «Ще раз з mm:ss» over the last camera frame (§5.4). Capture 2 starts with the new attempt's count-in. One video per attempt is the recommendation; one continuous video per sitting is question `rewinds` in the review. |
| A–B auto-repeat, «Повторити» in a session | each pass is a new attempt | each pass is a new capture; passes shorter than 30 s are not composed automatically (question `which`) |
| Session 3-2-1 auto-advance (PR #16, #18) | on `luma:finished` Studio shows the result card and **drops the frame**: `makeFrame(next)` calls `dropFrame()` (`studio/studio.html:350`, `:245-248`) | The video chunks are already in Studio. `tellHost()` (`app/app.js:891`) waits for the WAV and take uploads to settle as well as the history write (bounded at 10 s; on timeout it posts anyway and the activity log gets `video_upload` `{ok:false}`). Both uploads go to `localhost`: a 4-minute WAV is 23 MB. |
| Seek while singing | closes the attempt and starts a new one from the new place (`applySeek`, `app/app.js:1492-1494`) | the same: a new capture |
| Punch-in («Перезаписати з …») | splices the new segment into the shown attempt (`mergeTake`) | **off while camera mode is on**: «Співати» always records a new attempt (`punchTarget()` returns null). Splicing video is out of proportion to the need. |
| Tab hidden | the attempt stops (`app/app.js:1552`) | the capture ends with it |
| Two trainers open, one camera | — | the second gets `NotReadableError` and sings without camera, with the toast above |
| «Вимкнути мікрофон», device unplugged | releases the stream | releases the camera with it; a capture in progress ends with the attempt |

## 4. Alignment

### 4.1 One timeline: the WAV is already on it

The trainer opens the capture window `latency` ms after the music starts: the worker records from `when + lag`
(`app/app.js:410`, `app/workers.html:134-138`), and `analyzeTake` places points at `songT = a + t × speed`
(`app/app.js:439`). So **WAV sample k sits at song time `a + k / sampleRate × speed`**, with `prefs.latency` already
applied. The output video uses that timeline: output second `u` shows song time `a + u × speed`, at the speed the singer
heard. The video is in wall-clock time, so a 0.8× take runs at 0.8×.

| stream | where output second `u` comes from |
|---|---|
| voice | WAV sample `u × sampleRate` (as recorded, no shift) |
| instrumental | the trainer's `LUMA_ASSETS[speed].backing`, from `a / speed` seconds in |
| game layer | frame `round(u × 30)`, drawn at song time `a + u × speed` |
| camera | webm time `u − D + videoOffset`, where `D` is where webm t = 0 falls on the output timeline |

### 4.2 Finding D

Studio decodes both to 48 kHz mono and cross-correlates the webm's own microphone track with the WAV (FFT, numpy, as
`studio/stems.py:alignment` already does for stems), searching `D` in −3.5 … +0.5 s (the webm starts with the count-in, so `D` is negative: about −(2.1 s + latency), or
−(0.6 s + latency) after the short count-in of a re-sing):

```
c[k] = Σ wav[j + k] · webm[j]      D = −(argmax c + parabolic refinement) / 48000
accept when the normalized peak ≥ 0.5 and the second-best peak more than 50 ms away is below 0.7 × the best
```

Both signals are the same microphone, so the peak measured 0.83–0.92 even through Opus (§2.4). The latency setting needs
no second application: the correlation lines the webm up with the WAV, and the WAV already carries it.

**Fallback** when the take has no usable peak (a silent singer on headphones, or a periodic signal):
`D = ctxAtStartCall + 0.018 − (when + lag)`, from the stamp sent in the take record. The four measured runs fell
+8 … +31 ms after the call, so +18 ms is within ±13 ms of each (§2.4). The take and «Мої відео» say «синхрон оцінено приблизно».

### 4.3 Camera against microphone: `videoOffset`

Inside the webm the browser lines video up with audio by capture timestamps. A webcam still delivers its frames later
than the microphone delivers the same moment, and capture timestamps do not fully cover that. `videoOffset`
(`prefs.videoOffset`, ms, default 0, one value per camera) moves the picture against the sound. It is set once with the
clap test below and is written into each take record, so recomposing an old video uses the value it was recorded
with unless the operator changes it in the player.

### 4.4 Verifying A/V sync

- **Automatic, every take.** Studio stores `D`, the peak, the second peak and whether the fallback was used in the take
  record. The e2e suite checks the whole chain against known offsets (§8, checks 3–5).
- **Ground truth for the voice.** In the composed file, the voice and the WAV must line up to the sample: Studio
  re-correlates the MP4's audio against the WAV + instrumental mix it intended and refuses a result more than 1 ms off.
- **Clap test for the camera** (once per camera, Phase 1 acceptance, done by the operator): in camera mode, sing a short
  fragment and clap three times in view. In the player, «Перевірити синхрон» steps frame by frame around the loudest
  three onsets of the voice track. The frame where the hands meet should be on the onset. If it is k frames late,
  `videoOffset = k × 33 ms`, set with the «Зсув відео» field in the player and applied by recomposing. Lip-sync is
  comfortable within ±40 ms (about one frame either side at 30 fps).
- **The latency itself** stays the trainer's business: if the trace is drawn late, the voice in the video is late in the
  same way. The parallel auto-calibration lane (`docs/design/LATENCY_AUTOCAL.md`, branch `77a3bd63`) fixes that
  at the source. Videos keep the latency they were recorded with; a later change of the setting does not move old videos.

## 5. Composition

### 5.1 Options

| | how | quality | sync | speed | complexity | verdict |
|---|---|---|---|---|---|---|
| A. Live compositing in the browser | a canvas draws camera + game during the take, `captureStream` + `MediaRecorder` records it with a mix bus | WebM/Opus only, no AAC (§2.2); real-time encode at singing time | baked in at recording time; the voice heard live is late by the round trip, so R3 would need delay lines on every path | instant | moderate, but it loads the CPU while singing next to the pitch worker, and a dropped frame is permanent | rejected: fails R3 by construction |
| B. Offline, all in the browser | decode camera (needs a webm demuxer library, or a second live encode via `MediaStreamTrackProcessor`), draw, `VideoEncoder`, mux | no AAC in the browser, so Opus-in-MP4 or WebM; a JS muxer library | exact | fast | two vendored libraries in a dependency-free single-file app, plus a render tab | rejected |
| C. Studio only (Python + ffmpeg) | ffmpeg composes, Python redraws the game layer | ffmpeg quality | exact | fast | a second renderer of the notes, trace, words and lives that drifts from `app/app.js` with every change | rejected |
| **D. Trainer draws, Studio composes** | the trainer's own drawing code renders the game layer offline (§5.2), ffmpeg does camera, layout, mix and MP4 | H.264 High + AAC, phone-friendly | exact (§4) | 1.5–2.4 min render + ≈ 45 s compose for 4 min (§2.5, §2.6) | one render mode in `app/app.js`, one headless process supervisor and endpoints in `studio/studio_server.py`, one ffmpeg graph | **chosen** |

D wins on every column except one-step speed, and is the only option where the video's game layer can never diverge from
what the singer saw. Camera mode only exists in Studio (§3.1), and ffmpeg is already a hard requirement of Studio, so D adds no
dependency.

### 5.2 The render mode

`GET /video/<id>/render?o=portrait` serves the take's trainer file (by name from the take record) with `render` flagged.
In that mode the trainer:

- turns off the activity log, history writes, the microphone, autoplay and every dialog;
- pins the stage to the full viewport at DPR 1 and hides the readout, the lyric band, the rail, the invite and the
  count-in, collapsing the rail to zero height (§2.5);
- loads the take record from Studio and replays it through the **live path**: a virtual clock in place of the audio
  clock, `livePush` of the stored points as their time arrives, `scoreAdvance` and `livesStep` exactly as `tick()` runs
  them (`app/app.js:1477-1479`). Note states, the live line, the vertical scale and the lives come out as they were live.
  The scale planner reads `performance.now()` in `followRange()` (`app/app.js:214`); in render mode it reads the
  virtual clock. That is the one change to existing drawing code;
- draws on the same canvas, after `draw(t)`, what is DOM in the trainer: the lyric band (current line with the sung word
  lit and underlined, the next line dimmed), the hearts with the burn (§5.6), the live match % (small, beside the
  hearts). These are new canvas functions; the DOM versions stay for the trainer;
- draws a 1.2 s tail when the attempt ended in a lives rewind: the frozen last frame, the last heart's burn finishing,
  «Ще раз з mm:ss» as in the trainer's count-in notice;
- encodes each frame with `VideoEncoder({codec:'avc1.640028', avc:{format:'annexb'}, bitrate: 6e6, framerate: 30})`,
  a key frame every 2 s, and streams the chunks to `PUT /video/<id>/game?o=portrait&seq=<n>`; then
  `POST /video/<id>/rendered`.

Wordless target chains (PR #17, landed on main after this lane's base) are drawn dimmed by `draw()`, so the video inherits
them.

**Who runs it.** Studio starts the render itself in a headless browser:
`<browser> --headless=new --user-data-dir=<fresh temp dir> --disable-gpu --mute-audio --no-first-run
--window-size=<panel W>,<panel H> http://127.0.0.1:<port>/video/<id>/render?o=portrait`, under `nice -n 19`, one render at a
time (the queue of `worker()` in `studio/studio_server.py` is the model). It records the PID it started, ends that PID
when the page reports done or after `3 × duration + 60 s`, and removes the temp profile. The browser is `LUMA_BROWSER`, else
the first of `msedge`, `/opt/microsoft/msedge/msedge`, `google-chrome`, `chromium` found. Without one, videos stop at
Phase 1 output (camera + voice + instrumental) with «Для монтажу з нотами потрібен Edge або Chrome».

Why not in the operator's tab: a session frame is dropped the moment the attempt finishes (§3.3); a same-origin frame
shares the main thread with the singing frame, so rendering next to it would stutter the live line; and a headless
process needs no tab to stay open.

### 5.3 What the game layer shows, and what it never shows

Shown: the piano roll with named C lines and the note rail, target notes with their ✓ / × states as they happen, the live
pitch line with its halo and current-pitch marker, the personal-best shadow when it was on, words riding the melody, the
lyric band, the hearts with the burn, the live match %. In the last 1.2 s of a rewound attempt, the «Ще раз» notice.

Never shown: the top bar, the readout panel, the transport, the timeline, the takes and progress panel, buttons, toasts,
dialogs, the status pill, «● ВІДЕО». The «ЗАРАЗ» caption and the time axis stay: they are part of the plot.

### 5.4 Layouts

Frames: §7. Sizes are for the output file; the camera is centre-cropped from 1920×1080 (no upscaling in variant 1).

| variant | portrait 1080×1920 | landscape 1920×1080 | ffmpeg | cost |
|---|---|---|---|---|
| **1 · Split (recommended)** | camera 1080×1000 on top; game panel 1080×920 below (plot 760, lyric band 160); hearts + % in the panel's top-right corner | camera 760×1080 on the left; game 1160×1080 (plot 900, band 180) | `crop` + `vstack` / `hstack` | lowest: nothing over the face, no transparency, smallest render (80 fps panel) |
| 2 · Camera full frame, game over it | camera full-bleed, game layer over the lower 45 % on a dark gradient | camera full-bleed, game over the lower half | the game layer needs transparency; WebCodecs has no alpha (§2.2), so the render would draw colour and a matte stacked in one double-height H.264 frame and ffmpeg would `alphamerge` them | twice the pixels to render and encode; notes cross hands and microphone |
| 3 · Game full frame, camera in a bubble | game 1080×1300 + band; camera in a 360 px circle top-left | game 1920×900 + band; camera in a 300 px circle bottom-left, over the past part of the roll | `overlay` with a round mask (`geq` alpha) | low; the face is small |

The render draws the game layer at the panel size of the chosen layout, so text and lines are never scaled. In the
prototype, hearts and % sit over the top of the plot; in the product the plot's top inset makes room for them, as
`bounds()` already does for the stage head.

### 5.5 Audio

- Voice: the WAV as recorded, gain 0.9 (the review-playback voice gain, `app/app.js:266`).
- Instrumental: `LUMA_ASSETS[String(speed)].backing` from the trainer file, decoded by Studio once per song and speed into
  `songs/videos/.stems/<songHash>_<speed>.mp3`, trimmed from `a / speed`, at the singer's `prefs.back` (default 0.75).
- `amix=normalize=0`, then `alimiter=limit=0.95`; AAC LC 192 kbit/s, 48 kHz stereo.
- Without headphones the microphone also hears the speakers. The WAV is shifted by the latency, which is about the
  round trip, so that bleed lands nearly on the instrumental. The settings hint recommends headphones; nothing filters it.

### 5.6 The burn (R6)

The burn has one timing, the same in the trainer and in the video. Storyboard: `burn-storyboard-1600.png` in the review.

| ms | what happens to the heart that is lost |
|---|---|
| 0–120 | white-hot flash, scales to 1.35× |
| 120–700 | fire takes it from the tip upwards: a glowing char line climbs, three flame tongues ride it |
| 300–1100 | 6–8 embers rise and drift, fading (positions seeded by the heart's index, so the video and the trainer match) |
| 1100 → | the ash state: dark fill, dashed outline (today's `.life.lost` shell, `app/head.html:286-288`) |

One canvas function `drawHeart(ctx, x, y, size, state, msSinceLoss, seed)` draws it. The video calls it from the render
mode. The trainer keeps its DOM hearts, because `tests/e2e/lives.mjs` and the aria label read them, and lays a small canvas over the
burning heart for those 1.1 s, replacing the `lifeBreak` keyframes (`app/head.html:290-291`). With reduced motion the
trainer shows only the end state; the video always burns, because it is watched elsewhere.

### 5.7 The ffmpeg graph (variant 1, portrait)

```
ffmpeg -i camera.webm -f h264 -framerate 30 -i game-portrait.h264 -i voice.wav -i stems/<songHash>_<speed>.mp3 -filter_complex "
 [0:v]setpts=PTS-STARTPTS+(D−videoOffset)/TB,fps=30,scale=-2:1080,crop=1080:1000:(iw-1080)/2:40[,hflip],
      tpad=stop_mode=clone:stop_duration=<tail>[cam];
 [1:v]setpts=PTS-STARTPTS[game];  [cam][game]vstack,format=yuv420p[v];
 [2:a]aresample=48000,volume=0.9,aformat=channel_layouts=stereo[voice];
 [3:a]atrim=start=<a/speed>,asetpts=PTS-STARTPTS,aresample=48000,volume=<back>[inst];
 [voice][inst]amix=inputs=2:normalize=0,alimiter=limit=0.95[a]"
 -map [v] -map [a] -t <duration + tail> -c:v h264_nvenc -preset p5 -rc vbr -cq 23 -maxrate 5M -bufsize 10M
 (or -c:v libx264 -preset veryfast -crf 22 -maxrate 5M -bufsize 10M) -profile:v high
 -c:a aac -b:a 192k -movflags +faststart video-portrait.mp4
```

When `D − videoOffset` is negative, the camera input is cut with `trim=start=` by that amount. NVENC when `ffmpeg -encoders` lists it,
else libx264, chosen once at start like `stems.tempo_engine()`.

## 6. Storage, playback, export, size

### 6.1 On disk

`songs/videos/<captureId>/`, beside the other ignored song data:

| file | when | size, 4-minute take |
|---|---|---|
| `camera.webm` | streamed during the take | ≈ 80–130 MB (2.6–4.3 Mbit/s, §2.3) |
| `voice.wav` | at the end of the take | 23 MB (48 kHz mono 16-bit) |
| `take.json` | at the end of the take | ≈ 0.2 MB: capture id, run id, songHash, trainer file, a, endSong, speed, latency, level, view, octave, lives on / count, the packed trace (the history's `takePayload` format), the fallback stamp, `videoOffset`, mirror, camera label, startedAt, score |
| `align.json` | after alignment | D, peak, second peak, fallback flag |
| `game-portrait.h264` | during the render, deleted after compose | ≈ 100–165 MB |
| `video-portrait.mp4` (`video-landscape.mp4` on request) | after compose | ≤ 150 MB at the 5 Mbit/s cap; webcam footage typically half of that |
| `thumb.jpg` | after compose | ≈ 50 KB |

Studio lists videos by scanning these folders and caching each `take.json` by mtime, as `song_meta()` caches trainer heads.
No new index file.

### 6.2 Endpoints (`studio/studio_server.py`)

Write endpoints refuse another `Origin`, as `/activity` does (`activity()` in `studio/studio_server.py`).

```
PUT    /video/<id>/camera?seq=n        append a recorder chunk; seq must be the next one (409 otherwise); 507 under the disk floor
PUT    /video/<id>/voice               the WAV
PUT    /video/<id>/take                the take record: sources complete, alignment queued, composition queued per the rule in §7
DELETE /video/<id>                     drop a capture (discarded attempt, or «Видалити»)
GET    /videos                         [{id, songHash, title, startedAt, duration, score, state: recording|raw|aligning|rendering|composing|ready|failed,
                                         progress, layout, orientations, bytes, approximateSync, pinned}], plus {budget, used, free}
GET    /video/<id>/render?o=           the trainer in render mode (§5.2)
PUT    /video/<id>/game?o=&seq=n       H.264 chunks from the render;  POST /video/<id>/rendered?o=
POST   /video/<id>/compose?o=          compose (or recompose: another orientation, a new videoOffset)
POST   /video/<id>/pin                 keep it out of the clean-up
GET    /video/<id>/<orientation>.mp4   with HTTP Range (206): the handler sends whole files today (`send()`, `:168-169`); a player needs ranges to seek
GET    /video/<id>/thumb.jpg
```

### 6.3 Size budget

- **Videos cap at 5 GB in total** (`--video-budget`, default 5 GB, a third of today's 15 GB free). After each compose, Studio
  deletes, oldest first: the raw sources (`camera.webm`, `voice.wav`) of videos composed more than 7 days ago, then whole
  unpinned videos, until the store is under the cap. Pinned videos are never touched.
- **Disk floor 3 GB**: under it, Studio refuses new captures (507), so singing goes on without camera (§3.1); `/videos`
  reports it and «Мої відео» shows «На диску лишилось N ГБ: нові спроби без відео».
- Output bitrate is capped at 5 Mbit/s video + 192 kbit/s audio: a 4-minute video stays under 150 MB, small enough for
  messengers that take files up to 2 GB.

### 6.4 «Мої відео» in Studio

- A section on the Studio page, under the library header, with a count badge: «Мої відео · 12». Cards, newest first,
  grouped by day: the thumbnail, the song, date and time, duration, the attempt's match %, a state badge while it works
  («Монтую · 40 %», «Чекає на монтаж»). A rewound attempt says «до відмотки».
- A click opens the player: `<video controls playsinline>` over `/video/<id>/portrait.mp4`, with:
  - «Завантажити» (`<a download>`, file name from the song and the date),
  - «Альбомна версія» (composes landscape on demand, then becomes a second download),
  - «Зберегти назавжди» (pin), «Видалити» (with a confirm),
  - «Перевірити синхрон» and «Зсув відео, мс» (§4.4).
  A video composed without the game layer (no browser for rendering, or Phase 1) plays the same way.
- In the trainer, a takes card whose attempt has a video shows a small camera icon. A click opens `/#video/<id>` in
  Studio in a new tab.
- Activity log: `video_capture` {captureId, ok, reason}, `video_upload` {ok, ms, bytes}, `video_ready` {renderMs,
  composeMs, bytes, approximateSync}, `video_open`, `video_download`. Documented in `docs/ACTIVITY_LOG.md`.

### 6.5 Privacy

Camera video is the most personal data Luma would hold. It never leaves the computer: the trainer sends it only to the
Studio that served it (same origin), and Studio stores it under `songs/` (git-ignored) and serves it only on
`127.0.0.1`. The README's privacy section gains one paragraph: what is filmed, where it lies, how to delete it, and that
the switch is off by default. The history export never includes video.

## 7. Prototype review and operator choices

Published as review `pr_58bdcb710bc3d45ec5cc7389fcf65644` on this lane's task, with three layout variants in portrait and
landscape and the burn storyboard. Frames are under `/var/tmp/luma-camvideo-0067b6ea/frames/`. The game layer in each frame is the demo trainer's
own canvas (synthetic syllables, no song), rendered by `render.mjs` at that layout's panel size. The camera is a drawn
stand-in. The lyric band, hearts, burn and % are mocked where the render mode would draw them.

| id | question | options (recommended first) | why the recommendation |
|---|---|---|---|
| `layout` | Which frame first? | **1 · split** · 2 · camera full frame, game over it · 3 · game full frame, camera bubble | Both the singer and the line are fully visible, nothing covers the face, and it is the cheapest to render and compose. 2 costs a matte stream and doubles render pixels. |
| `orientation` | What is composed automatically? | **portrait itself, landscape on a button** · both at once · landscape only | Portrait is what a phone shares; landscape costs another render + compose and up to 150 MB. |
| `rewinds` | A lives rewind: one video or several? | **one video per attempt, ending on the burn and «Ще раз з …»** · one continuous video per sitting | Matches the history (one run, one video), keeps every video's music continuous, and the burn is still on camera. A sitting reel can come later by concatenating the attempts. |
| `which` | Which attempts are composed by themselves? | **every attempt of 30 s or more, within the 5 GB budget** · only passes to the end of the song · none, only on a button | «записывать автоматически … и мне показывалось потом в видео»: watching should need no step. The budget and the disk floor (§6.3) bound the cost. |
| `burn` | Where does the more spectacular burn appear? | **in the trainer while singing and in the video, identically** · only in the video | «когда жизнь сгорает, чтобы оно более так эффектно сгорало … И это чтобы было тоже на камере»: the burn is improved, and it is on camera as well. |

The design proceeds on the recommendations; a different answer changes only the parts named in the table. Phase 1 does
not depend on any of them.

## 8. End-to-end checks

All run under `tests/e2e/run.sh` with Chrome's fake devices (`--use-fake-device-for-media-stream`,
`--use-fake-ui-for-media-stream`, `--use-file-for-fake-audio-capture=<noise bursts WAV>` generated by the suite, never
Chrome's periodic beep, `--use-file-for-fake-video-capture=<MJPEG>` from ffmpeg), the test Studio on its own port and its
temporary library. New suite `tests/e2e/video.mjs`, plus `tests/studio_test.py` cases.

1. **One prompt.** With camera mode on, a sung attempt makes exactly one `getUserMedia` call, with audio and video;
   turning the switch on after an audio-only attempt makes one more, then none.
2. **Capture lifecycle.** Each attempt produces one capture folder with `camera.webm` (ffprobe: video + Opus, ≥ duration
   of the attempt), `voice.wav` and `take.json` whose run id matches the history row. A discarded attempt leaves nothing.
   Chunks arrive in order; a repeated or skipped `seq` is refused with 409.
3. **Alignment.** The fake microphone plays noise bursts. `D` from correlation agrees with the alignment the suite
   computes itself from the WAV and the webm within 1 ms, and `align.json` reports a peak ≥ 0.5.
4. **Latency is honoured once.** Two attempts at `latency 0` and `latency 150`: the composed audio's voice onsets sit 150 ms
   apart relative to the instrumental, the camera follows the voice, and `D` differs by 150 ms ± 1.
5. **Fallback.** A silent microphone gives `approximateSync: true` and a `D` within 40 ms of the stamp.
6. **Render = live.** For a seeded take, the render mode's note states and lives at five times equal what
   `Luma.test.fakeTick` reports at the same times (the frames are the live path); the canvas has no pixels of the
   readout, transport or rail (sampled at their trainer positions); the render page logs nothing to the console.
7. **Composed file.** ffprobe: H.264 High, 1080×1920 (or 1920×1080), 30 fps, AAC 48 kHz stereo, `moov` before `mdat`,
   duration = attempt + tail ± 0.1 s; the voice in it correlates with `voice.wav` at 0 ± 1 ms; the instrumental at the
   start matches the trainer's backing from `a / speed`.
8. **Lives.** A seeded attempt that loses all lives: two captures, the first composed with the 1.2 s tail carrying
   «Ще раз з mm:ss»; the burn frames appear at the loss times the trainer recorded.
9. **Session auto-advance.** In a «Заняття» frame with camera mode on, `luma:finished` arrives only after the WAV and
   take uploads settle; the dropped frame loses nothing; the next step's capture is separate.
10. **Camera refused / busy / disk floor.** The attempt sings audio-only, the toast and the `video_capture` event say why,
    the console stays clean apart from the expected warning.
11. **Budget.** With `--video-budget` set small, composing a new video deletes the oldest raw sources first, then the oldest
    unpinned video; a pinned one survives.
12. **Range.** `GET /video/<id>/portrait.mp4` with `Range: bytes=1000-1999` answers 206 with those bytes; Studio's
    `<video>` seeks to 75 % and plays.
13. **«Мої відео» layout** at 390×844 and 1440×900: no horizontal overflow, buttons ≥ 44 px at 390 px, the player fits;
    screenshots `tests/e2e/shot_video*.png`.
14. **Burn.** In the trainer with lives on, a lost life shows the burn canvas for 1.1 s and then the `.life.lost` state;
    `lives.mjs` still passes unchanged; with reduced motion only the end state.
15. **Process hygiene.** A render that hangs is ended at its deadline by the PID Studio recorded; no browser process
    outlives the suite.
16. **Privacy.** No request leaves `127.0.0.1` during capture, render or compose (the suite routes and counts them).

## 9. Phased plan

Order with other lanes: PR #17 (wordless targets) has landed. The latency auto-calibration lane changes the settings
dialog in `app/head.html` and the latency code paths in `app/app.js`; Phase 1 goes after it lands, or rebases onto it.

| phase | delivers | touches | done when |
|---|---|---|---|
| **1 · Camera + voice + instrumental** (smallest useful) | camera switch and preview, one prompt, capture per attempt, chunk streaming, uploads; Studio store, correlation alignment, ffmpeg compose of the camera (portrait crop) with the voice and instrumental; «Мої відео» with player, download, budget, disk floor, Range; clap test and «Зсув відео» | `app/app.js`, `app/head.html`, `studio/studio_server.py`, `studio/studio.html`, docs | checks 1–5, 7 (audio, camera-only video), 9–13, 16; the operator's clap test lands within ±1 frame |
| **2 · Game layer in the frame** | render mode (virtual clock, clean stage, canvas lyric band, hearts, %), headless renderer under Studio, the chosen layout in portrait, the rewind tail | `app/app.js`, `studio/studio_server.py` | checks 6, 7 (full), 8, 15 |
| **3 · The burn, landscape** | `drawHeart` burn in the trainer and the video; landscape on demand; variant 2 or 3 only if the operator chose it | `app/app.js`, `app/head.html`, `studio/studio_server.py` | check 14; landscape passes check 7 |

Docs with the implementation: README («What the trainer does», Privacy, Tests), `docs/ACTIVITY_LOG.md` (the video
events), `docs/SCORING.md` (lives: the burn), this file's status. `docs/HISTORY_SCHEMA.md` does not change: videos are
not history.

## 10. Validation against the quote

| quote | answered by |
|---|---|
| «вывести камеру на меня, чтобы записывать автоматически» | camera mode; every attempt is filmed with no extra step (§3.1, §3.2) |
| «писался … мой голос, камера, как оно обычно делается» | one camera + microphone stream, one prompt, one webm per attempt plus the lossless WAV (§3) |
| «потом подставлялся правильно с учётом сува и всего» | the WAV carries `prefs.latency`; the camera is placed by correlation against it; `videoOffset` for the camera (§4) |
| «правильно подставлялся именно минус этой песни» | the instrumental from the trainer file itself, at the singer's speed, from the attempt's start (§5.5) |
| «показывалось потом в видео … я посмотрю, как я пою» | «Мої відео»: composed by itself, played in Studio, downloadable (§6.4, question `which`) |
| «чтобы снималось то, как я играю, без лишнего интерфейса» | the render mode draws the game layer only, no chrome (§5.3) |
| «меня было видно, линию, как я пою. Также слова … жизни» | layouts with the camera and the live line, words on the melody and in the band, hearts and % (§5.4, §7) |
| «когда жизнь сгорает, чтобы оно более эффектно сгорало … и это … на камере» | the burn, identical in the trainer and the video (§5.6, question `burn`) |
| «красивое видео» | layouts at native camera resolution, game layer drawn at panel size, H.264 + AAC MP4 (§5.4, §5.7) |

## Deferred — not currently justified

- **Live compositing during the take** (option A). It fails R3 by construction and loads the CPU while singing.
- **Muxing or demuxing in the browser** (option B): vendored MP4/WebM libraries in a dependency-free single-file app,
  and still no AAC.
- **Capturing camera frames through `MediaStreamTrackProcessor` + `VideoEncoder`.** A second live encode with its own
  timestamp epoch (§2.4); `MediaRecorder` + correlation already gives sample-exact placement.
- **A transparent game layer (packed matte)**, needed only for variant 2. Built only if the operator picks variant 2.
- **One continuous video per sitting with the rewinds inside.** Only if the operator answers `rewinds` that way; the
  per-attempt videos can be concatenated by ffmpeg later without new capture work.
- **Automatic camera-lag measurement** (clap detection in picture and sound). The clap test is needed once per camera.
- **Face tracking for the crop.** The crop is centred; the framing preview lets the singer sit right.
- **Punch-in with video.** Splicing camera footage costs far more than the punch saves; camera mode records new attempts.
- **A quiet original vocal as a guide in the mix**, per-video mix sliders, two-pass loudness normalization.
- **4K capture, HEVC or AV1 output.** 1080p30 is the camera's best MJPG mode at 30 fps, and H.264 plays everywhere.
- **Sharing from Studio to messengers or social networks.** Download is enough; nothing leaves the computer.
- **Video without Studio** (`file://`). There is nowhere to store or compose it.
- **Video in the history export.** Videos are files in `songs/videos/`; the history stays numbers only.
- **An ADR.** The choice of D is reversible per phase: Phase 1 does not depend on the renderer.

## Notes on what could not be checked here

- The real MX Brio was not opened in a browser. Its formats come from `v4l2-ctl`, and every capture probe used Chrome's
  fake devices fed with files, so no image of a person was ever recorded. The camera's own lag against the microphone
  can only come from the clap test (§4.4), which Phase 1's acceptance hands to the operator.
- Hardware video encoding was absent in headless Edge. A headed Edge on this Linux + NVIDIA machine is unlikely to differ, and
  the design never needs it: the software paths measured above are fast enough.
