# Song quality pass

Run one package at a time from the **repository root**. This procedure checks
words, their placement against the vocal stem, and the contour the singer follows.
The operator requested this pass on 2026-11-16. A small model may perform the
picture review; it must leave uncertain passages for the operator to hear.

## Fences and setup

The library, saved pages, lyrics, exported attempts, reports containing words, and
pictures stay private on the machine. Publish song labels A–D, times and counts.
Do not commit private paths, metadata, lyric lines or screenshots. Do not open a
browser profile. Ask the operator for the Progress tab's history export if an
attempts layer would help; the pass works without it.

All commands below use shell variables supplied for this session:

```sh
P=.venv/bin/python
T=tools/song_qa
# Set PKG to the package directory and S to a private scratch directory outside it.
# Set BASE, WORDS and MELODY to private input files when reviewing an existing pass.
mkdir -p "$S"
uv pip install --python "$P" --target "$S/pylib" -r "$T/requirements.txt"
export PYTHONPATH="$S/pylib${PYTHONPATH:+:$PYTHONPATH}"
export MPLCONFIGDIR="$S/matplotlib" NUMBA_CACHE_DIR="$S/numba" TORCH_HOME="$S/torch"
```

The tool needs the project's Python dependencies plus matplotlib and Pillow for
pictures. It performs no paid requests. Optional forced alignment downloads model
weights on first use; keep them under `TORCH_HOME`. No server or browser is needed
for the mechanical pass.

## 1. Backup and first mechanical pass

```sh
"$P" "$T/run.py" "$PKG" --scratch "$S" --dry-run
```

The final JSON names a fresh output directory. Set `W` to it. The entry command
always reads the original package and writes a copy under scratch. It refuses
nested scratch/package trees and package symlinks. It saves `before/`, computes
features and candidates, draws before windows, generates a timing sheet, applies
provided edits to the copy, rebuilds `trainer.html`, verifies embedded data, draws
after windows, creates paginated sheets and runs the onset spot check. With no
edits, the apply step validates and preserves the copied target. Source file
hashes are checked at the end. `--dry-run` records acceptance intent; both modes
keep the original read-only. Each run has a fresh directory, so old evidence stays.

For an earlier target and approved edits:

```sh
"$P" "$T/run.py" "$PKG" --scratch "$S" --dry-run \
  --base "$BASE" --words "$WORDS" --melody "$MELODY" \
  --recorded-edits "$MELODY"
```

Candidates are computed before apply. `--recorded-edits` is used after detection
for the hit-rate report. It cannot influence a detector. Add `--attempts "$HISTORY"`
for a trainer export; without it windows omit the green layer. `attempts.py`
decodes `luma.history.v1`, filters by source ID, and places traces at
`run.a + (segment.t0 + frame * hop) * speed`. It keeps confident, audible frames.
The export already contains microphone timing correction; no extra latency or
octave folding is applied.

## 2. Verify the words

1. Identify the recording using the private manifest and audio metadata. Compare
   the exact recording duration against a synced source. Avoid substituting a
   live, shortened or alternate version.
2. Save at least two independent lyric sources locally and keep their originals.
   Extract known containers or explicitly select a container in another layout:

```sh
"$P" "$T/extract_lyrics_html.py" "$PAGE" "$TEXT"
"$P" "$T/extract_lyrics_html.py" "$PAGE" "$TEXT" --attribute id --value lyrics
"$P" "$T/compare_sources.py" "$W/package" "first=$TEXT" "second=$OTHER_TEXT"
```

An unknown/empty HTML layout refuses. Inspect the saved page and select the
actual lyric container, or transcribe it locally. The comparison normalizes curly
apostrophes and excludes bracketed/parenthesized echoes. Compare again with
`--include-echoes` and judge each backing answer against the lead stem. Counts and
index ranges identify disagreements without printing text; inspect private files.

3. Write `verified.txt`: one sung line per row, repeats written in full, no section
   labels. Write `synced.lrc` with the **same nonempty lines in the same order**.
   Empty timed LRC rows may mark vocal-window endings. Reflow text to the synced
   boundaries without adding/dropping tokens. Never pad with invented words or
   zip mismatched row counts. If the grouping remains doubtful, omit forced
   alignment and use the existing word sheet plus pictures.
4. If stored words already equal the verified text, retain the current target as
   the base and skip lyric rewriting and metadata changes. Still inspect timing.
5. For incorrect text, work on the scratch package. Correct artist metadata only
   when independently verified, before lyric correction (it changes the source
   cache identity):

```sh
"$P" "$T/set_artist.py" "$W/package" "$VERIFIED_ARTIST" --dry-run
"$P" "$T/set_artist.py" "$W/package" "$VERIFIED_ARTIST"
"$P" studio/lyrics_text.py "$W/package" --text "$VERIFIED" --synced "$SYNCED" --dry-run
"$P" studio/lyrics_text.py "$W/package" --text "$VERIFIED" --synced "$SYNCED" --no-html --json
cp "$W/package/target.json" "$S/base.json"
```

