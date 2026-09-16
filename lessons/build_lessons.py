#!/usr/bin/env python3
"""Build Luma's built-in singing lessons into a Studio library. Deterministic: no neural model, no network, no randomness.

Every lesson in lessons/definitions.py becomes one standalone trainer: a guide voice that sings the exact target melody,
a soft piano-and-pad backing with a gentle click, one syllable per note in the lyric lane, and a target map whose notes
are exact by construction (`ok` true, confidence 0.99) — so the strict corridor means what it says.

  build_lessons.py [--songs DIR]   build what is missing or stale (the default; a no-op in a few milliseconds when current)
  build_lessons.py --force         rebuild everything
  build_lessons.py --definitions   print the lesson definitions as JSON (used by tests/e2e/lessons.mjs)

Staleness has two levels: when only app/ changed, the existing trainers are re-wrapped with the current app code
(build_html --rebuild); when the lesson data changed, the audio and the map are synthesized again.
"""
from __future__ import annotations
import argparse, hashlib, json, subprocess, sys, tempfile, time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / 'studio'))
sys.path.insert(0, str(HERE))
from build_html import build, rebuild  # noqa: E402  (studio/build_html.py)
from definitions import LESSONS, Lesson  # noqa: E402

SR = 22050
HOP = .02                 # contour grid, as in the schema
LEAD_SILENCE = 1.0        # quiet head before the first count-in
TAIL = 1.5                # quiet tail after the last repetition
GAP_MAX, GAP_RATIO = .05, .22   # a note ends slightly before the next one starts, so notes stay separate
INDEX = 'lessons.index.html'    # the library server serves *.html only, so the lesson catalogue wears that extension
NAMES = ['C', 'C♯', 'D', 'D♯', 'E', 'F', 'F♯', 'G', 'G♯', 'A', 'A♯', 'B']
# Harmonic weights per vowel: enough colour that the guide sounds sung rather than beeped, cheap and deterministic.
VOWELS = {'a': (1, .55, .35, .18, .09, .05), 'o': (1, .45, .20, .09, .04, .02), 'e': (1, .60, .45, .25, .12, .06),
          'i': (1, .35, .50, .30, .12, .05), 'u': (1, .30, .12, .05, .02, .01)}

