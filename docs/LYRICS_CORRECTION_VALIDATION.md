# Synced lyric correction: validation

Dry-run evidence completed 2026-11-14 12:09 UTC. Project checks completed 2026-11-14 12:53 UTC. The table retains the original main baseline before optional anchors. The follow-up also compares the pinned `9c2ac731` source with the candidate using identical anchors. Candidate: the source delivered with this report.

Both versions use the supplied verified text. Local synced files are supplied for songs E, G, J, K, L, N and Q. Each package command uses `studio/lyrics_text.py --text verified.txt --dry-run --json`; anchored commands add `--synced lines.lrc`. Runs use the project virtual environment, isolated scratch, and local inputs without fetching.

## Nineteen-song comparison

Values are coverage % / uncovered singing seconds / silent holes, measured with the original pitch mask. P/R is the gate result. These pitch-based metrics omit unpitched voices; the independent line evidence below determines placement. The baseline accepted three of the seven defective placements.

| Song | Before | After |
|---|---|---|
| song A | 27.3/75.9/4 P | 27.3/75.9/4 P |
| song B | 28.4/50.8/3 P | 28.4/50.8/3 P |
| song C | 37.5/65.8/4 P | 37.5/65.8/4 P |
| song D | 27.6/34.3/4 P | 27.6/34.3/4 P |
| song E | 28.9/32.8/2 P | 26.1/24.8/0 P |
| song F | 38.2/16.9/0 P | 38.2/16.9/0 P |
| song G | 35.2/38.3/1 P | 31.8/45.6/1 P |
| song H | 30.1/22.3/0 P | 30.1/22.3/0 P |
| song I | 28.7/39.4/0 P | 28.7/39.4/0 P |
| song J | 36.2/55.1/0 R | 34.8/44.7/0 P |
| song K | 50.1/21.6/1 R | 44.1/24.3/1 P |
| song L | 29.6/16.8/3 R | 29.9/28.4/3 P |
| song M | 38.3/23.1/0 P | 38.3/23.1/0 P |
| song N | 26.9/40.8/1 R | 27.4/37.5/3 P |
| song O | 38.8/42.6/3 P | 38.8/42.6/3 P |
| song P | 39.6/37.8/3 P | 39.6/37.8/3 P |
| song Q | 32.9/35.5/1 P | 29.7/41.2/1 P |
| song R | 26.5/22.6/0 P | 26.5/22.6/0 P |
| song S | 46.2/28.3/2 P | 46.2/28.3/2 P |

All nineteen retain the complete placements and metrics of `9c2ac731` and the retained independent review; no line start changes. All twelve text-only controls (songs A, B, C, D, F, H, I, M, O, P, R and S) retain identical complete metrics and word placement. Two consecutive fresh-process dry runs produce byte-identical JSON reports and complete word data for every song. Small private package inputs are copied to scratch before comparison so parallel publication cannot change a repeat run; large recordings are read through links, and every command uses `--dry-run`. All 234 package files and 104 verified-input files retain their hashes, sizes, modification times and complete file set. All 357 line starts and original attack arrays match the independent review.

The anchored harm gate checks independently accepted voice/clock windows and the existing 50 ms onset margin. Raw pitch-hole counts above retain rounding-edge holes and a timed outro in song N; those do not require invented words.

## Five previously refused passages

Energy is mono vocal-stem RMS in dBFS on the aligner’s 10 ms grid (32 ms frames). Near-time median/p95 use ±1.5 s, clipped at the next line. Noise floor is local p20 within ±8 s, capped at stem p95 minus 20 dB. Sustained support requires 0.12 s above floor +10 dB, stem p95 minus 35 dB, and an absolute −80 dBFS floor that rejects numerical silence. Residual is final start minus compensated synced time.

