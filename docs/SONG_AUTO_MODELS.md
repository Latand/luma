# Song auto-placement: offline command and measured model choice

Choose **MMS for word proposals** and retain **pYIN + CREPE for melody**. The
placement path stays opt-in: neither alternative pitch configuration
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
This option does not change preparation's optional Soniox recognition or Demucs
download behaviour. The existing-package command itself uses no paid service.
Preparation remains opt-in because superiority on both required components
has not been demonstrated.

## End-to-end command measurements

GPU campaign: 2026-11-16 19:02:15–19:17:09 UTC, RTX 3060 (12 GB), PyTorch/torchaudio 2.10.0+cu128, two CPU threads, cached weights. One fresh command process per song, sequentially. Each command computed MMS words, fresh pYIN + CREPE pitch, features, QA and a full scratch trainer build. All five actual output files passed the step 1 scoring CLI. Both hashes and modification times of the audited package files stayed unchanged.

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

Single measured wall time per song, including process startup, model inference, hashes, feature extraction, checks and the full scratch trainer build. The scorer is excluded. Internal runtime starts after module imports and scratch setup. There are no repeated full-song timings or speedup claims against the historical baseline. The historical and replay baseline times above have different scope.

| Song | Wall seconds | Internal seconds | QA flags |
|---|---:|---:|---:|
| A | 140.46 | 137.39 | 759 |
| B | 149.60 | 147.11 | 949 |
| C | 156.49 | 153.15 | 880 |
| D | 158.24 | 155.47 | 1271 |
| E | 284.78 | 280.10 | 1679 |

The final path remains opt-in. Across A–E, final word median error is 138.5 ms
against 470.0 ms, with zero crossing starts. D regresses from 40.5 to 193.5 ms.
The pickup proxy improves in aggregate, with regressions on individual songs.
Fresh melody agrees within 50 cents on 97.5% of voiced reference frames against
97.6% for the saved baseline; false unpitched contour is 10.4% against 10.1%.
Held-note gaps and octave errors remain; the command lists their numeric
candidates for review. These small pitch differences cannot establish absolute
accuracy on the visual reference. Word ordering is valid by construction; its acoustic limitations remain visible in the errors and QA flags. Fresh baseline-model inference is measured here independently of saved baseline replay. The retained melody component does not establish superiority on both required jobs. There is no automatic listening verification, independent holdout, reference-library apply, browser test, full-song CPU benchmark or fresh paid transcription/separation evaluation in this campaign. Generic noise annotation is conservative and supplies no scream-identification accuracy claim.

## Verification

All **422 Python tests across 17 files passed** in an isolated scratch export,
with explicit file paths, one process at a time under the heavy-command gate.
This includes 26 benchmark tests and 21 command tests. Browser suites were
outside scope. No test downloads model weights.

Run `python tests/song_auto_bench_test.py` and `python tests/song_auto_test.py`,
and each other Python test file under `tests/`, using the project’s gate and
an isolated HOME, XDG configuration/data/cache directories and TMPDIR. The
full run used the existing project Python and read-only dependencies; candidate
and command probes used a separate scratch environment. No production dependency
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

The prior benchmark tests cover common-text matching and missing-word penalties,
confidence/pickup subsets, numeric pitch/unpitched/held-gap metrics, pooling,
chunk seams, output validation, input changes and read-only scratch guards.
A separate real-model CPU probe completed the full command on synthetic audio.
The five GPU command runs built real scratch trainers and scored their generated
targets; applying to the reference library and listening remain unverified.

Exact commands, dependency versions, model/input hashes, native outputs,
rescoring records and check logs stay in private evidence. No song mapping,
lyrics, audio, model weights or private paths are included in this change.
