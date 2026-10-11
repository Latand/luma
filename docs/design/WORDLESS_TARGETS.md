# Wordless targets: why fragments with no lyrics count as misses, and the rule that stops it

Research by lane 199c548c (§1–§3 and §6 are its measurements, unchanged). The rule in §4 is implemented in `app/app.js`
as the operator decided on 2026-10-11 (§5): every wordless chain is drawn dimmed, none is scored, and medians restart.
No song package in `songs/` was rewritten. Songs are named `W01`…`W28`:
the alphabetical order of the song trainers `songs/Luma_*.html` (lessons left out) on 2026-10-11, so `ls songs/Luma_*.html`
gives the mapping. PR #10's `docs/PITCH_ACCURACY.md` used `S01`…`S22` over package directories, a different and shorter
list, so the two id sets do not line up. No title, artist or lyric appears here.

## Originating requirement

Operator, 2026-10-11, spoken (Ukrainian), quoted verbatim from the pinned task. It was said about a trainer screenshot:
the contour view, the singer's grey line low on the left, a few tiny target fragments high on the right around the «ЗАРАЗ» playhead caption, no
lyric line on screen.

> «щоб не рахувало це як промахи, бо там немає слів, таке часто буває якісь дивні відрізки, взагалі б якось
> пропаналлізувати ще раз додатково як воно считує»

That makes three obligations:

1. **Target with no words under it must stop counting as a miss.**
2. **Explain the "weird fragments"** and say how often they happen.
3. **Re-check how the target is read**, from the audio to the score.

Earlier work: transcript and memory searches (English and Ukrainian, with and without the project) found nothing on
wordless targets except the requirement itself. PR #10 (`docs/PITCH_ACCURACY.md`) is the base for obligation 3, and it is
re-checked against the current code in §1.3.

## Short answer

- **The screenshot is W19 at 28.3 s** (traced in §2). The fragments sit in a 23 s instrumental break between two sung lines.
  They are five notes of 0.12–0.36 s, two octaves above the singer's line and 17–21 dB quieter than the song's singing. That
  is leakage left in the Demucs vocal stem. CREPE is confident on it (periodicity 0.78–0.86), and it sits 1.4–5 dB above
  the map's −43 dBFS gate, so it becomes notes. They are drafts, drafts count towards the match, and each one gets a ×.
  The activity log shows the operator singing none of it: phrase 5, 23 frames of target, 0 sung.
- **Across the library**, 20.0 % of the contour target lies more than 0.5 s from any lyric line. Most of it belongs to
  phrases that do have words: missing first syllables and missing words, which PR #10 had already found. Wordless
  *phrases*, chains of notes that come nowhere near a word, hold **4.5 %** of the target. The share is 0.1–22.7 % per
  song, median 2.1 %.
- **That 4.5 % is two different things.** Short wordless chains (under 0.65 s of target, 62 of 119) are quiet bleed: median
  19 dB under the song's singing, 7–18 % reliable frames. Long ones (3 s and more, 12 chains, 82 s) are loud and mostly
  reliable. That is real singing with no words: vocalise, or lines the transcription heard nothing in.
- **They cost more than percentage points.** Take a singer who hits every note that has words and stays silent where there
  are none. That singer still loses lives in **13 of 28 songs**: 29 in W05 and 12 in W11, both past the 10 lives a pass
  allows, so neither song can be finished.
- **Rule (§4):** stop scoring notes that sit in a wordless phrase. A phrase counts as having words when any of its notes
  comes within 0.5 s of a lyric line; phrases are chained the way the build already chains them (gaps ≤ 0.85 s). Apply it
  in the trainer when a song loads. Every wordless chain, short or long, is drawn dimmed and never scored (operator
  decisions 1 and 2, §5).
  Every song with lyrics gets a new `mapVersion` once, so histories and medians compare like with like. A song without
  lyrics and every lesson keep today's scoring.
- **Rejected on the numbers:** dropping notes shorter than X ms. Notes inside lyrics are just as short (median 0.18 s in
  both groups, 38–40 % under 150 ms), so such a rule would cut a third of the sung notes. Octave-outlier removal is
  rejected too: 507 of the 551 outliers sit inside sung phrases.

## 1. How a target is made and scored today (checked against `77e116d`)

### 1.1 From audio to target (`studio/prepare_song.py`)

