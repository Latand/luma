"""Every built-in Luma lesson lives here: the musical pattern, the key sweep and the Ukrainian text shown in Studio.

Adding a lesson means appending one `Lesson` below — `lessons/build_lessons.py` synthesizes the guide voice, the backing
and the exact target map from this data alone. Nothing here is random: the same definitions always produce the same files.

Pitch is MIDI (A4 = 69 = 440 Hz). A pattern is written as semitones above the root of the current key, so the same shape
can be moved through the keys. The classic warm-up form is a pattern repeated a semitone higher each time, with a breath
rest in between, up to the top key and back down; `Section.keys` spells that sweep out.
"""
from __future__ import annotations
from dataclasses import dataclass

MAJOR = (0, 2, 4, 5, 7, 9, 11, 12, 14, 16, 17, 19)  # semitones of major-scale degrees 1..12


def degrees(*ds: int) -> tuple[int, ...]:
    """Scale degrees → semitones above the root: degrees(1, 3, 5, 8) == (0, 4, 7, 12)."""
    return tuple(MAJOR[d - 1] for d in ds)


def sweep(top: int) -> tuple[int, ...]:
    """A semitone key sweep: `top` keys upward, then back down to the starting key."""
    return tuple(range(top)) + tuple(range(top - 2, -1, -1))


@dataclass(frozen=True)
class Pattern:
    name: str                    # short label, used for practice fragments
    syllable: str                # sung on every note; also the lyric under the melody
    semitones: tuple[int, ...]   # one entry per note, relative to the key root
    beats: float                 # length of every note in the pattern
    rest: float                  # breath rest after the pattern, in beats
    vowel: str = 'a'             # shapes the guide voice timbre: 'a', 'o', 'e', 'i', 'u'


@dataclass(frozen=True)
class Section:
    pattern: Pattern
    keys: tuple[int, ...]        # semitone offset of the key root for each repetition, in order
    lead: float = 4              # count-in beats before the first repetition (also the gap after the previous section)


@dataclass(frozen=True)
class Lesson:
    id: str
    order: int                   # position in Studio: beginner first
    file: str                    # trainer file name in the library
    title: str
    artist: str
    level: str                   # the level to set in the trainer; matches its «Рівень» buttons
    bpm: float
    root: int                    # MIDI note of the first key root
    sections: tuple[Section, ...]
    summary: str                 # one sentence: what this lesson trains
    description: str             # syllable, breathing, level, what to watch, vocal octave


SUSTAIN_MA = Pattern('Витримана нота', 'ма', (0,), beats=4, rest=3, vowel='a')
SCALE_5 = Pattern('Гама 1–5', 'ма', degrees(1, 2, 3, 4, 5, 4, 3, 2, 1), beats=1, rest=4, vowel='a')
ARPEGGIO = Pattern('Арпеджіо 1-3-5-8', 'но', degrees(1, 3, 5, 8, 5, 3, 1), beats=1, rest=2, vowel='o')
THIRDS = Pattern('Терції легато', 'лі', degrees(1, 3, 2, 4, 3, 5, 4, 2, 1), beats=.5, rest=2.5, vowel='i')
OCTAVE_LEAP = Pattern('Стрибок на октаву', 'а', degrees(1, 8, 1), beats=2, rest=2, vowel='a')
SCALE_9 = Pattern('Гама 1–9', 'а', degrees(1, 2, 3, 4, 5, 6, 7, 8, 9, 8, 7, 6, 5, 4, 3, 2, 1), beats=.25, rest=1.75, vowel='a')
ARPEGGIO_12 = Pattern('Арпеджіо 1-5-8-12', 'но', degrees(1, 5, 8, 12, 8, 5, 1), beats=1, rest=2, vowel='o')
CHROMATIC = Pattern('Хроматичний хід', 'мі', (0, 1, 2, 3, 4, 5, 6, 7, 6, 5, 4, 3, 2, 1, 0), beats=.5, rest=2.5, vowel='i')
HIGH_HOLD = Pattern('Довга нота', 'а', degrees(8,), beats=8, rest=4, vowel='a')

LESSONS: tuple[Lesson, ...] = (
    Lesson(
        id='beginner', order=1, file='Luma_Lesson_1_Novachok.html',
        title='Урок 1 · Новачок', artist='Luma · розспівка', level='Легко', bpm=70, root=60,
        sections=(
            Section(SUSTAIN_MA, keys=(0, 1, 2, 3)),
            Section(SCALE_5, keys=sweep(5)),
        ),
        summary='Влучити в ноту, утримати її рівно — і проспівати перші п’ять щаблів гами вниз і вгору.',
        description='Спочатку чотири витримані ноти на «ма»: вдихни носом і тримай звук рівно, без коливань. '
                    'Далі гама 1-2-3-4-5-4-3-2-1 на той самий склад, п’ять півтонів угору і назад; у паузі — спокійний вдих. '
                    'Рівень «Легко» (±80 ¢) прощає невеликий промах і помилку на октаву. '
                    'Дивись, щоб лінія голосу йшла серединою нот. '
                    'Діапазон C4–B4; для нижчого чи вищого голосу перемкни «Вокальну октаву» — мінус лишиться тим самим.',
    ),
    Lesson(
        id='intermediate', order=2, file='Luma_Lesson_2_Seredniy.html',
        title='Урок 2 · Середній', artist='Luma · розспівка', level='Звично', bpm=84, root=57,
        sections=(
            Section(ARPEGGIO, keys=sweep(6)),
            Section(THIRDS, keys=sweep(6)),
            Section(OCTAVE_LEAP, keys=sweep(6)),
        ),
        summary='Три форми поспіль: арпеджіо, терції легато і чистий стрибок на октаву.',
        description='Арпеджіо 1-3-5-8-5-3-1 на «но», терції 1-3-2-4-3-5-4-2-1 на «лі» суцільною лінією без поштовхів, '
                    'стрибок 1-8-1 на «а»: верхню ноту бери на тій самій опорі дихання. '
                    'Шість півтонів угору і назад у кожній вправі, вдих лише в паузі. Рівень «Звично», коридор ±50 ¢. '
                    'Слідкуй за стрибком: саме там лінія найчастіше падає нижче цілі. '
                    'Діапазон A3–D5; нижчі та вищі голоси перемикають «Вокальну октаву» в налаштуваннях.',
    ),
    Lesson(
        id='expert', order=3, file='Luma_Lesson_3_Ekspert.html',
        title='Урок 3 · Експерт', artist='Luma · розспівка', level='Точно', bpm=110, root=55,
        sections=(
            Section(SCALE_9, keys=sweep(5)),
            Section(ARPEGGIO_12, keys=sweep(5)),
            Section(CHROMATIC, keys=sweep(5)),
            Section(HIGH_HOLD, keys=(0, 1, 2, 1, 0)),
        ),
        summary='Швидка гама на дев’ять щаблів, арпеджіо через дуодециму, хроматика і довга нота нагорі.',
        description='Гама 1-2-3-4-5-6-7-8-9 і назад шістнадцятими на «а» — рівно, без прискорення в кінці. '
                    'Далі арпеджіо 1-5-8-12-8-5-1 на «но», хроматичний хід на «мі» й довга нота на октаві у вісім долей. '
                    'Темп 110, вдих у паузі, плечі опущені. Рівень «Точно», коридор ±35 ¢: тут чутно кожну ноту пасажу. '
                    'Слідкуй за хроматикою, де найлегше змазати півтон, і за довгою нотою: лінія має триматися рівно до кінця. '
                    'Діапазон G3–F♯5; октаву голосу можна перемкнути в налаштуваннях.',
    ),
)