note_name = lambda m: NAMES[int(m) % 12] + str(int(m) // 12 - 1)
hz = lambda m: 440 * 2 ** ((m - 69) / 12)


def validate(lesson: Lesson) -> None:
    """Definition invariants that would otherwise fail quietly, long after the build reported success."""
    if not (lesson.file.startswith('Luma_') and lesson.file.endswith('.html')):
        raise SystemExit(f'{lesson.id}: the library lists Luma_*.html, so «{lesson.file}» would never appear in Studio')
    for section in lesson.sections:
        p = section.pattern
        if round((len(p.semitones) * p.beats + p.rest) % 1, 6):
            raise SystemExit(f'{lesson.id}: «{p.name}» must fill a whole number of beats, so the click stays on the grid')


def plan(lesson: Lesson):
    """Note-by-note timeline of a lesson: exact seconds and exact MIDI, the single source for audio, map and lyrics."""
    beat = 60 / lesson.bpm
    notes, reps, t = [], [], LEAD_SILENCE
    for index, section in enumerate(lesson.sections):
        p = section.pattern
        t += section.lead * beat
        for key in section.keys:
            start, first = t, len(notes)
            for semi in p.semitones:
                d, m = p.beats * beat, lesson.root + key + semi
                notes.append({'id': len(notes), 'a': round(t, 3), 'b': round(t + d - min(GAP_MAX, GAP_RATIO * d), 3),
                              'm': float(m), 'n': m, 'q': .99, 'ok': True, 'ignored': False,
                              'syllable': p.syllable, 'vowel': p.vowel, 'rep': len(reps)})
                t += d
            reps.append({'section': index, 'a': round(start, 3), 'b': round(t, 3), 'root': lesson.root + key,
                         'exercise': p.name, 'label': f'{p.name} · {note_name(lesson.root + key)}',
                         'first': first, 'last': len(notes) - 1})
            t += p.rest * beat
    return notes, reps, round(t + TAIL, 3), beat


def voice(notes: list[dict], n: int) -> np.ndarray:
    """The guide voice: harmonics shaped by the vowel, a soft attack and release, and vibrato only on long notes,
    so the sung pitch stays within a few cents of the target everywhere."""
    out = np.zeros(n)
    for note in notes:
        i0, i1 = int(note['a'] * SR), min(n, int(note['b'] * SR))
        if i1 <= i0:
            continue
        length = (i1 - i0) / SR
        seg = np.arange(i1 - i0) / SR
        depth = np.clip((seg - .35) / .45, 0, 1) * .002          # ±3.5 ¢ at most, and never on short notes
        f = hz(note['m']) * (1 + depth * np.sin(2 * np.pi * 5.3 * seg))
        phase = 2 * np.pi * np.cumsum(f) / SR
        env = np.minimum(1, seg / min(.03, .3 * length)) * np.minimum(1, (length - seg) / min(.08, .35 * length))
        tone = sum(a * np.sin(k * phase) for k, a in enumerate(VOWELS[note['vowel']], start=1))
        out[i0:i1] += env * tone
    return out


def backing(reps: list[dict], beat: float, duration: float, n: int) -> np.ndarray:
    """Piano chord on every repetition, a quiet pad under it, and a click on every beat with the downbeat accented."""
    out = np.zeros(n)
    def add(start, samples, wave):
        i0 = int(start * SR); i1 = min(n, i0 + samples)
        if i1 > i0:
            out[i0:i1] += wave[:i1 - i0]
    for rep in reps:
        base = rep['root'] - 12
        chord = np.arange(int(2.2 * SR)) / SR
        struck = np.zeros_like(chord)
        for semi, gain in ((0, .10), (4, .07), (7, .07), (12, .05)):      # major triad of the key, softly struck
            for k, a in ((1, 1.), (2, .35), (3, .14), (4, .06)):
                struck += gain * a * np.sin(2 * np.pi * hz(base + semi) * k * chord) * np.exp(-chord * (1.1 + .45 * k))
        add(rep['a'] - .12, len(chord), struck * np.minimum(1, chord / .006))
        span = rep['b'] - rep['a'] + .5                                    # pad: root and fifth, barely there
        pad = np.arange(int(span * SR)) / SR
        shape = np.minimum(1, pad / .35) * np.minimum(1, (span - pad) / .5)
        add(rep['a'] - .25, len(pad), shape * sum(.035 * np.sin(2 * np.pi * hz(base + semi) * pad) for semi in (0, 7)))
    starts = np.array([rep['a'] for rep in reps])
    click = np.arange(int(.06 * SR)) / SR
    t = LEAD_SILENCE
    while t < duration - TAIL + 1e-6:
        accent = bool(np.any(np.abs(starts - t) < 1e-3))
        add(t, len(click), (.075 if accent else .04) * np.sin(2 * np.pi * (2200 if accent else 1500) * click) * np.exp(-click / .012))
        t += beat
    return out


def encode(package: Path, source: Path, role: str, duration: float) -> None:
    for speed, suffix in ((1, ''), (.8, '_80')):
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(source),
                        '-af', f'atempo={speed},apad,atrim=duration={duration / speed:.9f}',
                        '-ac', '1', '-c:a', 'libmp3lame', '-b:a', '64k', '-write_xing', '1',
                        str(package / f'{role}{suffix}.mp3')], check=True)


