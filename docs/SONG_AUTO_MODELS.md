# Song auto-placement: offline command and measured model choice

Choose **MMS for word proposals** and retain **pYIN + CREPE for melody**. The
placement path stays opt-in. The measured boundary refinement also stays opt-in
(`--word-refinement boundary`): its pooled median and 200 ms accuracy regress.
Neither alternative pitch configuration
beats the saved baseline on the required combination of pitch and unpitched
metrics.

Run `python -m tools.song_auto.run PACKAGE` to align the package's known text,
track melody, build a trainer in scratch and list doubtful places in seconds.
MMS supplies word proposals; the shared preparation tracker supplies fresh
pYIN + CREPE melody. The model comparison entry point remains
`python -m tools.song_auto.bench.run`. Preparation gains `--auto-place`; its
existing default remains in place.

## Reference and measurement limits

The accuracy numbers below measure agreement with five targets edited by eye from
spectrograms on 2026-11-16. Nobody verified these targets by ear. Song E was
edited by a smaller model and contains many words with reference confidence
`c <= 0.4`. Every word table therefore gives all words and `c > 0.4` separately;
pooled results give both A–D and A–E. Filtering word confidence leaves pitch
metrics unchanged: word confidence supplies no frame-level pitch annotation.

These are five selected, difficult recordings. Model selection had no independent
holdout. The later fixed-rule refinement audit excludes each song in turn without
fitting parameters on the other four; it supplies no new independent recordings.
Unchanged reference contour frames retain the old algorithm's decisions. This
favours the saved pitch baseline, so small differences cannot establish absolute
pitch accuracy. An absent `unpitched` annotation supplies no scream/noise labels
for that song. A zero denominator is N/A. These limits apply to every table.
The pitch results compare the listed configurations: the saved baseline includes
its existing energy, periodicity and minimum-run gates; the alternatives use
their native voiced decisions. No thresholds were optimized against these targets.

Known text comes from the current package. Coarse time anchors come exclusively
from the immutable saved **before** target. Corrected word times, contour and
unpitched annotations are used only by the scorer. Maximum ordered exact-token
matching supplies coarse clocks for the corrected text; missing words interpolate
between matched clocks. Each lyric row hears 1.5 s before its first coarse clock
and 2.5–4 s after its last, with at most 30 s per window. Long internal spans
refuse. All aligners use the same text and windows. This evaluates alignment with
imperfect existing clocks.
The initial comparison does not use independent published line clocks; the later
"Published synced line anchors" section measures that separate input.
The supplied corrected text and row grouping are assumed available; this run
does not measure lyric recognition or automatic row reflow.

The saved baseline includes the text and timing path that actually shipped,
including cached text corrections. Its text differs from the known corrected
text given to aligners. Missing words count as failures; common-text sensitivity
also isolates words present in both texts. Repeated-text ties use a fixed token
order rule, independent of either set of word times. Ambiguous missing repeats
can still make this correspondence uncertain.

## Candidates and sources

Sources were checked on 2026-11-16. Download sizes are decimal MB of model
artifacts, excluding the shared PyTorch runtime. Model implementations and weights stay external.
All evaluated neural implementations provide CUDA and CPU inference paths.

