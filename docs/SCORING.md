# Scoring, levels and the recorded trace

## Live match ("Збіг з ціллю")
The song is split into 20 ms frames from the start of the attempt. For every frame:

- **no target drawn** (no note or contour there) → the frame is excluded from both numerator and denominator;
- **target present** → the frame counts. It is a **hit** when a confident sung pitch (YIN periodicity ≥ 0.8) exists within the
  level's time slack and its distance to the target is inside the corridor; **silence, noise or low-confidence pitch under a
  target is a miss**.

`match = hits ÷ frames with a target`. Draft (dashed) targets count too; the readout says "чернетка" while the fragment is
unverified. Each frame is scored once, so seeking, redrawing and looping never double-count. The same engine scores finished
attempts, which is why the live number and the attempt card agree.

## Levels

| level | corridor | time slack | note counts as ✓ when | octave |
|---|---|---|---|---|
| Легко | ±80 ¢ | 120 ms | ≥ 35 % of its frames hit | forgiven (distance folded into ±6 semitones) |
| Звично | ±50 ¢ | 60 ms | ≥ 50 % | strict |
| Точно | ±35 ¢ | 50 ms | ≥ 65 % | strict |

A custom corridor typed in settings switches to "свій коридор" with the Звично timing parameters. The level is stored in each
attempt, so a card keeps the rules it was recorded with.

## Colour and non-colour cues
Fill and outline carry the state on their own, so hit and miss stay apart for an eye that does not read the colours. In the
notes view a hit is the only solid bar on the roll, carrying a ✓ and its note name in dark ink; a miss is a diagonally
hatched bar with an ×, dotted when the miss was silence; a draft note has a dashed outline and light type. Every label is
measured off the canvas against the bar under it and has to clear 4.5:1. In the contour view every scored note gets a marker under it: a filled
disc with a ✓ for a hit, a dashed ring with an × for a miss. The sung trace is mint inside the corridor, subdued red
outside, dim where there was no target. The current note glows while you are inside it.

## Attempts are traces, audio is optional
Recording the voice into a WAV is a switch in the settings and it is **off by default**. The microphone always runs — there
is no pitch without it — but with the switch off the worker keeps no PCM and the attempt has no blob. Everything else is
unchanged: the attempt keeps its timestamped pitch points and its per-frame state array, it stays on screen after the run,
it is scored the same way, and it goes into the local history. ▶ on such an attempt plays the backing in sync with the
trace instead of your voice; the WAV button is absent and CSV and JSON are not. Punch-in needs the attempt and the switch
to agree: re-recording into an attempt recorded the other way would leave half of it with audio and half without.

Two budgets apply to the tab; the history has neither. Traces: 20 attempts and 400 000 points, and they never stop
practice. When a new attempt needs room, the oldest attempt that is already in the history, holds no WAV, is not on screen
and is not held by undo leaves the tab by itself. «Співати» refuses only when no attempt qualifies, and the message then
asks to save what matters as a file. Audio: the old 10 attempts / 100 MiB, and only while the switch is on. Every pass of
the A–B auto-repeat is an attempt of its own.

## Trace history
The trace stays on screen after the take: drag the plot, use ← → or the wheel, or jump between misses. CSV export includes
the per-point match state. Every finished attempt is also written to a local practice history — see
[docs/HISTORY_SCHEMA.md](HISTORY_SCHEMA.md).

## Punch-in
With an attempt on screen and the playhead inside it, "Співати" becomes "Перезаписати з …" and re-records that attempt from the
playhead: old audio before the point, new audio, then the old tail beyond the new end. Seeking back while singing does the
same. The WAV and the points are spliced and rescored; with the recording switch off only the points and the duration are.
The attempt and the switch have to agree, and so do the speeds — otherwise the button says "Співати" and a separate
attempt is recorded.

## Strict statistics
"У коридорі", "Покриття" and "Медіана |Δ|" on attempt cards use only `ok` frames inside fragments the user confirmed by ear.
They exist so that a verified fragment can be judged without draft noise.

## Scores that can stand side by side
Every attempt also stores three numbers derived from the same pass over its frames: **voice coverage** (`sung ÷ target`,
so silence under a target is visible on its own), the **median |Δ|** in cents over every drawn target, and the **draft
share** — frames whose target has `ok = 0`. Draft targets count towards the match exactly as they do live; there is no
separate "draft scale", because draftness is a property of the target map and the map version is already part of the key
below. The Прогрес tab prints the share for the area on screen (the song, the phrase or the A–B fragment), and a record
over any draft target is labelled «Рекорд · за чернеткою», the way the attempt card says «Попередня оцінка за чернеткою»,
so a number never passes for more than it is.

Two scores may be compared only when they were measured with the same ruler:

```
cmpKey = songHash · mapVersion · level · view · speed
```

Re-preparing a song opens a new `mapVersion` and keeps the history; editing a note opens a new one too, because you
changed the target; confirming a fragment by ear does not, because `verified` never reaches `targetAt().m`. The vocal
octave is not in the key: it moves the target and leaves the difficulty alone. The microphone shift is not in it either —
it is not scored and it is not calibrated.

A re-scored attempt (a changed view or vocal octave) is re-summarized with it, so the card and the JSON it exports never
mix two rulers; the history keeps the run as it was measured when it finished.

The numbers over a fragment are read the same way. An A–B region has no entity of its own: when it lines up with a
phrase, every attempt that counted that phrase — a pass of the fragment or a pass of the whole song — contributes its
score *for that phrase*, never its whole-song percentage. An A–B that is not a phrase is spoken for only by attempts
recorded at that very fragment.

**Song record**: the best match among full passes of one ruler (≥ 95 % of the song's frames with a target, at least 4 s of
them). **Phrase record**: the best match among attempts that covered ≥ 80 % of that phrase, with at least 1.5 s of target
in it — without those floors "100 % over 0.3 s" would hold first place forever. A phrase with under 1.5 s of target in
the whole map can therefore never hold one: the weak-phrase map labels it «закоротка для рекорду», puts it last and leaves
it out of the count of phrases without a counted attempt. Ties go to the smaller median |Δ|, then to
the earlier date. For a lesson a record is also kept per exercise, on each level separately, because one exercise is one
skill sung in nine keys. Rhythm and entry timing are still not scored: the end-to-end microphone latency is not measured,
so a rhythm mark would be an invention.