Inspect a refusal at its timestamp. Fix the source or clock after checking the
picture; never force acceptance. Keep the published LRC separately. Without a
reliable synced clock for unpitched singing, leave the passage for the operator.
The single entry command runs mechanical steps; it does not decide lyrics or
fetch sources. The base for subsequent edits is the corrected target above.

## 3. Pictures, candidates and timing sheet

```sh
"$P" "$T/features.py" "$W/package" "$S/features.npz"
"$P" "$T/candidates.py" "$W/package" "$S/features.npz" "$S/candidates.json"
"$P" "$T/onsets.py" "$S/features.npz"
# Optional proposal; requires matching text/LRC rows and model weights:
"$P" "$T/fa_align.py" "$W/package" "$VERIFIED" "$SYNCED" "$S/fa.json"
"$P" "$T/make_sheet.py" "$S/base.json" > "$S/words.txt"
"$P" "$T/draw_windows.py" "$W/package" "$S/features.npz" "$S/windows" --step 12
# Add --fa "$S/fa.json" and/or --sung "$W/attempts.json" when present.
```

Read **every** window, including repeats and the last partial window. Each 12 s
window has two strips with 0.1 s ticks. The upper panel is the log-frequency stem
spectrum; cyan solid and white dashed lines are confident/draft contour. Yellow
marks are word starts/ends; white brackets are lyric lines. The middle panel
shows spectral onset flux (white), broadband level (green), and 4–10 kHz energy
(orange); red ticks have candidate numbers. The lower panel shows the contour
and derived note bars. Optional magenta marks are forced alignment, and green
dots are exported attempts. Neither proposal is ground truth. The final window
is clipped to audio duration and unused rows retain the dark page background.

Change **only what the picture shows without doubt**. List everything else with
start/end times, the competing readings, and what the operator should hear.

Word-start signs:

- Stops and voiceless consonants show a short fundamental dip, burst in the white
  curve, or rise in orange before the vowel. Place the consonant at that burst.
- Voiced consonants and vowels may start on a pitch step, scoop or change of
  partial brightness with continuous energy. Count syllables against the steps.
- A final word extends through the held vowel; noise after its partials fade is
  a breath. A legato word may have no separate energy onset.
- A scream has broadband bursts/formants without a harmonic ladder. Count
  syllable bursts; mark uncountable starts doubtful.
- For repeated lines, measure the stem offset on several strong bursts, then
  inspect each repeat. Review `repeat` candidates even when the LRC looks tidy.

The generated word sheet uses `index word = =`: these rows preserve the original
start, end and confidence. Change just the rows supported by the picture. Use
seconds for exact times, `~seconds` for an eye estimate snapped within 70 ms, or
`o123` for an onset index printed by `onsets.py`. An omitted end uses a level drop
or ends just before the next word. `?` marks doubtful placement at confidence 0.4;
blank rows begin a lyric line. Word order/text must match the base. If snaps
collide, both involved estimates fall back to their supplied eye times and are
reported under `collisions`. If those still collide, apply refuses: re-read the
picture and enter distinct exact times. Never shift unrelated words to make room.

## 4. Numeric candidates and contour edits

The detectors print time spans and heuristic confidence 0–1, and write JSON.
These numbers rank places to inspect; they have no calibrated probability.

| Candidate | Evidence to confirm in the picture | Edit |
|---|---|---|
| `octave` | Spectrum supports half/double pitch; compare the lowest bright partial, odd partials and the surrounding phrase | `octave`, shift ±12, `lo`/`hi` restricting affected frames |
| `unpitched` | Audible stem energy with weak periodicity/harmonic concentration; inspect for scream, shout, breath, band noise or stem leakage | `clear`, explicit `kind: scream` or `kind: noise` when established |
| `broken` | A supported fundamental continues through a missing contour run or after its end | `fill`, pitch `m` and search tolerance `tol` read from partials |
| `repeat` | Repeated text aligns inconsistently with the stem energy pattern in surrounding context | correct supported word rows; inspect variations separately |

Octave checks use a six-partial spectral comb and odd/even partial evidence;
phrase context ranks confidence after spectral disagreement. Neighbour pitch
alone supplies no octave verdict. Unpitched checks use energy, autocorrelation
and harmonic concentration. A noise band can resemble a tone and a rough vowel
can resemble noise. Broken-note checks search a local pitch band near flanking
contour frames and include short intervening fragments on another partial; distant runs can be missed. Repeat checks correlate the stem's
100 ms energy envelope across ±2.5 s around repeated lines. Shared three-word
prefixes also find repeats whose alignment split the occurrences into different rows. Two identical words
in different musical settings can disagree legitimately. A coherent late section
or a different arrangement can defeat that reference. These remain visual tasks.

Write a private JSON list, for example:

```json
[
  {"op":"octave","a":1.2,"b":1.8,"shift":-12,"lo":75,"hi":83},
  {"op":"clear","a":2.0,"b":2.8,"kind":"scream"},
  {"op":"fill","a":3.0,"b":3.4,"m":60,"tol":1.2}
]
```

