# Song auto-placement: measured model choice (step 1)

Choose **MMS for word proposals** and retain **pYIN + CREPE for melody**. The
future placement path stays opt-in: neither alternative pitch configuration
beats the saved baseline on the required combination of pitch and unpitched
metrics.

This page covers the model benchmark for the future one-command placement tool.
The benchmark entry point is `python -m tools.song_auto.bench.run`. Preparation,
application, backups and trainer rebuilding are the subsequent implementation
steps. The existing preparation path is unchanged by this step.

## Reference and measurement limits

The accuracy numbers below measure agreement with five targets edited by eye from
spectrograms on 2026-11-16. Nobody verified these targets by ear. Song E was
edited by a smaller model and contains many words with reference confidence
`c <= 0.4`. Every word table therefore gives all words and `c > 0.4` separately;
pooled results give both A–D and A–E. Filtering word confidence leaves pitch
metrics unchanged: word confidence supplies no frame-level pitch annotation.

These are five selected, difficult recordings, with no independent holdout.
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
Independent published line clocks are not used.
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
MMS therefore supplies the word proposal engine for the next implementation step.

**MMS is insufficient for an unconditional replacement.** It has 28 crossing
starts across A–E. Song D's overall median regresses from 40.5 to 197.7 ms, and
some individual pickup subsets regress too. The subsequent command must report
and handle invalid order and doubtful spans, and its guarded output must be
measured again. The measurements here cover raw proposals, with no repaired
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

Steps 2–4 still need the production entry command, target/notes/unpitched output,
confidence assignment, deterministic QA list, apply backups and full trainer
build, and preparation integration. The existing preparation default stays in
place because the required improvement on both jobs has not been demonstrated.
Tests for this step cover the neutral benchmark and scorer; apply/backup tests
belong with that subsequent writer.

## Verification

All **401 Python tests across 16 files passed**, including 26 new benchmark
tests. The existing 105-CLI lyric regression case was run separately with a
longer timeout after both branch and base hit the same 240 s wrapper limit;
that case and the remaining lyric cases passed. Browser suites were outside
this step's scope.

Run each Python test file explicitly in an isolated scratch export using the
project's heavy-command wrapper. The new suite is
`python tests/song_auto_bench_test.py`; it uses synthetic audio and stubbed
acoustic/pitch outputs and downloads no model. It covers ordered compound-token
ownership, optimal repeated-text matching, missing-word penalties, confidence
subsets, pickup subsets, numeric thresholds, octave and unpitched metrics,
single-frame held-note gaps, empty/reference-absent cases, weighted pooling,
chunk seams, output validation and real-process scratch guards across restarts.
The baseline writer's output is read back through the real scoring CLI; input
bytes and modification times are checked across repeated processes.
An injected source change also verifies that the harness refuses to publish
output from inputs that changed during a run.

Exact commands, dependency versions, model/input hashes, native outputs,
rescoring records and check logs stay in private evidence. No song mapping,
lyrics, audio, model weights or private paths are included in this change.
