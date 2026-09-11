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
notes view a hit is a filled bar with a solid outline and a ✓; a miss is a diagonally hatched bar with an ×, dotted when the
miss was silence; a draft note has a dashed outline. In the contour view every scored note gets a marker under it: a filled
disc with a ✓ for a hit, a dashed ring with an × for a miss. The sung trace is mint inside the corridor, subdued red
outside, dim where there was no target. The current note glows while you are inside it.

## Trace history
Every attempt keeps its timestamped pitch points and the per-frame state array. The trace stays on screen after the take:
drag the plot, use ← → or the wheel, or jump between misses. ▶ on an attempt plays your voice over the backing in sync with
the same trace. CSV export includes the per-point match state.

## Punch-in
With an attempt on screen and the playhead inside it, "Співати" becomes "Перезаписати з …" and re-records that attempt from the
playhead: old audio before the point, new audio, then the old tail beyond the new end. Seeking back while singing does the
same. The WAV and the points are spliced and rescored.

## Strict statistics
"У коридорі", "Покриття" and "Медіана |Δ|" on attempt cards use only `ok` frames inside fragments the user confirmed by ear.
They exist so that a verified fragment can be judged without draft noise.
