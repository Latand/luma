# Design: a 3D cut-away head that shows how to sing what is due

> **Status (2026-11-14):** slice 1 is built (§8): the panel with the male or female head, hair, articulation from the
> lyric's sounds on the target's timing, the air, the three layouts, the frame budget and the 2D fallback, baked from
> Chimera commit **`e81bc07`** (the fork's main was still at `2e567e2` when the build started). Slices 2 (engaged zones and
> hints) and 3 (the air in detail) are still to come. The build changed settled details, each marked where it stands:
> the hair's colour (§4.2), an onset's length after a rest (§4.5), and in §5 the head in the narrower column, a short
> column's shape and the phone overlay's place and size while singing. Below, the design as settled on 2026-11-13; § [Operator
> decisions](#operator-decisions-settled-2026-11-13) pins the operator's answers.

## Originating requirement

Operator, 2026-11-13, in Ukrainian; the verbatim text is kept in the task record (board task `4986eff8`,
«3D-зріз голови: як треба співати»). Restated: the operator built a 3D version of the head in their fork of the
open-source Chimera vocal synth and wants it brought into Luma as a cut (a cross-section) that shows how to sing. The
singer picks a man or a woman, the head gets hair, the side view shows what clamps or tenses (which muscles and so on),
and the view shows how the air goes.

Read as six obligations:

| # | Obligation | Where this design answers it |
|---|---|---|
| R1 | The 3D head from the operator's Chimera work, in Luma, shown as a cut | §3 |
| R2 | It shows how to sing: the shape for what is due now | §4.5, §5 |
| R3 | The singer chooses a male or a female head | §4.1 |
| R4 | The head has hair | §4.2 |
| R5 | From the side: what tenses or clamps, which muscles | §4.3 |
| R6 | How the air flows | §4.4 |

«Затискається» covers two things a singer cares about: a muscle group that engages for a sound, and a clamp (затиск)
that a singer learns to avoid. §4.3 shows the first from the model and names the second as a tip.

## Operator decisions (settled, 2026-11-13)

Form `pr_9be3d864`, published 20:46 UTC and answered 20:52 UTC; the orchestrator relayed the answers the same evening as
settled, with the details below.

| # | Point | Settled answer |
|---|---|---|
| 1 | Placement | In the song's trainer: a panel beside the notes that moves during singing |
| 2 | Driver | The target only: how the current note and word should be sung. No head driven by the microphone |
| 3 | Body | Head and neck only, no torso. The air is shown from the trachea at the bottom of the neck upward |
| 4 | Depth | Simple: highlighted zones (jaw, tongue, soft palate, larynx) and a short hint in plain words |
| 5 | Source | This lane compares the states and picks, weighing speed heavily (frame time and load cost measured per state), and names the exact commit |

On point 5 the operator added that another of their agents is merging the 3D work into the fork's main, and that the
version wanted is the one that runs fast. The form had recommended a torso as a later step on point 3; the operator
chose none.

What follows:

- The torso (lungs, diaphragm, ribs, abdominal wall), the Studio page, a head driven by the microphone and named muscles
  are under [Deferred](#deferred--not-currently-justified).
- Four zones are highlighted. The lips keep their modelled shape on the cut and appear in the hint when they matter
  (rounded, closed), with no highlight of their own (§4.3).
- Source: Chimera commit **`e81bc07`**, the head of pull request #2, picked on looks and on measured speed (§2.6, §3.1).
  The fork was read again at 23:04 UTC (`gh pr list`, `gh api …/branches`): main still at `2e567e2`, #2 at `e81bc07`,
  #3 at `645d301`, both pull requests open. The fork's older 3D branches (`t3/3d-face-diagram`,
  `t3/enhance-3d-head-diagram`, `t3/animate-eye-movements`) are already in main, and no branch is newer than #2's head
  (2026-11-10). The build lane reads it once more when it starts. If main then contains `e81bc07`
  (`git merge-base --is-ancestor e81bc07 <main>`), it bakes from that main commit after checking that
  `src/ui/render/head/` and `crates/chimera/src/anatomy/tract3d/` match `e81bc07` or improve on it. If main took #3's
  line instead, it differs from `e81bc07` by #2's last four commits (§2.2), and the lane bakes from `e81bc07`, or from
  main once those four are in. Otherwise it bakes from `e81bc07`.
- Speed in Luma: Luma never runs Chimera's engine. Every posture is baked offline into a table (§3.3), so the head's
  frame cost in Luma is Luma's own renderer's, under the budget in §6.

## 1. Answer first

- **Port pull request #2's head** (branch `pipeline/1-opus-3d-cb6d341d`, head `e81bc07`). It is the only state with a
  solid head opened along the midline and an anatomical cut face. Pull request #3's 3D is #2's without #2's last four
  commits (three geometry fixes and one test change); main draws a wireframe with no cut (§2.2, frames in the evidence).
- **What crosses into Luma:** #2's skin mesh (MakeHuman, CC0; male and female), its jaw and lip rig, its cut-face painter
  and its material colours, ported to plain JavaScript. React, three.js, the WASM engine and the audio engine stay behind.
- **Speed, measured:** while a song plays on a desktop GPU at full CPU speed, #2's head costs 11.7–12.9 ms of script
  per frame and drops the page to 39–51 frames a second; #3's costs 16.5–18.2 ms (probably because it lacks #2's faster
  meshes); main's wireframe 1.4–3.8 ms at 60 frames a second (§2.6). #2's cost is the WASM geometry on every change of
  posture plus three.js; Luma's frame budget allows +1 ms. So Luma takes #2's look and none of its runtime: postures are
  baked offline and drawn with Luma's own renderer.
- **Shapes from precomputed tables.** A generator bakes 55 postures per body (22 vowels, 33 consonants), 461 midline
  points each, from Chimera at a pinned commit: 202,840 bytes as 16-bit integers for both bodies. A straight blend
  between two keyframes stays on average 0.06–0.52 mm from Chimera's own in-between posture (§3.3).
- **Raw WebGL2**, as `app/xr.js` already does; three.js would add 541,898 bytes to every trainer (§3.4).
- **Words become phonemes at build time** in Studio (CMUdict for English, rules for Ukrainian) into a per-song table
  beside the song data. In the browser, letter rules cover a missing word, and the panel marks it «приблизно» (§4.5).
- **Placement:** a column beside the roll on wide screens; on a phone, over the already-sung third of the roll (§5).
- **First slice:** the cut head with the male or female choice, hair, articulation and airflow for the target. Then
  the engaged zones and hints, then the air in detail (§8).
- **Cost:** about 0.7 MB per trainer, 1.8 % of the median trainer (40.5 MB), plus a frame budget with checks (§6).

## 2. Ground truth (observed 2026-11-13, 20:48–23:10 UTC)

### 2.1 How the evidence was made

- The fork was cloned into this stage's scratch directory, outside the worktree, and both pull request branches were
  fetched. `gh pr view` confirmed the heads: #2 `e81bc07` (57 commits over main, 82 files, +15,403 / −2,704 lines),
  #3 `645d301` (54 commits), main `2e567e2`.
