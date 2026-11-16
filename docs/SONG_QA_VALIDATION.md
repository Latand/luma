# Song QA validation

Verified 2026-11-16 with Python 3.11.13 in an isolated scratch export of the final lane source.
The final acceptance campaign ran from 2026-11-16T14:13:40.013385+00:00 to 2026-11-16T14:18:34.210347+00:00.
Exact source fingerprints, dependency versions, commands, frozen references, logs, reports and images are retained in private evidence.
The procedure is [SONG_QA.md](SONG_QA.md).

Song D names the reviewed fourth-song run. The earlier report used directory order;
this report uses the retained revised private mapping for all tables.

## Four-package acceptance

The entry command ran from the scratch repository root for each package:

```sh
"$P" tools/song_qa/run.py "$PKG" --scratch "$S" --dry-run \
  --base "$BASE" --melody "$MELODY" --recorded-edits "$MELODY" \
  --synced "$SYNCED"
# Song D also supplies --review "$SPANS".
```

All four runs passed. Source hashes remained unchanged; targets validated and rebuilt HTML embedded the same target.
There are 80 windows per version (160 total), plus sheets, candidate lists and both placement reports.
These runs apply frozen melody references to copies of saved bases. They preserve the bases' word times;
the separate song D comparison below reads the actual saved small-model and reviewed targets.
A legacy word sheet with a different base word count remains outside this acceptance command;
word application and refusal are exercised by synthetic tests.

| Song | Octave | Removals | Held fills | Event coverage |
|---|---:|---:|---:|---:|
| song A | 3/3 | 10/10 | 3/3 | 16/16 |
| song B | 3/3 | 6/6 | 2/2 | 11/11 |
| song C | 2/2 | 8/8 | 1/1 | 11/11 |
| song D | N/A | 6/6 | 4/4 | 10/10 |

All 48 reference events are located. A hit requires 80 ms overlap (half a shorter edit), matching octave direction and fill pitch within two semitones.
Removals can match unpitched or broken-note candidates. Unpitched alone finds 7/8 clears in song C; the remaining pitched interruption is found by the held-note detector.
The latest reviewed song D melody references also score 10/10 against independently generated candidates.
These figures measure event coverage. Thresholds use the pilot data; precision, complete-span coverage and held-out accuracy are unmeasured.

| Song | Octave | Unpitched | Broken | Repeat | Parallel harmonics | Starts without boundary / words (saved base) |
|---|---:|---:|---:|---:|---:|---:|
| song A | 107 | 110 | 129 | 1 | 10 | 24/167 |
| song B | 183 | 200 | 152 | 2 | 29 | 34/166 |
| song C | 86 | 180 | 145 | 1 | 22 | 33/203 |
| song D | 161 | 218 | 241 | 2 | 32 | 67/282 |

Parallel-harmonic candidates can also describe chords or leakage. Their voice identity requires picture review.
All candidates are proposals; the helper changes no target.

## Song D review comparison

Unchanged tokens are matched in order between the saved small-model output and reviewed target.
Of 100 starts moved by more than 20 ms, 48 receive a new word-start flag.
Within the first 26 s this is 1/4 moved starts.
The full flagged and missed time lists stay private. Flags can overlap: 43 moved starts lack a boundary,
21 lie inside level contour, and 6 fall in supplied scream spans.
The comparison has 12 unmatched small-model tokens after the response-line removals.

| Screen | Saved small-model output | Reviewed target |
|---|---:|---:|
| Words | 282 | 270 |
| Starts without boundary | 65 (23.05%) | 37 (13.70%) |

Both missing-boundary and level-note flags need a disposition even below the 20% screen threshold.
Every supplied scream start is doubtful; legato vowel changes need the picture.

| Reviewed location | New report and limit |
|---|---|
| First word | Earliest burst/harmonic proposal 0.197 s, published stamp 1.82 s, displacement -1.623 s; confirm moving formants |
| Cut held end | No held-word-tail flag; the existing broken-note detector locates the 1.60–3.44 s fill; the reviewed end is 3.44 s |
| Pad/chord stretches | 3.44–8.56 s at 0.586/s and 11.42–16.40 s at 0.402/s, both sparse/hopping; inspect simultaneous partials |
| Responses | See measured slots below; unmatched stored rows are separately flagged from the synced source |
| Screams | 6 word starts flagged in reviewer-supplied spans at 72.06–75.70, 144.05–148.70 and 200.25–204.00 s; syllable arcs still require visual reading |
| Intro clock conflict | Difference -1.62 s is flagged; a nearby contour/onset sign keeps the strict R4 decision at `keep_nearest_sign` |

