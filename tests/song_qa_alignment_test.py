"""Token ownership regressions using the project tokenizer and real sheet CLI.

Usage: python tests/song_qa_alignment_test.py
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/song_qa'))
import fa_align as fa
from lyric_tokens import tokenize


# All text is synthetic; expected spans are independent of tokenizer/model code.
SHAPES = [
    ('flim-borp nuv', [(1., 1.7), (1.8, 2.1)]),
    ('nuv flim-borp zas', [(1., 1.3), (1.4, 2.1), (2.2, 2.5)]),
    ('nuv flim-borp', [(1., 1.3), (1.4, 2.1)]),
    ('flim–borp nuv', [(1., 1.7), (1.8, 2.1)]),
    ('flim—borp nuv', [(1., 1.7), (1.8, 2.1)]),
    ("flim's borp’s", [(1., 1.3), (1.4, 1.7)]),
    ('flim, borp!', [(1., 1.3), (1.4, 1.7)]),
    ('flim flim-borp flim', [(1., 1.3), (1.4, 2.1), (2.2, 2.5)]),
    ('flim 123 borp', None),
    ('flim q12 borp', None),
    ('flim абв borp', None),
    ('flim café borp', None),
    ('flim q́ borp', None),
    ('flim !!! borp', None),
    ('flim — borp', None),
]


def target_line(text):
    return {'words': [dict(w=w, a=10.+k, b=10.5+k) for k, w in enumerate(tokenize(text))]}


def proposal(text, row=0):
    return dict(line=row, words=[dict(owner, a=round(1.+k*.4, 1), b=round(1.3+k*.4, 1))
                                for k, owner in enumerate(fa.model_word_owners(text, row))])


class Alignment(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        # These fail loudly if either CLI imports an audio/model dependency.
        for name in ('soundfile', 'torch', 'torchaudio', 'librosa'):
            (self.root / (name + '.py')).write_text("raise RuntimeError('dependency imported')")
        self.env = {**os.environ, 'PYTHONPATH': str(self.root)}

    def sheet(self, lyrics, alignment):
        (self.root / 'target.json').write_text(json.dumps(dict(lyrics=lyrics)))
        (self.root / 'fa.json').write_text(json.dumps(alignment))
        return subprocess.run([sys.executable, str(ROOT / 'tools/song_qa/make_sheet.py'),
                               str(self.root / 'target.json'), '--fa', str(self.root / 'fa.json')],
                              env=self.env, capture_output=True, text=True)

    def test_token_shape_table(self):
        for text, expected in SHAPES:
            with self.subTest(text=text):
                if expected is None:
                    with self.assertRaisesRegex(ValueError, 'row 1, token 2.*manual'):
                        fa.model_words(text)
                    # An unsupported token in the final row must suppress even
                    # the valid first row's hints.
                    result = self.sheet([target_line('nuv'), target_line(text)],
                                        [proposal('nuv'), dict(line=1, words=[])])
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, '')
                    self.assertIn('row 2, token 2', result.stderr)
                    self.assertIn('manual', result.stderr)
                    self.assertNotIn('dependency imported', result.stderr)
                    continue
                self.assertEqual(fa.checked_lines(text, '[00:01]' + text)[1], [text])
                aligned = proposal(text)
                self.assertEqual([w['w'] for w in aligned['words']], fa.model_words(text))
                # Both newly owned and older flat proposals must map by token.
                for owned in (True, False):
                    row = copy.deepcopy(aligned)
                    if not owned:
                        for word in row['words']:
                            del word['target_token'], word['target_w']
                    result = self.sheet([target_line(text)], [row])
                    self.assertEqual(result.returncode, 0, result.stderr)
                    rows = [s for s in result.stdout.splitlines() if s]
                    self.assertEqual(len(rows), len(tokenize(text)))
                    for k, (token, span) in enumerate(zip(tokenize(text), expected)):
                        self.assertTrue(rows[k].startswith(f'{k} {token} = ='))
                        self.assertTrue(rows[k].endswith(f'fa {span[0]}..{span[1]}'), rows[k])

    def test_unsupported_producer_table_refuses_before_imports(self):
        for text, expected in SHAPES:
            if expected is not None: continue
            with self.subTest(text=text):
                (self.root / 'text.txt').write_text('nuv\n' + text)
                (self.root / 'rows.lrc').write_text('[00:01]nuv\n[00:02]' + text)
                result = subprocess.run([sys.executable, str(ROOT / 'tools/song_qa/fa_align.py'),
                                         str(self.root / 'missing-package'), str(self.root / 'text.txt'),
                                         str(self.root / 'rows.lrc'), str(self.root / 'out.json')],
                                        env=self.env, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')
                self.assertIn('row 2, token 2', result.stderr)
                self.assertIn('manual', result.stderr)
                self.assertNotIn('dependency imported', result.stderr)
                self.assertFalse((self.root / 'out.json').exists())

    def test_late_mapping_mismatch_table_is_atomic(self):
        lyrics = [target_line('nuv'), target_line('flim-borp flim')]
        good = [proposal('nuv'), proposal('flim-borp flim', 1)]
        mutations = [
            ('word', lambda rows: rows[1]['words'][2].update(w='zas')),
            ('missing', lambda rows: rows[1]['words'].pop()),
            ('extra', lambda rows: rows[1]['words'].append(dict(rows[1]['words'][-1]))),
            ('owner', lambda rows: rows[1]['words'][2].update(target_token=0)),
            ('owner text', lambda rows: rows[1]['words'][2].update(target_w='zas')),
            ('partial owner', lambda rows: rows[1]['words'][2].pop('target_token')),
            ('row id', lambda rows: rows[1].update(line=0)),
            ('row missing', lambda rows: rows.pop()),
            ('row extra', lambda rows: rows.append(proposal('nuv', 2))),
            ('bad words', lambda rows: rows[1].update(words=None)),
            ('bad word', lambda rows: rows[1]['words'].__setitem__(2, None)),
            ('null time', lambda rows: rows[1]['words'][2].update(a=None)),
            ('nan time', lambda rows: rows[1]['words'][2].update(b=float('nan'))),
            ('bool time', lambda rows: rows[1]['words'][2].update(b=True)),
            ('negative', lambda rows: rows[1]['words'][2].update(a=-1)),
            ('reversed', lambda rows: rows[1]['words'][2].update(b=1)),
            ('unordered', lambda rows: rows[1]['words'][2].update(a=1)),
        ]
        self.assertEqual(self.sheet(lyrics, good).returncode, 0)
        for name, mutate in mutations:
            with self.subTest(case=name):
                rows = copy.deepcopy(good); mutate(rows)
                result = self.sheet(lyrics, rows)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')
                self.assertRegex(result.stderr, r'row [23], token [12]:.*manual')
                self.assertNotIn('dependency imported', result.stderr)

    def test_repeated_words_retain_row_and_token_ownership(self):
        lyrics = [target_line('flim flim'), target_line('flim flim')]
        rows = [proposal('flim flim'), proposal('flim flim', 1)]
        for w in rows[1]['words']: w['a'] += 3; w['b'] += 3
        result = self.sheet(lyrics, rows)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('2 flim = = # current 10.000..10.500 fa 4.0..4.3', result.stdout)
        rows[1]['words'].reverse()
        result = self.sheet(lyrics, rows)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertIn('row 2, token 1', result.stderr)


if __name__ == '__main__': unittest.main()