- Each state was built: a separate Rust toolchain with the `wasm32-unknown-unknown` target installed into scratch (the
  same rustup command as the fork's `vercel.json`), then `bun install --frozen-lockfile`,
  `cargo build -p chimera-wasm --release --target wasm32-unknown-unknown` and `bunx vite build`. All three built.
- Frames: headless Chromium 1243 driven by Playwright. Each production build was served on a port the system assigned,
  and the Play face screen was captured with 3D on, for the male and the female body, silent and while a key sounds,
  cut away and whole, at 1440×900 and 390×844. For #2 and #3, the lab was captured at 1440×1000: side cuts of /a/, /i/,
  /u/, /s/ for the male, /a/ and /i/ for the female, and a three-quarter cut of each. 35 frames, in the stage's
  evidence directory under `chimera/main`, `chimera/pr2` and `chimera/pr3`.
- Measurements: bun scripts calling #2's WASM the way its own tests do (`tests/harness.ts`): mesh counts, vertex motion
  between vowels, view-call time, skin subdivision, baked table size, blend error, the far half of the static meshes.
  The scripts and their output are kept in the evidence's `probes/` directory.
- Speed: the three production builds in headless Chromium 1243, once with software GL (24 runs) and once on a desktop
  discrete GPU through ANGLE (24 runs, the last six finished at 23:07 UTC), described in §2.6 (`probes/speed*.ts`,
  `speed*.jsonl`, `summarise.py`).
- Luma was read at `7ad0bdd` (this worktree's base; `origin/main` unchanged and no open pull requests at 23:10 UTC).

### 2.2 Chimera's three states

| | main `2e567e2` | #2 `e81bc07` | #3 `645d301` |
|---|---|---|---|
| Look in the frames | A glowing wireframe head in a three-quarter view; the 2D view's midsagittal lines inside a see-through shell (`main/01`–`05`) | A shaded skin; opened, the near half is hidden and the cut face is painted (`pr2/02`, `pr2/07`–`14`) | The same as #2 at panel size (`pr3/07`–`14`) |
| Surfaces | Head shell as rings from tables of proportions; airway as elliptical rings from the area function; ribbed tongue and soft palate; a lips patch; teeth; larynx cartilages and hyoid; vertebrae; eyes with lids and brows (`src/ui/render/anatomy3d.ts`, `beams3d.ts`) | Rust `tract3d`: 8 element meshes (tongue and floor, palate, soft palate and uvula, pharynx, larynx and epiglottis, lips, teeth with gums and jaw, cheeks), 11,732 vertices and 20,852 triangles at rest for the male; skin from MakeHuman's CC0 base mesh, 4,527 vertices, 18,109 after Catmull–Clark, eyes closed, on a stand | #2 without its last four commits: three geometry fixes (incisor rows through the midline, upright buccal faces, the tongue's underside, the cheek bulge, a gum strip: 157 lines in `mesh.rs` and `parts.rs`, 7 in `rig.ts`) and one test change |
| Cut plane | None | «Cut away»: the cut face shows skin, fat, muscle, skull and brain, spine and cord, nasal cavity, hard palate, chin bone, hyoid, laryngeal cartilages, trachea, gullet, the vocal and ventricular folds and the genioglossus' fibres; the air is a hole in it (`src/ui/render/head/section.ts`) | Same |
| Male / female | Male, female and child presets and a continuous blend (`src/ui/body.ts`) | Same, plus a skin shape per body | Same |
| Hair | None | None; listed as deferred in `docs/tract3d/README.md` | None |
| Muscles | None | A tissue colour on the cut face and fibres in the tongue; nothing shows engagement | Same |
| Airflow | Particles along the tube, speed from the engine's flow and area telemetry (`anatomy3d.ts:1171`), turbulence sparks, a pressure heat colour | None in 3D: the Airflow switch hides when the head shows (`src/ui/App.tsx:129`) | None |
| Driven by | The WASM model's midsagittal frame for the articulators, and the audio worklet's telemetry | WASM `tract3dView(model, artic, shape)` on each change of posture; the skin rig reads its jaw pivot and angle and its lip lines | Same |
| Dependencies and size | three 0.186.1 (fat lines, OrbitControls), React 19.3.1, zustand; WASM 1,009,625 B; the 3D chunk 607 KB minified (157 KB gzip) | three 0.186.1 (with RoomEnvironment), React 19.3.1; WASM 1,297,684 B (437 KB gzip); `head.generated.bin` 150,716 B; the head chunk 593 KB minified | As #2 |
| Finished or experimental | A switch on every human screen, off by default (`src/ui/store.ts:134`) | The default view of Play, Speak, Sing and Beatbox (`store.ts:165`). The voice does not read the 3D tract yet; some cut-shape measures and default shapes are outside their pass lines (its README, «Slice fix»). Pull request open | The description reports a 3D wave render and consonant work; the pushed head holds only design documents for it (no render code found). Pull request open |
| Cost of a posture | — | `tract3dView` median 2.5 ms in headless Chromium (its `validation-results.md` §4); 3.8–5.4 ms median here under bun | Same |

Also seen in the frames: at 390 px every state covers the head with its start prompt until audio starts (`main/05`,
`pr2/06`). #2's whole head reads as a bald bust with closed eyes on a stand (`pr2/05`). Its male and female cuts
differ mostly in size; the profiles are close (`pr2/07` against `pr2/12`), so the hair styles of §4.2 and the panel's
words carry most of the difference a singer sees.

### 2.3 What the trainer knows at each moment

| Fact | Where |
|---|---|
| The target note: `targetAt(t)` returns `{m, ok, verified, id}`, MIDI with the vocal octave applied; null outside scored time | `app/app.js:92` |
| Notes `{a, b, m, n, q, ok, ignored}`, sorted, non-overlapping | `docs/TARGET_MAP_SCHEMA.md` |
| The word due now: `lyricAt(t)` gives the current line; a word is "on" while `t` is in `[w.a, w.b + 0.08)` | `app/app.js:1671`–`1673` |
| Word timings `{a, b, w, c}`: ASR alignment with a confidence `c`, or lesson syllables at `c = 0.99` | schema; `lessons/build_lessons.py:164` |
| The live voice: the worker posts `{t, f, confidence, db, peak}`; the app smooths it into `s.current {m, raw, songT}` | `app/workers.html:129`; `app/app.js:444` |
| Voicing as scoring reads it: confidence ≥ 0.8 | `scoreAdvance` in `app/app.js` |
| The draw loop: `tick()` draws at most every 15 ms (32 ms with reduced motion); the readout every 55 ms | `app/app.js:1698` |
| The visible window: 7, 10 or 12 s by width; the playhead 34 % from the left | `app/app.js:1480` |
| The microphone is refused on `file://`; listening works there | `app/app.js:412`–`413`; README |
| Unknown to the trainer: the singer's tongue, jaw or lips; the target's loudness; the phonemes of the words | — |

The library, read without copying anything out (aggregate counts only, recounted at 23:09 UTC): 33 trainers, 32 with
song data. Every song's lyrics are in Latin script (29). Cyrillic appears in the three lessons (two with Ukrainian-only
letters, none with Russian-only letters) and in two tokens of one Latin-script song, each mixing the two alphabets in
one word. 1,406 distinct Latin-script words, 1,363 of them in CMUdict, which covers 99.1 % of the 7,336 Latin-script
word tokens (words split on letters with inner apostrophes kept). Trainer files: median 40.5 MB, largest 92.9 MB; the
app code is about 390 KB (389,795 bytes: `head.html`, `workers.html` and the seven scripts at `7ad0bdd`). The lessons
sing the Ukrainian syllables ма, но, лі, мі and а (`lessons/definitions.py:58`–`66`); the demo song sings Latin
syllables (`examples/make_demo.py:18`).

### 2.4 Shipping a 3D scene in the one-file trainer

- `app/xr.js` (34,208 bytes) uses no three.js. It draws the headset panel with raw WebGL2: one shader pair, textured
  quads, canvas textures; the chart's texture goes up without mipmaps because mipmaps cost a fifth of the frame rate on
  the emulator (`app/xr.js:255`–`282`). The precedent for a 3D scene in the trainer is therefore raw WebGL2.
- `studio/build_html.py:26` concatenates classic scripts in a fixed order. `wrap()` (`build_html.py:29`) is the one path
  for a build, `--rebuild`, `reassets` and the Studio server's import (`studio/studio_server.py:300`).
- From `file://`, Chromium 1243 blocks a module script that imports a local file (CORS, origin `null`); inline classic
  scripts run (probe in the evidence). three.js r186 ships only as ES modules, so it would have to be bundled once into
  a classic script and vendored: 541,898 bytes minified (133,824 gzip) for the subset a lit mesh scene uses, 748,839
  bytes whole (`bun build --format=iife --minify`).