| Song / line | Synced time s | Rule | Placed s | Residual s | Near median / p95 dBFS | Noise floor / threshold dBFS |
|---|---:|---|---:|---:|---:|---:|
| song E / 35 | 168.645 | a: stem energy | 168.623 | -0.022 | -19.350 / -16.129 | -35.214 / -25.214 |
| song J / 29 | 121.370 | a: stem energy | 121.417 | +0.047 | -29.201 / -13.953 | -37.780 / -27.780 |
| song K / 2 | 12.800 | a: stem energy | 12.817 | +0.017 | -16.997 / -13.510 | -71.423 / -49.549 |
| song L / 42 | 204.280 | a: stem energy | 204.280 | +0.000 | -27.234 / -12.497 | -43.192 / -33.192 |
| song N / 1 | 1.340 | b: validated clock | 1.340 | +0.000 | -70.372 / -51.835 | -72.240 / -48.244 |

Song E’s detected +6.665 s offset is applied before the stem tests. Song L has sustained energy at the predicted time; its evidence marks `energy.sustained_at_synced_time` because that continuous voice has no separate detected attack there. Song N’s first words carry `timing_source: synced_time_without_voice_support` in the resulting word data and `synced_lines` report. Its line starts exactly at the published time; the original pitch mask is preserved.

Clock residuals below are ASR prefix deltas after subtracting their median. Ordinary ASR latency under 1.5 s is retained for local onset placement.

| Song | Agreeing / all timed lines | Median ASR delta s | Residual p10 / p90 s | Group median spread s | Strong clock validated |
|---|---:|---:|---:|---:|---|
| song E | 18/53 | +6.665 | -0.689 / +0.469 | 0.795 | no; uses voice evidence |
| song J | 31/55 | +0.545 | -0.325 / +0.245 | 0.120 | yes |
| song K | 24/45 | +0.370 | -0.347 / +0.320 | 0.300 | yes |
| song L | 26/42 | +0.375 | -0.210 / +0.185 | 0.200 | yes |
| song N | 44/51 | +0.615 | -0.202 / +0.386 | 0.200 | yes |

Quiet placement requires at least three independent matches, covering at least 50% of all timed lines and 80% of matched lines. Residual p90−p10 must be at most 1 s; chronological group medians must span at most 0.75 s; evidence must span at least half the timed song. The same checks run with the quiet line excluded, keeping its inferred median within 0.75 s. An unvalidated clock or a different edit refuses with line, time and reason (rule c).

All seven pass the final voice/evidence and section-boundary gates. Maximum absolute synced-start residuals: song E 0.925 s, song G 0.448 s, song J 0.325 s, song K 0.359 s, song L 0.970 s, song N 1.350 s, song Q 1.190 s. Song G restores no ASR repeats. Song Q’s disputed backing-line start moves from 235.613 s to 273.260 s, against 273.310 s synced time.

## Contradictory phrase regression

A stable majority could hide a single contradictory timestamp: twelve distinct synthetic phrases have two-second voiced regions at 1, 11, …, 111 s, but line 6 is stamped at 47 s instead of its 51 s vocal onset. Eleven coherent matches produced a zero-spread clock. The previous quiet-line veto still allowed an incidental pitch or stem-energy attack at 47 s to place that phrase four seconds early.

`studio/lyrics_synced.py` retains per-line phrase evidence, including outliers and every occurrence beyond the clock search radius. Each line is checked before selecting any placement branch, discarding ASR, replacing the first word's time or exempting a window from the harm gate. For a phrase of at least three words or a uniquely identified one- or two-word line, an occurrence within 1.5 s of the compensated timestamp or the ASR clock median supports placement. If every occurrence contradicts both tolerances and at least one is unexplained by another coherently timed row, correction refuses with line, timestamp, nearest ASR occurrence and residual. This preserves ordinary ASR latency and valid repeated phrases.

