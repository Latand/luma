# The burn of a lost life

Operator, 2026-10-11: «когда жизнь сгорает, чтобы оно более так эффектно сгорало, нужно. И это чтобы было тоже на
камере». Camera review, 2026-10-14: the burn is the same in the trainer while singing and in the camera video.

In lives mode ([docs/SCORING.md](../SCORING.md#lives-mode-режим-життів)), a heart that is lost flashes, swells, shakes,
burns from its tip upward and throws embers for 0.8 s. After that only the outline of a lost heart is left. One pure canvas function draws it, so the camera video's render mode can draw the
same pixels at the same times. The camera video design is [CAMERA_VIDEO.md](CAMERA_VIDEO.md), built per
[CAMERA_VIDEO_BUILD_BRIEF.md](CAMERA_VIDEO_BUILD_BRIEF.md); its §5.2 is the render mode and §5.6 the burn, and §4 below is written against them.

## 1. Storyboard (variant 1 «Згоряє знизу», 800 ms)

| ms | the heart that is lost |
|---|---|
| 0–90 | white-hot flash; the heart swells to 2.4× its size, with an orange glow around it |
| 0–300 | it shakes sideways, settling |
| 70–560 | fire takes it from the tip upward: a glowing ragged char line climbs, the heart is ash below it and rose above it, and three flame tongues ride the line and flicker |
| 140–800 | eight embers rise from it, drift and fade |
| 480–760 | it shrinks back to its own size and the flames die out; the outline of a lost heart fades in under it |
| 800 → | the end state: the outline only (`.life.lost`, `app/head.html`) |

The other hearts stay where they are. Nothing in the layout moves: the burn is a canvas taken out of the flow and
drawn over the heart. It is click-through, and it stays in the stage head above the piano roll, so it never covers a
note. With `prefers-reduced-motion: reduce` the trainer skips the burn and the heart goes straight to its outline.

The two other prototype variants («Тріщина»: a crack and the halves falling apart; «Спалах»: a swell, a shock ring and a
ring of embers) were rendered with the same API and are in the lane's prototype review; variant 1 was built as the
recommendation, because it is the storyboard the camera review already showed.

## 2. API (`app/burn.js`)

Every trainer embeds `app/burn.js` before `app/app.js` (`studio/build_html.py`), which defines one frozen global:

```js
window.LumaBurn = {
  ms: 800,                                  // length of the burn
  box: {l: 3, r: 3, t: 5.6, b: 2.6},        // how far it paints around the heart's centre, in heart sizes
  drawHeart(ctx, x, y, size, state, ms = 0, seed = 0),
}
```

`drawHeart` draws into a `CanvasRenderingContext2D` in the context's current transform:

| argument | meaning |
|---|---|
| `x`, `y` | centre of the heart's square |
| `size` | side of that square. The trainer's hearts are 14 px (13 px on a phone), drawn from the `i-heart` symbol's 24-unit viewBox |
| `state` | `'full'` (rose heart over its outline), `'lost'` (outline only), `'burn'` |
| `ms` | for `'burn'`: milliseconds since the life was lost. `ms < 0` draws `'full'`, `ms ≥ LumaBurn.ms` draws `'lost'` |
| `seed` | the heart's index in its row (0 = the leftmost). It picks the ember paths and the flicker phases |

The function is pure. It reads no clock, no DOM and no `Math.random`, and nothing outside its arguments changes its
pixels. The same `(state, ms, seed, size)` gives the same frame in any browser and at any frame rate. It does not clear:
the caller clears its own region, at least `box` × `size` around the centre. Nothing reaches the edge of that box:
the glow, the widest part, fades out 2.4 sizes from the centre, so a canvas cut to `box` shows no flat edge. The char
line's glow (`shadowBlur`, which a canvas measures in device pixels) is scaled by the context's transform too, so it is
the same at any `devicePixelRatio`. Colours are the trainer's own: rose `#f3a1b5` for a full heart, `#76839b` for an
outline. The fire adds its own warm range (`#fff4dc`, `#ffd27a`, `#ff9a3c`, `#ff6a2b`) and ash `#1b1a22`.

## 3. How the trainer uses it

`renderLives('lose')` in `app/app.js` calls `burnLife(heart, index)`:

1. The heart takes `.life.lost` at once, so the aria label, the row and `Luma.test.state().lives.lost` change at the
   moment of the loss, exactly as before.
2. Unless reduced motion is on, a `<canvas class="life-burn">` of `box` × `size` CSS px (× `devicePixelRatio` in
   pixels) is appended to that heart, positioned absolutely, `pointer-events: none`.
3. Each animation frame clears it and calls `drawHeart(ctx, box.l·size, box.t·size, size, 'burn', now − t0, index)`.
   `t0` is the `performance.now()` of the loss. At `ms ≥ 800` the canvas is removed and the outline under it is what
   is left: `drawHeart`'s `'lost'` state is that same outline, so the end is seamless.
4. A rebuild of the row (another number of lives) removes any canvas still burning. A canvas no longer in the document
   ends its own frame loop.
5. A refill leaves a burn that is still running on screen to play out and remove itself at `ms ≥ 800`. The refill
   pop of that heart (`lifeRefill` in `app/head.html`) waits for it: `renderLives('refill')` sets the heart's `--wait`
   to the burn's remaining milliseconds, which is added to the pop's `animation-delay`. The heart shows only its outline
   under the burn until then, so the burn ends on the outline as it always does, and then the rose pops back in.

The last life burns the same way, and it is the one a refill meets. The attempt stops on it, and the new attempt's
count-in, which brings the refill, starts within about 0.1 s, while the burn is still at its start. The burn plays its
full 0.8 s over the count-in, and the hearts refill when it is done.

`Luma.test.state().lives` reports `burns` (burns started in this page) and `burning` (canvases on screen now) for the
suites.

## 4. How the camera video reproduces it

The render mode (CAMERA_VIDEO.md §5.2) replays the take through the live path with a virtual clock. It draws the hearts
onto the game canvas after `draw(t)`, through a transparent layer (**Compositing** below):

```js
// for each heart i of the row: lossAt[i] is the virtual time (ms) at which livesStep() took that life, or undefined
const B = window.LumaBurn;
for (let i = 0; i < total; i++) {
  const lost = i >= left, at = lossAt[i];
  const state = !lost ? 'full' : at !== undefined && vt - at < B.ms ? 'burn' : 'lost';
  B.drawHeart(ctx, x0 + i * (size + gap) + size / 2, y0 + size / 2, size, state, at === undefined ? 0 : vt - at, i);
}
```

- **Time.** `vt` is the render's virtual clock in wall milliseconds of the video, the same clock the frames are
  stamped with (output second `u` → `u × 1000`). The trainer measures the burn in wall time from the loss too, so a
  take sung at 0.8× burns for 0.8 s in both. Record `lossAt[i]` when `livesStep()` lowers `left` during the replay; the
  replay finds losses on the same score frames as the live take did.
- **Seed.** The heart's index, the same as the trainer's (`box.children[left]` is the heart lost when `left` drops).
- **Size.** Any size; the burn scales with it. Leave `box.t × size` of free room above the row and `box.l/r × size` at
  its ends, or let the flames and embers run over the plot's top inset, as they run over the stage head in the
  trainer.
- **The rewind tail.** When the attempt ends in a rewind, the last heart's burn finishes in the 1.2 s tail
  (CAMERA_VIDEO.md §5.2), and keeps drawing with `vt − lossAt[last]` over the frozen frame.
- **Reduced motion.** The trainer's preference does not apply to the video, which is watched elsewhere: the video always
  burns (CAMERA_VIDEO.md §5.6).

- **Compositing.** The glows and embers use `'lighter'`. The trainer draws them on a transparent canvas, which the page
  then lays over the stage head; drawn straight onto the opaque video frame they would add light to it instead, and
  come out brighter. For the trainer's pixels, draw the row into a transparent canvas the size of `box` around it
  (cleared each frame) and `drawImage` that onto the frame.

The only difference from the trainer is when frames are sampled: the trainer draws at its display rate, the video at
30 fps. Any one frame is the same function of the same arguments.

## 5. Checks

`tests/e2e/lives.mjs`:

- a wrong passage that costs N lives starts exactly N burns, and redrawing afterwards starts none;
- at 390 px and 1440 px a single loss puts one burn canvas on the heart that was lost, painted, click-through, covering
  the heart and ending above the piano roll; the hearts, the stage head and the match keep their boxes before, during
  and after it; within a second the canvas is gone and the outline is left;
- `drawHeart` into a canvas cut to `box` leaves every edge pixel transparent at every 5 ms of the burn, for sizes 13
  and 14 at 1×, 2× and 3×;
- with reduced motion lives are lost exactly as before and nothing burns;
- through the real transport, losing all three lives starts three burns (the last one too), and each canvas stays for
  its full 0.8 s; the refill comes while the last one is still on and keeps it, that heart's rose is still hidden when
  the burn ends, and after that no burn is left and all three hearts are full.

The rest of `lives.mjs` and every other suite in `tests/e2e/run.sh` pass unchanged, so the lives rule, the rewind and
the scoring do not change.