| Job / candidate | Primary source | Licence / permitted use | Download | Offline after download |
|---|---|---|---:|---|
| Saved word baseline | [Existing preparation](PIPELINE.md), Soniox plus onset snapping and cached corrections | Existing proprietary recognizer; saved output replayed locally | No new download | Replay yes; original recognition requires the service |
| MMS FA | [Torchaudio bundle](https://docs.pytorch.org/audio/stable/generated/torchaudio.pipelines.MMS_FA.html), the acoustic model already used by `tools/song_qa/fa_align.py` | Checkpoint CC-BY-NC 4.0; suitable for this local noncommercial benchmark; retains the noncommercial restriction | 1262.05 MB | Yes |
| wav2vec2 base 960h | [Torchaudio bundle](https://docs.pytorch.org/audio/stable/generated/torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H.html) | Torchaudio's redistributed checkpoint: MIT | 377.66 MB | Yes |
| SOFA English v100 | [Singing aligner source](https://api.github.com/repositories/692173601), [checkpoint release](https://api.github.com/repositories/732253401/releases/tags/v1.0.0_en) | Code MIT; checkpoint sharing post explicitly permits public and commercial annotation use. No separate checkpoint redistribution licence found | 406.08 MB + 3.38 MB dictionary | Yes |
| Saved pYIN + CREPE | [Existing map rules](PIPELINE.md), [torchcrepe 0.0.24](https://pypi.org/project/torchcrepe/0.0.24/), librosa 0.11.0 | torchcrepe MIT; librosa ISC | CREPE full 88.99 MB; pYIN has no weights | Yes |
| FCPE | [torchfcpe 0.0.4](https://pypi.org/project/torchfcpe/0.0.4/), bundled `fcpe_c_v001` | MIT distribution | 43.36 MB weights; compressed package about 40 MB | Yes, weights bundled |
| PENN FCNF0++ | [PENN 1.0.0](https://pypi.org/project/penn/1.0.0/) | MIT implementation and upstream checkpoint distribution | 107.25 MB | Yes, local checkpoint argument |

SOFA supplies a singing-trained English acoustic model. The adapter uses its own
dictionary, phoneme alignment and word ownership, then the project's existing
token-group validation. It refuses out-of-vocabulary words instead of dropping
them. Its WAV reader uses soundfile for the already resampled mono windows;
this avoids an additional decoder dependency. Model inference is unchanged.
The measured SOFA path is its core forced alignment, before the optional breath
detector and export postprocessing.

MMS uses the project's existing normalization, compound-token ownership,
star-token windows, CTC forced alignment and complete `sheet_hints` validation.
The wav2vec2 adapter uses the same ownership and CTC code with its own acoustic
model, uppercase alphabet and word separator. It has no MMS star token.
Both CTC adapters inherit the existing helper's Latin a–z/apostrophe token
support. Unsupported characters and digits refuse before weights are loaded;
these English references do not establish multilingual alignment support.

FCPE uses its model's native 10 ms frame grid, local-argmax decoding, its default 0.006
threshold and no unvoiced interpolation. Its public API supplies a binary
decision, so the neutral confidence is a decision indicator. PENN uses native
10 ms frames, zero-centred windows, Viterbi decoding, periodicity threshold
0.065 and no interpolation. Both pitch adapters own 20 s blocks with 1 s context
on either side. Thresholds were fixed before scoring, with no per-song tuning.

## Metrics

Word error is absolute start-time error, in milliseconds. The median pools
individual errors; missing words have infinite error and remain in the 80/200 ms
denominators. A median containing too many missing words is N/A. Crossings stay
in lyric order and count as errors; the harness never sorts proposals into a
better-looking order. Common-text tables use only reference tokens matched to
the saved baseline, with the same missing-prediction penalty.

The pickup subset is a reproducible **proxy**, since the reference contains no
syllable or pickup labels. A held note lasts at least 600 ms and starts within
120 ms of its owning word, ending no later than 200 ms after the word. The one
or two preceding words qualify when each lasts at most 300 ms and the gap to the
next word is at most 150 ms. This subset measures short words before a long note;
it cannot establish that every qualifying word is a single short syllable.

Pitch is sampled on the reference grid using the nearest native frame within
half a candidate hop. Gaps and out-of-range coverage remain unvoiced. Agreement
within 50 cents uses **all voiced reference frames** as its denominator; a
missing estimate fails. Octave error means a nonzero multiple of 1200 cents,
within 50 cents, divided by the same denominator. False unpitched contour is the
share of annotated reference unpitched frames predicted voiced. Ignored notes
are excluded from held-note analysis. A held reference note must have continuous
reference pitch for at least 600 ms; a break is an internal predicted unvoiced
gap of at least one reference frame (20 ms here), with voiced estimates on both
sides. The scorer also counts gaps lasting at least 60 ms. Fully missed held
notes and total voiced recall are reported too, so an empty tracker cannot win
by producing fewer internal gaps.

## Reproduce in scratch

Install the project dependencies and
`tools/song_auto/bench/requirements.txt` into an external environment. The SOFA
adapter additionally uses `tools/song_auto/bench/sofa-requirements.txt` and an
external upstream source checkout. The measured environment reused the existing
project packages through a read-only site-packages path in a scratch venv;
candidate additions were installed only in that venv. Exact resolved versions,
checkpoint hashes, input hashes, commands and time bounds remain in private
evidence. No browser profile is involved.

Supply private paths in shell variables. `PKG` holds the corrected package,
`BEFORE` its saved before target, and `S` an external scratch directory disjoint
from both input trees. `PY` is the isolated environment's Python executable.

```sh
export TORCH_HOME="$S/models/torch" HF_HOME="$S/models/hf"
export NUMBA_CACHE_DIR="$S/numba" PYTHONDONTWRITEBYTECODE=1
# First provision the documented checkpoints into these external caches.
"$PY" -m tools.song_auto.bench.run "$PKG" mms \
  --seed-target "$BEFORE" --scratch "$S/runs"
# Substitute baseline, wav2vec2, fcpe or penn; PENN can take --checkpoint.
# SOFA requires --sofa-source, --checkpoint and --dictionary.
"$PY" -m tools.song_auto.bench.score "$OUTPUT" "$PKG/target.json" --baseline "$BEFORE"
```

Each invocation creates a new output directory containing `output.json` and
`provenance.json`. The neutral schema `song-auto-bench.v1` stores duration, native
pitch hop, lyric-order words `{w,a,b,confidence}`, pitch frames
`{t,hz,voiced,confidence}`, candidate name, measured component and runtime.
Unvoiced frames have `hz: null`. The other component is copied from the saved
baseline, so every output contains both words and pitch; only
`measured_component` identifies the newly measured job. A missing component
(`null`) and an attempted empty prediction (`[]`) have different meanings to the
scorer. Raw output contains private words and stays outside the repository.

The benchmark has no apply mode and never calls a package writer. It resolves
scratch symlinks, fences inherited model-cache overrides too, refuses overlap
with input trees, the repository and the active Python environment, hashes the three input
files before and after a run, validates output and writes only to a fresh scratch
directory. The campaign used a socket-denying Python startup shim and offline
hub mode after prefetch, with one model process at a time.

## Measured results

Final GPU campaign: 2026-11-16 17:43:01–18:44:51 UTC, RTX 3060 (12 GB), PyTorch/torchaudio 2.10.0+cu128, Torch/OMP/MKL thread limits set to 2. Two fresh model processes per successful neural candidate/song; all 24 repeated word/contour pairs were identical. Scores below use the first run. Downloads were prefetched.

### Word starts per song

Visual reference, unheard; each pair is **all / reference c > 0.4**. Crossings count the full output independently of filtering. Missing words remain in the denominator.

| Song | Model | Reference words | Matched | Median ms | Within 80 ms % | Within 200 ms % | Crossings |
|---|---|---:|---:|---:|---:|---:|---:|
| A | baseline | 167 / 156 | 84 / 81 | 1654.0 / 1440.0 | 12.0 / 12.8 | 13.8 / 14.7 | 0 |
| A | mms | 167 / 156 | 167 / 156 | 234.7 / 250.4 | 35.3 / 35.9 | 46.7 / 45.5 | 6 |
| A | wav2vec2 | 167 / 156 | 167 / 156 | 588.2 / 594.1 | 25.7 / 25.6 | 31.7 / 31.4 | 17 |
| A | sofa | 167 / 156 | 167 / 156 | 529.5 / 455.4 | 16.8 / 17.3 | 27.5 / 28.8 | 17 |
| B | baseline | 166 / 164 | 143 / 141 | 575.5 / 583.5 | 2.4 / 2.4 | 10.2 / 9.8 | 0 |
| B | mms | 166 / 164 | 166 / 164 | 85.9 / 85.9 | 48.2 / 48.2 | 69.3 / 69.5 | 4 |
| B | wav2vec2 | 166 / 164 | 166 / 164 | 163.8 / 163.8 | 39.2 / 39.0 | 53.0 / 53.0 | 20 |
| B | sofa | 166 / 164 | 166 / 164 | 503.0 / 490.2 | 14.5 / 14.6 | 31.9 / 32.3 | 17 |
| C | baseline | 203 / 183 | 158 / 142 | 401.0 / 412.0 | 31.0 / 31.1 | 37.4 / 36.6 | 0 |
| C | mms | 203 / 183 | 203 / 183 | 286.1 / 259.1 | 33.0 / 33.9 | 42.9 / 44.8 | 4 |
| C | wav2vec2 | 203 / 183 | 203 / 183 | 401.6 / 398.0 | 22.7 / 23.5 | 32.5 / 32.8 | 24 |
| C | sofa | 203 / 183 | 203 / 183 | 714.2 / 714.2 | 11.8 / 13.1 | 25.6 / 27.3 | 21 |
| D | baseline | 270 / 233 | 270 / 233 | 40.5 / 29.0 | 52.6 / 60.1 | 61.1 / 67.0 | 0 |
| D | mms | 270 / 233 | 270 / 233 | 197.7 / 201.0 | 35.9 / 34.3 | 50.0 / 49.8 | 8 |
| D | wav2vec2 | 270 / 233 | 270 / 233 | 276.8 / 293.9 | 28.5 / 26.2 | 42.2 / 40.8 | 36 |
| D | sofa | 270 / 233 | 270 / 233 | 685.9 / 790.5 | 19.3 / 18.5 | 29.6 / 26.6 | 30 |
| E | baseline | 280 / 171 | 278 / 169 | 595.0 / 478.0 | 7.9 / 9.9 | 11.1 / 12.9 | 0 |
| E | mms | 280 / 171 | 280 / 171 | 69.5 / 46.2 | 53.2 / 65.5 | 71.4 / 83.0 | 6 |
| E | wav2vec2 | 280 / 171 | 280 / 171 | 177.6 / 89.4 | 35.0 / 49.1 | 52.9 / 67.3 | 27 |
| E | sofa | N/A | N/A | N/A | N/A | N/A | N/A |

### Pooled word starts

Visual reference, unheard; all / c > 0.4. Individual errors are pooled across songs. The A–E SOFA result is unavailable because E refused.

| Set | Model | Reference words | Matched | Median ms | Within 80 ms % | Within 200 ms % | Crossings |
|---|---|---:|---:|---:|---:|---:|---:|
| A–D | baseline | 806 / 736 | 655 / 597 | 422.5 / 416.5 | 28.4 / 30.0 | 34.9 / 35.6 | 0 |
| A–D | mms | 806 / 736 | 806 / 736 | 188.2 / 182.8 | 37.6 / 37.6 | 51.5 / 52.0 | 22 |
| A–D | wav2vec2 | 806 / 736 | 806 / 736 | 316.6 / 314.3 | 28.7 / 28.3 | 39.8 / 39.5 | 97 |
| A–D | sofa | 806 / 736 | 806 / 736 | 641.4 / 675.8 | 15.9 / 16.0 | 28.7 / 28.5 | 85 |
| A–E | baseline | 1086 / 907 | 933 / 766 | 470.0 / 432.0 | 23.1 / 26.2 | 28.7 / 31.3 | 0 |
| A–E | mms | 1086 / 907 | 1086 / 907 | 126.6 / 119.8 | 41.6 / 42.9 | 56.6 / 57.9 | 28 |
| A–E | wav2vec2 | 1086 / 907 | 1086 / 907 | 283.2 / 253.4 | 30.3 / 32.2 | 43.2 / 44.8 | 124 |
| A–E | sofa | N/A | N/A | N/A | N/A | N/A | N/A |

### Common-text sensitivity

Visual reference, unheard; all / c > 0.4. Only tokens also present in the saved baseline enter this table. This separates alignment improvement from the advantage of receiving corrected text.

| Set | Model | Common words | Matched | Median ms | Within 80 ms % | Within 200 ms % | Crossings |
|---|---|---:|---:|---:|---:|---:|---:|
| A–D | baseline | 655 / 597 | 655 / 597 | 290.0 / 279.0 | 35.0 / 37.0 | 42.9 / 43.9 | 0 |
| A–D | mms | 655 / 597 | 655 / 597 | 157.8 / 148.9 | 40.0 / 40.0 | 54.4 / 54.9 | 22 |
| A–D | wav2vec2 | 655 / 597 | 655 / 597 | 255.6 / 253.4 | 31.6 / 31.2 | 44.3 / 43.9 | 97 |
| A–D | sofa | 655 / 597 | 655 / 597 | 537.6 / 574.7 | 18.5 / 18.6 | 32.1 / 31.7 | 85 |
| A–E | baseline | 933 / 766 | 933 / 766 | 392.0 / 349.5 | 26.9 / 31.1 | 33.4 / 37.1 | 0 |
| A–E | mms | 933 / 766 | 933 / 766 | 107.4 / 99.3 | 44.1 / 45.8 | 59.6 / 61.4 | 28 |
| A–E | wav2vec2 | 933 / 766 | 933 / 766 | 234.3 / 206.0 | 32.7 / 35.2 | 46.9 / 49.2 | 124 |
| A–E | sofa | N/A | N/A | N/A | N/A | N/A | N/A |

### Pickups before held notes

Visual reference, unheard; the temporal pickup proxy defined above, all / c > 0.4. Small denominators and absent syllable labels limit this comparison.

| Song / set | Model | Reference words | Matched | Median ms | Within 80 ms % | Within 200 ms % | Crossings |
|---|---|---:|---:|---:|---:|---:|---:|
| A | baseline | 2 / 2 | 1 / 1 | N/A / N/A | 50.0 / 50.0 | 50.0 / 50.0 | 0 |
| A | mms | 2 / 2 | 2 / 2 | 350.4 / 350.4 | 0.0 / 0.0 | 0.0 / 0.0 | 6 |
| A | wav2vec2 | 2 / 2 | 2 / 2 | 340.4 / 340.4 | 0.0 / 0.0 | 0.0 / 0.0 | 17 |
| A | sofa | 2 / 2 | 2 / 2 | 361.4 / 361.4 | 0.0 / 0.0 | 0.0 / 0.0 | 17 |
| B | baseline | 9 / 9 | 9 / 9 | 267.0 / 267.0 | 0.0 / 0.0 | 11.1 / 11.1 | 0 |
| B | mms | 9 / 9 | 9 / 9 | 23.0 / 23.0 | 66.7 / 66.7 | 88.9 / 88.9 | 4 |
| B | wav2vec2 | 9 / 9 | 9 / 9 | 81.3 / 81.3 | 44.4 / 44.4 | 55.6 / 55.6 | 20 |
| B | sofa | 9 / 9 | 9 / 9 | 300.1 / 300.1 | 22.2 / 22.2 | 33.3 / 33.3 | 17 |
| C | baseline | 5 / 5 | 4 / 4 | 209.0 / 209.0 | 40.0 / 40.0 | 40.0 / 40.0 | 0 |
| C | mms | 5 / 5 | 5 / 5 | 558.1 / 558.1 | 40.0 / 40.0 | 40.0 / 40.0 | 4 |
| C | wav2vec2 | 5 / 5 | 5 / 5 | 2196.3 / 2196.3 | 20.0 / 20.0 | 20.0 / 20.0 | 24 |
| C | sofa | 5 / 5 | 5 / 5 | 515.5 / 515.5 | 20.0 / 20.0 | 40.0 / 40.0 | 21 |
| D | baseline | 14 / 10 | 14 / 10 | 130.0 / 125.5 | 28.6 / 40.0 | 64.3 / 70.0 | 0 |
| D | mms | 14 / 10 | 14 / 10 | 24.5 / 22.7 | 71.4 / 60.0 | 78.6 / 70.0 | 8 |
| D | wav2vec2 | 14 / 10 | 14 / 10 | 44.9 / 42.8 | 64.3 / 60.0 | 78.6 / 80.0 | 36 |
| D | sofa | 14 / 10 | 14 / 10 | 871.0 / 871.0 | 28.6 / 30.0 | 28.6 / 30.0 | 30 |
| E | baseline | 2 / 2 | 2 / 2 | 80.5 / 80.5 | 50.0 / 50.0 | 100.0 / 100.0 | 0 |
| E | mms | 2 / 2 | 2 / 2 | 194.5 / 194.5 | 50.0 / 50.0 | 50.0 / 50.0 | 6 |
| E | wav2vec2 | 2 / 2 | 2 / 2 | 1178.6 / 1178.6 | 0.0 / 0.0 | 0.0 / 0.0 | 27 |
| E | sofa | N/A | N/A | N/A | N/A | N/A | N/A |
| A–D | baseline | 30 / 26 | 28 / 24 | 237.0 / 237.0 | 23.3 / 26.9 | 43.3 / 42.3 | 0 |
| A–D | mms | 30 / 26 | 30 / 26 | 26.5 / 37.4 | 60.0 / 53.8 | 70.0 / 65.4 | 22 |
| A–D | wav2vec2 | 30 / 26 | 30 / 26 | 124.7 / 175.6 | 46.7 / 42.3 | 56.7 / 53.8 | 97 |
| A–D | sofa | 30 / 26 | 30 / 26 | 430.2 / 422.4 | 23.3 / 23.1 | 30.0 / 30.8 | 85 |
| A–E | baseline | 32 / 28 | 30 / 26 | 216.5 / 216.5 | 25.0 / 28.6 | 46.9 / 46.4 | 0 |
| A–E | mms | 32 / 28 | 32 / 28 | 33.0 / 45.1 | 59.4 / 53.6 | 68.8 / 64.3 | 28 |
| A–E | wav2vec2 | 32 / 28 | 32 / 28 | 175.6 / 205.5 | 43.8 / 39.3 | 53.1 / 50.0 | 124 |
| A–E | sofa | N/A | N/A | N/A | N/A | N/A | N/A |

### Melody per song

Visual reference, unheard; retained baseline frames favour the baseline. Word-confidence filtering does not change these frame metrics. E has no annotated unpitched frames, so its false-unpitched result is N/A.

| Song | Model | Within 50 cents % | Octave errors % | False unpitched % | Voiced recall % | Broken / held notes | Internal gaps | Missed held |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| A | baseline | 92.0 | 2.2 | 6.9 | 94.6 | 4 / 42 | 10 | 0 |
| A | fcpe | 89.3 | 3.3 | 64.0 | 99.4 | 0 / 42 | 0 | 0 |
| A | penn | 78.6 | 2.8 | 34.9 | 89.5 | 22 / 42 | 80 | 0 |
| B | baseline | 96.3 | 1.8 | 4.4 | 98.4 | 1 / 69 | 1 | 0 |
| B | fcpe | 93.3 | 1.7 | 36.7 | 99.3 | 2 / 69 | 7 | 0 |
| B | penn | 77.5 | 4.2 | 17.8 | 89.3 | 43 / 69 | 123 | 0 |
| C | baseline | 99.0 | 0.8 | 15.4 | 100.0 | 1 / 54 | 2 | 0 |
| C | fcpe | 92.6 | 1.6 | 68.0 | 99.3 | 3 / 54 | 3 | 0 |
| C | penn | 84.4 | 1.2 | 43.1 | 93.3 | 27 / 54 | 63 | 0 |
| D | baseline | 99.2 | 0.0 | 12.6 | 99.2 | 4 / 62 | 10 | 0 |
| D | fcpe | 94.6 | 0.7 | 79.3 | 99.4 | 2 / 62 | 2 | 0 |
| D | penn | 74.8 | 2.7 | 48.6 | 86.7 | 53 / 62 | 153 | 0 |
| E | baseline | 98.9 | 0.3 | N/A | 99.1 | 5 / 98 | 10 | 0 |
| E | fcpe | 89.1 | 4.2 | N/A | 99.0 | 3 / 98 | 3 | 0 |
| E | penn | 75.7 | 4.6 | N/A | 90.3 | 52 / 98 | 146 | 0 |

### Pooled melody

Visual reference, unheard; frame and note counts are pooled. Both reference sets are shown. Confidence filtering of words leaves these results identical.

| Set | Model | Within 50 cents % | Octave errors % | False unpitched % | Voiced recall % | Broken / held notes | Internal gaps | Missed held |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| A–D | baseline | 97.0 | 1.1 | 10.1 | 98.3 | 10 / 227 | 23 | 0 |
| A–D | fcpe | 92.9 | 1.6 | 66.6 | 99.4 | 7 / 227 | 12 | 0 |
| A–D | penn | 78.4 | 2.8 | 38.8 | 89.4 | 145 / 227 | 419 | 0 |
| A–E | baseline | 97.6 | 0.8 | 10.1 | 98.6 | 15 / 325 | 33 | 0 |
| A–E | fcpe | 91.6 | 2.5 | 66.6 | 99.3 | 10 / 325 | 15 | 0 |
| A–E | penn | 77.5 | 3.4 | 38.8 | 89.7 | 197 / 325 | 565 | 0 |

### Wall time per song

Seconds for a full benchmark subprocess, including Python startup, hashes, audio I/O, resampling, model loading, inference and neutral output; scorer time is excluded. Values are median [min–max] of two runs. The baseline column times one saved-output replay, which performs no recognition or pitch inference. SOFA E shows its failed attempt time.

| Song | Baseline replay | MMS | wav2vec2 | SOFA | FCPE | PENN |
|---|---:|---:|---:|---:|---:|---:|
| A | 0.13 | 8.48 [8.42–8.55] | 5.36 [5.18–5.54] | 12.79 [10.93–14.64] | 4.68 [4.42–4.94] | 16.31 [15.54–17.07] |
| B | 0.14 | 8.88 [8.87–8.89] | 5.53 [5.49–5.57] | 10.78 [10.62–10.93] | 4.68 [4.60–4.76] | 16.90 [16.90–16.91] |
| C | 0.18 | 8.91 [8.86–8.96] | 6.21 [5.99–6.43] | 10.38 [10.33–10.42] | 5.08 [5.08–5.09] | 17.40 [17.33–17.47] |
| D | 0.16 | 10.07 [9.81–10.34] | 6.35 [6.27–6.43] | 10.75 [10.62–10.87] | 5.00 [5.00–5.01] | 15.99 [15.87–16.12] |
| E | 0.21 | 11.25 [11.22–11.29] | 7.35 [7.24–7.47] | failed 6.26 | 6.17 [5.98–6.37] | 28.01 [27.74–28.29] |

For context, the saved manifests contain these **historical** inference times. They were recorded under different runs and loads, so they support no speedup claim against the new measurements. The recognizer time omits later cached text correction and snapping; separation and trainer building are excluded.

| Song | Historical recognition s | Historical pYIN + CREPE s |
|---|---:|---:|
| A | 13.8 | 100.5 |
| B | 13.1 | 114.9 |
| C | 13.4 | 122.8 |
| D | 25.3 | 89.2 |
| E | 11.7 | 170.5 |

## Choice and integration limits

On this visual reference, which remains unverified by ear, **MMS wins the pooled
word comparison** with and without E and low-confidence words. On A–D, median
error is 188.2 ms against the baseline's 422.5 ms; the confident common-text
subset gives 148.9 against 279.0 ms. The pickup proxy also improves in aggregate.
wav2vec2 is quicker in these runs, with weaker alignment and many more crossings.
SOFA is worse on A–D and cannot cover all five songs with its supplied dictionary.
MMS therefore supplies the command’s word proposal engine.

**MMS is insufficient for an unconditional replacement.** It has 28 crossing
starts across A–E. Song D's overall median regresses from 40.5 to 197.7 ms, and
some individual pickup subsets regress too. The command reports
invalid order and doubtful spans. Its guarded output is measured separately
below. The measurements here cover raw proposals, with no repaired
crossings or unmeasured hybrid result presented as a winner.

**Keep the existing pYIN + CREPE melody component.** On A–E, agreement within
50 cents is 97.6% for the saved baseline, 91.6% for FCPE and 77.5% for PENN.
False contour inside annotated unpitched spans is 10.1%, 66.6% and 38.8%,
respectively. FCPE reduces broken held notes from 15/325 to 10/325, so the
baseline does lose that individual metric. That improvement comes with worse
pitch and unpitched results. Neither alternative wins the required overall
melody comparison, including when E is excluded. The reference's retained
baseline frames limit this conclusion to the stated benchmark.

SOFA English v100 was downloaded with the [v005 dictionary asset](https://api.github.com/repositories/732253401/releases/tags/v0.0.5)
specified by that release, and its
core inference was run offline using the optional requirements and upstream
source revision `9549c6a`. A–D completed twice. E refused because five word
occurrences are missing from that dictionary; the project's CMU dictionary also
has no entries for those occurrences. Its failed attempt is retained, and E
and A–E are explicitly unavailable for SOFA. No guessed pronunciation was used.
All other candidates installed and completed every reference song.

All five neural candidates also completed a two-second synthetic-audio CPU
probe with networking disabled and `--device cpu`. This checks execution and
device support; it supplies no CPU accuracy or full-song performance claim.
GPU runs were serial, and one model process exited before the next started.

## Run the command

Use Python 3.11 and install `requirements.txt` into an external environment.
The command adds no production dependencies: the existing pinned PyTorch,
torchaudio, torchcrepe and librosa versions and bounded NumPy, SciPy and
soundfile versions cover it. Candidate-only dependencies remain in the benchmark
requirements files. Model weights are external; the MMS checkpoint retains its
CC-BY-NC 4.0 restriction. The source, licence and download sizes are in the
candidate table above (MMS 1262.05 MB; CREPE full 88.99 MB).

Set `PY` to that environment's Python, `PKG` to a song package, `S` to an external
scratch directory and `MODELS` to an external Torch cache. Neither output nor
cache may overlap the package, its coarse timing source, the repository or the
active Python environment. Provision weights once while online:

```sh
"$PY" -m tools.song_auto.run --download-models --model-cache "$MODELS"
"$PY" -m tools.song_auto.run "$PKG" --scratch "$S" --model-cache "$MODELS"
# Optional: --device cpu (auto chooses CUDA when available).
# Optional: --seed-target "$BEFORE/target.json" for independent coarse clocks.
# Experimental: --word-refinement boundary (or boundary-baseline).
```

Inference denies socket connections, including implicit downloads on cache miss.
It needs the package's `target.json`, `vocals_44k.flac` and four playback MP3s.
Known text and row grouping come from `target.json`; coarse clocks default to
that same file. Supplying `--seed-target` changes only coarse clocks. It does not
supply reference melody or unpitched labels. Unsupported tokens, empty rows and
coarse windows over 30 seconds refuse. CREPE decoding has a fixed NumPy seed in both entry paths.
A full command run on two seconds of synthetic audio passed with real models
and `--device cpu`, offline. This verifies execution; full-song CPU runtime
was not benchmarked. GPU and CPU results are not asserted identical.

Each run creates a fresh `song-auto-*` directory. It contains `target.json`,
`trainer.html`, the scorer-compatible `output.json`, full `checks.json` and
private input-hash provenance. The last stdout line is a JSON object with output
paths and runtime. The preceding short list gives up to 20 doubtful intervals;
all flags remain in `checks.json`. These artifacts contain private text and
must stay outside the repository. A nonzero exit means the command failed;
QA flags by themselves leave a successful, unverified draft.

Word ownership uses `studio/lyric_tokens.py` through the shared forced-aligner
helpers. Across-row overlaps are repaired with a deterministic least-squares
isotonic projection, retaining lyric order and at least 40 ms between starts.
Word ends are capped before the next word. Every repaired word and every word
with acoustic confidence below 0.6 has confidence at most 0.4. Word-start placement
flags and repeat disagreements also lower affected word confidence to 0.4.
Projection supplies a valid draft; it establishes no acoustic accuracy. Stored
confidence is a review signal and has no calibrated probability interpretation.

MMS FA in the pinned torchaudio bundle returns letter log probabilities and
appends a wildcard with log score zero. The adapter passes these emissions
unchanged to CTC alignment; only wav2vec2 logits receive `log_softmax`.
An earlier adapter normalized the extended MMS output again, halving every
letter probability and making the 0.6 gate unreachable. That defect forced
every generated word below the acoustic gate in the previous run. The correction
preserves native acoustic scores; order repair, refinement doubts and final QA
can still lower a high acoustic score to 0.4. The threshold remains 0.6.

The command shares preparation's pYIN + CREPE inference and QA's feature
extraction, placement screen, octave/broken-note/repeat candidates, note
rederivation and schema validator. It keeps the better measured melody component.
Octave and gap hypotheses remain review items. Generic `noise` spans require
at least 120 ms of audible, weakly harmonic, aperiodic stem energy with no
surviving pitch estimate. Silence and missing pitch alone create no annotation.
This conservative rule never erases a surviving pitch frame and does not infer
`scream` identity; scream-specific classification still requires review. The
output always includes `unpitched`, including an empty list. New contour and
words derive a new edit id; old trainer edits cannot silently apply to the draft.

To apply a reviewed run configuration explicitly:

```sh
"$PY" -m tools.song_auto.run "$PKG" --scratch "$S" --model-cache "$MODELS" --apply
# Add --trainer "$HTML" if the manifest does not identify the intended trainer.
```

Apply reruns inference. It locks auto writers, checks the input hash, copies the
previous target, trainer and manifest into
`backups/song-auto-<UTC timestamp>/<package>/` beside the song packages, and
records recovery locations in `restore.json`. Only after backup does it replace
the target and run `studio/build_html.py` with the actual package path. It checks
that the newly built trainer embeds the generated target, replaces the trainer
atomically and updates the manifest. Exceptions restore the previous records;
backups survive. Process termination or power loss may require restoring the
three files using `restore.json`; multi-file replacement is not transactional
across a system crash. A persistent `.song-auto.lock` serializes auto writers.
Do not run unrelated song editors concurrently. Trainer paths must be inside
or beside the package. No apply run on the reference library was made here.

For newly prepared songs, add `--auto-place` to `studio/prepare_song.py`; set
`TORCH_HOME="$MODELS"` to the provisioned cache. It uses the freshly recognized
text and freshly computed melody, runs MMS plus end checks and builds the final
trainer normally. Its QA report is in `manifest.json` under `steps.auto_place`.
Add `--word-refinement boundary` or `boundary-baseline` with `--auto-place` to
try the measured experimental refinement. Preparation refuses a refinement option
without `--auto-place`, before creating a package. The fallback uses only the
pre-alignment target (in preparation, the freshly recognized and onset-snapped
words); it never uses a corrected evaluation target.
This option does not change preparation's optional Soniox recognition or Demucs
download behaviour. The existing-package command itself uses no paid service.
Preparation remains opt-in because superiority on both required components
has not been demonstrated.

## End-to-end command measurements

GPU campaign: 2026-11-16 20:48:01–21:02:50 UTC, RTX 3060 (12 GB), PyTorch/torchaudio 2.10.0+cu128, two CPU threads, cached weights. One fresh command process per song, sequentially. Each command computed MMS words, fresh pYIN + CREPE pitch, features, QA and a full scratch trainer build. All five actual output files passed the step 1 scoring CLI. Both hashes and modification times of the audited package files stayed unchanged. Private instrumentation captured proposals and features without replacing inference.

The visual reference was not checked by ear. E has many reference words with c <= 0.4; pairs below are **all / reference c > 0.4**. A–D and A–E are both reported. The reference retains baseline contour frames and favours the saved tracker. The command received corrected text and row grouping, with coarse clocks only from the saved before target. The baseline retains its historical text differences. See common-text sensitivity below. These limits apply to every table in this section.

### Final word starts

| Song / set | Path | Reference words | Matched | Median ms | Within 80 ms % | Within 200 ms % | Crossings |
|---|---|---:|---:|---:|---:|---:|---:|
| A | baseline | 167 / 156 | 84 / 81 | 1654.0 / 1440.0 | 12.0 / 12.8 | 13.8 / 14.7 | 0 |
| A | command | 167 / 156 | 167 / 156 | 272.0 / 272.0 | 32.9 / 33.3 | 43.1 / 42.3 | 0 |
| B | baseline | 166 / 164 | 143 / 141 | 575.5 / 583.5 | 2.4 / 2.4 | 10.2 / 9.8 | 0 |
| B | command | 166 / 164 | 166 / 164 | 88.5 / 88.5 | 48.2 / 48.2 | 68.1 / 68.3 | 0 |
| C | baseline | 203 / 183 | 158 / 142 | 401.0 / 412.0 | 31.0 / 31.1 | 37.4 / 36.6 | 0 |
| C | command | 203 / 183 | 203 / 183 | 273.0 / 253.0 | 33.0 / 34.4 | 43.8 / 45.9 | 0 |
| D | baseline | 270 / 233 | 270 / 233 | 40.5 / 29.0 | 52.6 / 60.1 | 61.1 / 67.0 | 0 |
| D | command | 270 / 233 | 270 / 233 | 193.5 / 194.0 | 36.7 / 35.2 | 50.4 / 50.2 | 0 |
| E | baseline | 280 / 171 | 278 / 169 | 595.0 / 478.0 | 7.9 / 9.9 | 11.1 / 12.9 | 0 |
| E | command | 280 / 171 | 280 / 171 | 69.5 / 46.0 | 53.2 / 65.5 | 70.7 / 81.9 | 0 |
| A–D | baseline | 806 / 736 | 655 / 597 | 422.5 / 416.5 | 28.4 / 30.0 | 34.9 / 35.6 | 0 |
| A–D | command | 806 / 736 | 806 / 736 | 192.5 / 187.5 | 37.3 / 37.5 | 50.9 / 51.5 | 0 |
| A–E | baseline | 1086 / 907 | 933 / 766 | 470.0 / 432.0 | 23.1 / 26.2 | 28.7 / 31.3 | 0 |
| A–E | command | 1086 / 907 | 1086 / 907 | 138.5 / 123.0 | 41.4 / 42.8 | 56.0 / 57.2 | 0 |

### Final pickup proxy

Short words before a long reference note; the small proxy subsets establish no syllable-level or listening accuracy. All / c > 0.4.

| Song / set | Path | Reference words | Matched | Median ms | Within 80 ms % | Within 200 ms % | Crossings |
|---|---|---:|---:|---:|---:|---:|---:|
| A | baseline | 2 / 2 | 1 / 1 | N/A / N/A | 50.0 / 50.0 | 50.0 / 50.0 | 0 |
| A | command | 2 / 2 | 2 / 2 | 350.5 / 350.5 | 0.0 / 0.0 | 0.0 / 0.0 | 0 |
| B | baseline | 9 / 9 | 9 / 9 | 267.0 / 267.0 | 0.0 / 0.0 | 11.1 / 11.1 | 0 |
| B | command | 9 / 9 | 9 / 9 | 23.0 / 23.0 | 66.7 / 66.7 | 88.9 / 88.9 | 0 |
| C | baseline | 5 / 5 | 4 / 4 | 209.0 / 209.0 | 40.0 / 40.0 | 40.0 / 40.0 | 0 |
| C | command | 5 / 5 | 5 / 5 | 558.0 / 558.0 | 40.0 / 40.0 | 40.0 / 40.0 | 0 |
| D | baseline | 14 / 10 | 14 / 10 | 130.0 / 125.5 | 28.6 / 40.0 | 64.3 / 70.0 | 0 |
| D | command | 14 / 10 | 14 / 10 | 24.5 / 22.5 | 71.4 / 60.0 | 85.7 / 80.0 | 0 |
| E | baseline | 2 / 2 | 2 / 2 | 80.5 / 80.5 | 50.0 / 50.0 | 100.0 / 100.0 | 0 |
| E | command | 2 / 2 | 2 / 2 | 194.5 / 194.5 | 50.0 / 50.0 | 50.0 / 50.0 | 0 |
| A–D | baseline | 30 / 26 | 28 / 24 | 237.0 / 237.0 | 23.3 / 26.9 | 43.3 / 42.3 | 0 |
| A–D | command | 30 / 26 | 30 / 26 | 26.5 / 37.0 | 60.0 / 53.8 | 73.3 / 69.2 | 0 |
| A–E | baseline | 32 / 28 | 30 / 26 | 216.5 / 216.5 | 25.0 / 28.6 | 46.9 / 46.4 | 0 |
| A–E | command | 32 / 28 | 32 / 28 | 33.0 / 45.0 | 59.4 / 53.6 | 71.9 / 67.9 | 0 |

### Final common-text sensitivity

Only tokens also present in the saved baseline, all / c > 0.4.

| Set | Path | Common words | Matched | Median ms | Within 80 ms % | Within 200 ms % | Crossings |
|---|---|---:|---:|---:|---:|---:|---:|
| A–D | baseline | 655 / 597 | 655 / 597 | 290.0 / 279.0 | 35.0 / 37.0 | 42.9 / 43.9 | 0 |
| A–D | command | 655 / 597 | 655 / 597 | 161.0 / 153.0 | 40.2 / 40.4 | 54.2 / 54.9 | 0 |
| A–E | baseline | 933 / 766 | 933 / 766 | 392.0 / 349.5 | 26.9 / 31.1 | 33.4 / 37.1 | 0 |
| A–E | command | 933 / 766 | 933 / 766 | 112.0 / 100.0 | 44.2 / 46.1 | 59.3 / 61.1 | 0 |

### Final melody

All voiced reference frames, including missed predictions. Word-confidence filtering leaves these frame metrics unchanged. E has no reference unpitched annotation.

| Song / set | Path | Within 50 cents % | Octave errors % | False unpitched % | Voiced recall % | Broken / held notes | Internal gaps | Missed held |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| A | baseline | 92.0 | 2.2 | 6.9 | 94.6 | 4 / 42 | 10 | 0 |
| A | command | 92.0 | 2.2 | 7.6 | 94.6 | 4 / 42 | 10 | 0 |
| B | baseline | 96.3 | 1.8 | 4.4 | 98.4 | 1 / 69 | 1 | 0 |
| B | command | 96.2 | 1.8 | 4.4 | 98.4 | 1 / 69 | 1 | 0 |
| C | baseline | 99.0 | 0.8 | 15.4 | 100.0 | 1 / 54 | 2 | 0 |
| C | command | 98.8 | 0.8 | 15.4 | 99.8 | 1 / 54 | 2 | 0 |
| D | baseline | 99.2 | 0.0 | 12.6 | 99.2 | 4 / 62 | 10 | 0 |
| D | command | 99.0 | 0.0 | 12.6 | 99.0 | 4 / 62 | 10 | 0 |
| E | baseline | 98.9 | 0.3 | N/A | 99.1 | 5 / 98 | 10 | 0 |
| E | command | 98.9 | 0.3 | N/A | 99.2 | 5 / 98 | 10 | 0 |
| A–D | baseline | 97.0 | 1.1 | 10.1 | 98.3 | 10 / 227 | 23 | 0 |
| A–D | command | 96.9 | 1.1 | 10.4 | 98.2 | 10 / 227 | 23 | 0 |
| A–E | baseline | 97.6 | 0.8 | 10.1 | 98.6 | 15 / 325 | 33 | 0 |
| A–E | command | 97.5 | 0.8 | 10.4 | 98.5 | 15 / 325 | 33 | 0 |

### Final command runtime

Fresh measured wall time per song, including process startup, model inference, hashes, feature extraction, checks and the full scratch trainer build. The scorer is excluded. Internal runtime starts after module imports and scratch setup. This table reports one fresh run per song; earlier campaign times remain in private evidence. No controlled timing study or speedup claim against the historical baseline is made. The historical and replay baseline times above have different scope.

| Song | Wall seconds | Internal seconds | QA flags |
|---|---:|---:|---:|
| A | 156.97 | 153.09 | 741 |
| B | 159.99 | 156.45 | 919 |
| C | 150.98 | 147.85 | 840 |
| D | 138.87 | 136.37 | 1226 |
| E | 279.07 | 274.07 | 1630 |

The final path remains opt-in. Across A–E, final word median error is 138.5 ms
against 470.0 ms, with zero crossing starts. D regresses from 40.5 to 193.5 ms.
The pickup proxy improves in aggregate, with regressions on individual songs.
Fresh melody agrees within 50 cents on 97.5% of voiced reference frames against
97.6% for the saved baseline; false unpitched contour is 10.4% against 10.1%.
Held-note gaps and octave errors remain; the command lists their numeric
candidates for review. These small pitch differences cannot establish absolute
accuracy on the visual reference. Word ordering is valid by construction; its acoustic limitations remain visible in the errors and QA flags. Fresh baseline-model inference is measured here independently of saved baseline replay. The retained melody component does not establish superiority on both required jobs. There is no automatic listening verification, independent recording holdout, reference-library apply, browser test, full-song CPU benchmark or fresh paid transcription/separation evaluation in this campaign. Generic noise annotation is conservative and supplies no scream-identification accuracy claim.

## Boundary refinement: fixed rules and held-out audit

**Keep refinement opt-in. It does not close the autonomous-placement gap.**
Across A–E, raw MMS has 126.6 ms median error, 41.6% within 80 ms and 56.6%
within 200 ms. Boundary refinement gives 145.5 ms, 43.0% and 54.6%; the
per-word baseline fallback gives 145.5 ms, 43.3% and 54.1%. Zero crossings
come from retaining the existing order guard. The ordered-only command gives
138.5 ms, 41.4% and 56.0%. Both refinements fail the requested condition of
improving raw alignment without a clearly worse song.

The command defaults to `--word-refinement none`. Try the experimental step
with `--word-refinement boundary`; `boundary-baseline` adds the measured
per-word fallback. `studio/prepare_song.py --auto-place` remains opt-in under
the specification's rule: neither refinement establishes a reliable word win
on every song, and melody superiority over today's baseline is still unproven
(97.5% versus 97.6% within 50 cents; 10.4% versus 10.1% false unpitched contour).

The implementation in `tools/song_auto/refine.py` consumes the fresh contour,
shared QA features, aligned words and, for the fallback only, the saved before
words. It never reads corrected evaluation starts, contour or unpitched spans.
It reuses `placement.Evidence`; the scorer and placement screen are unchanged.
The following constants were fixed from the written procedure before scoring:

- Search at most 250 ms from an order-repaired aligner start. This is half
  the QA held-note exclusion window and limits a correction to local evidence;
  it supplies no claim that the nearest sign belongs to the right syllable.
- Reuse actual contour transitions, pitch steps of at least 0.8 semitone
  within 150 ms, and onsets at least 0.25 times the full envelope's 99.5th
  percentile. Absent contour supplies no edge. Retained baseline times also
  need a qualified sign within 60 ms, displacement at most 250 ms, and order.
- Reject candidates inside QA's level-note window: finite contour for 250 ms
  each side, within 0.5 semitone of its median. Check the stored millisecond
  time after rounding. A strong burst within that window cannot override it.
- A step additionally needs 80 ms plateaus on both sides, each spanning at
  most 0.5 semitone, and no return to the preceding pitch in the following
  150 ms. This rejects returning vibrato and leaves ambiguous bends unresolved.
- Count syllables from the bundled CMU dictionary's first pronunciation,
  summing compound components. Unknown spellings get no invented count.
  Count phrase segments after gaps of at least 40 ms or qualified steps.
  With a unique exact syllable/segment count and every word assignment in
  reach, use cumulative syllable counts to select each word's first segment.
  This places a multi-syllable word before its last long note and retains a
  compound through the last aligned subword's end. Excess segments, missing
  segments and unknown counts remain in the audit; unresolved multi-syllable
  words and syllable shortfalls are doubtful. Melisma, vowel/formant changes
  and voice identity cannot be established by this count alone.
- Select candidates jointly in lyric order with at least 40 ms between starts,
  first minimizing unsupported starts, then preserving feasible exact-count
  assignments (or the explicit baseline fallback), then minimizing movement.
  Ties select earlier starts. Word ends retain their aligned span, capped at
  the next word. No subsequent projection can shift a selected sign inside
  a level note. If no usable sign is reachable, keep the order-repaired
  aligner start and mark it doubtful; order conflicts also remain doubtful.

`checks.json` contains per-word old/new starts, decisions, doubtful reasons,
word/phrase syllable counts, contour-segment counts and exact-assignment status.
The baseline fallback uses maximum ordered token matches without reference
word times; unmatched baseline text provides no fallback. A boundary alone
never raises acoustic confidence or removes another QA doubt.

Measurement uses the corrected native MMS scores and fresh pYIN + CREPE
output from the five full command runs above. Shared features were recomputed
serially from read-only stems. Raw, ordered, boundary and fallback paths were
rescored with the same scorer; their word-start and pitch metrics match the
previous campaign exactly. Confidence and QA counts below replace the earlier
counts from the double-normalized adapter. Each fixed-rule held-out prediction
is reproduced from these same proposals without tuning on other songs.
All audited input hashes and modification times stay unchanged.

The visual reference was set by eye and never checked by ear. E was corrected
by a smaller model and has many c <= 0.4 words. Every comparison below reports
all / reference c > 0.4 and pooled A–D / A–E. Historical text differences,
missing-token penalties and pickup-proxy limits remain as described above.

The radius, QA thresholds, plateau rule and syllable policy use no fitted
parameters. The held-out audit rotates through A to E: each excluded song's
prediction is reproduced with the same fixed configuration; the other four
songs are unused. Pooled held-out predictions therefore equal the pooled
fixed-rule results. This is the reasoning-fixed alternative to tuning on four
songs; it does not create an independent model-selection or listening test.

### Fixed-rule word starts

All / reference c > 0.4. In the count column each pair is reference / matched. Raw includes unrepaired crossings; boundary and hybrid include the existing order repair. The ordered-only path is reported in the end-to-end tables above.
Crossings cover all predicted starts, including confidence/pickup subsets.
Here `hybrid` means `boundary-baseline`.

| Song / set | Path | Reference / matched | Median ms | Within 80 ms % | Within 200 ms % | Crossings |
|---|---|---:|---:|---:|---:|---:|
| A | baseline | 167 / 84 / 156 / 81 | 1654.0 / 1440.0 | 12.0 / 12.8 | 13.8 / 14.7 | 0 |
| A | raw | 167 / 167 / 156 / 156 | 234.7 / 250.4 | 35.3 / 35.9 | 46.7 / 45.5 | 6 |
| A | boundary | 167 / 167 / 156 / 156 | 278.0 / 279.0 | 34.7 / 34.6 | 44.3 / 43.6 | 0 |
| A | hybrid | 167 / 167 / 156 / 156 | 273.0 / 275.5 | 35.3 / 35.3 | 44.9 / 44.2 | 0 |
| B | baseline | 166 / 143 / 164 / 141 | 575.5 / 583.5 | 2.4 / 2.4 | 10.2 / 9.8 | 0 |
| B | raw | 166 / 166 / 164 / 164 | 85.9 / 85.9 | 48.2 / 48.2 | 69.3 / 69.5 | 4 |
| B | boundary | 166 / 166 / 164 / 164 | 81.0 / 81.0 | 48.8 / 48.8 | 63.9 / 64.0 | 0 |
| B | hybrid | 166 / 166 / 164 / 164 | 92.5 / 92.5 | 47.0 / 47.0 | 61.4 / 61.6 | 0 |
| C | baseline | 203 / 158 / 183 / 142 | 401.0 / 412.0 | 31.0 / 31.1 | 37.4 / 36.6 | 0 |
| C | raw | 203 / 203 / 183 / 183 | 286.1 / 259.1 | 33.0 / 33.9 | 42.9 / 44.8 | 4 |
| C | boundary | 203 / 203 / 183 / 183 | 267.0 / 260.0 | 30.0 / 31.7 | 41.9 / 44.3 | 0 |
| C | hybrid | 203 / 203 / 183 / 183 | 267.0 / 255.0 | 32.0 / 33.9 | 42.4 / 44.8 | 0 |
| D | baseline | 270 / 270 / 233 / 233 | 40.5 / 29.0 | 52.6 / 60.1 | 61.1 / 67.0 | 0 |
| D | raw | 270 / 270 / 233 / 233 | 197.7 / 201.0 | 35.9 / 34.3 | 50.0 / 49.8 | 8 |
| D | boundary | 270 / 270 / 233 / 233 | 209.0 / 208.0 | 38.5 / 39.1 | 49.3 / 49.8 | 0 |
| D | hybrid | 270 / 270 / 233 / 233 | 204.0 / 170.0 | 40.0 / 41.6 | 50.0 / 51.1 | 0 |
| E | baseline | 280 / 278 / 171 / 169 | 595.0 / 478.0 | 7.9 / 9.9 | 11.1 / 12.9 | 0 |
| E | raw | 280 / 280 / 171 / 171 | 69.5 / 46.2 | 53.2 / 65.5 | 71.4 / 83.0 | 6 |
| E | boundary | 280 / 280 / 171 / 171 | 40.5 / 17.0 | 58.2 / 71.3 | 69.6 / 80.7 | 0 |
| E | hybrid | 280 / 280 / 171 / 171 | 40.5 / 21.0 | 57.1 / 70.2 | 67.5 / 77.2 | 0 |
| A–D | baseline | 806 / 655 / 736 / 597 | 422.5 / 416.5 | 28.4 / 30.0 | 34.9 / 35.6 | 0 |
| A–D | raw | 806 / 806 / 736 / 736 | 188.2 / 182.8 | 37.6 / 37.6 | 51.5 / 52.0 | 22 |
| A–D | boundary | 806 / 806 / 736 / 736 | 208.5 / 198.0 | 37.7 / 38.5 | 49.4 / 50.3 | 0 |
| A–D | hybrid | 806 / 806 / 736 / 736 | 208.5 / 197.5 | 38.5 / 39.5 | 49.4 / 50.4 | 0 |
| A–E | baseline | 1086 / 933 / 907 / 766 | 470.0 / 432.0 | 23.1 / 26.2 | 28.7 / 31.3 | 0 |
| A–E | raw | 1086 / 1086 / 907 / 907 | 126.6 / 119.8 | 41.6 / 42.9 | 56.6 / 57.9 | 28 |
| A–E | boundary | 1086 / 1086 / 907 / 907 | 145.5 / 122.0 | 43.0 / 44.7 | 54.6 / 56.0 | 0 |
| A–E | hybrid | 1086 / 1086 / 907 / 907 | 145.5 / 122.0 | 43.3 / 45.3 | 54.1 / 55.5 | 0 |

### Fixed-rule pickup proxy

Same scorer and small reference-defined proxy subset; all / reference c > 0.4.

| Song / set | Path | Reference / matched | Median ms | Within 80 ms % | Within 200 ms % | Crossings |
|---|---|---:|---:|---:|---:|---:|
| A | baseline | 2 / 1 / 2 / 1 | N/A / N/A | 50.0 / 50.0 | 50.0 / 50.0 | 0 |
| A | raw | 2 / 2 / 2 / 2 | 350.4 / 350.4 | 0.0 / 0.0 | 0.0 / 0.0 | 6 |
| A | boundary | 2 / 2 / 2 / 2 | 364.5 / 364.5 | 0.0 / 0.0 | 0.0 / 0.0 | 0 |
| A | hybrid | 2 / 2 / 2 / 2 | 364.5 / 364.5 | 0.0 / 0.0 | 0.0 / 0.0 | 0 |
| B | baseline | 9 / 9 / 9 / 9 | 267.0 / 267.0 | 0.0 / 0.0 | 11.1 / 11.1 | 0 |
| B | raw | 9 / 9 / 9 / 9 | 23.0 / 23.0 | 66.7 / 66.7 | 88.9 / 88.9 | 4 |
| B | boundary | 9 / 9 / 9 / 9 | 0.0 / 0.0 | 88.9 / 88.9 | 88.9 / 88.9 | 0 |
| B | hybrid | 9 / 9 / 9 / 9 | 0.0 / 0.0 | 88.9 / 88.9 | 88.9 / 88.9 | 0 |
| C | baseline | 5 / 4 / 5 / 4 | 209.0 / 209.0 | 40.0 / 40.0 | 40.0 / 40.0 | 0 |
| C | raw | 5 / 5 / 5 / 5 | 558.1 / 558.1 | 40.0 / 40.0 | 40.0 / 40.0 | 4 |
| C | boundary | 5 / 5 / 5 / 5 | 534.0 / 534.0 | 40.0 / 40.0 | 40.0 / 40.0 | 0 |
| C | hybrid | 5 / 5 / 5 / 5 | 534.0 / 534.0 | 20.0 / 20.0 | 20.0 / 20.0 | 0 |
| D | baseline | 14 / 14 / 10 / 10 | 130.0 / 125.5 | 28.6 / 40.0 | 64.3 / 70.0 | 0 |
| D | raw | 14 / 14 / 10 / 10 | 24.5 / 22.7 | 71.4 / 60.0 | 78.6 / 70.0 | 8 |
| D | boundary | 14 / 14 / 10 / 10 | 9.0 / 9.0 | 85.7 / 80.0 | 92.9 / 90.0 | 0 |
| D | hybrid | 14 / 14 / 10 / 10 | 42.0 / 42.0 | 64.3 / 60.0 | 85.7 / 80.0 | 0 |
| E | baseline | 2 / 2 / 2 / 2 | 80.5 / 80.5 | 50.0 / 50.0 | 100.0 / 100.0 | 0 |
| E | raw | 2 / 2 / 2 / 2 | 194.5 / 194.5 | 50.0 / 50.0 | 50.0 / 50.0 | 6 |
| E | boundary | 2 / 2 / 2 / 2 | 197.5 / 197.5 | 50.0 / 50.0 | 50.0 / 50.0 | 0 |
| E | hybrid | 2 / 2 / 2 / 2 | 110.5 / 110.5 | 50.0 / 50.0 | 100.0 / 100.0 | 0 |
| A–D | baseline | 30 / 28 / 26 / 24 | 237.0 / 237.0 | 23.3 / 26.9 | 43.3 / 42.3 | 0 |
| A–D | raw | 30 / 30 / 26 / 26 | 26.5 / 37.4 | 60.0 / 53.8 | 70.0 / 65.4 | 22 |
| A–D | boundary | 30 / 30 / 26 / 26 | 10.0 / 10.0 | 73.3 / 69.2 | 76.7 / 73.1 | 0 |
| A–D | hybrid | 30 / 30 / 26 / 26 | 40.5 / 40.5 | 60.0 / 57.7 | 70.0 / 65.4 | 0 |
| A–E | baseline | 32 / 30 / 28 / 26 | 216.5 / 216.5 | 25.0 / 28.6 | 46.9 / 46.4 | 0 |
| A–E | raw | 32 / 32 / 28 / 28 | 33.0 / 45.1 | 59.4 / 53.6 | 68.8 / 64.3 | 28 |
| A–E | boundary | 32 / 32 / 28 / 28 | 12.0 / 12.0 | 71.9 / 67.9 | 75.0 / 71.4 | 0 |
| A–E | hybrid | 32 / 32 / 28 / 28 | 42.5 / 42.5 | 59.4 / 57.1 | 71.9 / 67.9 | 0 |

### Placement screen and doubtful words

The screen uses each path’s own contour. Counts and percentages use actual predicted starts, so missing reference words do not enter this denominator. Confident subsets contain only exact matched predictions with reference c > 0.4. All / confident. Baseline doubtful counts apply the same end checks to the historical target; its stored original confidence alone is not the count shown.

| Song / set | Path | Predicted starts | No boundary % | Inside level count | Doubtful count |
|---|---|---:|---:|---:|---:|
| A | baseline | 157 / 81 | 32.5 / 27.2 | 14 / 11 | 151 / 76 |
| A | raw | 167 / 156 | 24.6 / 25.0 | 17 / 16 | 167 / 156 |
| A | ordered | 167 / 156 | 27.5 / 26.3 | 16 / 15 | 167 / 156 |
| A | boundary | 167 / 156 | 9.6 / 9.0 | 14 / 13 | 167 / 156 |
| A | hybrid | 167 / 156 | 9.6 / 9.0 | 14 / 13 | 167 / 156 |
| B | baseline | 165 / 141 | 26.1 / 24.8 | 45 / 38 | 147 / 125 |
| B | raw | 166 / 164 | 9.0 / 9.1 | 11 / 11 | 165 / 163 |
| B | ordered | 166 / 164 | 10.2 / 10.4 | 11 / 11 | 165 / 163 |
| B | boundary | 166 / 164 | 3.0 / 3.0 | 7 / 7 | 166 / 164 |
| B | hybrid | 166 / 164 | 3.0 / 3.0 | 7 / 7 | 166 / 164 |
| C | baseline | 208 / 142 | 21.6 / 22.5 | 25 / 19 | 194 / 131 |
| C | raw | 203 / 183 | 21.2 / 21.3 | 27 / 25 | 203 / 183 |
| C | ordered | 203 / 183 | 21.7 / 21.3 | 27 / 25 | 203 / 183 |
| C | boundary | 203 / 183 | 6.9 / 6.6 | 16 / 16 | 203 / 183 |
| C | hybrid | 203 / 183 | 6.4 / 6.0 | 16 / 16 | 203 / 183 |
| D | baseline | 282 / 233 | 23.8 / 20.2 | 28 / 20 | 281 / 232 |
| D | raw | 270 / 233 | 15.2 / 15.0 | 13 / 12 | 270 / 233 |
| D | ordered | 270 / 233 | 17.4 / 17.6 | 13 / 12 | 270 / 233 |
| D | boundary | 270 / 233 | 5.9 / 6.9 | 11 / 11 | 270 / 233 |
| D | hybrid | 270 / 233 | 5.9 / 6.9 | 10 / 10 | 270 / 233 |
| E | baseline | 280 / 169 | 18.2 / 16.0 | 30 / 16 | 269 / 162 |
| E | raw | 280 / 171 | 17.5 / 14.0 | 11 / 3 | 277 / 168 |
| E | ordered | 280 / 171 | 17.1 / 14.0 | 11 / 3 | 277 / 168 |
| E | boundary | 280 / 171 | 2.9 / 0.0 | 10 / 2 | 280 / 171 |
| E | hybrid | 280 / 171 | 2.9 / 0.0 | 10 / 2 | 280 / 171 |
| A–D | baseline | 812 / 597 | 25.4 / 22.8 | 112 / 88 | 773 / 564 |
| A–D | raw | 806 / 736 | 17.4 / 17.4 | 68 / 64 | 805 / 735 |
| A–D | ordered | 806 / 736 | 19.1 / 18.8 | 67 / 63 | 805 / 735 |
| A–D | boundary | 806 / 736 | 6.3 / 6.4 | 48 / 47 | 806 / 736 |
| A–D | hybrid | 806 / 736 | 6.2 / 6.2 | 47 / 46 | 806 / 736 |
| A–E | baseline | 1092 / 766 | 23.5 / 21.3 | 142 / 104 | 1042 / 726 |
| A–E | raw | 1086 / 907 | 17.4 / 16.8 | 79 / 67 | 1082 / 903 |
| A–E | ordered | 1086 / 907 | 18.6 / 17.9 | 78 / 66 | 1082 / 903 |
| A–E | boundary | 1086 / 907 | 5.4 / 5.2 | 58 / 49 | 1086 / 907 |
| A–E | hybrid | 1086 / 907 | 5.3 / 5.1 | 57 / 48 | 1086 / 907 |

### Fixed-rule held-out audit

Each row reproduces one excluded song with identical fixed parameters. The other four songs supply no tuning inputs. Each result cell is median ms; within 80%; within 200%, all / reference c > 0.4. The pooled out-of-fold predictions equal the pooled boundary/hybrid rows above. This tests fixed-rule stability; model choice and the visual reference still come from the original five-song study.

| Held out | Other four (unused) | Raw | Boundary | Hybrid |
|---|---|---|---|---|
| A | B, C, D, E | 234.7 / 250.4; 35.3 / 35.9; 46.7 / 45.5 | 278.0 / 279.0; 34.7 / 34.6; 44.3 / 43.6 | 273.0 / 275.5; 35.3 / 35.3; 44.9 / 44.2 |
| B | A, C, D, E | 85.9 / 85.9; 48.2 / 48.2; 69.3 / 69.5 | 81.0 / 81.0; 48.8 / 48.8; 63.9 / 64.0 | 92.5 / 92.5; 47.0 / 47.0; 61.4 / 61.6 |
| C | A, B, D, E | 286.1 / 259.1; 33.0 / 33.9; 42.9 / 44.8 | 267.0 / 260.0; 30.0 / 31.7; 41.9 / 44.3 | 267.0 / 255.0; 32.0 / 33.9; 42.4 / 44.8 |
| D | A, B, C, E | 197.7 / 201.0; 35.9 / 34.3; 50.0 / 49.8 | 209.0 / 208.0; 38.5 / 39.1; 49.3 / 49.8 | 204.0 / 170.0; 40.0 / 41.6; 50.0 / 51.1 |
| E | A, B, C, D | 69.5 / 46.2; 53.2 / 65.5; 71.4 / 83.0 | 40.5 / 17.0; 58.2 / 71.3; 69.6 / 80.7 | 40.5 / 21.0; 57.1 / 70.2; 67.5 / 77.2 |

### Where the refinement helps and hurts

A's median worsens from 234.7 to 278.0 ms and its 200 ms hit rate falls from
46.7% to 44.3%. B improves median (85.9 to 81.0 ms) while losing 5.4 percentage
points within 200 ms. C improves median (286.1 to 267.0 ms) while losing both
80 ms and 200 ms accuracy. D worsens median (197.7 to 209.0 ms) and remains far
behind today's 40.5 ms baseline. E improves median (69.5 to 40.5 ms) and 80 ms
accuracy, while its 200 ms accuracy falls from 71.4% to 69.6%. The baseline
fallback retains 112 supported baseline starts (A–E: 6, 6, 10, 62, 28). It
does not repair these tradeoffs; B's median becomes 92.5 ms and its
200 ms hit rate falls to 61.4%. These observations also hold as the individual
fixed-rule held-out results, with no song-specific thresholds.

Pickup proxies improve pooled: median 33.0 to 12.0 ms, within 80 ms 59.4% to
71.9%, within 200 ms 68.8% to 75.0%. The tiny individual subsets remain mixed.
The screen also improves: no-boundary starts fall from 189/1086 (17.4%) raw
to 59/1086 (5.4%); level-note starts fall from 79 to 58. Those 58 were retained
unsupported aligner starts. Selected new boundaries never enter a level note.
Fewer screen flags do not establish closer agreement with the visual reference.

The share over 140 ms grows from 49.1% raw to 50.2% refined (50.3% with the
baseline fallback). Over 200 ms grows from 43.4% to 45.4% (45.9% fallback).
After correcting MMS confidence, **1082/1086 words in the default
ordered command remain doubtful after final QA**. Raw proposals give
1082/1086, boundary 1086/1086, and baseline fallback
1086/1086. Native acoustic confidence is below 0.6 on 1016/1086
words before ordering and QA; the previous universal acoustic rejection came
from the adapter defect. High native scores can now pass that gate.
Order repair, refinement ambiguity and other QA reasons still mark words
doubtful. Stored confidence remains an uncalibrated review signal and supplies
no listening verification. About half of starts still lie over 140 ms from
the eye-set, unheard reference; E contains many low-confidence reference
words. The requested unattended placement outcome remains unmet, and the
experimental flags preserve the measured result without changing the default.

## Original implementation verification

All **438 Python tests across 18 files passed** in an isolated scratch export,
with explicit file paths, one process at a time under the heavy-command gate.
This includes 29 benchmark tests, 21 command tests and 13 refinement tests. Browser suites were
outside scope. No test downloads model weights.

Run `python tests/song_auto_bench_test.py`, `python tests/song_auto_test.py`,
`python tests/song_auto_refine_test.py`, and each other Python test file under
`tests/`, using the project’s gate and
an isolated HOME, XDG configuration/data/cache directories and TMPDIR. The
full run used a scratch Python environment borrowing the installed project
dependencies read-only; LUMA_PY retained the main interpreter path. Candidate
and command probes also used scratch environments. No production dependency
was added and the project environment was not installed into or upgraded.

The command tests cover shared compound-token ownership, missing/extra/wrong
subwords, malformed times/confidence, crossing repair, confidence assignment,
audible unpitched spans versus silence and harmonic gaps, exact frame endpoints,
placement/octave/broken/repeat checks and scorer read-back. Real subprocesses
exercise scratch defaults, unique runs, input bytes/mtime and hostile symlink
paths across restarts. Apply tests verify backup before mutation, full package
build and embedded-target equality, failures after each write, missing prior
records, backup failure, stale targets and concurrent writers. Preparation tests
cover the default, opt-in reuse of fresh pitch, manifest/HTML consistency and
cache failure before target publication. One-time provisioning is stubbed.

The refinement tests cover contour edges, inclusive search radius, strong-onset
thresholds, pitch steps, returning vibrato, held-note and rounding exclusions,
compound spans, first syllables, unavailable counts, collision fallback, order
keeping, baseline ownership, doubtful marking, CLI restarts and preparation
option propagation/refusal. Real synthetic audio uses stubbed aligner output
and synthetic pitch fixtures; no inference model is downloaded.

The prior benchmark tests cover common-text matching and missing-word penalties,
confidence/pickup subsets, numeric pitch/unpitched/held-gap metrics, pooling,
chunk seams, output validation, input changes and read-only scratch guards.
The added confidence tests exercise the installed MMS bundle wrapper with a
stub acoustic model and stub weight retrieval, followed by real CTC alignment
and token merging. They cover high and low scores, both sides of the 0.6 gate,
unchanged word times, wildcard preservation, wav2vec2 logit normalization, and
word/span QA that still marks high-score words doubtful. They reproduced the
MMS defect against the previous adapter and passed after the correction.

A separate real-model CPU probe completed the full command on synthetic audio.
The five GPU command runs built real scratch trainers and scored their generated
targets; applying to the reference library and listening remain unverified.

Exact commands, dependency versions, model/input hashes, native outputs,
rescoring records and check logs stay in private evidence. No song mapping,
lyrics, audio, model weights or private paths are included in this change.

## Published synced line anchors: measured

**Keep stored-clock MMS as the word-placement default. Published line anchors
remain an opt-in experiment.** After the matching and window fixes, A and C
complete; B, D and E refuse before inference. On the same completed A/C set,
synced median error is 270.0 ms against 272.0 ms with stored clocks, while the
share within 200 ms falls from 43.5% to 41.6%. Every completed synced word stays
doubtful. The requested autonomous-placement outcome remains unmet.

The question was whether published line starts plus neural alignment inside each
line improve word placement over stored-clock MMS and today's saved preparation.
The scorer in `tools/song_auto/bench/score.py` is unchanged. This is a word-only
comparison: melody is replayed from each saved baseline, with the same contour
for every variant's QA. Fresh pitch inference, listening and full-command runtime
are outside this experiment.

### Source availability and reference limits

On 2026-11-17 the public [LRCLIB API](https://lrclib.net/docs) and private
published-source copies were checked for A to E. Selection used the same artist
and track metadata, a studio recording, and duration within 2 s; live,
instrumental, paused and alternate-edit entries were excluded. The ordinary
studio album was preferred where available; E uses the nearest-duration studio
single entry. No source was selected by its alignment score. Duration and text
agreement cannot prove audio identity; other editions and other lyric services
may differ. Downloaded records, exact source identifiers and hashes stay private.

| Song | Recording duration s | Published duration s | Difference s | Line clocks | Word clocks in file |
|---|---:|---:|---:|---|---|
| A | 217.77 | 218.00 | 0.23 | Yes | No |
| B | 241.56 | 242.00 | 0.44 | Yes | No |
| C | 248.03 | 248.00 | 0.03 | Yes | No |
| D | 222.45 | 222.00 | 0.45 | Yes | No |
| E | 443.73 | 444.00 | 0.27 | Yes | No |

Every selected file contains line clocks only. Direct published word times are
**N/A for A to E**; no word-time accuracy result is inferred from line clocks.

The references were set by eye and never checked by ear. D's saved preparation
and subsequent reference history used published synced timing, favouring synced
comparisons; pooled A/B/C/E below removes D. Published files are also present in
the manual-reference source directories for A, B, C and E, so excluding D does
not establish an independent reference set. All five are selected recordings
already used for model choice. E has many low-confidence reference words.
Every pair below means **all / reference c > 0.4**. Missing baseline words remain
failures under the unchanged scorer. The baseline received its historical text;
aligners and even spacing received the same corrected package text.

References and stems were copied to private scratch before inference. Their
source hashes were checked after measurement; no reference changed and no
saved-after fallback was needed. No library package was written.

### Fixed procedure and command

`--synced-lyrics` adds an external ordinary LRC file to the command and MMS
benchmark. The existing correction reader parses timestamps, empty instrumental
rows and millisecond offsets. Minimum-edit token correspondence follows lyric
order, with the existing 80% exact-token floor, independent of reference word
times. Known spelling and package row grouping survive, including safe reflow
across published rows. Every known token must have a counterpart, every known
row must contain at least one exact token match, and the first and last source
tokens of each mapped row must match exactly. Interior substitutions are allowed within the 80% floor;
missing known words and unsupported row edges refuse before inference. Source-only
rows reserve time and add no words. These checks replace the earlier rule that
attached unmatched words to the preceding span. Repeated-text correspondence
remains a limit of minimum-edit matching. Invalid/out-of-recording clocks and
insufficient room also refuse clearly.
Enhanced word-timestamp files explicitly refuse; none was available in this run.

The original parameters were fixed by reasoning before scoring: 250 ms context,
the 80% exact-token floor and a 30 s inference cap. Review found that giving each
next row early context removed the preceding vocal tail. The fixed rule retains
the preceding interval up to the next start stamp. Early context is available
only for the first timed row or after an explicit empty row establishing an
instrumental gap, and never starts before that gap. Empty and source-only rows
also close the preceding window. A start-only LRC supplies no vocal end, so no
additional padding is inferred between adjacent sung rows. Recording duration
bounds the last window; every crop remains capped at 30 s. Bounds round inward
to milliseconds. The command's existing 40 ms start spacing runs separately
inside each window; starts and ends cannot cross into a neighbour's window.
No song-specific margin, clock shift, source choice by score or threshold fitting
was used. Boundary refinement cannot be combined with synced anchors.

The cached MMS checkpoint was reused read-only, with its built-in alphabet,
star-token mode, sample rate and configuration hashed in private evidence.
Model inference and the noncommercial checkpoint licence remain as documented
above. Fixed word campaign: 2026-11-17 13:31:28–13:34:16 UTC, RTX 3060,
PyTorch/torchaudio 2.10.0+cu128. Runs used one model at a time and two CPU threads.
The stored-clock results reproduce the existing ordered command's word path.
Even spacing begins at the published line start and divides the remaining line
window equally; it has no acoustic confidence and every word is doubtful.

```sh
# SYNCED is a private, recording-matched LRC file; other variables as above.
"$PY" -m tools.song_auto.run "$PKG" --seed-target "$BEFORE" \
  --synced-lyrics "$SYNCED" --scratch "$S/runs" --model-cache "$S/models/torch"
"$PY" -m tools.song_auto.bench.run "$PKG" mms --seed-target "$BEFORE" \
  --ordered-words --synced-lyrics "$SYNCED" --scratch "$S/runs"
# Omit --synced-lyrics for stored-clock MMS; use baseline for saved preparation.
# Use synced-even with --synced-lyrics for the trivial comparison.
```

The LRC input is included in the command and harness input hashes; a file changed
during inference refuses publication/application. The default command and
preparation behaviour remain unchanged. The condition for adding a preparation
input was a clear synced-anchor win; this experiment does not meet it.

### Word starts and doubtful words

All / reference c > 0.4, except the explicitly labelled doubtful count fractions.
B refuses an unsupported published row edge, D has unmatched known words, and E
has a known row without an exact counterpart. Both synced variants refuse on the
same planner checks. No source, text, threshold or margin was adjusted per song
to obtain coverage. A and C cover 370/1086 reference words (34.1%). A–E and
A/B/C/E synced pools are N/A because the method did not produce those complete
sets; A/C is shown for all four variants as the comparison with equal coverage.
Refused runs produce no predictions, crossings or doubtful count.

| Song / set | Variant | Reference words | Matched | Median ms | Within 80 ms % | Within 200 ms % | Crossings | Doubtful/predicted: all ; confident |
|---|---|---:|---:|---:|---:|---:|---:|---|
| A | Saved baseline | 167 / 156 | 84 / 81 | 1654.0 / 1440.0 | 12.0 / 12.8 | 13.8 / 14.7 | 0 | 151/157 ; 76/81 |
| A | MMS stored clocks | 167 / 156 | 167 / 156 | 272.0 / 272.0 | 32.9 / 33.3 | 43.1 / 42.3 | 0 | 167/167 ; 156/156 |
| A | MMS synced lines | 167 / 156 | 167 / 156 | 201.0 / 217.5 | 35.3 / 36.5 | 49.7 / 48.7 | 0 | 167/167 ; 156/156 |
| A | Line times evenly spread | 167 / 156 | 167 / 156 | 213.0 / 205.9 | 22.2 / 23.7 | 47.9 / 49.4 | 0 | 167/167 ; 156/156 |
| B | Saved baseline | 166 / 164 | 143 / 141 | 575.5 / 583.5 | 2.4 / 2.4 | 10.2 / 9.8 | 0 | 147/165 ; 125/141 |
| B | MMS stored clocks | 166 / 164 | 166 / 164 | 88.5 / 88.5 | 48.2 / 48.2 | 68.1 / 68.3 | 0 | 165/166 ; 163/164 |
| B | MMS synced lines | 166 / 164 | Refused | N/A | N/A | N/A | N/A | N/A |
| B | Line times evenly spread | 166 / 164 | Refused | N/A | N/A | N/A | N/A | N/A |
| C | Saved baseline | 203 / 183 | 158 / 142 | 401.0 / 412.0 | 31.0 / 31.1 | 37.4 / 36.6 | 0 | 194/208 ; 131/142 |
| C | MMS stored clocks | 203 / 183 | 203 / 183 | 273.0 / 253.0 | 33.0 / 34.4 | 43.8 / 45.9 | 0 | 203/203 ; 183/183 |
| C | MMS synced lines | 203 / 183 | 203 / 183 | 331.0 / 334.0 | 25.1 / 24.6 | 35.0 / 35.5 | 0 | 203/203 ; 183/183 |
| C | Line times evenly spread | 203 / 183 | 203 / 183 | 345.7 / 304.0 | 16.3 / 18.0 | 33.5 / 35.0 | 0 | 203/203 ; 183/183 |
| D | Saved baseline | 270 / 233 | 270 / 233 | 40.5 / 29.0 | 52.6 / 60.1 | 61.1 / 67.0 | 0 | 281/282 ; 232/233 |
| D | MMS stored clocks | 270 / 233 | 270 / 233 | 193.5 / 194.0 | 36.7 / 35.2 | 50.4 / 50.2 | 0 | 270/270 ; 233/233 |
| D | MMS synced lines | 270 / 233 | Refused | N/A | N/A | N/A | N/A | N/A |
| D | Line times evenly spread | 270 / 233 | Refused | N/A | N/A | N/A | N/A | N/A |
| E | Saved baseline | 280 / 171 | 278 / 169 | 595.0 / 478.0 | 7.9 / 9.9 | 11.1 / 12.9 | 0 | 269/280 ; 162/169 |
| E | MMS stored clocks | 280 / 171 | 280 / 171 | 69.5 / 46.0 | 53.2 / 65.5 | 70.7 / 81.9 | 0 | 277/280 ; 168/171 |
| E | MMS synced lines | 280 / 171 | Refused | N/A | N/A | N/A | N/A | N/A |
| E | Line times evenly spread | 280 / 171 | Refused | N/A | N/A | N/A | N/A | N/A |
| A–E | Saved baseline | 1086 / 907 | 933 / 766 | 470.0 / 432.0 | 23.1 / 26.2 | 28.7 / 31.3 | 0 | 1042/1092 ; 726/766 |
| A–E | MMS stored clocks | 1086 / 907 | 1086 / 907 | 138.5 / 123.0 | 41.4 / 42.8 | 56.0 / 57.2 | 0 | 1082/1086 ; 903/907 |
| A–E | MMS synced lines | 1086 / 907 | N/A (refused B,D,E) | N/A | N/A | N/A | N/A | N/A |
| A–E | Line times evenly spread | 1086 / 907 | N/A (refused B,D,E) | N/A | N/A | N/A | N/A | N/A |
| A/B/C/E | Saved baseline | 816 / 674 | 663 / 533 | 569.0 / 527.5 | 13.4 / 14.5 | 18.0 / 19.0 | 0 | 761/810 ; 494/533 |
| A/B/C/E | MMS stored clocks | 816 / 674 | 816 / 674 | 120.5 / 103.0 | 43.0 / 45.4 | 57.8 / 59.6 | 0 | 812/816 ; 670/674 |
| A/B/C/E | MMS synced lines | 816 / 674 | N/A (refused B,E) | N/A | N/A | N/A | N/A | N/A |
| A/B/C/E | Line times evenly spread | 816 / 674 | N/A (refused B,E) | N/A | N/A | N/A | N/A | N/A |
| A/C (accepted) | Saved baseline | 370 / 339 | 242 / 223 | 538.5 / 535.0 | 22.4 / 22.7 | 26.8 / 26.5 | 0 | 345/365 ; 207/223 |
| A/C (accepted) | MMS stored clocks | 370 / 339 | 370 / 339 | 272.0 / 264.0 | 33.0 / 33.9 | 43.5 / 44.2 | 0 | 370/370 ; 339/339 |
| A/C (accepted) | MMS synced lines | 370 / 339 | 370 / 339 | 270.0 / 270.0 | 29.7 / 30.1 | 41.6 / 41.6 | 0 | 370/370 ; 339/339 |
| A/C (accepted) | Line times evenly spread | 370 / 339 | 370 / 339 | 274.0 / 244.0 | 18.9 / 20.6 | 40.0 / 41.6 | 0 | 370/370 ; 339/339 |

Doubtful counts use the unchanged acoustic/confidence gates and final QA with
the replayed baseline contour. Their denominator is actual predictions, including
unmatched baseline words; the second pair uses only predictions matched to
reference c > 0.4. Counts identify review candidates. Missing reference words
enter accuracy denominators, never doubtful counts.

### Pickup proxy

Same reference-defined pickup-before-held-note proxy and small denominators as
above; every cell is all / reference c > 0.4. Crossings count complete outputs;
all completed outputs have zero crossings. Refusals remain N/A.

| Song / set | Variant | Pickup words | Matched | Median ms | Within 80 ms % | Within 200 ms % |
|---|---|---:|---:|---:|---:|---:|
| A | Saved baseline | 2 / 2 | 1 / 1 | N/A / N/A | 50.0 / 50.0 | 50.0 / 50.0 |
| A | MMS stored clocks | 2 / 2 | 2 / 2 | 350.5 / 350.5 | 0.0 / 0.0 | 0.0 / 0.0 |
| A | MMS synced lines | 2 / 2 | 2 / 2 | 357.5 / 357.5 | 0.0 / 0.0 | 0.0 / 0.0 |
| A | Line times evenly spread | 2 / 2 | 2 / 2 | 164.6 / 164.6 | 0.0 / 0.0 | 100.0 / 100.0 |
| B | Saved baseline | 9 / 9 | 9 / 9 | 267.0 / 267.0 | 0.0 / 0.0 | 11.1 / 11.1 |
| B | MMS stored clocks | 9 / 9 | 9 / 9 | 23.0 / 23.0 | 66.7 / 66.7 | 88.9 / 88.9 |
| B | MMS synced lines | 9 / 9 | Refused | N/A | N/A | N/A |
| B | Line times evenly spread | 9 / 9 | Refused | N/A | N/A | N/A |
| C | Saved baseline | 5 / 5 | 4 / 4 | 209.0 / 209.0 | 40.0 / 40.0 | 40.0 / 40.0 |
| C | MMS stored clocks | 5 / 5 | 5 / 5 | 558.0 / 558.0 | 40.0 / 40.0 | 40.0 / 40.0 |
| C | MMS synced lines | 5 / 5 | 5 / 5 | 570.0 / 570.0 | 40.0 / 40.0 | 40.0 / 40.0 |
| C | Line times evenly spread | 5 / 5 | 5 / 5 | 357.0 / 357.0 | 20.0 / 20.0 | 40.0 / 40.0 |
| D | Saved baseline | 14 / 10 | 14 / 10 | 130.0 / 125.5 | 28.6 / 40.0 | 64.3 / 70.0 |
| D | MMS stored clocks | 14 / 10 | 14 / 10 | 24.5 / 22.5 | 71.4 / 60.0 | 85.7 / 80.0 |
| D | MMS synced lines | 14 / 10 | Refused | N/A | N/A | N/A |
| D | Line times evenly spread | 14 / 10 | Refused | N/A | N/A | N/A |
| E | Saved baseline | 2 / 2 | 2 / 2 | 80.5 / 80.5 | 50.0 / 50.0 | 100.0 / 100.0 |
| E | MMS stored clocks | 2 / 2 | 2 / 2 | 194.5 / 194.5 | 50.0 / 50.0 | 50.0 / 50.0 |
| E | MMS synced lines | 2 / 2 | Refused | N/A | N/A | N/A |
| E | Line times evenly spread | 2 / 2 | Refused | N/A | N/A | N/A |
| A–E | Saved baseline | 32 / 28 | 30 / 26 | 216.5 / 216.5 | 25.0 / 28.6 | 46.9 / 46.4 |
| A–E | MMS stored clocks | 32 / 28 | 32 / 28 | 33.0 / 45.0 | 59.4 / 53.6 | 71.9 / 67.9 |
| A–E | MMS synced lines | 32 / 28 | N/A (refused B,D,E) | N/A | N/A | N/A |
| A–E | Line times evenly spread | 32 / 28 | N/A (refused B,D,E) | N/A | N/A | N/A |
| A/B/C/E | Saved baseline | 18 / 18 | 16 / 16 | 261.5 / 261.5 | 22.2 / 22.2 | 33.3 / 33.3 |
| A/B/C/E | MMS stored clocks | 18 / 18 | 18 / 18 | 66.0 / 66.0 | 50.0 / 50.0 | 61.1 / 61.1 |
| A/B/C/E | MMS synced lines | 18 / 18 | N/A (refused B,E) | N/A | N/A | N/A |
| A/B/C/E | Line times evenly spread | 18 / 18 | N/A (refused B,E) | N/A | N/A | N/A |
| A/C (accepted) | Saved baseline | 7 / 7 | 5 / 5 | 209.0 / 209.0 | 42.9 / 42.9 | 42.9 / 42.9 |
| A/C (accepted) | MMS stored clocks | 7 / 7 | 7 / 7 | 449.0 / 449.0 | 28.6 / 28.6 | 28.6 / 28.6 |
| A/C (accepted) | MMS synced lines | 7 / 7 | 7 / 7 | 446.0 / 446.0 | 28.6 / 28.6 | 28.6 / 28.6 |
| A/C (accepted) | Line times evenly spread | 7 / 7 | 7 / 7 | 174.8 / 174.8 | 14.3 / 14.3 | 57.1 / 57.1 |

### Conclusion and verification

Use stored-clock MMS for the general automatic draft. Synced anchors help A
(272.0 to 201.0 ms), while C worsens from 273.0 to 331.0 ms. B, D and E cannot
safely use the selected files with the known package text. D's saved baseline
remains much better at 40.5 ms. On completed A/C, synced median is 270.0 versus
272.0 ms stored, but 80 ms accuracy falls from 33.0% to 29.7%, and 200 ms accuracy
from 43.5% to 41.6%. The seven pickup words have medians 449.0 ms stored and
446.0 ms synced, with 28.6% within 200 ms for both. This establishes no clear win.
The earlier five-song synced result used unsafe matching and transferred vocal
tails; it is superseded by these fixed-window measurements and explicit refusals.

For completed synced anchors, 233/370 starts (63.0%) are more than 140 ms from
the visual reference, and 58.4% are over 200 ms. The unchanged QA marks
**370/370 words (100%) doubtful**, including 339/339 in the confident-reference
subset. Stored-clock MMS also marks all 370 words doubtful on A/C; across A–E
it leaves 1082/1086 (99.6%) doubtful. Plan to review every completed synced word;
three recordings additionally need a suitable source or manually resolved text.
The synced input stays available for explicit experiments, with clear refusals.
Preparation keeps its existing default and gains no switch from this result.

All **457 Python tests across 19 files passed**, with explicit file paths in an
isolated scratch export, serially under the project gate. The 19 synced tests
cover synthetic audio crops, stub acoustic output, safe row reflow, missing
first/middle/final rows and boundary words, unsupported row edges, interior
substitutions, explicit-gap padding, offsets, window budgets and bounds, word
ends and starts staying inside their line, CLI option refusals, scratch trainer
construction, changed-source detection and real-process restarts. Both command
entry points refuse the review's missing-row/boundary cases before inference.
An audio impulse at 1.90 s stays in the preceding crop and out of the next crop.
The three original reviewer reproductions also pass. Existing command,
refinement, benchmark and all other Python suites passed. Browser suites were
outside scope. No test downloaded weights.

Run `python tests/song_auto_synced_test.py` and each other Python file under
`tests/` with the gate and isolation described in the original verification
section. No production environment or dependency was modified.

Exact commands, UTC bounds, environment versions, checkpoint/configuration and
input hashes, neutral predictions, unchanged-scorer CLI/API outputs, refusals
and QA reports stay in private evidence. Song metadata, lyrics, downloaded files
and weights remain outside the repository.
