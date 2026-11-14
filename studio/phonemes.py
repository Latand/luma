#!/usr/bin/env python3
"""Lyric words → the sounds the trainer's head shapes («Голова», app/tract3d.js; docs/design/VOCAL_TRACT_3D.md §4.5).

build_html.wrap() writes one line before the app scripts of every trainer:

    <script>window.LUMA_PHONES={"v":1,"words":{"ма":"m a","time":"t a+ɪ m",…}};</script>

Keys are the song's distinct lyric words, normalised by key() (app/tract3d.js normalises the same way). Values are
space-separated IPA symbols from the 55 postures the head knows; `+` joins a diphthong's glide to its first vowel
(«a+ɪ» is one syllable), and `ʲ` after a consonant marks it soft. A word this module cannot read is left out: the
trainer then reads it with letter rules and marks it «приблизно».

  English    CMUdict (studio/data/cmudict.txt.gz, licence beside it), first pronunciation of a homograph, stress
             dropped, unstressed AH as /ə/, the diphthongs AW AY EY OW OY as two vowels. A word written mostly in Latin
             letters has its look-alike Cyrillic letters read as Latin first.
  Ukrainian  rules: the spelling is close to the sound. A word with a letter outside the table is left out.

    python3 studio/phonemes.py слово word …      prints each word's sounds
"""
from __future__ import annotations
import gzip, json, re, sys, unicodedata
from functools import lru_cache
from pathlib import Path

DICT = Path(__file__).resolve().parent / 'data' / 'cmudict.txt.gz'
ARPABET = {'AA': 'ɑ', 'AE': 'æ', 'AH': 'ʌ', 'AO': 'ɔ', 'AW': 'a+ʊ', 'AY': 'a+ɪ', 'EH': 'ɛ', 'ER': 'ɝ', 'EY': 'e+ɪ', 'IH': 'ɪ',
           'IY': 'i', 'OW': 'o+ʊ', 'OY': 'ɔ+ɪ', 'UH': 'ʊ', 'UW': 'u', 'B': 'b', 'CH': 'tʃ', 'D': 'd', 'DH': 'ð', 'F': 'f',
           'G': 'g', 'HH': 'h', 'JH': 'dʒ', 'K': 'k', 'L': 'l', 'M': 'm', 'N': 'n', 'NG': 'ŋ', 'P': 'p', 'R': 'ɹ', 'S': 's',
           'SH': 'ʃ', 'T': 't', 'TH': 'θ', 'V': 'v', 'W': 'w', 'Y': 'j', 'Z': 'z', 'ZH': 'ʒ'}
LOOKALIKE = str.maketrans('аеорсухі', 'aeopcyxi')
UK_VOWEL = {'а': 'a', 'е': 'ɛ', 'и': 'ɪ', 'і': 'i', 'о': 'ɔ', 'у': 'u'}
UK_IOTATED = {'я': 'a', 'ю': 'u', 'є': 'ɛ', 'ї': 'i'}
UK_CONS = {'б': 'b', 'в': 'ʋ', 'г': 'ɦ', 'ґ': 'g', 'д': 'd', 'ж': 'ʒ', 'з': 'z', 'й': 'j', 'к': 'k', 'л': 'l', 'м': 'm',
           'н': 'n', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'ф': 'f', 'х': 'x', 'ц': 'ts', 'ч': 'tʃ', 'ш': 'ʃ',
           'щ': 'ʃ tʃ'}
APOSTROPHES = re.compile(r"[’ʼ`´]")
MARKS = re.compile(r'[̀-ͯ]')
EDGE = re.compile(r"^(?:[^\w']|[\d_])+|(?:[^\w']|[\d_])+$")


def key(word: str) -> str:
    """The form a lyric word is looked up by: NFC, no stress marks, one apostrophe, lower case, no edge punctuation."""
    w = MARKS.sub('', unicodedata.normalize('NFC', str(word)))
    return EDGE.sub('', APOSTROPHES.sub("'", w).lower())


@lru_cache(maxsize=1)
def dictionary() -> dict[str, str]:
    out: dict[str, str] = {}
    with gzip.open(DICT, 'rt', encoding='utf-8') as f:
        for line in f:
            word, _, phones = line.rstrip('\n').partition('\t')
            if word and phones and word not in out: out[word] = phones
    return out


def english(word: str) -> str | None:
    arpa = dictionary().get(word)
    if not arpa: return None
    out = []
    for p in arpa.split():
        base, stress = p.rstrip('012'), p[len(p.rstrip('012')):]
        if base not in ARPABET: return None
        out.append('ə' if base == 'AH' and stress == '0' else ARPABET[base])
    return ' '.join(out)


def ukrainian(word: str) -> str | None:
    out: list[str] = []
    letters = [c for c in word if c != "'"]
    i, prev = 0, ''          # prev: what came before ('' at the start, 'v' a vowel, 'c' a consonant, "'" an apostrophe)
    chars = list(word)
    while i < len(chars):
        c = chars[i]
        if c == "'":
            prev = "'"; i += 1; continue
        if c == 'ь':
            if out and out[-1] not in UK_VOWEL.values() and not out[-1].endswith('ʲ') and prev == 'c': out[-1] += 'ʲ'
            i += 1; continue
        if c in UK_VOWEL:
            out.append(UK_VOWEL[c]); prev = 'v'; i += 1; continue
        if c in UK_IOTATED:
            v = UK_IOTATED[c]
            if c != 'ї' and prev == 'c' and out and not out[-1].endswith('ʲ'): out[-1] += 'ʲ'; out.append(v)
            else: out += ['j', v]
            prev = 'v'; i += 1; continue
        nxt = chars[i + 1] if i + 1 < len(chars) else ''
        if c == 'д' and nxt == 'ж':
            out.append('dʒ'); prev = 'c'; i += 2; continue
        if c == 'д' and nxt == 'з':
            out += ['d', 'z']; prev = 'c'; i += 2; continue
        if c in UK_CONS:
            s = UK_CONS[c]
            # в closing a syllable after a vowel (before a consonant or at the word's end) is a /w/
            if c == 'в' and prev == 'v' and (not nxt or (nxt in UK_CONS or nxt == 'ь')): s = 'w'
            out += s.split(); prev = 'c'; i += 1; continue
        return None
    if not letters or not any(p.split('+')[0] in UK_VOWEL.values() for p in out): return None
    return ' '.join(out)


def word_phones(word: str) -> str | None:
    """The sounds of one lyric word, or None when it cannot be read here."""
    w = key(word)
    if not w: return None
    latin = sum('a' <= c <= 'z' for c in w); cyr = sum('Ѐ' <= c <= 'ӿ' for c in w)
    if latin and latin >= cyr: return english(w.translate(LOOKALIKE))
    if cyr: return ukrainian(w)
    return None


def song_phones(song: dict) -> dict:
    words: dict[str, str] = {}
    for line in song.get('lyrics') or []:
        for w in (line.get('words') or []) if isinstance(line, dict) else []:
            k = key(w.get('w', '')) if isinstance(w, dict) else ''
            if not k or k in words: continue
            p = word_phones(k)
            if p: words[k] = p
    return {'v': 1, 'words': dict(sorted(words.items()))}


def phones_line(song: dict) -> str:
    """The trainer's LUMA_PHONES line; JSON cannot close the script element it sits in."""
    return '<script>window.LUMA_PHONES=' + json.dumps(song_phones(song), ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c') + ';</script>'


if __name__ == '__main__':
    for arg in sys.argv[1:]: print(arg, '→', word_phones(arg) or '(left out)')