A plain `clear` can remove a second voice or pad without marking it unpitched.
Use `kind` explicitly for screams/noise; do not infer it from prose `why`. A kind
requires clearing the whole pitch range. The containing 20 ms grid cells are
cleared at a fractional-frame boundary so no derived note intersects the span. Kinds are `scream` and `noise`; optional
`why` explains the observed sign and stays in the private report. A fill searches
the stem inside `m ± tol`, stores draft frames, and reports `at_band_edge`. Above
about 0.2, inspect and adjust the search band. `over: true` replaces existing
frames too and requires clear visual evidence for each such replacement.

```sh
"$P" "$T/apply_edits.py" "$W/package" "$S/features.npz" --base "$S/base.json" \
  --words "$S/words.txt" --melody "$S/melody.json" --report "$S/apply-report.json" --dry-run
# After inspecting that report, repeat without --dry-run on this scratch copy.
"$P" "$T/finish_song.py" "$W/package" "$S/trainer.html"
"$P" "$T/draw_windows.py" "$W/package" "$S/features.npz" "$S/after" --step 12
"$P" "$T/sheets.py" "$S/after" "$S/sheets"
"$P" "$T/check_onsets.py" "$W/package" --n 28 --tol 0.08
```

Each apply begins from its base, validates before replacing `target.json`, and
backs up existing records in content-addressed `.song-qa-backups/` siblings.
Keep the original base immutable for repeatable edits. Metadata changes retain
backups of target and manifest before either is written; restore both together
if a later write fails. Notes follow `prepare_song.build_map`: median of five
frames, split beyond 0.72 semitones from the rounded current note, minimum four
frames per note, `ok` at 55% reliable frames. Runs shorter than five frames are
removed. Phrases, metrics and initial time are derived again. The tool writes
optional `unpitched` data; renderer changes are separate work.

The onset check uses level rises independently of spectral-flux snapping.
Inspect outliers and words with no rise; do not equate this proxy with accuracy.
Compare after pictures with before and confirm the rebuilt embedded target equals
the package. Keep resulting packages in scratch for review; replacing the private
library is a separate operation that requires its owner's authorization and backup.

## Optional real-trainer screenshots

`shoot_trainer.mjs` and `contact_sheets.py` retain the original screenshot overlay
workflow. Use a fresh profile in a **short private scratch path** (the script
refuses paths too long for Chromium sockets), never an existing browser profile.
Serve the rebuilt HTML as `/qa/trainer.html` from an isolated local static server,
outside the activity logger's `/song/`, `/demo` and `/` routes. Set `NODE` to the
project-supported Node executable; it must report no `process.versions.bun`.

```sh
"$NODE" "$T/shoot_trainer.mjs" "$QA_URL" "$S/shots" --profile-root "$SHORT_SCRATCH"
"$P" "$T/contact_sheets.py" "$S/shots" "$S/features.npz" "$W/package/target.json" "$S/contacts"
```

The screenshot tool turns off activity logging before page code, blocks network
writes, and refuses a logger-active route. A plain static server has no activity
write handler. Stop just the server PID you started. Omit this optional workflow
when a short scratch profile is unavailable; ordinary windows need no browser.

## Report and acceptance

Keep a private report with the following table and a time-indexed doubtful list.
A visual pass remains unverified by ear until the operator checks it.

| Item | Before / after or result |
|---|---|
| Words / lines; inserted, changed, dropped | counts |
| Words moved >20 ms; median/largest shift | counts and seconds |
| Snaps / eye times / collisions; doubtful starts | counts |
| Melody filled / octave-corrected / removed | seconds and time ranges |
| Scream / noise spans | count, kind, times |
| Notes / confident notes; unchanged notes | counts |
| Repeat outliers and disposition | times, offset, evidence |
| Onset check within 80 ms / measured / no rise | counts |
| Target validation / embedded equality / source unchanged | checks |
| Candidate recall by category / total; candidate counts | numerator/denominator |
| Uncertain passages | times and reason for operator review |

For benchmark recall, each recorded `octave`, `clear`, and `fill` is one event.
A hit requires at least 80 ms overlap, or half a shorter edit; octave direction
must match and a fill must be within two semitones. Every recorded clear enters
the removal denominator, including pitched clutter a reviewer removed. A removal
can match an unpitched candidate or a broken-note candidate that locates a pitched
interruption; the reference edits predate explicit scream/noise kinds. The table
therefore reports diagnostic event coverage, with the contributing candidate types
recorded separately. It does not claim every removal is unpitched. Report
misses explicitly. A category with no reference events is N/A. Report candidate
counts alongside recall: high recall alone does not establish precision or
whole-span coverage. The four private packages are labelled song A–D, ordered by
package directory name locally; their mapping stays private.

Run the Python tests using explicit paths and the project's check wrapper in an
isolated scratch export. The new suite is `tests/song_qa_test.py`; browser suites
are unaffected. Retain the revision, command, environment dependency versions,
run time bounds, check results and per-song recall in local evidence. Public
reports carry the aggregate table and repository-relative file references only.
