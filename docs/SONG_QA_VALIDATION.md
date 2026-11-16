# Song QA validation

Verified 2026-11-16 with the project Python 3.11.13 environment in a scratch export, based on `b030b9d6`. The procedure is [SONG_QA.md](SONG_QA.md). The local evidence retains source fingerprints, frozen references, command drivers, logs and images.

The entry command was run from the scratch repository root for each private package:

```sh
"$P" tools/song_qa/run.py "$PKG" --scratch "$S" --dry-run \
  --base "$BASE" --melody "$MELODY" --recorded-edits "$MELODY"
```

The source packages remained read-only. Melody edits were applied to copies; each target validated, rebuilt HTML embedded the same target, and before/after windows, sheets and onset reports completed. One private reference word sheet had a different count from its saved base and was refused as designed in an earlier run. The acceptance command above omits word edits; the synthetic tests exercise word application and refusal.

| Song | Octave | Unpitched candidates / recorded clears | Held-note fills | Diagnostic coverage |
|---|---:|---:|---:|---:|
| song A | 3/3 | 10/10 | 3/3 | 16/16 (100%) |
| song B | N/A | 6/6 | 4/4 | 10/10 (100%) |
| song C | 3/3 | 6/6 | 2/2 | 11/11 (100%) |
| song D | 2/2 | 7/8 | 1/1 | 11/11 (100%) |

The remaining clear in song D removes a pitched interruption and is located by the held-note detector. Diagnostic coverage accepts an unpitched or broken-note candidate for a removal. A hit needs 80 ms overlap (half the interval for a shorter edit); octave direction must match and fill pitch must be within two semitones. These are event hits, with no claim of complete span coverage. Thresholds were developed on this same pilot; precision and held-out accuracy remain unmeasured. Candidates require picture review and never become edits automatically.

| Song | Octave candidates | Unpitched candidates | Held-note candidates | Repeat outliers | Windows per version |
|---|---:|---:|---:|---:|---:|
| song A | 107 | 110 | 129 | 1 | 19 |
| song B | 161 | 218 | 241 | 2 | 19 |
| song C | 183 | 200 | 152 | 2 | 21 |
| song D | 86 | 180 | 145 | 1 | 21 |

The repeated-section outlier previously described as roughly 1.4 seconds late is listed in the private candidate report for picture review.

| Python check (explicit file path) | Tests | Result |
|---|---:|---|
| `tests/audio_stems_test.py` | 9 | PASS |
| `tests/lan_proxy_test.py` | 10 | PASS |
| `tests/lyrics_align_test.py` | 30 | PASS |
| `tests/lyrics_synced_test.py` | 95 | PASS |
| `tests/lyrics_text_test.py` | 85 | PASS |
| `tests/phonemes_test.py` | 12 | PASS |
| `tests/pitch_quality_test.py` | 12 | PASS |
| `tests/retranscribe_song_test.py` | 7 | PASS |
| `tests/separation_test.py` | 6 | PASS |
| `tests/studio_test.py` | 22 | PASS |
| `tests/video_test.py` | 14 | PASS |
| `tests/song_qa_test.py` | 32 | PASS |

334 Python tests passed, including 32 new QA tests. The existing Python suites ran sequentially through the project heavy-command wrapper with isolated home/config/temp directories; the QA suite was rerun after final input-validation changes.

`node --check tools/song_qa/shoot_trainer.mjs`, Python source compilation, `git diff --check`, and a publication scan for private names, lyric lines, paths and emails passed. The Node runtime had no Bun version. No repository publication-check command exists; the local privacy scan covered the proposed files and publication text. Browser suites were outside scope. The optional model-download forced alignment and real-browser screenshot workflows were not executed.