def target(lesson: Lesson, notes, reps, duration, mix) -> dict:
    """The song package: scalars first, so the Studio library can read title / artist / duration from the head of the file."""
    sung = round(sum(x['b'] - x['a'] for x in notes), 2)
    song = {
        'schema': 'luma.song.v1', 'title': lesson.title, 'artist': lesson.artist, 'duration': duration, 'a4': 440, 'hop': HOP,
        'status': 'exact_synthetic', 'neuralSeparation': False,
        'method': f'Synthetic lesson: exact target melody and guide voice generated by lessons/build_lessons.py ({lesson.bpm:g} BPM, root {note_name(lesson.root)})',
        'warning': 'Урок синтезовано: мелодія-ціль точна за побудовою, а голос-провідник співає саме її.',
        'createdBy': 'lessons/build_lessons.py', 'initialTime': round(max(0, notes[0]['a'] - 1), 2),
        'lesson': {'id': lesson.id, 'level': lesson.level, 'bpm': lesson.bpm},
        'metrics': {'notes': len(notes), 'candidateSeconds': sung, 'comparableSeconds': sung,
                    'comparablePercentOfTrack': round(100 * sung / duration, 1)},
    }
    # Keyed by the music alone: rewording a description must not orphan the note edits and confirmations a user saved.
    music = {k: v for k, v in asdict(lesson).items() if k in ('id', 'bpm', 'root', 'sections')}
    song['id'] = hashlib.sha256(json.dumps(music, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]
    song['sourceId'] = hashlib.sha256(mix.tobytes()).hexdigest()
    points, index = [], 0
    for step in range(int(round(duration / HOP)) + 1):
        t = round(step * HOP, 3)
        if t > duration:
            break
        while index < len(notes) and notes[index]['b'] <= t:
            index += 1
        inside = index < len(notes) and notes[index]['a'] <= t
        points.append([t, notes[index]['m'] if inside else None, .99 if inside else 0, 1 if inside else 0])
    song['points'] = points
    song['notes'] = [{k: v for k, v in n.items() if k not in ('syllable', 'vowel', 'rep')} for n in notes]
    song['phrases'] = [{'id': i + 1, 'a': round(max(0, r['a'] - .8), 2), 'b': round(min(duration, r['b'] + .2), 2),
                        'label': r['label'], 'exercise': r['exercise'], 'verified': False} for i, r in enumerate(reps)]
    song['waveform'] = [round(float(np.max(np.abs(z))), 3) for z in np.array_split(mix, 1000)]
    song['lyrics'] = [{'a': notes[r['first']]['a'], 'b': notes[r['last']]['b'],
                       'words': [{'a': n['a'], 'b': n['b'], 'w': n['syllable'], 'c': .99} for n in notes[r['first']:r['last'] + 1]]}
                      for r in reps]
    song['lyricsSource'] = 'lesson syllables'
    return song


def make(lesson: Lesson, songs: Path) -> dict:
    notes, reps, duration, beat = plan(lesson)
    n = int(duration * SR)
    fore = voice(notes, n)
    back = backing(reps, beat, duration, n)
    fore *= .72 / max(1e-9, np.max(np.abs(fore)))
    back *= .5 / max(1e-9, np.max(np.abs(back)))
    song = target(lesson, notes, reps, duration, fore + back)
    with tempfile.TemporaryDirectory(prefix='luma-lesson-') as tmp:
        package = Path(tmp)
        for role, signal in (('foreground', fore), ('backing', back)):
            wav = package / f'{role}.wav'
            sf.write(wav, signal.astype('float32'), SR)
            encode(package, wav, role, duration)
            wav.unlink()
        (package / 'target.json').write_text(json.dumps(song, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        # Into place in one step: an interrupted build must never leave a half-written trainer that looks finished.
        staging = songs / (lesson.file + '.part')
        build(package, staging); staging.replace(songs / lesson.file)
    lo, hi = min(x['n'] for x in notes), max(x['n'] for x in notes)
    return {'order': lesson.order, 'id': lesson.id, 'html': lesson.file, 'title': lesson.title, 'artist': lesson.artist,
            'level': lesson.level, 'summary': lesson.summary, 'description': lesson.description, 'bpm': lesson.bpm,
            'duration': duration, 'notes': len(notes), 'repetitions': len(reps),
            'range': f'{note_name(lo)}–{note_name(hi)}', 'bytes': (songs / lesson.file).stat().st_size}


def digest(paths) -> str:
    h = hashlib.sha256()
    for p in paths:
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def fingerprints() -> tuple[str, str]:
    """Lesson data (audio and map) and app code (the wrapper around the data) age independently."""
    return (digest([HERE / 'definitions.py', HERE / 'build_lessons.py']),
            digest([ROOT / 'app' / 'head.html', ROOT / 'app' / 'workers.html', ROOT / 'app' / 'app.js', ROOT / 'studio' / 'build_html.py']))


def read_index(songs: Path) -> dict | None:
    try:
        text = (songs / INDEX).read_text(encoding='utf-8')
        index = json.loads(text.split('<script type="application/json" id="luma-lessons">')[1].split('</script>')[0])
        return index if isinstance(index, dict) and isinstance(index.get('lessons'), list) else None
    except (OSError, IndexError, ValueError):
        return None


def write_index(songs: Path, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    (songs / INDEX).write_text(
        '<!doctype html><html lang="uk"><head><meta charset="utf-8"><title>Luma · уроки</title></head><body>\n'
        '<script type="application/json" id="luma-lessons">' + body + '</script>\n'
        '<p>Каталог вбудованих уроків Luma. Його читає сторінка Studio; уроки відкриваються зі списку бібліотеки.</p>\n'
        '</body></html>\n', encoding='utf-8')


def ensure(songs: Path, force: bool = False) -> dict:
    for lesson in LESSONS:
        validate(lesson)
    songs.mkdir(parents=True, exist_ok=True)
    data_fp, app_fp = fingerprints()
    index = None if force else read_index(songs)
    current = bool(index) and index.get('data') == data_fp and all((songs / l.file).is_file() for l in LESSONS)
    if current and index.get('app') == app_fp:
        return {'action': 'current', 'lessons': index['lessons']}
    started = time.time()
    if current:                                    # only app/ moved: keep the data line, swap in the current app parts
        try:
            for lesson in LESSONS:
                rebuild(songs / lesson.file)
            payload = {**index, 'app': app_fp, 'built': time.strftime('%Y-%m-%d %H:%M:%S')}
            for entry in payload['lessons']:
                entry['bytes'] = (songs / entry['html']).stat().st_size
            write_index(songs, payload)
            return {'action': 'rewrapped', 'seconds': round(time.time() - started, 1), 'lessons': payload['lessons']}
        except (OSError, ValueError, KeyError, SystemExit):
            pass                                   # a trainer we cannot re-wrap is synthesized again below
    lessons = [make(lesson, songs) for lesson in sorted(LESSONS, key=lambda l: l.order)]
    write_index(songs, {'data': data_fp, 'app': app_fp, 'built': time.strftime('%Y-%m-%d %H:%M:%S'), 'lessons': lessons})
    return {'action': 'built', 'seconds': round(time.time() - started, 1), 'lessons': lessons}


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--songs', default=str(ROOT / 'songs'), help='library directory (default: songs/)')
    ap.add_argument('--force', action='store_true', help='rebuild even when nothing changed')
    ap.add_argument('--definitions', action='store_true', help='print the lesson definitions as JSON and exit')
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args()
    for lesson in LESSONS:
        validate(lesson)
    if a.definitions:
        print(json.dumps({'timing': {'leadSilence': LEAD_SILENCE, 'tail': TAIL, 'gapMax': GAP_MAX, 'gapRatio': GAP_RATIO, 'hop': HOP},
                          'lessons': [asdict(l) for l in sorted(LESSONS, key=lambda l: l.order)]}, ensure_ascii=False))
        raise SystemExit(0)
    result = ensure(Path(a.songs).expanduser().resolve(), a.force)
    if not a.quiet:
        if result['action'] == 'current':
            print('lessons: up to date')
        else:
            print(f"lessons: {result['action']} in {result['seconds']} s")
            for l in result['lessons']:
                print(f"  {l['html']}  {l['title']} · {l['level']} · {int(l['duration']) // 60}:{int(l['duration']) % 60:02d} · "
                      f"{l['range']} · {l['notes']} notes · {l['bytes'] // 1048576} MB")
