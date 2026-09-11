# How a song becomes a trainer

`studio/prepare_song.py` runs eight steps. Everything except the optional transcription happens on your machine.

1. **Decode.** FFmpeg → 44.1 kHz stereo float WAV.
2. **Separation.** Official Demucs `htdemucs_ft` (four fine-tuned checkpoints, downloaded once from Meta's public bucket into
   `~/.cache/torch/hub/checkpoints`). `vocals` is the model output; `backing = mix − vocals`, so the two stems sum back to the
   original. A 5-minute song takes about 50 s on an RTX 3060 and several minutes on CPU.
3. **pYIN** (librosa) on the vocal stem: fundamental, voicing probability, RMS, plus plain YIN as a second opinion.
4. **CREPE** (`torchcrepe`, "full" model, Viterbi decoding, 10 ms hop) on the same stem. CREPE holds up far better than pYIN on
   rough, high or breathy passages.
5. **Map.** CREPE pitch is the source; pYIN is the cross-check.
   - *valid* frame: CREPE periodicity > 0.45, level > −43 dBFS, MIDI 43..90; runs shorter than 5 frames are dropped.
   - *reliable* frame: valid, periodicity ≥ 0.70, level > −38 dBFS, and either pYIN agrees within 50 cents or periodicity ≥ 0.85.
   - Notes: hysteretic labelling over a median-filtered contour (a change of more than 0.72 semitones starts a new note); a note is
     `ok` when at least 55 % of its frames are reliable. Phrases are short automatic groupings for the settings dialog.
6. **Stems.** MP3 at 1.0× and 0.8× (`atempo=0.8`, pitch preserved), padded/trimmed to identical lengths; a lossless FLAC copy of
   the vocal stem is kept in the package for listening.
7. **Lyrics (optional).** The mono mix is sent to Soniox `stt-async-v5`; tokens are merged into words with start/end times and
   grouped into lines. Skipped when no key is configured.
8. **HTML.** `build_html.py` embeds the map and the stems into the app.

## What the numbers mean
`comparableSeconds` / `comparablePercentOfTrack` count reliable frames only. Automatic maps of real songs typically reach
20–35 % of the track; the rest is instrumental, rough vocal, or too uncertain. Every map is a draft until a human confirms
fragments by ear in the app.

## Known limits
- Screamed, distorted or whispered vocals lose CREPE periodicity and drop out of the map.
- Backing vocals and doubled leads can be picked up as the melody in dense arrangements.
- Word recognition is automatic; expect occasional wrong words, timings are usually usable.
- Octave errors survive both estimators occasionally; the "Легко" level forgives them on purpose.