| step | where | what it does |
|---|---|---|
| separation | `:189-212` | Demucs `htdemucs_ft`; `vocal` is the model output, `backing = mix − vocal`. Whatever the model leaves of an instrument in `vocal` reaches every later step |
| pYIN + YIN + RMS | `:252-260` | on the 22 kHz vocal copy × joint gain, C2–E6, 25 s blocks; RMS window 2048 samples (93 ms) |
| CREPE | `:262-267` | `full`, Viterbi, 10 ms hop, periodicity median-3 and pitch mean-3 |
| strong frame | `:103-104` | MIDI 36..90, periodicity > 0.45, level > **−43 dBFS**. The level gate is absolute and never compared with how loud the song's singing is |
| weak (draft) frame | `:106-109` | periodicity > 0.25, level > −34 dBFS, within 1 semitone of an 11-frame median, run ≥ 8 frames |
| valid run | `:110-112` | strong ∨ weak, runs shorter than 5 frames (100 ms) dropped |
| reliable | `:113-114` | strong, periodicity ≥ 0.70, level > −38 dBFS, pYIN within 50 ¢ or periodicity ≥ 0.85; 2 edge frames of each run never reliable |
| notes | `:115-125` | median-5 contour; a new note when it leaves the current semitone by > 0.72; notes shorter than 4 frames (80 ms) dropped; `ok` when ≥ 55 % of frames are reliable |
| phrases | `:126-137` | notes chained while the gap is ≤ **0.85 s**; a chain shorter than **0.65 s** never becomes a phrase; long chains split into ≤ 8 s pieces, ±0.45 s padding |
| points | `:139` | every valid frame keeps its pitch in `points`, **including frames that ended up in no note** |
| lyrics | `:279-295` | Soniox on the vocal stem, then `align_lyrics.realign`; nothing in the map refers to the lyrics, and nothing in the lyrics changes the map |

Nothing here knows whether a word is sung at a given moment. The map and the lyrics are two independent layers, and
lyric timing affects only where words are drawn.

### 1.2 From target to score (`app/app.js`)

- `targetAt(t)` (`:57-62`): in the notes view, the non-ignored note containing `t`. In the contour view, the `points` frame
  near `t` when its pitch is not null and it is not inside an ignored note. A contour frame that belongs to no note is
  still a target: 334 s of the library's contour target are such frames.
- `scoreAdvance` (`:66-79`): one pass over a 20 ms grid. No target → state 0, outside both numerator and denominator.
  Target → hit (1) when a confident voice frame (YIN periodicity ≥ 0.8) within the level's time slack is inside the
  corridor, else 2 (sung outside the corridor) or 3 (silence). **Silence under a target is a miss, and a draft target
  counts the same as an `ok` one.**
- Levels (`:10`): ±80 / 50 / 35 ¢, slack 120 / 60 / 50 ms, note ✓ at 35 / 50 / 65 % of its frames; "easy" folds octaves.
- `noteKind` (`:82`): any note with ≥ 3 scored frames gets a ✓ or ×. A 0.12 s fragment has 6 frames, so it gets its own ×.
- Lives (`:20`, `:96-107`): a life goes when, within 4 s of song, ≥ 1.5 s of target frames were missed and the misses are
  ≥ 60 % of the target frames, at most one per 2.5 s. Only target frames count, so a fragment shorter than 1.5 s can never
  cost a life by itself, while a wordless sung passage of 1.5 s or more can.
- History keys (`:457`, `docs/HISTORY_SCHEMA.md`): `mapVersion = song.id + ':' + hash16(note tuples)`,
  `cmpKey = songHash · mapVersion · level · view · speed`. Records, and the median in lane f81c2c96's result card, are
  computed inside one `cmpKey`.
- `loadEdits` (`:46`): when `localStorage['luma.target.<id>']` exists (any note edit, **and any verified fragment**), the
  stored note list *replaces* the built one. Flags written into `target.json` therefore never reach a song the operator has
  edited or verified. That is one of the reasons §4 computes the rule in the trainer.

### 1.3 PR #10's findings against the current code

Everything PR #10 describes in its §3 still holds. The gates, the 0.72 hysteresis, the 4-frame note minimum, `ok ≥ 0.55`
and octave forgiveness on "easy" are unchanged. Its line numbers refer to `8ebbc11`; the map is now
`prepare_song.py:96-146`, pYIN `:252-260`, CREPE `:262-267`. Its two relevant conclusions are confirmed by the numbers
below. First, notes are fragmented everywhere, inside sung lines too (§3.4). Second, the transcription misses words and
first syllables, which is why a simple "outside the words" rule over-reaches (§3.2). The library has grown from 22 to 28
songs.