- Chimera's WASM as base64 would be 1,730,248 characters.
- The frame budget precedent: the dust of past takes may add at most a quarter or 1.5 ms to the p95 frame and 1 ms to
  the median, at 390 px and on desktop, under 1× and 4× CPU throttle (`tests/e2e/cloud.mjs:190`–`192`).

### 2.5 Earlier work

- Transcripts, this project first and then everywhere ("vocal tract 3D head cross-section Luma", "chimera anatomy3d head
  hair male female cut away", "chimera tract3d", "chimera-vocal-synth merge pull request main tract3d"): only this
  task's own records, its form and the orchestrator's note that the fork's main was still at `2e567e2`. No earlier Luma
  design touches a head, a vocal tract or airflow, and the agent merging the fork's 3D work left nothing searchable.
- Memory and learned rules: nothing on the subject. The project's rules on scratch exports and on rendering from a
  copied browser profile apply to the build lane's checks.
- Used: Chimera's `docs/tract3d/README.md`, `head-asset.md`, `model-design.md` §0.2 and `validation-results.md` §4 at
  `e81bc07`; Luma's [TAKE_CLOUD.md](TAKE_CLOUD.md) (frame budget, painting off the main path),
  [CAMERA_VIDEO.md](CAMERA_VIDEO.md) (overlays on the sung part of the roll, the render mode), `app/xr.js` (WebGL2) and
  `studio/difficulty.py` (the comfort band, §4.1).

### 2.6 Speed of the three states

Each production build was served on a port the system assigned and opened in headless Chromium 1243. The probe chose
Sing, turned «Cut away» on where it exists, started the first demo song and recorded, for 5 s, the script time inside
each animation-frame callback; then it turned «3D» off and recorded 5 s more. The head's cost is the median script time
per frame with the 3D view on minus the same with it off. Two runs per cell, in alternating order, no uncaught page
error in any run.

On the desktop GPU (ANGLE over OpenGL ES 3.2), at full CPU speed:

| Width | State | Head's script per frame, ms (two runs) | All script per frame with the head, median (p95), ms | Frames a second with the head (two runs) | Bytes before the head's first draw | First draw, ms |
|---|---|---|---|---|---|---|
| 1440 | main `2e567e2` | 3.8, 1.4 | 6.4 (11.8) | 59.1, 60.0 | 2.20 MB | 892 after the «3D» click |
| 1440 | #2 `e81bc07` | 12.9, 11.9 | 16.5 (23.2) | 39.5, 48.4 | 2.48 MB | 601 |
| 1440 | #3 `645d301` | 17.8, 18.2 | 21.9 (27.3) | 42.4, 43.0 | 2.48 MB | 560 |
| 390 | main | 1.4, 1.8 | 4.7 (7.8) | 59.9, 60.0 | 2.20 MB | 397 after the click |
| 390 | #2 | 11.7, 12.2 | 15.5 (22.2) | 45.3, 51.1 | 2.48 MB | 560 |
| 390 | #3 | 16.5, 16.5 | 20.3 (27.9) | 42.7, 47.3 | 2.48 MB | 689 |

- Only main keeps 60 frames a second with its head on. #2 drops to 39–51 and #3 to 42–47; with «3D» off, the same
  pages run at 59.6–60.1. The median frame interval stays 16.7 ms in every case; the drops are single frames that take
  33 ms (frame interval p95 33.4 ms with #2 and #3, 16.7–16.8 ms with main).
- #3 is slower than #2, most likely because it lacks #2's commit `5deeecf` («the meshes' time halved again»).
- Under 4× CPU throttle the runs scatter (#2 at 1440 px: 63.7 and 40.1 ms; at 390 px: 3.7 and −0.1 ms, below its own
  1× figure, so those two runs did not measure the same work). They rank nothing beyond "#2 and #3 can cost tens of
  milliseconds a frame on a slow processor".
- With software GL (no GPU) every 3D view costs 140–600 ms a frame, #2's and #3's 1.6–3.5 times main's.
- What the head's script time is made of in #2: the WASM view call on each change of posture (2.5 ms median in
  Chromium by Chimera's own bench; 3.8–5.4 ms under bun here), the skin rig, and three.js drawing a physical material
  with clear coat, a room environment map, shadows and clipping planes (`src/ui/render/head/scene.ts`).

For Luma this settles two things. The source's runtime cannot come along: 12 ms a frame is twelve times the 1 ms median
the trainer allows an addition (§2.4). The choice of state then rests on the picture and the geometry, where #2 is the
most finished and faster than #3.

(Bytes and first draw are the page's whole load: Chimera's app, its WASM and, for #2 and #3, the head asset.)

## 3. Which state, and the smallest port

### 3.1 The choice: pull request #2's head

The requirement asks for a 3D head seen as a cut, and #2 already draws one (`pr2/07`–`14`): the near half hidden, the
cut face painted in anatomical layers, the tract's air a hole through it, the half-head solid in a three-quarter view
(`pr2/11`). Main's head (`main/01`–`05`) is a wireframe with the section's lines floating inside it; its airflow needs
the engine's live telemetry, which Luma does not have. #3 adds nothing visible over #2; its acoustics work is design
text on the pushed branch. #2 lacks four things the requirement asks for: hair (R4), engagement (R5), airflow (R6), and
a source of postures that does not run the engine (R2 in Luma). §4 designs each.

### 3.2 What crosses over

| Chimera file at `e81bc07` | Into Luma | Change |
|---|---|---|
| `src/ui/render/head/head.generated.bin` (from `tools/gen-head.ts`) | baked into `app/tract3d.data.js` | male and female only; the child is dropped |
| `src/ui/render/head/asset.ts` (reader, Catmull–Clark) | `app/tract3d.js` | TypeScript to plain JavaScript |
| `src/ui/render/head/rig.ts` (`HeadRig`, `bared`) | `app/tract3d.js` | reads the jaw and the lips from the table |
| `src/ui/render/head/section.ts` (`SectionPainter`) | `app/tract3d.js` | inputs from the table; a hair band; zone tints |
| `src/ui/render/head/scene.ts` (camera, clip plane, materials, cut quad) | `app/tract3d.js` on WebGL2 | one lit shader; the physical material, the room environment and the shadows are dropped |
| `crates/chimera` (`tract3d`, `human.rs`, vowel and consonant targets, planner) | run only by the generator | nothing at runtime |
| `anatomy3d.ts` on main, `drawParticles` | `app/tract3d.js` | the perceptual speed formula only (`anatomy3d.ts:1182`) |

Left behind: the React components, the store, the lab, the audio engine and its worklet, three.js, OrbitControls, the
WASM and the browser-side dictionary loader.

Licences: every Luma file that carries code from Chimera opens with Chimera's MIT notice, its `LICENSE` text copied
unchanged. The generated data names the Chimera commit it was baked from and the MakeHuman source commit recorded in
Chimera's `docs/tract3d/head-asset.md` (CC0 1.0).

### 3.3 Where the shapes come from: tables or the WASM

| | A. Baked tables (recommended) | B. Chimera's WASM in every trainer | C. A geometry-only WASM |
|---|---|---|---|
| In the browser | a linear blend of two keyframes | `tract3dView` on each change of posture | the same as B |
| Exactness | keyframes exact; halfway between two of them the blend is 0.06–0.52 mm from Chimera's own posture on average and 3.2–7.5 mm at the worst point, while points travel 15.6–48.6 mm (five transitions, /a/→/i/, /ə/→/t/, /ə/→/k/, /u/→/i/, /a/→/m/, both bodies) | exact for any articulation | exact |
| Bytes per trainer | 202,840 B posture table (270,456 base64), static meshes about 90 KB, skin about 127 KB (estimated) | 1,730,248 base64 characters, plus the same skin | not measured; needs a new Rust crate in the fork |
| Time per change | a blend, about 0.1 ms (to be measured by the build) | 2.5 ms per call in Chromium (Chimera's bench), 3.8–5.4 ms here | likely the same as B |
| What ships | data only | the whole engine | geometry and phonetics |
| Tooling | a bun generator against a Chimera checkout; Luma never needs Rust | Rust to rebuild | Rust and a crate in the fork |
| Postures | the 55 symbols the phoneme tables can produce, per body | any | any |

Recommendation: **A**. Consonant keyframes are baked in a schwa context: the planner's targets for /əCə/ laid over /ə/
(probe in the evidence: /m/ gives `lipAp −0.25` and `velum 0.45`; voiceless stops add `abduction 0.36`). Next to a
front or a back vowel, the tongue body then sits at schwa during the consonant, a few millimetres from where Chimera's
planner would put it. That is acceptable for a teaching view and listed under risks.

The postures: the 22 vowels Chimera calibrates per body (a e i o u y æ ø œ ɐ ɑ ɒ ɔ ə ɛ ɝ ɤ ɨ ɪ ɯ ʊ ʌ) and 33 consonants
(p b t d k g ʔ m n ŋ f v θ ð s z ʃ ʒ x h ɦ ts tʃ dʒ w ʋ ɹ j l r ɲ ʎ ç), which cover what §4.5's English and Ukrainian
tables produce.

Per posture and body, the table holds:

- 461 midline points at fixed counts per named polygon, 16-bit at 0.1 mm: air envelope 64, tube 48, vallecula 20;
  tongue 56, epiglottis 8, upper lip 12, lower lip 14, pharynx wall 60, uvula 12; outlines of the tongue 56, soft palate
  24, upper teeth 6, lower teeth 5, jaw bone 8, nasal cavity 18; the two lip lines 25 each. Resampling by arc length is
  what makes a pointwise blend possible: Chimera's own counts change between postures (the envelope has 61 points for
  /a/ and 60 for /i/).
- The jaw's angle, the larynx's height, the soft palate's port area, the glottis' position, and the planner's
  abduction or closure.
- The articulator values the zones read (jaw, tongue body x and y, tip x and y, lip aperture, protrusion and width, soft
  palate, larynx).
- A 24-point centreline and 24 area samples for the air (§4.4), and the sung consonant duration (Chimera's phoneme
  duration × 0.8, `crates/chimera/src/phonetics/sing.rs:123`).

Per body, once: the jaw's pivot; the far half of the static meshes for palate, teeth with gums, and cheeks (2,691
vertices, 4,772 triangles, about 45 KB); the nasal path; the zone regions (§4.3).

The generator is `tools/gen_tract3d.ts`, run with bun against a Chimera checkout at a pinned commit after that
checkout's `bun run wasm`: `bun tools/gen_tract3d.ts <chimera checkout>`. It imports the checkout's `src/wasm/engine.ts`
the way Chimera's tests do, is deterministic, and writes `app/tract3d.data.js` with a header naming the commits, the
counts and the licences. Like every generated file, it is regenerated and never edited by hand.

### 3.4 Renderer: raw WebGL2

| | WebGL2 (recommended) | three.js, vendored |
|---|---|---|
| Code | two programs (a lit mesh with a clip plane and vertex colours; a textured quad for the cut face) and points for the air; an estimated 400–500 lines | `scene.ts` ports closer to as written |
| Bytes | the code only | +541,898 B in every trainer, bundled once with `bun build --format=iife` |
| Look | Lambert and Blinn shading with a hemisphere light; #2's clear-coat sheen, room reflections and shadows are gone | #2's look |
| Precedent | `app/xr.js` | none in Luma |

Recommendation: **WebGL2**. In a side view at panel size, the painted cut face carries the picture; the skin's sheen
matters least. If the visual critic fails the skin's look specifically, three.js at the cost above is the way back.

Changed in the build: the head is drawn into a multisampled framebuffer of its own (4 samples) and copied onto the
canvas at the end of each frame; the canvas itself has no antialiasing. Drawn into the canvas's own multisampled buffer,
desktop Chromium on ANGLE over OpenGL ES, on a desktop graphics processor, at times left whole draws out of a frame: the
far half's teeth and palate, the skin, the air's lines. A paused head kept such a frame. Measured on 2026-11-14, a
paused head redrawn 186 times lost a draw in 8 and 10 of them in two runs; drawn through its own framebuffer, 0 and 0,
every redraw the same picture.

## 4. The elements

### 4.1 (a) Male and female head

| | Male | Female | Source |
|---|---|---|---|
| Overall scale | 1.0 | 0.9 | Chimera `crates/chimera/src/anatomy/human.rs:276`–`277` |
| Extra pharynx scale | 1.0 | 0.88 | same |
| Tongue body radius, template cm | 2.25 | 2.2 | same |
| Widest lips, cm | 4.6 | 4.4 | same |
| Tract length at rest in Chimera | 17.2 cm | 14.7 cm | the fork's readout (frames `main/02`, `main/03`) |
| Tract length in the literature | about 18 cm | about 15 cm | Vorperian et al. 2009 (JASA), summarising Fitch and Giedd 1999; seen only in a secondary source |
| Vocal fold length | 17–25 mm | 12.5–17.5 mm | Titze 1994; seen only as quoted by a secondary source |
| Chimera's default pitch | 110 Hz | 205 Hz | `src/ui/body.ts:54` |
| Skin shape | MakeHuman's male macro shape | MakeHuman's female macro shape | Chimera `docs/tract3d/head-asset.md` |
| Larynx position at rest: the glottis below the upper teeth's lowest point | 7.95 cm | 6.40 cm | #2's `tract3dView` at the neutral posture (`probes/probe-larynx.txt`) |
| Larynx drawing | the template scaled by the body; #2 draws no sex-specific thyroid prominence | same | `section.ts` |
| Range for the larynx hint (§4.3) | C3–E4 (MIDI 48–64) | A3–C♯5 (MIDI 57–73) | Chimera's keyboard for each body: its lowest key and the 16 keys above it (`src/ui/components/Keys.tsx:7`–`8`); a teaching default |

The literature rows feed the ⓘ text only, and the build lane cites them at the page or drops them. Every drawn
dimension comes from Chimera. Luma's comfort band `COMFORT` (A3–D5, `studio/difficulty.py:10`) rates songs against one
singer's comfortable range, so it is no per-body range and the head does not use it. The trainer knows no singer's
range; a range the singer sets is deferred.

Choosing: the panel's header holds «Чоловік · Жінка». The choice is saved in the trainer's preferences
(`luma.trainer.settings`, which belong to the page's origin). Nothing guesses it: the panel opens on the two buttons,
draws no head until one is pressed, and remembers the answer. The vocal octave setting already shifts the target, and
the range position reads the shifted pitch.

### 4.2 (b) Hair

The generator grows a hair shell from each body's skin. Scalp vertices above a hairline on the base mesh (forehead,
temples, above the ears, the nape) are pushed out along their normals:

- male: short, 0.6 cm at the crown tapering to 0.2 cm at the hairline;
- female: 1.2 cm over the scalp, plus a drape lofted from the back of the skull down to the level of the larynx,
  1.5–2.5 cm thick, closed at its edges and kept behind the neck so the larynx on the cut face stays visible.

The shell is one closed, opaque surface (an estimated 2,000–3,000 vertices per body), mid brown with a light rim where it
turns away (built: `#8a6a52` on the shell, `#80604a` on the cut; a dark brown measured 1.47:1 against the panel and the
short style read as a bald head), with a highlight band stretched along a strand direction the generator bakes per vertex. At the cut plane the same clip removes the near
half, and the cut face paints the hair's section between the scalp outline and the shell's midline loop (baked like
the skin's `midFront` and `midBack` loops) in the hair colour with fine strand strokes. The cut shows hair as a band on
the scalp and, for the long style, a band behind the neck. Both bands stay outside the tract's region.

The alternative is MakeHuman's own hair proxies: CC0 since 2020 according to its asset repository, with each file's
licence field still to be checked. They are textured alpha cards: more realistic, more bytes, and they need sorted
transparency. Deferred.

### 4.3 (c) The side view of what tenses

What Luma can show, and on what authority:

| Structure | Shown | From | Class |
|---|---|---|---|
| Jaw | opening at the incisors | the posture table | modelled (Chimera's targets, calibrated against formants) |
| Tongue | shape; which part is raised (tip, front, back, root); where the narrowing is | the table | modelled |
| Lips (no zone, by the settled answer) | rounded, spread, closed, lip to teeth, on the cut and in the hint | the table | modelled |
| Soft palate | raised for oral sounds, lowered for nasals; the port's area | the table | modelled |
| Larynx height per sound | the vowel's larynx offset | the table | modelled (Chimera's vowel targets carry it, e.g. /i/ 1.149 cm up for the male) |
| Larynx and pitch | the larynx tends to rise with pitch; a singer keeps it steady | the target's place in the chosen range | teaching illustration |
| Vocal folds | vibrating, apart or shut | the planner's voicing: abduction 0.30–0.36 for voiceless sounds, 0.035 for voiced fricatives, closure for /ʔ/ | modelled (as a state) |
| Fold thickness and stretch | thinner and stretched high, thicker low | the target's place in the range | teaching illustration |
| Loudness and breath support | not shown | the target has no loudness | deferred |
| Diaphragm, ribs, abdominal wall | not shown | the torso is out of scope | deferred |

The four highlighted zones are the settled ones: jaw, tongue, soft palate, larynx. How each zone's level (0–1) and word
come from the posture at time `t`:

- **Щелепа:** jaw opening over the largest jaw opening in Chimera's articulator ranges → «відкрита», «напіввідкрита»,
  «майже закрита».
- **Язик:** the raised part is the tip (alveolar and dental consonants), the front (/i/, /ɪ/, /e/, /j/, /ʃ/), the back
  (/u/, /k/, /g/, /ŋ/, /x/) or the root drawn back (/a/, /ɑ/, /ɔ/), read from the tongue values and the place of the
  smallest area along the centreline; the level is how far that area falls below its value at rest.
- **М'яке піднебіння:** raised, level 1, «підняте: повітря йде лише ротом»; lowered for a nasal, level 0.2,
  «опущене: повітря йде носом».
- **Гортань:** the level from the larynx offset and from `p = (m − lo) / (hi − lo)`, the target's place in the chosen
  range. Above 0.8: «Висока нота: складки тонші й натягнуті. Гортань не тягни вгору». Below 0.15: «Низька нота: не тисни
  гортань униз». Plus the folds' state in words: «звучать», «розведені», «зімкнені».

The lips have no zone. The hint names them when their shape carries the sound: closed (lip aperture ≤ 0, «губи
зімкнені»), lip to teeth (/f/, /v/), rounded (narrow and protruded, «губи округлені вперед»).

Clamps (затиск), named as a tip line «Не затискай …» from a small table: the jaw on closed vowels high in the range,
the tongue's root on back vowels low in the range, the larynx rising on high notes, tight lips on rounded vowels.

One hint line shows at a time. During a consonant it names that consonant's zone or lips («м'яке піднебіння опущене»,
«губи зімкнені»); during a vowel it gives the larynx hint when the note is high or low, else the clamp tip if one
applies, else the tongue's word. On wide screens the zones' labels carry the rest.

How tension is drawn: each zone has a fixed region on the cut face in template coordinates, scaled per body (the jaw
muscles over the ramus and the floor of the mouth, the tongue's polygon, the soft palate's outline, the larynx around
the thyroid and cricoid with the folds). An engaged zone takes a warm amber tint over the painted
tissue at alpha 0.15 + 0.45 × level, a 2 px outline, and a slow 1 Hz pulse while its level rises (none with reduced
motion). On wide screens each engaged zone gets one short label on a leader line; on a phone the tint and the one hint
line under the panel. Every zone is named in text, so no state depends on colour alone.

Honesty, in the UI copy. Under the panel: «Форма тракту — модель синтезатора Chimera для цієї ноти і слова. Підсвітка
зон, натяг складок і рух повітря — навчальна схема; твій голос і твої м'язи вона не вимірює.» Behind ⓘ, three short
lists: «Модель Chimera» (the shapes of the tongue, jaw, lips and soft palate, the larynx height for each sound, the
folds' state), «Навчальна схема» (the lit zones and hints, the folds' stretch with pitch, the air's speed, the hair),
«Не вимірюється» (your voice's shape, your muscles).

### 4.4 (d) Airflow

The path runs from the trachea at the bottom of the neck's cut, through the glottis, the pharynx and the mouth, out at
the lips. At the soft palate's port it branches into the nasal cavity and out of the nostrils. The oral centreline is
24 points per posture, baked from the air "tube" polygon as midpoints between its two walls, and blended like the
outlines. The areas are 24 samples per posture from the 3D model's area function. The nasal path is fixed per body,
from Chimera's nasal cavity outline.

Particles (120 on desktop, 60 on a phone) move as short streaks in the cut plane, drawn just in front of the cut face
with WebGL points and lines, so the cut-face texture is not uploaded again for them. Speed follows continuity on a
perceptual scale, the formula main's head uses (`anatomy3d.ts:1182`: 2.2 · ln(1 + |U/A| / 30) cm/s on screen), with a
fixed teaching flow `U` per state. The flow splits between mouth and nose by the port's area against the mouth's
smallest area.

Changed in the build: each particle stands at an even share of the time the air takes from the windpipe out of the
head, moved on by one clock. Particles crowd where the air runs slowly, and as many stand in front of the mouth at a held
note's end as at its start. Another flow on the mouth's way (a hiss, a closure) changes only how fast the clock runs and
moves no streak; a turn between the mouth's way and the nose's puts each streak at its share of the other way. Particles that aged out and came back low in the throat had thinned the breath in front of the lips
to nothing up to 0.8 s before a long note ended.

| Sound | Folds | Air |
|---|---|---|
| Vowel | vibrating, drawn at a slowed rate | pulses in step with the folds; a steady stream out of the lips |
| Voiced fricative (/z/, /v/, /ð/, /ʒ/) | vibrating | pulses, plus sparks at the narrowing |
| Voiceless fricative (/s/, /f/, /ʃ/, /θ/, /x/, /h/) | apart, the gap drawn | a faster continuous stream; sparks at the narrowest point (as main's `drawTurbulence`) |
| Stop (/p/, /b/, /t/, /d/, /k/, /g/) | voiced stops keep vibrating | at the closure the particles slow and bunch behind it under a glow that grows (pressure); at the release, a 40 ms burst |
| Nasal (/m/, /n/, /ŋ/) | vibrating | the mouth is shut at the place; every particle turns at the port into the nose |
| Vowel beside a nasal | vibrating | a share through the nose while the port is open (the blended soft palate) |
| /ʔ/ | shut | none |
| A rest of 0.5 s or more before the next scored word | apart | reversed, in through the nose and mouth to the trachea, labelled «вдих» |
| Reduced motion | still | still arrows along the path; their width shows the share through mouth and nose |

The path, the closures and the nasal routing follow the modelled shapes. The speeds and pulses are a teaching
illustration, and the copy in §4.3 says so. During singing, the trachea's end is labelled «з легень».

### 4.5 (e) From a lyric word to phonemes, offline

**Where.** At build time, inside `wrap()`. Every build, `--rebuild`, `reassets` and the server's import pass through it,
so a corrected lyric gets new phonemes at its next rebuild. A new module `studio/phonemes.py` turns each distinct lyric
word into IPA symbols, and `wrap()` writes one more line before the app scripts:
`<script>window.LUMA_PHONES={"v":1,"words":{…}};</script>`, with `<` written as `\u003c` as the server's import
already does for the song data (`studio/studio_server.py:298`). The song data line stays byte for byte. A song adds a few
kilobytes (estimate: 100–300 distinct words at about 15 bytes each).

**English.** CMUdict, vendored as `studio/data/cmudict.txt.gz` (868,793 bytes; 3,330,130 uncompressed) with its BSD-style
licence file, the same file Chimera ships. ARPAbet goes to IPA through a 39-symbol table: unstressed `AH0` becomes /ə/,
stress is dropped, and the diphthongs `AW AY EY OW OY` split into two vowels for the glide. A homograph takes the first
entry. A word written mostly in Latin letters has its look-alike Cyrillic letters (а е о р с у х і) mapped to Latin
first: the library holds two such words today (§2.3).

**Ukrainian.** Rules, since the spelling is close to the sound: а /a/, е /ɛ/, и /ɪ/, і /i/, о /ɔ/, у /u/; я, ю, є, ї as
/j/ + vowel, or as a soft consonant + vowel after a consonant; ь softens the consonant before it, and after the
apostrophe я, ю, є, ї stay /j/ + vowel; г /ɦ/, ґ /g/, в /ʋ/ (/w/ before a
consonant at a syllable's end), ж /ʒ/, ч /tʃ/, ш /ʃ/, щ /ʃtʃ/, ц /ts/, дж /dʒ/, дз as /d/ then /z/, х /x/. A soft
consonant uses the plain posture blended a third of the way toward /j/'s tongue body. The lessons' syllables are
covered.

**Other languages.** None in the library today. A word in another Latin-script language falls through to the browser
rules below.

**In the browser.** `app/tract3d.js` reads `LUMA_PHONES`. A word missing from it (an imported target whose words
changed, a trainer built before this feature and not yet rebuilt) goes through small letter rules: Latin vowel letters
to the nearest vowel posture and consonant letters to their plain consonant; Cyrillic through the Ukrainian table. The
panel then marks the word «приблизно». A word with no letters or no vowel sings /ə/ on its note, with the hint
«Слово без вимови: показую нейтральний голосний».

**Timing**, ported from Chimera's sung rules (`sing.rs:1`–`10`):

1. Syllables come from the vowel nuclei; onsets take the longest legal cluster.
2. A word's notes are the notes not ignored that overlap `[w.a, w.b]`. With at least as many notes as syllables, each
   syllable takes one note in order and the last syllable takes the rest (a melisma). With fewer notes or none (a gap
   in the note map, notes marked ignored), the word's span is split evenly.
3. Within a syllable, the vowel starts on the note. Onset consonants end at the note's start; codas end at the next
   onset. Consonant durations are Chimera's phoneme durations × 0.8. A diphthong holds its first vowel for 80 %.
   After a rest of 0.25 s or more, or at the start, an onset shorter than 180 ms takes its closure up earlier, out of
   the silence, so it lasts 180 ms (added in the build: at 55 ms the /m/ of lesson 1 was three frames while playing and
   could not be seen); inside a phrase onsets keep their length.
4. Transitions are a raised-cosine cross-fade of 30 ms into a consonant and 60 ms into a vowel, in line with the ramps
   of Chimera's planner (probe /əmə/: 0.03 s into /m/, 0.06–0.07 s into /ə/).
5. A gap of 0.25 s or more between words relaxes the head toward rest over 150 ms; a gap of 0.5 s or more before a
   scored word starts the breath in (§4.4).
6. A word with confidence `c < 0.5` is marked «приблизно» too.

## 5. Where it sits in the trainer

As decided: a panel in the trainer beside the roll, live while listening and singing, and showing the playhead's
moment while idle or scrubbing.

| Width | Place |
|---|---|
| ≥ 1100 px | a column on the right inside the stage, 28 % of the stage's width clamped to 300–420 px, the plot's full height. The roll's right edge moves left by it: `bounds()` (`app/app.js:1458`) gets `s.tractW`, measured in `measureStage()` beside `headH` and `railH` (named for the tract because `app.js` already uses `head` for the stage header, `s.headH` and `#stageHead`). The span stays 12 s |
| 720–1099 px | the same column at 240–300 px, with the whole head (changed in the build: a mouth-to-larynx crop below 280 px cut the skull, the hair and the nose while the whole head fits the column at the same scale as at 1440 px) |
| a short column, any width from 720 px (added in the build) | the column is as tall as the plot, which is short after a take and in a low window (1440 × 900 after a take, 1366 × 650 idle): where the whole head would get less than 8.5 CSS px a centimetre of the cut (the 900 px column idle gives it about 9), the column takes a wide shape, the title, «Чоловік · Жінка» stacked and the caption in a column on the left, and on the right, at the panel's whole height, the mouth to the larynx, a little closer than the phone's crop (the front of the spine to the breath in front of the lips, the windpipe under the folds to the nasal cavity's roof). There the lips to the pharynx's back wall stand 90 CSS px wide at least. Before a choice the column holds «Обери голову» with the two buttons under it, one block in its middle |
| < 720 px | the head stands on the sung third of the roll (between the pitch rail and the playhead), bottom left, at 40 % of the plot's height (changed in the build: while the notes sung in the last 2 s, or those reaching it within 0.8 s, lie in its rows, it stands top left, and it moves back only when the top is in the way; while singing it is a quarter smaller, 30 % of the plot high, because at 40 % the notes of the last 2 s of the demo left no clear place in one frame of six; where a run of notes crosses both ends while singing, it draws in toward an end's corner, to 55 % of that at least, and grows back when clear). The roll fades under it, as the camera video's overlays do ([CAMERA_VIDEO.md](CAMERA_VIDEO.md)); its rectangle goes into `drawWords`' list of placed labels first (`app/app.js:1465`–`1472`), so a word that would fall under it climbs above it the way overlapping words already do (below it when it stands at the top). It shows the mouth to the larynx: from the spine to past the nostril, from the neck's cut (or 2 cm under the glottis) to above the nasal cavity, and «Чоловік» or «Жінка» stands in its bottom right corner, in front of the neck; an enlarge mark (a 24 px button) stands in its top right corner, in front of the forehead, and both step aside while singing. Before a choice it holds the two buttons and «Обери голову», one block in its middle; while a toast covers the overlay's bottom, where the two buttons cannot clear it, the overlay steps aside until the toast goes. A tap while idle enlarges it over the stage from edge to edge, the piano rail included, down to the plot's bottom (changed in the build: inset by 8 px it left a strip of the rail's keys beside it), its caption hidden while a toast stands over it; a second tap, the ✕ in its header or Esc returns |

- **Switch:** «Голова» in the stage rail beside «Слова» (`aria-pressed`), preference `tract`, on by default. The panel's
  header holds «Чоловік · Жінка» and ⓘ. Both preferences join the activity state beside `lyrics` (`app/app.js:359`).
- **Camera:** a side view turned 15° toward the face, so the half-head reads as solid. Dragging turns it up to ±60°,
  only while idle; a double click resets it.
- **Pauses:** the panel draws nothing while it is hidden, while the document is hidden, in VR (`s.xr`) and in the camera
  video's render mode. Its canvas sits inside its own `<div>` in `#chartWrap`: the render mode hides every child of
  `#chartWrap` that is not a canvas (`app/head.html:316`), so a bare second canvas there would leak into camera videos.

## 6. Budget

**Bytes per trainer.** Posture points 202,840 B (measured) and their centrelines, areas and values about 20 KB
(estimated); skin for two bodies about 127 KB (estimated from the three-body file of 150,716 B); far-half static
meshes about 90 KB (45 KB of positions and indices measured, doubled for normals and colours); hair about 50 KB
(estimated). That is about 490 KB of binary, 650 KB as base64, plus about 70 KB of code (estimated): about 0.7 MB per
trainer, 1.8 % of the median trainer and about 24 MB across today's 33 trainers.

**Start.** The data is decoded only when the panel first shows. The skin's subdivision takes 63.5 ms per body (measured
under bun). It runs in idle time after the first paint, or the generator bakes the subdivided mesh if the phone
measurement asks for it.

**Per frame**, with targets the build lane measures:

- blending the points and the centreline: about 0.1 ms;
- the skin: each keyframe is rigged once on first use and cached (eight at most, oldest out). The target's timeline is
  known in advance, so the next keyframes are rigged ahead of time. A frame then only blends two cached position arrays
  (18,109 vertices) and uploads one buffer;
- the cut face is painted again only when the blend has moved some point by more than 0.2 mm or a zone changed, and it
  goes up without mipmaps (the `xr.js` lesson);
- the particles: one small buffer.

**Acceptance.**

- The roll's `draw()` with the panel on against off: p95 within +25 % or +1.5 ms, median within +1 ms, at 390 and
  1440 px under 1× and 4× throttle (the `cloud.mjs` rule).
- The head's own work per frame: median ≤ 2 ms and p95 ≤ 4 ms at 1440 px and 1×. At 390 px and 4× throttle, p95 ≤ 8 ms,
  or the panel steps down to 30 Hz and the test asserts the step.

**Fallback.** Without WebGL2, or after a lost context, the panel shows the 2D cut face alone (the painter, the zones,
the air drawn in 2D).

## 7. Decision points (settled 2026-11-13)

All five are settled, four of them as recommended. The other options keep their cost so a brief can follow any of them
if a decision is reopened.

| Point | Option | Recommendation | Cost |
|---|---|---|---|
| 1 Placement | trainer panel beside the roll | **recommended; settled** | layouts at three widths (§5); at 1440 px the roll gives up 300–420 px and draws its 12 s denser; the frame budget of §6; about 0.7 MB in every trainer |
| | a separate page in Studio | — | a new route in `studio/studio_server.py` and a page that reuses `app/tract3d.js` with the song's target and stems; the data lives once on the server (no bytes in trainers); the singer cannot watch it while singing; not available from `file://` |
| | both | — | the sum; the page reuses the panel's module, so about a third more than slice 1 |
| 2 Driver | the song's target | **recommended; settled** | as designed |
| | the singer's voice from the microphone | — | the microphone gives pitch, voicing and loudness (`{f, confidence, db}`), so only the larynx height and the folds' state could follow it; the tongue, jaw and lips would need a formant tracker in the worker and an inverse model Chimera does not have; nothing on `file://`, where the microphone is refused |
| | both side by side | — | a second head (twice the room, so none under 720 px), a legend telling the two apart in words, and the microphone's costs |
| 3 Body | head and neck, air from the trachea | **settled** (the form recommended this first and a torso as a later slice) | as designed |
| | with a simplified torso (lungs, diaphragm, ribs, abdominal wall) | — | a new torso (Chimera has none; MakeHuman's CC0 base mesh has one); breath shown only from the target's rests, since nothing measures support; a panel about twice as tall, which covers the roll on a phone; one more slice; every part of it is illustration |
| 4 Depth | simple: four zones and a plain hint | **recommended; settled** | §4.3 |
| | detailed named muscles | — | a region and a cited activation per muscle and sound (the genioglossus, the levator veli palatini, the cricothyroid and others); most activations are not in Chimera's model, so they would be illustration; labels crowd a 300 px panel |
| | simple, with a switch to detailed | — | both costs |
| 5 Source | main `2e567e2` | — | a wireframe with no cut; its airflow needs the engine's live telemetry; 1.4–3.8 ms a frame as Chimera runs it (§2.6) |
| | #2 `e81bc07` | **recommended; picked** | the solid cut head with the painted anatomy; 11.7–12.9 ms a frame as Chimera runs it, none of which comes to Luma, because its geometry is baked (§3.3) |
| | #3 `645d301` | — | #2 without four geometry fixes, plus design text; 16.5–18.2 ms a frame |

## 8. Build plan

Each slice ends with something a person can see, the project's checks (`tests/e2e/run.sh` with the new suite) and the
pinned renders of §9. Before slice 1, the build lane re-reads the fork's main (§ Operator decisions).

**Slice 1 — the cut head sings the target** (the operator's first slice): the panel with the male or female choice,
hair, the articulation from the lyric's phonemes on the target's timing, the airflow, the layout at three widths, the
frame budget and the 2D fallback.

| File | Change |
|---|---|
| `tools/gen_tract3d.ts` (new) | the generator: postures, skin, hair shells, static meshes, centrelines, nasal path, provenance |
| `app/tract3d.data.js` (new, generated) | the baked data and its header (commits, counts, MIT and CC0 notes) |
| `app/tract3d.js` (new) | `LumaTract.attach(host)` in the style of `xr.js`: WebGL2 renderer, skin subdivision and rig, cut-face painter with the hair band, posture blending, phoneme timeline, airflow, 2D fallback; Chimera's MIT notice at the top |
| `app/app.js` | the panel's life (create, size, show, hide); `tick()` calls `LumaTract.frame(t)` while visible; the host API (song, `targetAt`, lyrics, notes, preferences); preferences `tract` and `tractBody`; `bounds()` and `measureStage()` leave the column; `drawWords` places the phone overlay first; activity state; `Luma.test.tract()` and `Luma.test.wordBoxes()` |
| `app/head.html` | the panel's markup (title, «Чоловік · Жінка», ⓘ), the «Голова» switch, styles at three widths |
| `studio/build_html.py` | `tract3d.data.js` and `tract3d.js` in the script list before `app.js`; the `LUMA_PHONES` line from `studio/phonemes.py` |
| `studio/phonemes.py` (new) | CMUdict lookup, ARPAbet to IPA, the Ukrainian rules |
| `studio/data/cmudict.txt.gz`, `studio/data/CMUDICT-LICENSE.txt` (new) | the vendored dictionary and its licence |
| `tests/e2e/tract3d.mjs` (new), `tests/e2e/run.sh` | the suite (§9) |
| `tests/phonemes_test.py` (new) | the dictionary and the rules |
| `README.md`, `docs/TARGET_MAP_SCHEMA.md` | the feature, the layout, the tests; the `LUMA_PHONES` line |
| `docs/design/VOCAL_TRACT_3D.md` | the status line |

**Slice 2 — what engages:** the four zones with their levels, tints, labels and the hint line; the clamp tips; the ⓘ
popover with the three lists; the honesty line. Files: `app/tract3d.js` (zone regions and levels, the painter's tints),
`app/head.html` (hint line, popover, styles), `tools/gen_tract3d.ts` and the regenerated data (zone regions and the
per-body range, if slice 1 did not bake them), `tests/e2e/tract3d.mjs`, `README.md`.

**Slice 3 — the air in detail:** the stop's build-up and burst, sparks at fricatives, the nasal share beside nasals,
the breath in before phrases, the «вдих» and «з легень» labels, reduced motion. Files: `app/tract3d.js`,
`tests/e2e/tract3d.mjs`.

## 9. Acceptance checks

### 9.1 The suite (`tests/e2e/tract3d.mjs`), with a clean console in every case

1. At 1440 px the panel shows by default beside the roll. The roll's right edge (`Luma.test.plot()`) sits left of the
   panel's box, and no drawn word (`Luma.test.wordBoxes()`, the boxes `drawWords` placed) overlaps it; at 390 px no
   word box overlaps the overlay, and the playhead and the next 2 s of notes (`Luma.test.noteBoxes()`) stay clear of it.
   (Added in the build: through a sung pass of the demo at 390 px no note sung in the last 2 s, `Luma.test.noteRects()`,
   lies under the overlay; a short column, 1440 × 900 and 900 × 1000 after a take and 1366 × 650 idle, draws the lips to
   the pharynx's back wall, `Luma.test.tract().mouthPx`, 90 CSS px wide at least; before a choice the column holds the
   prompt with the two buttons under it.)
2. «Чоловік» and «Жінка» survive a reload. `Luma.test.tract()` reports the body and its scale (1.0 and 0.9), and the
   two heads' outlines differ (MakeHuman's two shapes).
3. Lesson 1, «Витримана нота» on «ма»: at the /m/ the hook reports phoneme `m`, air `nasal`, lips closed, soft palate
   lowered; on the held /a/ it reports `a` and air `voiced`, and played through, as many streaks stand in front of the
   lips at its end as at its start (added in the build).
4. Demo song: on «ta» or «do» the closure reports `closed`, then `voiced` after the release.
5. A fixture word missing from `LUMA_PHONES` reports `approx: true`, and «приблизно» is visible.
6. The demo opened from `file://`: listening moves the head (the phoneme changes), and request interception sees no
   network request.
7. `--rebuild` keeps the data line byte for byte and writes `LUMA_PHONES`; a changed word in `target.json` changes the
   table at the next rebuild.
8. The budget of §6 at 390 and 1440 px, 1× and 4× throttle. (Added in the build: the 3D head through its own
   multisampled framebuffer draws the same picture each time a paused moment is drawn again.)
9. With «Голова» off, `Luma.test.plot()` equals today's at the same moment and width.
10. With WebGL2 creation stubbed to fail, the 2D cut face shows, with no console error.
11. In a VR session (the `iwer` emulator, as `xr.mjs`) and in a hidden tab, the head draws no frames.
12. With reduced motion, two frames 200 ms apart show the same particles.

`tests/phonemes_test.py`: dictionary words to IPA, the lessons' syllables, a missing word left out, the same output on
two runs.

### 9.2 Pinned renders for the visual critic

Taken from a scratch export of the build's head, at 1440×900 (DPR 2), 900×1000 (between) and 390×844 (DPR 3), each
in a fresh browser profile whose `luma.trainer.settings` sets `tract` and `tractBody` before load. Fixtures are the
lessons, the synthetic demo song and one made-up word; no song from the library and no real history appears.

| # | State | Head | Defining element that must be visible text or shape |
|---|---|---|---|
| 1 | lesson 1, «ма», on the /m/ | male | lips shut, the soft palate lowered, air leaving the nose; hint names the soft palate |
| 2 | lesson 1, «ма», the held /a/ | female | jaw open, flat tongue, air out of the mouth; the hair band on the cut |
| 3 | lesson 3, «Довга нота», the top note | male | larynx zone lit, the high-note hint |
| 4 | demo «ta», at the closure | female | pressure glow behind the tongue tip; folds apart |
| 5 | demo «sa», on the /s/ | male | sparks at the narrowing; folds apart; tongue tip zone lit |
| 6 | the made-up word | female | «приблизно» |
| 7 | idle, paused on a note, turned three-quarter | male and female | the solid half-head with hair; the choice in the header |
| 8 | the rest before a phrase | male | reversed air, «вдих» |
| 9 | WebGL2 unavailable | female | the 2D cut face with zones and air |
| 10 | «Голова» off | — | today's roll |

At every width the critic checks: the head, its hair and the cut face are readable; no label, hint or popover overlaps
the roll's words or leaves the viewport; text contrast and target sizes meet the platform floor; the two heads differ
in visible words as well as size; the phone overlay leaves the playhead and the upcoming notes clear.

### 9.3 For the reviewer

- The generator run twice against the same Chimera commit writes byte-identical `app/tract3d.data.js`, and its header
  names that commit and the MakeHuman source.
- Every file carrying Chimera's code opens with its MIT notice; `studio/data/CMUDICT-LICENSE.txt` sits beside the
  dictionary.
- `tests/e2e/run.sh` and `tests/phonemes_test.py` pass; the trainer built from the demo opens from `file://` with a
  clean console.
- No commit carries a song from the library, its title, its artist or its words: fixtures are the lessons, the
  synthetic demo and a made-up word.

## 10. Risks

- **The source may move.** #2 is open and another agent is merging; the generator records the Chimera commit, and a
  re-bake is one command.
- **Blending between keyframes:** measured 0.06–0.52 mm mean, up to 7.5 mm at a point, halfway through a transition.
  Visible only in fast consonant transitions.
- **Consonants in a schwa context** keep the tongue body a few millimetres off next to front and back vowels.
- **Speech shapes for singing.** Chimera calibrated its vowels for speech. Singers open the jaw more and shift vowels on
  high notes; the high-note hints are illustration and say so.
- **Word timings come from ASR** (or the lessons' exact syllables). A misaligned word shifts the postures by its error;
  a low confidence marks «приблизно».
- **Phone cost is unmeasured** here, as it was in #2. The adaptive 30 Hz step and the 2D fallback are the guards.
- **Looks.** #2's head was critiqued as a mannequin's bust before its sculpt; a shell of hair can read as a helmet. The
  visual critic decides; MakeHuman's hair proxies are the next step.
- **Pronunciation:** homographs take the first dictionary entry; a Russian song would be read with Ukrainian rules and
  marked «приблизно» only where a letter is unknown.
- **Size:** about 24 MB more across the library's trainers.
- **Privacy:** `LUMA_PHONES` repeats words that the trainer's data line already holds; nothing new leaves the computer.
  Tests and renders use the lessons, the synthetic demo and a made-up word only.

## Deferred — not currently justified

- A torso with lungs, diaphragm, ribs and abdominal wall: the operator chose head and neck only (2026-11-13). Cost in §7.
- Detailed named muscles: the operator chose simple zones. Cost in §7.
- A Studio page to study a note or word without singing: the operator chose the trainer's panel.
- The singer's own voice from the microphone, alone or beside the target: the operator chose the target. The cheap
  later form is a mark for the singer's pitch on the larynx zone.
- The target's loudness and breath support: the map has no loudness; the vocal stem inside the trainer could give an
  envelope later.
- The head in the VR panel (`app/xr.js`) and in camera videos (`app/render.js`).
- Chimera's WASM in the trainer, live geometry for any articulation, and consonants baked per vowel context.
- Russian with stress, and other languages' rules.
- A voice range the singer sets for the larynx hint, in place of the per-body default (§4.1).
- MakeHuman's hair proxies with textures, open eyes, skin texture.
- The child body.
- The lab's planes, cuts, area screen and exploded view.
- A faint preview of the next posture.
- Turning the head freely while singing.
- The live 3D meshes of the tongue and the other moving parts behind the cut.

## Validation against the requirement

| # | Obligation | Met by |
|---|---|---|
| R1 | the 3D head from the operator's Chimera work, as a cut | #2's skin, rig and cut face, ported (§3), baked from a pinned Chimera commit |
| R2 | how to sing what is due | target note and lyric word → phonemes → timed postures (§4.5); the panel beside the roll (§5) |
| R3 | male or female | the choice in the panel; Chimera's two bodies and MakeHuman's two shapes (§4.1), told apart by hair and words as well as size |
| R4 | hair | a shell per body, a hair band on the cut (§4.2) |
| R5 | what tenses, which muscles | four zones lit from the model (jaw, tongue, soft palate, larynx), clamp tips, the class of each shown in the copy (§4.3) |
| R6 | how the air goes | the path from the trachea through the mouth and nose, with voicing, closures and nasals (§4.4) |

## Notes on what could not be checked here

- The merging agent's work is not reachable from this lane; the fork's main was unchanged at 23:04 UTC.
- No prototype was built (a design stage writes no product code), so the head's frame cost in Luma, the WebGL2 look and
  the phone layout are targets to measure, with the checks in §6 and §9.
- The literature numbers in §4.1 were read from secondary sources; the build lane cites them at the page or drops them.
- The licence field of each MakeHuman hair proxy was not opened.
- Chimera's frames and speed runs were taken in headless Chromium on a desktop (software GL and a discrete GPU); the
  head's look and cost on a phone's GPU were not seen.