The two follow-up findings concerned repeated prefixes disabling this veto, and one- or two-word lines receiving no evidence. `synced_clock.line_evidence[].occurrences` now retains all candidate times and residuals. Shared prefixes, including fragments inside longer timed phrases, extend through the first distinguishing word. Broader observations remain in `prefix_occurrences_s`; when the distinguishing words are absent, that fragment does not identify the line. Short matches unique in both ASR and the timed text provide per-line veto evidence; ambiguous fragments can still use independent placement evidence. The global clock still requires at least three independent matches of three or more words. Repetition alone cannot waive a contradiction. An occurrence already explained by another coherently timed row is retained with `explained_by_line`. It supplies no negative evidence for a missing repeat. When none of the occurrences are compatible, an unexplained conflicting occurrence still vetoes placement beside such explained observations. A missing phrase can still use the other lines' validated clock.

Focused command: `"$LUMA_PY" tests/lyrics_synced_test.py MajorityContradictionTests`. Twenty synthetic test methods cover pitch, stem-energy and quiet-clock placement, early/late four-second contradictions, offset compensation, tolerance boundaries, valid repeats, distinguishing fourth and fifth words, unique and ambiguous one- and two-word lines, missing phrases, and out-of-search-range evidence. Real synthetic-audio CLI runs cover unique phrases, repeated phrases, shared prefixes and both short-line lengths through explicit input and cached replay in separate processes, including `--force`. Correctly timed controls pass; repeated refusal reports are byte-identical and leave package bytes unchanged. Both realignment and retranscription use the shared `corrected_seed` consumer. The actual `retranscribe_song.py --cache-only --no-html` CLI is also tested in fresh processes: repeated and uniquely identified two-word contradictions with ordinary 0.6 s ASR latency leave every package file unchanged, with each combination of existing or absent mix/vocal transcripts. Valid controls still persist both transcripts and corrected words.

## Review follow-up regressions

ASR phrase windows now require chronological word starts and at most 3 s between
one word's end and the next start, with the preceding word duration capped at the
aligner's 1.5 s maximum. This continuity check runs before occurrence counting,
short-line uniqueness, clock voting and explained-span construction. A lexical
duplicate across a long pause cannot disable a unique short-line contradiction;
a gapped-only fragment supplies no veto against an independently supported line.
The global clock still requires at least three independent three-word matches.

Occurrence ownership is recomputed against the inferred clock before constructing
explained spans. Missing repeats therefore retain the other repeat's explanation
after source-clock compensation, including ordinary 0.6 s ASR latency. Explained
spans stop at a long pause even when their first three words match coherently.

Each parsed timestamp occurrence is identified by its physical line and time. ASR ownership therefore treats consecutive repeats at 51 and 61 s identically whether they use separate LRC rows or two timestamp tags on one row. Quiet-clock validation excludes only the current occurrence and retains other timestamps from the same physical row. The public `explained_by_line` diagnostic keeps the original physical line number.

`MultipleTimestampRepeatTests` covers either missing ASR repeat through pitch, stem-energy and quiet-clock placement; it also covers the minimum independent clock evidence with a multi-tag repeat. Fresh-process CLI controls cover both formats through explicit inputs, cached replay and successful forced writes. Early/late unexplained contradictions beside an explained repeat still refuse through direct correction, cached CLI and `--force`, preserving the entire synthetic package and repeatable reports.

`SyncedRetranscriptionCliTests` exercises the real cache-only retranscription consumer before any mix/vocal transcript write. It covers repeated and unique two-word lines, all four combinations of existing and absent transcripts, repeated process restarts, exit 1 and line/time reasons on refusal, and successful controls that save both transcripts. The input ASR cache is prepopulated, so the test makes no paid calls.

`TemporalOccurrenceTests` adds the pause-spanning duplicate and gapped-only controls,
the exact 3 s pause boundary, overlong ASR token durations, and a pause after an
explained prefix. Compensated missing repeats pass in both LRC formats through all
three voice branches with 6, 10 and 25 s source-clock offsets. Fresh-process explicit
and cached CLI runs cover ordinary and forced writes, repeated dry runs, and
unexplained early/late contradictions with unchanged package bytes. Cache-only
retranscription also covers the gapped refusal with all four existing/absent
transcript combinations, plus valid gapped-only and compensated-repeat controls.

