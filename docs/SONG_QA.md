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
after windows, creates paginated sheets and runs the all-word placement screen
before and after edits, plus the onset spot check. With no
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
for a trainer export; without it windows omit the green layer. Add `--synced "$SYNCED"`
for published-clock comparisons and `--review "$S/spans.json"` for counted phrase,
intro, response and scream spans described below. The placement screen reports
word indices and times in `placement-before.json` and `placement-after.json`.
`attempts.py`
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

Before including each echo, response or backing row, apply **R5**. Use the slot
between neighbouring lead words, count its syllables, and measure it with the
placement helper. Require at least **0.15 s per syllable**, plus **1.5 strong
onsets/s** or one contour segment per syllable. An unbroken preceding lead note
through the slot belongs to its held word. Inspect parallel partials: a second
voice can make a separate line while the lead continues. Clear those second-voice
contour fragments and give them no words unless the operator requests them.
For a full-text row absent from the synced source that fails these checks, remove
it from the verified text and the scratch package's cached source, list its times
in the private report, and place no words. Preserve both originals. Never compress
a response into the remaining space. If the voices or formants are unclear, list
the span for the operator before declaring the text verified.

3. Write `verified.txt`: one sung line per row, repeats written in full, no section
   labels. Write `synced.lrc` with the **same nonempty lines in the same order**.
   Empty timed LRC rows may mark vocal-window endings. Reflow text to the synced
   boundaries without adding/dropping tokens. Never pad with invented words or
   zip mismatched row counts. If the grouping remains doubtful, omit forced
   alignment and use the existing word sheet plus pictures.
4. If stored words already equal the verified text, retain the current target as
   the base and skip lyric rewriting and metadata changes. Still inspect every
   word's timing (**R2**). A start with `c <= 0.3` or
   `timing_source: vocal_stem_energy` is unplaced: ignore its time as a proposal and
   place it from the picture. Keeping any other word requires R1 boundary evidence.
   Keeping a whole section also requires the original recogniser transcript to
   contain its words within **0.3 s**, plus a passing R1 screen. Without that
   transcript, inspect words individually. Record each disposition privately.
5. For incorrect text, work on the scratch package. Correct artist metadata only
   when independently verified, before lyric correction (it changes the source
   cache identity):

```sh
"$P" "$T/set_artist.py" "$W/package" "$VERIFIED_ARTIST" --dry-run
"$P" "$T/set_artist.py" "$W/package" "$VERIFIED_ARTIST"
"$P" studio/lyrics_text.py "$W/package" --text "$VERIFIED" --synced "$SYNCED" --dry-run
"$P" studio/lyrics_text.py "$W/package" --text "$VERIFIED" --synced "$SYNCED" --no-html --json
```

Inspect a refusal at its timestamp. Fix the source or clock after checking the
picture; never force acceptance. Keep the published LRC separately. Without a
reliable synced clock for unpitched singing, leave the passage for the operator.
Use the published clock under **R4**. If a boundary sign exists within **0.5 s**
of a synced line start, choose the sign nearest the stamp, preferring a strong
onset, and stop the search there. Override the stamp using a burst pattern only
when all three hold: no sign within 0.5 s; a pattern within **3 s** whose segment
count equals the line's syllable count; and an independent second witness. A
witness is the same line's pattern at the same relative offset elsewhere, a fixed
section offset measured on two or three strong onsets, or a recogniser word time.
Without a witness keep the stamp and mark the line doubtful. Record both original
and proposed times for every override and retain the published LRC beside the
corrected one. A line stamp supplies no internal word positions: use R1 per word.

The single entry command runs mechanical steps; it does not decide lyrics or
fetch sources. After either text branch, snapshot the target used by every later
sheet, apply and placement command:

```sh
cp "$W/package/target.json" "$S/base.json"
```

For already-correct words this preserves the current target; for rewritten words
it preserves the corrected target.

## 3. Pictures, candidates and timing sheet

```sh
"$P" "$T/features.py" "$W/package" "$S/features.npz"
"$P" "$T/candidates.py" "$W/package" "$S/features.npz" "$S/candidates.json"
"$P" "$T/onsets.py" "$S/features.npz"
# Optional proposal; requires matching text/LRC rows, Latin a-z tokens and model weights:
"$P" "$T/fa_align.py" "$W/package" "$VERIFIED" "$SYNCED" "$S/fa.json"
"$P" "$T/make_sheet.py" "$S/base.json" > "$S/words.txt"
"$P" "$T/draw_windows.py" "$W/package" "$S/features.npz" "$S/windows" --step 12
# Add --fa "$S/fa.json" and/or --sung "$W/attempts.json" when present.
```

The optional aligner preserves alphanumeric content when comparing verified and
synced rows. Digits, mixed letter/digit tokens and unsupported letters refuse
before audio or model imports. Use the word sheet and pictures for those passages.

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

