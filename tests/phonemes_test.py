#!/usr/bin/env python3
"""studio/phonemes.py: lyric words → the sounds the trainer's head shapes (docs/design/VOCAL_TRACT_3D.md §4.5).

Dictionary words to IPA, the built-in lessons' syllables, a word neither the dictionary nor the rules read left out, the
trainer's LUMA_PHONES line, and the same output on two runs. The words are the lessons' syllables, the synthetic demo's
syllables, common English dictionary words and made-up words; no song from the library.
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'studio'))
sys.path.insert(0, str(ROOT / 'lessons'))
import phonemes as ph  # noqa: E402

# every symbol the head has a posture for (tools/gen_tract3d.ts VOWELS and CONSONANTS)
POSTURES = set('a e i o u y æ ø œ ɐ ɑ ɒ ɔ ə ɛ ɝ ɤ ɨ ɪ ɯ ʊ ʌ p b t d k g ʔ m n ŋ f v θ ð s z ʃ ʒ x h ɦ ts tʃ dʒ w ʋ ɹ j l r ɲ ʎ ç'.split())


def symbols(s: str) -> list[str]:
    return [p.rstrip('ʲ') for tok in s.split() for p in tok.split('+')]


class Dictionary(unittest.TestCase):
    def test_arpabet_to_ipa(self):
        self.assertEqual(ph.word_phones('time'), 't a+ɪ m')            # AY: one syllable, two vowels for the glide
        self.assertEqual(ph.word_phones('sing'), 's ɪ ŋ')
        self.assertEqual(ph.word_phones('voice'), 'v ɔ+ɪ s')
        self.assertEqual(ph.word_phones('the'), 'ð ə')                  # unstressed AH is a schwa
        self.assertEqual(ph.word_phones('love'), 'l ʌ v')               # stressed AH is not
        self.assertEqual(ph.word_phones('night'), 'n a+ɪ t')
        self.assertEqual(ph.word_phones('show'), 'ʃ o+ʊ')
        self.assertEqual(ph.word_phones('judge'), 'dʒ ʌ dʒ')

    def test_demo_syllables(self):
        for w, want in {'la': 'l ɑ', 'ta': 't ɑ', 'do': 'd u', 'ma': 'm ɑ', 'sa': 's ɑ', 'li': 'l i', 'mo': 'm o+ʊ'}.items():
            self.assertEqual(ph.word_phones(w), want, w)
        self.assertIsNone(ph.word_phones('ri'))                         # not in CMUdict: the trainer's letter rules read it

    def test_homograph_takes_the_first_entry(self):
        self.assertEqual(ph.word_phones('a'), 'ə')                      # «a  AH0» comes before «a(2)  EY1»

    def test_case_punctuation_and_apostrophes(self):
        self.assertEqual(ph.key(' Time, '), 'time')
        self.assertEqual(ph.key('don’t'), "don't")
        self.assertEqual(ph.word_phones('DON’T!'), 'd o+ʊ n t')
        self.assertEqual(ph.key('Ма́'), 'ма')                           # a stress mark is dropped

    def test_cyrillic_lookalikes_in_a_latin_word(self):
        self.assertEqual(ph.word_phones('tіmе'), ph.word_phones('time'))   # і and е are Cyrillic here

    def test_every_symbol_has_a_posture(self):
        for w in ['time', 'sing', 'voice', 'thought', 'measure', 'church', 'yellow', 'ring', 'world']:
            self.assertTrue(set(symbols(ph.word_phones(w))) <= POSTURES, w)


class Ukrainian(unittest.TestCase):
    def test_lesson_syllables(self):
        from definitions import LESSONS
        syllables = {s.pattern.syllable for lesson in LESSONS for s in lesson.sections}
        self.assertEqual(syllables, {'ма', 'но', 'лі', 'мі', 'а'})
        want = {'ма': 'm a', 'но': 'n ɔ', 'лі': 'l i', 'мі': 'm i', 'а': 'a'}
        for s in syllables: self.assertEqual(ph.word_phones(s), want[s], s)

    def test_rules(self):
        self.assertEqual(ph.word_phones('пісня'), 'p i s nʲ a')         # я after a consonant softens it
        self.assertEqual(ph.word_phones("сім'я"), 's i m j a')          # after the apostrophe: /j/ + vowel
        self.assertEqual(ph.word_phones('яблуко'), 'j a b l u k ɔ')     # at the start: /j/ + vowel
        self.assertEqual(ph.word_phones('сіль'), 's i lʲ')              # ь softens
        self.assertEqual(ph.word_phones('щастя'), 'ʃ tʃ a s tʲ a')
        self.assertEqual(ph.word_phones('джміль'), 'dʒ m i lʲ')
        self.assertEqual(ph.word_phones('дзвін'), 'd z ʋ i n')
        self.assertEqual(ph.word_phones('любов'), 'lʲ u b ɔ w')         # в closing a syllable after a vowel
        self.assertEqual(ph.word_phones('голос'), 'ɦ ɔ l ɔ s')
        self.assertTrue(set(symbols(ph.word_phones('хрущ'))) <= POSTURES)


class LeftOut(unittest.TestCase):
    def test_unreadable_words(self):
        for w in ['zorvik', 'blorvikest', 'ыы', '...', '', '42', 'мтк']:   # made up, letters outside the table, none, no vowel
            self.assertIsNone(ph.word_phones(w), w)

    def test_song_table(self):
        song = {'lyrics': [{'a': 0, 'b': 3, 'words': [{'a': 0, 'b': 1, 'w': 'Ма,'}, {'a': 1, 'b': 2, 'w': 'zorvik'}, {'a': 2, 'b': 3, 'w': 'time'}]},
                           {'a': 3, 'b': 4, 'words': [{'a': 3, 'b': 4, 'w': 'ма'}]}]}
        t = ph.song_phones(song)
        self.assertEqual(t, {'v': 1, 'words': {'time': 't a+ɪ m', 'ма': 'm a'}})
        self.assertEqual(ph.song_phones({}), {'v': 1, 'words': {}})
        self.assertEqual(ph.song_phones({'lyrics': [{'words': [{'w': 7}, 'x']}]}), {'v': 1, 'words': {}})

    def test_line_cannot_close_its_script(self):
        line = ph.phones_line({'lyrics': [{'words': [{'w': 'time'}]}]})
        self.assertTrue(line.startswith('<script>window.LUMA_PHONES={') and line.endswith('};</script>'))
        self.assertNotIn('<', line[len('<script>'):-len('</script>')])
        self.assertEqual(json.loads(line[len('<script>window.LUMA_PHONES='):-len(';</script>')]), {'v': 1, 'words': {'time': 't a+ɪ m'}})


class Repeatable(unittest.TestCase):
    def test_same_output_on_two_runs(self):
        code = ("import json,sys;sys.path.insert(0,'studio');import phonemes as p;"
                "print(json.dumps([p.word_phones(w) for w in ['time','пісня','ма','zorvik','voice','щастя']],ensure_ascii=False))")
        a, b = (subprocess.run([sys.executable, '-I', '-c', code], cwd=ROOT, capture_output=True, text=True, check=True).stdout for _ in range(2))
        self.assertEqual(a, b)
        self.assertEqual(json.loads(a), ['t a+ɪ m', 'p i s nʲ a', 'm a', None, 'v ɔ+ɪ s', 'ʃ tʃ a s tʲ a'])


if __name__ == '__main__':
    unittest.main(verbosity=1)