## Project checks

Every suite ran as its own process by explicit file path, serially through the heavy-command wrapper. Scratch HOME, XDG_CONFIG_HOME, XDG_STATE_HOME and TMPDIR were isolated. Browser checks used distinct free demo and Studio ports and an empty test library. The project Python path was preserved; node dependencies were linked from the unchanged checkout.

| Suite | Result |
|---|---|
| `tests/e2e/scoring.mjs` | PASS (exit 0) |
| `tests/e2e/audio.mjs` | PASS (exit 0) |
| `tests/e2e/ux.mjs` | PASS (exit 0) |
| `tests/e2e/studio.mjs` | PASS (exit 0) |
| `tests/e2e/scale.mjs` | PASS (exit 0) |
| `tests/e2e/lessons.mjs` | PASS (exit 0) |
| `tests/e2e/finish.mjs` | PASS (exit 0) |
| `tests/e2e/history.mjs` | PASS (exit 0) |
| `tests/e2e/progress.mjs` | PASS (exit 0) |
| `tests/e2e/lives.mjs` | PASS (exit 0) |
| `tests/e2e/activity.mjs` | PASS (exit 0) |
| `tests/e2e/session.mjs` | PASS (exit 0) |
| `tests/e2e/wordless.mjs` | PASS (exit 0) |
| `tests/e2e/autopick.mjs` | PASS (exit 0) |
| `tests/e2e/latency.mjs` | PASS (exit 0) |
| `tests/e2e/cloud.mjs` | PASS (exit 0) |
| `tests/e2e/xr.mjs` | PASS (exit 0) |
| `tests/studio_test.py` | PASS (exit 0) |
| `tests/separation_test.py` | PASS (exit 0) |
| `tests/lyrics_text_test.py` | PASS (exit 0) |
| `tests/lyrics_align_test.py` | PASS (exit 0) |
| `tests/lyrics_synced_test.py` | PASS (exit 0) |
| `tests/retranscribe_song_test.py` | PASS (exit 0) |
| `tests/pitch_quality_test.py` | PASS (exit 0) |
| `tests/video_test.py` | PASS (exit 0) |
| `tests/lan_proxy_test.py` | PASS (exit 0; also with `-I`) |
| `tests/audio_stems_test.py` | PASS (exit 0) |

The Python files pass 290 tests, including 95 synthetic synced-lyrics tests covering stem-supported voice, quiet-clock placement, clock/edit refusal, unrelated ASR, onset spacing and rounding, next-line attacks, cache replay, and CLI restarts.

All renewed individual suites pass, including Session and History. Earlier timeout and timing-failure evidence and the equivalent base/candidate comparisons remain preserved separately.

### Existing video failure

The earlier `bash tests/e2e/run.sh` run exited 143 during the browser video groups. Preserved comparisons run `VIDEO_ONLY=basic bun tests/e2e/video.mjs` in branch, base, branch, base order under identical isolated settings, with a 360 s outer timeout for each. All four reach the same render-deadline error. A roughly 6.7 s sitting has a configured deadline of `3 × duration + 60 s` (about 80 s). The individual comparisons exit 1 after this error; later plain-demo navigation also lacked its server. The retained full-run log additionally shows downstream sync and lives failures. This evidence establishes the shared render failure; remaining browser video groups have no completed passing result. Video source and tests were left untouched under the scope ruling. Python video tests pass separately above.

Implementation and limits: `docs/LYRICS_TIMING.md:533`, `studio/lyrics_synced.py`, and `tests/lyrics_synced_test.py`. Energy is a voice-support heuristic inside verified line windows; it does not identify words. Text-only runs retain existing placement and harm checks.