Before placing words in a phrase, apply **R1** in this order:

1. Count syllables in the verified phrase, then count contour segments. A segment
   begins after a gap of at least **40 ms** or a pitch step of **0.8 semitone**
   completed within **150 ms**. The helper lists segment-start candidates; check
   tracking fragments, scoops and vibrato against the stem partials before
   accepting its count.
2. With at least as many segments as syllables, assign word starts to segment
   starts in sung order. For the common two-short-pickups/long-note pattern, the
   final word begins at the start of the long segment and holds through its end.
3. With fewer segments than syllables, inspect moving bright partials **above
   500 Hz** for the vowel change while the fundamental continues. Mark each such
   legato start doubtful and record its vowel-change evidence.
4. Require a boundary sign: contour start/stop within **80 ms**, pitch variation
   of at least **0.8 semitone** inside ±80 ms, or a strong onset within **60 ms**.
   A strong onset has strength at least **0.25 × the 99.5th percentile** of the
   full onset envelope. A wholly absent contour supplies no edge by itself.
5. A start inside an unbroken contour level within **±0.5 semitone for 0.25 s on
   each side** must move to a supported boundary, unless the legato evidence in
   step 3 is present and recorded. A weak vibrato/noise tick supplies no evidence.

Consonant bursts can precede the vowel: stops show a short fundamental dip or a
white-curve burst; sibilants show orange energy. Voiced consonants may show a
scoop or changed partial brightness. Read those signs together with R1.

For the **intro (R3)**, measure candidate spans before trusting the first synced
stamp or contour. At **≥1.5 strong onsets/s**, confirm moving formants above 500 Hz
between bursts before placing a sung word. Follow its last burst: a steady partial
continuing without a gap or hop belongs to that word; join supported contour pieces
and extend its end to the partial's stop. At **≤0.6/s**, short pieces **under
0.5 s** hopping between fixed pitches with both partials continuously bright
identify a pad/chord: clear that contour and place no word. The numbers and the
picture must agree. Between **0.6 and 1.5/s**, place no word, keep the contour and
list the span for the operator. An unresolved band/formant reading also requires
operator review; make and record the disposition for every measured span.

For **screams (R6)**, assign all clean segments before the scream first so every
clean syllable has its segment. Inside the scream, count bright formant arcs of
about **0.2–0.5 s** as syllables in order. The final flat texture holds the last
syllable; place no new word inside it. Every scream start is doubtful, including
starts on a burst. Clear contour fragments there and write the scream span as
unpitched data. Harmonic/onset numbers cannot identify these formant arcs reliably;
inspect the spectrum and list ambiguous readings for the operator.

For repeats (**R7**), check the first occurrence by R1 before copying its relative
placements. Measure the section offset on two or three strong onsets and inspect
each occurrence. Agreement establishes consistency; the first occurrence still
needs independent boundary evidence. Review every `repeat` candidate.

The generated word sheet uses `index word = =`: these rows preserve the original
start, end, confidence and timing provenance. Explicitly placed rows receive
`timing_source: reviewed_spectrogram`; doubtful rows still carry confidence 0.4.
Change just the rows supported by the picture. Use
seconds for exact times, `~seconds` for an eye estimate snapped within 70 ms, or
`o123` for an onset index printed by `onsets.py`. After snapping, inspect the chosen
candidate. Keep it only with a strong onset or a contour sign within 80 ms. If it
fails, discard the snap and enter the nearest visually confirmed segment start
as plain seconds. This also applies to explicit onset indices. Apply accepts
proposals mechanically; the placement report and picture review supply this guard.
An omitted end uses a level drop
or ends just before the next word. `?` marks doubtful placement at confidence 0.4;
blank rows begin a lyric line. Word order/text must match the base. If snaps
collide, both involved estimates fall back to their supplied eye times and are
reported under `collisions`. If those still collide, apply refuses: re-read the
picture and enter distinct exact times. Never shift unrelated words to make room.

### Placement screen and counted spans

```sh
"$P" "$T/placement.py" "$W/package" "$S/features.npz" "$S/placement.json" \
  --synced "$SYNCED" --review "$S/spans.json" --base "$S/base.json"
```