## 2. The screenshot, traced

- **Which song.** The screenshot (16:44 local) follows that afternoon's activity log
  (`songs/logs/activity/2026-10-11.jsonl`): lives mode was switched on in W19 at 16:07, then W19, W17 and W23 were sung in
  the contour view on "easy". A search of all 28 maps for the pattern on screen found one place only. The pattern: no
  target in the 4 s before the playhead, a fragment at the playhead, then three more within 5 s, the second 5 semitones
  above the first and the last two an octave below the second. The place is **W19 at 28.26 s**, with fragments at
  +0, +2.86, +3.68 and +4.94 s. Their spacing matches the screenshot at that stage width's 10 s view (`app.js:1285`).
- **What is there.** The last word of a line ends at 18.90 s and the next line starts at 41.85 s. In between, the map has
  five notes at 23.34, 28.26, 31.12, 31.94 and 33.24 s: 0.12–0.36 s each, 1.12 s in total, MIDI 73–85 (C#5–C#6). The sung
  notes on either side sit at MIDI 49–53, two octaves lower. Four of the five are drafts (`ok = false`), with 0, 0, 0, 4
  and 3 reliable frames. CREPE periodicity 0.78–0.86 passes the strong gate (> 0.45) easily.
- **Why they exist.** In those notes the vocal stem plays at −37.7…−41.6 dBFS. The sung lines around them play at
  −23…−29 dBFS. The song's median sung level is −20.9 dBFS, so the fragments are 17–21 dB under it and only 1.4–5 dB above
  the absolute −43 dBFS gate. Demucs left a quiet, periodic, high-pitched residue in an instrumental passage, and it could be
  an instrument or a faint backing voice (not listened to). CREPE tracks it confidently, the strong mask admits it, the
  5-frame run and 4-frame note minimums let 6–18-frame pieces through, and the trainer treats drafts as full targets.
- **What it cost.** In the operator's first W19 attempt, phrase 5 (30.67–32.75 s, notes 47–48) logged `target 23, hit 0,
  sung 0`. The second attempt logged the same at phrase 27 (203.03–204.71 s), another wordless fragment. The note at
  33.24 s is too short a chain to be a phrase, so it shows on no weak-phrase bar but still counts in the match. The grey
  line on the left of the screenshot is the operator's own voice at about 24–27 s. It is drawn in the "no target" colour
  (`app.js:1376`) because the map has nothing there.

## 3. The library, measured

**Method.** The song data was read from each trainer's embedded `LUMA_SONG`; for all 28 songs it matches the package's
`target.json` (notes and lyrics compared). Stem level: `vocals_44k.flac` × the manifest's joint gain, RMS over 93 ms (the
pYIN RMS window) on the 20 ms points grid. A song's *sung level* is the median level of its target frames inside words
(−27.0…−16.9 dBFS, median −20.3); "quiet" means more than 12 dB under it. Contour target = what `targetAt` returns in the
contour view; notes target = the same in the notes view. All 28 songs have lyrics. The scripts stayed outside the
repository, as PR #10's did; the appendix lists them.

### 3.1 Target outside lyric spans, frame by frame

| frames more than … from any lyric line | contour target | share |
|---|---|---|
| 0 s (outside the line itself) | 1438.6 s | 37.5 % |
| 0.5 s | 770.2 s | 20.0 % |
| 1.0 s | 501.0 s | 13.0 % |
| 2.0 s | 308.1 s | 8.0 % |
| 0.25 s from any **word** | 1261.8 s | 32.8 % |

Total contour target: 3841 s over 8012 s of music; lyric lines span 3099 s. 59 % of the frames that lie more than 0.5 s
from any line are reliable (`ok`), and only 18 % are quiet. **Most target outside the lyrics is confident, loud voice.**

### 3.2 What that target is: phrases with words vs phrases without

Notes were chained as the build chains them (gap ≤ 0.85 s), giving 632 chains. A chain is *worded* when any of its notes
comes within 0.5 s of a lyric line.

| | chains | notes target | median chain | stem level vs song's singing (p10 / p50 / p90) |
|---|---|---|---|---|
| worded | 513 | 3348.5 s | 3.16 s | −4.7 / −1.0 / +1.5 dB |
| wordless | 119 | 158.8 s (4.5 %) | 0.54 s | −20.9 / −14.5 / +0.6 dB |

The gap between 20.8 % (frame rule, notes view) and 4.5 % (chain rule) is target inside worded phrases that has no word on
top: a phrase sung before its first transcribed word, a held note after the last one, a word the transcription dropped
mid-line. PR #10 measured the same thing from the lyric side: in 314 of 546 phrase starts the singing begins before the
first word. Scoring only frames near words would cut 15.5 % of the target at a 0.5 s margin, most of it sung melody. The
chain rule is insensitive to the margin: 4.7 % at 0.25 s, 4.5 % at 0.5 s, 4.4 % at 1.0 s.

Wordless chains by size:

| target in chain | chains | seconds | quiet (< −12 dB) | median level | reliable share |
|---|---|---|---|---|---|
| < 0.25 s | 40 | 6.1 | 35 | −19.5 dB | 7 % |
| 0.25–0.65 s | 22 | 9.6 | 16 | −14.7 dB | 18 % |
| 0.65–1.5 s | 27 | 27.0 | 8 | −5.9 dB | 38 % |
| 1.5–3 s | 18 | 33.8 | 7 | −8.6 dB | 59 % |
| 3–6 s | 8 | 35.3 | 0 | −4.5 dB | 69 % |
| ≥ 6 s | 4 | 47.0 | 1 | −0.3 dB | 87 % |

Short worded chains look nothing like short wordless ones. Of the 81 worded chains under 0.65 s, only one is quiet
(median +0.7 dB). The "weird fragments" are the top two rows: 62 chains, 15.7 s, 51 of them quiet. The bottom rows are
voice. The 13 longest wordless chains (≥ 2.5 s, in W05, W07, W09, W10, W13 and W16) play at −18…−33 dBFS, and the raw
Soniox transcript (`lyrics/vocal.json`) has **no word** in any of them. So the aligner did not lose those words; there
were none to lose (vocalise, or lines the model could not hear as words).

### 3.3 Durations of single notes do not separate the two

| notes | count | p10 / p25 / p50 / p75 / p90, s | < 150 ms | < 250 ms | `ok` |
|---|---|---|---|---|---|
| in wordless chains | 499 | 0.10 / 0.12 / 0.18 / 0.32 / 0.66 | 39.7 % | 67.3 % | 35 % |
| in worded chains | 12 067 | 0.08 / 0.12 / 0.18 / 0.32 / 0.56 | 38.1 % | 64.5 % | 61 % |

Every note is short, because the frame mask breaks sustained tones into pieces (PR #10 §6b). A "drop notes shorter than
X ms" rule would remove the same share of sung notes as of fragments. What separates the two groups is the phrase around
a note: whether it chains to anything and whether any word lies near it (§3.2).

### 3.4 Octave outliers

A note is counted as an outlier when it lies ≥ 9 semitones from the duration-weighted median of the notes within ±5 s.
There are 551: **507 in worded phrases, 44 in wordless ones.** PR #10 showed that most notes an octave from their neighbours
are real jumps (174 of 234 already in the right octave), and it measured an octave fix-up by neighbours as harmful. The
44 wordless outliers leave the score with their chains anyway. Nothing here justifies a separate octave rule.

### 3.5 Per song, under the recommended rule

"Excluded" is contour target that stops counting. "Match at 50 % →" is what a singer who scores 50 % on the target with
words, and stays silent where there are no words, would see instead of 50 %. "No-lyrics fallback" is the share an
isolated-chain rule (chains under 0.65 s) would exclude if the song had no lyrics, for comparison with §4.6. The last
column gives octave outliers inside worded phrases / inside wordless ones.

| id | contour target, s | excluded, s | excluded | wordless chains | of them < 0.65 s | quiet share of excluded | match at 50 % → | no-lyrics fallback | octave outliers |
|---|---|---|---|---|---|---|---|---|---|
| W01 | 121.0 | 4.9 | 4.1 % | 12 | 11 | 86 % | 52.1 | 2.5 % | 17 / 2 |
| W02 | 120.0 | 7.1 | 5.9 % | 9 | 6 | 67 % | 53.1 | 1.4 % | 41 / 9 |
| W03 | 100.7 | 2.2 | 2.1 % | 3 | 1 | 53 % | 51.1 | 0.3 % | 0 / 0 |
| W04 | 123.3 | 1.3 | 1.1 % | 2 | 1 | 38 % | 50.5 | 0.4 % | 16 / 0 |
| W05 | 283.2 | 64.4 | 22.7 % | 17 | 5 | 23 % | 64.7 | 0.4 % | 7 / 10 |
| W06 | 138.7 | 0.3 | 0.2 % | 1 | 1 | 0 % | 50.1 | 2.3 % | 9 / 0 |
| W07 | 130.0 | 14.6 | 11.3 % | 2 | 0 | 6 % | 56.3 | 0.0 % | 15 / 0 |
| W08 | 100.2 | 1.6 | 1.6 % | 4 | 4 | 53 % | 50.8 | 3.4 % | 4 / 2 |
| W09 | 145.5 | 7.2 | 4.9 % | 2 | 0 | 20 % | 52.6 | 0.7 % | 3 / 7 |
| W10 | 155.8 | 6.5 | 4.2 % | 4 | 1 | 42 % | 52.2 | 2.0 % | 27 / 0 |
| W11 | 126.2 | 22.4 | 17.8 % | 18 | 1 | 2 % | 60.8 | 0.5 % | 16 / 3 |
| W12 | 185.1 | 6.0 | 3.3 % | 3 | 0 | 23 % | 51.7 | 0.1 % | 36 / 3 |
| W13 | 223.6 | 6.1 | 2.7 % | 5 | 4 | 25 % | 51.4 | 0.4 % | 22 / 2 |
| W14 | 95.0 | 0.3 | 0.3 % | 1 | 1 | 43 % | 50.1 | 0.7 % | 8 / 1 |
| W15 | 125.7 | 0.6 | 0.5 % | 0 | 0 | 41 % | 50.3 | 0.0 % | 9 / 0 |
| W16 | 116.2 | 6.4 | 5.5 % | 4 | 2 | 10 % | 52.9 | 1.0 % | 9 / 0 |
| W17 | 248.8 | 5.2 | 2.1 % | 4 | 0 | 62 % | 51.1 | 0.0 % | 28 / 2 |
| W18 | 102.5 | 0.3 | 0.3 % | 0 | 0 | 27 % | 50.1 | 0.8 % | 8 / 0 |
| W19 | 133.5 | 1.7 | 1.3 % | 5 | 5 | 89 % | 50.6 | 2.2 % | 24 / 2 |
| W20 | 102.1 | 2.1 | 2.0 % | 7 | 7 | 59 % | 51.0 | 1.8 % | 16 / 0 |
| W21 | 129.5 | 0.2 | 0.2 % | 0 | 0 | 20 % | 50.1 | 0.0 % | 33 / 0 |
| W22 | 118.2 | 0.1 | 0.1 % | 1 | 1 | 100 % | 50.0 | 1.3 % | 10 / 0 |
| W23 | 165.9 | 0.8 | 0.5 % | 1 | 1 | 69 % | 50.2 | 0.4 % | 46 / 0 |
| W24 | 139.9 | 4.3 | 3.1 % | 8 | 6 | 35 % | 51.6 | 1.7 % | 20 / 0 |
| W25 | 94.1 | 0.4 | 0.4 % | 1 | 1 | 0 % | 50.2 | 8.1 % | 12 / 1 |
| W26 | 78.3 | 3.0 | 3.8 % | 3 | 2 | 0 % | 52.0 | 8.6 % | 17 / 0 |
| W27 | 129.8 | 0.1 | 0.1 % | 1 | 1 | 100 % | 50.0 | 0.1 % | 40 / 0 |
| W28 | 108.4 | 2.3 | 2.1 % | 1 | 0 | 29 % | 51.1 | 0.5 % | 14 / 0 |
| **all** | **3841.3** | **172.4** | **4.5 %** | **119** | **62** | **26 %** | | **1.2 %** | **507 / 44** |

Songs with no wordless chain still lose a little contour target (W15, W18, W21: 0.2–0.5 %). That target is contour frames
belonging to no note that lie more than 0.5 s from any line.

### 3.6 What the singer actually does there

All 13 song attempts in the activity log (W15, W17, W18, W19, W23; the log only began on 2026-10-11) carry per-phrase
counts. On phrases with words, the operator voiced **94 %** of the target frames (39 526 of 42 068) and hit 52.5 %. On the
six fully wordless phrases they voiced **35 %** (101 of 291) and hit 26 %. Four of those six got no voice at all. The
exception is W17 phrase 23 (204–207 s, a loud wordless chain), which the operator sang and hit at 87 %. Long wordless
passages can be singable, which matters for operator choice 1.

### 3.7 Lives

The simulation took the `LIVES` constants and a singer who hits every target frame with words and is silent on wordless
target. In the contour view that singer loses lives in **13 of 28 songs**: W05 29, W11 12, W07 7, W02, W09, W10 and W16 3
each, W12, W13 and W17 2 each, W01, W26 and W28 1 each. The notes view gives the same 13 songs (66 in total). In W05 and
W11, a perfect singer of the words runs out of 10 lives and is sent back again and again. Under the rule, these frames are
not targets and the count is 0 by construction.

### 3.8 Rule variants compared

| variant | contour target excluded | notes | quiet share of what it excludes | per song min / median / max |
|---|---|---|---|---|
| note-level, no line within 0.25 s | 19.4 % | 2441 | 18 % | 6.3 / 17.8 / 37.2 % |
| note-level, 0.5 s | 15.2 % | 1844 | 20 % | 3.7 / 13.2 / 34.1 % |
| note-level, 1.0 s | 10.8 % | 1264 | 21 % | 1.8 / 7.0 / 30.8 % |
| **chain-level, 0.5 s (recommended)** | **4.5 %** | **499** | 26 % | 0.1 / 2.1 / 22.7 % |
| chain-level, 0.25 s / 1.0 s | 4.7 % / 4.4 % | 505 / 497 | 25 % / 26 % | |
| isolated chains < 0.65 s, lyrics ignored | 1.2 % | 246 | 28 % | 0.0 / 0.7 / 8.6 % |

The note-level variants exclude three times more, and the extra is loud, reliable voice inside phrases that have words.
The isolated-chain variant does not need lyrics. It catches only part of the fragments (8.4 of the 15.7 s of short
wordless chains), and 10.9 s of what it removes is short loud notes inside lyric lines.

## 4. Recommended rule

### 4.1 Definition

Applies when the song has at least one lyric word and is not a lesson (`song.lesson` absent):

1. Take the non-ignored notes after `loadEdits`, sorted. Chain consecutive notes while the gap is ≤ **0.85 s**, the build's
   own phrase chaining (`prepare_song.py:128`).
2. A chain is **worded** when any of its notes overlaps `[line.a − 0.5 s, line.b + 0.5 s]` for some lyric line.
3. **Scored time** = the union of `[first.a, last.b]` over worded chains and of every lyric line widened by 0.5 s.
4. Outside scored time there is no target: `targetAt` returns null, so the frame is excluded from the match, the voice
   coverage, the median |Δ|, the draft share, `songTarget`, the full-pass rule, the strict statistics and lives. Every
   counter in `app.js` already reads `targetAt`, so they stay consistent with no further change.
5. Drawing reads the target through an accessor that ignores the rule (`targetAt(t, opt, true)`). A note or contour
   stretch outside scored time is drawn at 35 % opacity in the plain target style, with no corridor and no ✓/× marker.
   That holds for every wordless chain, the 0.12 s fragments as much as a 6 s vocalise (operator decision 1).
6. When the playhead is on a dimmed target, the readout that now says «Тут ціль не визначена» says
   «Без слів — не рахується».
7. A phrase with no scored frame is shown as «без слів» on the weak-phrase map, outside the count of phrases without an
   attempt. Today it would land in «закоротка для рекорду», which states the wrong reason.

Why 0.85 s and 0.5 s: the first is the build's own chaining, so a "phrase" means the same thing in both places. The second
barely matters (4.7 / 4.5 / 4.4 % at 0.25 / 0.5 / 1.0 s), and it equals the release lane f81c2c96 uses after the last line.

### 4.2 Where: trainer, at load

| | trainer, computed at load (recommended) | build time (`ignored` or nulled points in `target.json`) |
|---|---|---|
| existing 28 songs | `build_html.py --rebuild` (data line untouched), as after every merge | a rewrite pass over every `target.json`, then a rebuild |
| songs the operator edited or verified | applies: computed after `loadEdits` | never reaches them: `loadEdits` replaces the built notes with the stored ones (§1.2) |
| lyrics re-transcribed (`retranscribe_song.py`) | follows automatically | the flags go stale until the pass is re-run |
| contour frames in no note | handled by the time spans | each frame's pitch has to be nulled, and `points` is outside the `mapVersion` hash |
| "ignored" meaning | stays the user's own choice | automatic and manual exclusions can no longer be told apart |

The rule needs only `song.notes` and `song.lyrics`, both already in every trainer. A level-based test (§6) would need the
stem level, which only the build has. It is not needed: wordless chains are found without it.

### 4.3 History, records and the median

The rule changes the ruler, so scores before and after it must not stand side by side. Fold the scored spans into
`mapVersion`: hash `[noteTuples, scoredSpans]` instead of `noteTuples` whenever the rule is on. Then:

- every song with lyrics opens a new `mapVersion` group once (all 28 change, even if only by 0.1 %). Old attempts stay in
  the history under their old group, as after a re-preparation;
- lessons and songs without lyrics keep their `mapVersion` and their whole history;
- lane f81c2c96's result card takes its median from the same `cmpKey`, so the first pass of each song after the change
  shows «Перший прохід!» and the median rebuilds from there. That is honest: the new scores run 0–15 points higher on the
  affected songs (§3.5), and mixing them with old ones would make every song look improved;
- re-scoring stored traces under the new rule into the new group was considered and left out (§6).

### 4.4 Lane f81c2c96 (session flow, PR #16)

Its `singEnd()` was the last non-ignored note or lyric line + 0.5 s, and a pass ends there. With the rule in place,
`singEnd()` takes the last *scored* note (a wordless note is skipped), so a take no longer waits through a wordless tail. Twelve songs have wordless target after their last line, and they
would make the singer wait 2.7–105.8 s longer for nothing: W02 23.0, W03 7.5, W04 17.7, W05 105.8, W09 4.2, W10 2.7,
W11 18.4, W12 15.1, W13 18.0, W17 3.3, W20 4.3, W28 3.9 s. The span cache is dropped in `invalidateMap()`, with the
map version and the target totals, so a note edit or an import recomputes it.

### 4.5 Lessons

All three lessons have lyrics, and none has a wordless chain (0 of 13, 33 and 32 chains). The rule would change nothing
for them today. It is still switched off for `song.lesson`, because lesson targets are exact synthetic notes and a future
exercise without a label must not lose its target.

### 4.6 Songs without lyrics

Studio skips lyrics when there is no Soniox key or the request fails. Such a song keeps today's scoring: every target
counts. The alternative measured in §3.8 (dropping chains under 0.65 s) would exclude 1.2 % of the target, about half of it
short loud notes. Those fragments cost a few tenths of a point each and can never cost a life (each is shorter than 1.5 s).
None of the 28 songs is in this state.

### 4.7 Checks that prove it

A new suite `tests/e2e/wordless.mjs` builds its own fixture from the demo package: a copy of `target.json` with three
changes, built with `build_html.py`, in the way `session.mjs` makes its fixture. The changes are:
(a) three notes of 0.12, 0.14 and 0.36 s, 12 semitones above the melody, in a 6 s gap with no lyric line;
(b) a 3 s wordless chain at the melody's pitch;
(c) a phrase whose first note starts 0.8 s before its first word, standing for a dropped first syllable.

1. `targetAt` is null on every frame of (a) and (b) in both views, and not null anywhere in (c).
2. A synthetic voice that matches every scored frame and is silent on (a) and (b) scores 100 %, and (a)/(b) get no ✓/×.
   The draw probe reports (a) and (b) as drawn dimmed, in both views.
3. The same voice in lives mode keeps all its lives across (b). On the same notes with the rule off (the build with
   `lyrics: []`) it loses one, which proves the test can fail.
4. The readout says «Без слів — не рахується» with the playhead in (b).
5. `mapVersion` of the fixture differs from what the same notes give with the rule off. The demo's own `mapVersion` changes
   too (it has lyrics), and `history.mjs` still passes: records stay inside one ruler and a stored trace re-scores to its
   stored numbers.
6. The fixture with `lyrics: []` scores (a) and (b) as today.
7. `lessons.mjs` passes, and each lesson's `mapVersion` is unchanged.
8. The weak-phrase map labels the phrase over (b) «без слів».
9. A pass on the fixture, whose last notes are wordless, ends at the last scored note + 0.5 s; with the rule off it runs
   to the last note.
10. The console stays clean (every suite already asserts it).

The suite is `tests/e2e/wordless.mjs`, run by `tests/e2e/run.sh`; `LUMA_SHOT_WORDLESS=1` also writes 390 px and desktop
screenshots of both views with the playhead in (a) and in (b). The existing `scoring.mjs`, `lives.mjs`, `progress.mjs`
and `history.mjs` stay unchanged and green. After the merge, a library check: on W19 at 28.26 s the four fragments are
dimmed on the stage, and W05 and W11 can be finished in lives mode by a voice that sings only the worded phrases.

### 4.8 Documentation the change must update

`docs/SCORING.md` (what counts as a target, the readout, lives), `docs/HISTORY_SCHEMA.md` (`mapVersion` input),
`docs/TARGET_MAP_SCHEMA.md` ("How the app uses the map") and the README's "Live match score" line.

## 5. Choices for the operator, and what was decided

Decided by the operator on 2026-10-11, in chat:

1. **Short wordless bleed chains: shown dimmed** (not hidden), never scored, never cost a life.
2. **Long wordless singing (vocalise): shown dimmed, not scored.**
3. **Medians restart from zero** under the new rule: a new `mapVersion` for every song with words (§4.3).

The options as they were put:

1. **What wordless targets look like.** *Recommended:* hide chains with under 0.65 s of target (the "weird fragments") and
   dim longer ones. A dimmed passage still guides anyone who wants to sing a vocalise (the operator sang one at 87 %, §3.6),
   and the fragments from the screenshot disappear. *Alternatives:* dim everything (simplest, the fragments stay visible
   but harmless), or hide everything (cleanest stage, and the 82 s of loud wordless chains of 3 s and more disappear with
   the fragments).
2. **Long wordless sung passages.** *Recommended:* not scored, like every other wordless target. That is the literal
   requirement, and it is what frees W05 and W11 from endless lives rewinds. *Alternative:* keep chains of 3 s and more
   scored. That brings back 82 s of target (12 chains), and with it the lives they cost in W05 (22.7 % of its target is
   wordless) and W07. W11's losses come from shorter chains and would stay fixed.
3. **History after the change.** *Recommended:* a new ruler (§4.3), so each song's median starts again with its next full
   pass. *Alternative:* re-score the stored traces into the new ruler. Only records and the last 20 attempts per song keep
   a trace, so the median would rest on a subset; this is listed under §6.

## 6. Deferred — not currently justified

- **A relative level gate in `build_map`** (drop frames more than 12 dB under the song's sung level). It would catch bleed
  inside lyric spans too: 131 s of quiet target lie within 0.5 s of a line, against 135 s outside. But quiet frames inside
  lines can be soft singing, nobody has listened to them, and the change needs every song re-prepared or re-mapped from
  PR #10's pitch cache. Revisit with the hand labels PR #10 asks for.
- **Dropping notes shorter than X ms.** Measured to hit sung notes as often as fragments (§3.3).
- **Octave-outlier removal.** 507 of 551 outliers sit inside sung phrases, and PR #10 measured an octave fix-up as harmful
  (§3.4).
- **An isolated-fragment rule for songs without lyrics.** 1.2 % of target, half of it real short notes, no lives at stake
  (§4.6).
- **Re-scoring stored traces into the new ruler.** Traces exist only for records and the last 20 attempts, so it would
  give a partial median, and it needs migration code for a one-time change.
- **A guard for partly failed transcriptions** (switch the rule off when it would exclude more than some share). The
  largest share today is W05's 22.7 %, and its long wordless chains have no word in the raw transcript either, so no
  failure of this kind was found.
- **Listening to the excluded passages** of W05 (536–590 s) and W11 to tell vocalise from backing voices. Under the rule
  they are unscored either way, so the answer changes nothing in the design.

## Appendix: reproduction

Scripts (outside the repository, not committed):

- `extract.py`: reads `LUMA_SONG` from every `songs/Luma_*.html` except lessons and assigns `W01…` in file order.
- `levels.py`: per-frame stem level (`vocals_44k.flac` × the manifest gain, 93 ms RMS on the points grid).
- `measure.py`: frame-level spans and per-note features.
- `clusters.py`: chains and the size, level and reliability tables.
- `rules.py`: the variants of §3.8 and the excluded spans.
- `table.py`: §3.5.
- `evidence.py`: §3.6, from `songs/logs/activity/*.jsonl`.
- `lives.py`: §3.7, a line-for-line port of `livesStep`.
- `find_shot.py` / `window.py`: §2.

Data as of 2026-10-11: 28 songs, the activity log of that day.