| Response slot | Strong onsets/s | Segments / counted syllables | Room | Report |
|---|---:|---:|---|---|
| 12.90–14.70 s | 0.556 | 3/5 | yes | `exclude_if_absent_from_synced` |
| 91.90–92.40 s | 0.000 | 1/5 | no | `exclude_if_absent_from_synced` |
| 96.10–97.40 s | 0.769 | 6/5 | yes | `inspect_independent_lead` |

Counted spans and syllables are explicit private review inputs. They are not automatic voice or pronunciation labels.
The response slot at 91.9–92.4 s needs 0.75 s for five syllables and has only 0.5 s.
At 96.1–97.4 s the arithmetic accepts six contour segments for five syllables; it does not reject the response the review removed.
Those tracking fragments require a visual check of the continuing lead partial before accepting an independent articulation.
The first intro conflict illustrates a remaining limit: the raw contour can supply an internal edge near the stamp.
The clock helper conservatively keeps a nearby sign; the independent intro/phrase review is needed to identify the first word.
Segment candidates can include tracking fragments and scoops. Review their count against the spectrum before using a clock override.
The numeric flags cover only part of the reviewed start changes; every phrase and its first repeat still requires R1.

## Verification

357 Python tests passed with zero skips: 302 existing tests, 38 QA tests, and 17 placement tests.
All 13 test files ran sequentially through the heavy-command wrapper with isolated home/config/temp directories and distinct test ports.
Both focused QA suites passed in the final run (55 tests).
The project virtual-environment interpreter path was preserved.

The focused suites are `tests/song_qa_test.py` and `tests/song_qa_placement_test.py`.
They cover synthetic harmonic audio, weak ticks, boundary thresholds, short pickups, density bands,
held tails, synced-clock witnesses and refusal, response room/articulation and continuous-lead veto,
parallel harmonics, scream starts, movement auditing, source matching, malformed inputs, CLI output refusal and source immutability.
The entry test checks both placement outputs and forwards counted spans and synced rows.

`git diff --check` and publication scans of proposed files, commit text and PR body passed.
The scan checks private package metadata, lyric lines, paths and identities. No project publication-check command exists.
Node and browser sources were unchanged; browser suites, optional model alignment and real-trainer screenshots were outside this run.
Ordinary windows require no browser or profile.

## Review regressions

Seven focused regression tests cover the seven review findings:

| Finding | Verification |
|---|---|
| Already-correct lyrics | Executes the documented shared snapshot, sheet, apply and rebuild commands from fresh synthetic scratch |
| Self-closing HTML | Built-in and selected containers retain all three lines after ordinary/self-closing breaks and images; void containers refuse |
| Low/high target pitches | Real candidate CLI accepts schema-valid MIDI 24, 96 and 108 packages with gaps, preserving all source files |
| Reviewed timing origin | Explicit timing replaces the energy origin; the placement screen no longer calls it unplaced; untouched rows retain every value |
| Fractional refill | Real apply CLI fills through 0.907 s with consistent full-frame annotation coverage, validates and retains both remaining noise spans plus a backup |
| Unsupported alignment letters | Mismatched non-Latin rows refuse; matching unsupported, mixed and empty rows refuse before audio/model imports; supported words remain present |
| Boundary labels | Pixel bounds fit inside full and partial strips while word-start markers retain their original times |

The held-note detector searches its cached MIDI 36–90 grid. An anchor with no
intersecting band supplies no held-note candidate; its contour still needs the
picture review. Annotation edits cover whole selected 20 ms frames, including
the complete final filled frame. Optional model weights were not loaded.

Fresh default-size renders of the reported song C/D windows and both final
partial windows measured 197 labels with zero clipping. The single-tick final
strip is covered by the focused regression. Visual inspection confirmed the
boundary word and edge ticks are readable; the final partial window stays dark.