`--synced`, `--review`, and `--base` are optional. The all-word screen always runs.
Read `flags` by word index/time, `segment_starts`, `strong_onsets` and the computed
`onset_strength_threshold`, plus `intro_windows` (4 s windows,
2 s step over the first 20 s), and `first_word_candidates` (2 s burst/harmonic
windows requiring at least 1.5 strong onsets/s and some harmonic support). Intro candidates include harmonic-energy fraction and displacement
from the first synced stamp. These identify windows for formant review; neither
energy nor parallel harmonics alone prove the voice or a word's identity.
`held_word_tail` asks whether the same partial continues after a line's last word.
It can also find a following word or chord: confirm continuity before extending.
`--synced` matches normalized full row text, reports >0.5 s disagreements, and
lists unmatched rows without guessing a row mapping. `target_unsynced` identifies
stored lines absent from those matches; inspect them as potential responses and
supply counted spans. It never overrides a stamp. `parallel_harmonics` lists
stretches of at least 0.2 s with competing combs **2–10 semitones** apart and a
second/first strength ratio of at least **0.55**, with odd-partial and harmonic
energy support. These can be chords, leakage or another voice. Confirm that the
lead partial continues before clearing a second-voice fragment; close unisons,
octaves and wide intervals remain outside this particular screen.

`spans.json` is a private JSON list with explicit syllable counts read by the
reviewer; the helper never guesses pronunciation. Example with synthetic times:

```json
[
  {"role":"intro","a":0.2,"b":2.2,"syllables":4},
  {"role":"response","a":5.0,"b":5.5,"syllables":5},
  {"role":"scream","a":8.0,"b":9.5,"syllables":3},
  {"role":"phrase","a":12.0,"b":13.8,"syllables":3,
   "synced":13.6,"burst_start":12.0,
   "witness":{"kind":"recognizer","a":12.1}}
]
```

Roles are `intro`, `response`, `scream`, `phrase`; `a/b` bound the measured span,
`syllables` is positive. For clock checks provide both `synced` and `burst_start`.
A witness `kind` is `recognizer`, `repeat` or `section`; its `a` is an independently
measured start in this occurrence's clock within **0.3 s** of the burst reading.
For a section/repeat witness, retain the measured anchor times and offset in
private notes. `override_candidate` requires no sign near the stamp, a reading
within 3 s, equal segment/syllable counts and that witness. Confirm the picture
and witness before overriding. Otherwise follow `keep_nearest_sign` or
`keep_stamp_doubtful`. A response flag gives room, articulation and continuous-lead
measurements; confirm a separate lead articulation before including its words.
Parallel voice identity and vowel changes remain visual judgments.

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
phrase context ranks confidence after spectral disagreement. Comparisons outside
the cached MIDI 36–90 grid supply no evidence; proposed pitches must also fit
the schema range. Candidate spans stop at unsupported frames. Neighbour pitch
alone supplies no octave verdict. Unpitched checks use energy, autocorrelation
and harmonic concentration. A noise band can resemble a tone and a rough vowel
can resemble noise. Broken-note checks search a local pitch band near flanking
contour frames and include short intervening fragments on another partial; distant runs can be missed. Repeat checks correlate the stem's
100 ms energy envelope across ±2.5 s around repeated lines. Shared three-word
prefixes also find repeats whose alignment split the occurrences into different rows. Two identical words
in different musical settings can disagree legitimately. A coherent late section
or a different arrangement can defeat that reference. These remain visual tasks.

Octave edits preserve existing scream/noise annotations, including gaps within
a phrase and operations that change no frames. A fill trims annotations only
where pitched frames survive contour derivation. An explicitly classified clear
replaces the classification over its selected frame coverage.

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
# R7: inspect all flags and record dispositions before rebuilding.
"$P" "$T/placement.py" "$W/package" "$S/features.npz" "$S/placement-after.json" \
  --base "$S/base.json" --synced "$SYNCED" --review "$S/spans.json"
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

Before rebuilding (**R7**), run the screen on the finished target. Above **20%**
of word starts without a boundary sign on clean singing, return to every flagged
word's picture. For every flag, move it to a supported sign or mark it doubtful
with its legato/formant reason; a share at or below 20% still leaves every flag to
review. For every word moved more than **0.1 s**, record both times and its sign
(gap, step, burst, vowel change). A mismatched base cannot supply a movement audit;
use a base with identical words/order or retain a separate explicit mapping.

The onset check samples 28 words and can accept a nearby vibrato tick. It supplies
an additional spot check; run the all-word R1 screen and inspect its flags too.
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
| R1 missing signs / all starts; flagged dispositions | counts, share, times, move or doubtful reason |
| Unplaced origins / reviewed words | counts and per-word decision |
| Intro / response / clock / scream checks | times, density, syllables, room, witness and disposition |
| Moves >0.1 s and signs; overridden stamps | both times and gap/step/burst/vowel-change evidence |
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
whole-span coverage. The four private packages are labelled song A–D, with the
reviewed fourth-song run labelled song D; their mapping stays private.
Earlier validation used directory order; use the mapping retained with each run.

Run the Python tests using explicit paths and the project's check wrapper in an
isolated scratch export. The QA suites are `tests/song_qa_test.py` and
`tests/song_qa_placement_test.py`; browser suites are unaffected. Retain the revision, command, environment dependency versions,
run time bounds, check results and per-song recall in local evidence. Public
reports carry the aggregate table and repository-relative file references only.
