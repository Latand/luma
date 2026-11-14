# Synced lyric correction: validation

Evidence read 2026-11-14 02:54 UTC. Baseline: main at the lane start. Candidate: the source delivered with this report.

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

All twelve text-only controls (songs A, B, C, D, F, H, I, M, O, P, R and S) retain identical complete metrics and word placement. Two consecutive fresh-process dry runs produce byte-identical JSON reports and complete word data for every song. Package content and metadata and the retained baseline hashes are unchanged.

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

## Contradictory quiet-line regression

A stable majority could previously hide a single contradictory timestamp: twelve distinct synthetic phrases have two-second voiced regions at 1, 11, …, 111 s, but line 6 is stamped at 47 s instead of its 51 s vocal onset. Eleven coherent matches produced a zero-spread clock and allowed the first word at 47 s in silence. Both early and late four-second shifts fail the new regression on the reviewed revision.

`studio/lyrics_synced.py` now retains per-line phrase evidence, including outliers and occurrences beyond the clock search radius. Before entering the quiet fallback, it refuses an unambiguous phrase whose residual from the clock median exceeds 1.5 s. The error names the line, timestamp, ASR occurrence and residual; constant offsets and ordinary ASR latency are accounted for. Repeated phrases remain explicitly ambiguous, and a missing phrase can still use the other lines' validated clock. This runs before ASR is discarded and before any window is exempted from the harm check.

Focused command: `"$LUMA_PY" tests/lyrics_synced_test.py MajorityContradictionTests`. Seven synthetic cases cover early/late shifts, compensation, ambiguous repeats, missing quiet phrases, ordinary ASR delay, an occurrence outside the search radius, and fresh CLI processes including `--force`. Direct correction and both cache replay consumers share `build_correction`; refusals leave synthetic package bytes unchanged. The renewed nineteen-song outputs preserve all reviewed word data and all 357 anchored line starts.

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

The Python files pass 262 tests, including 71 synthetic synced-lyrics tests covering stem-supported voice, quiet-clock placement, clock/edit refusal, unrelated ASR, onset spacing and rounding, next-line attacks, cache replay, and CLI restarts.

The earlier session run initially missed its reduced-motion card limit by 6 ms (306 ms against 300 ms). Its subsequent alternating base, branch, base runs pass in fresh isolation; the suite and application code are unchanged. That earlier timing comparison remains preserved separately; the table above records this fix round's fresh per-file runs.

### Existing video failure

The earlier `bash tests/e2e/run.sh` run exited 143 during the browser video groups. Preserved comparisons run `VIDEO_ONLY=basic bun tests/e2e/video.mjs` in branch, base, branch, base order under identical isolated settings, with a 360 s outer timeout for each. All four reach the same render-deadline error. A roughly 6.7 s sitting has a configured deadline of `3 × duration + 60 s` (about 80 s). The individual comparisons exit 1 after this error; later plain-demo navigation also lacked its server. The retained full-run log additionally shows downstream sync and lives failures. This evidence establishes the shared render failure; remaining browser video groups have no completed passing result. Video source and tests were left untouched under the scope ruling. Python video tests pass separately above.

Implementation and limits: `docs/LYRICS_TIMING.md:533`, `studio/lyrics_synced.py`, and `tests/lyrics_synced_test.py`. Energy is a voice-support heuristic inside verified line windows; it does not identify words. Text-only runs retain existing placement and harm checks.
