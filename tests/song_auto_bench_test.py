"""Synthetic reference, audio and acoustic-output tests; never downloads weights.

Usage: python tests/song_auto_bench_test.py
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.song_auto.bench import run, score


def reference():
    return dict(duration=2., hop=.02, lyrics=[dict(words=[
        dict(w='ab-cd', a=.1, b=.3, c=.4), dict(w='ef', a=.3, b=1.4, c=.9)])],
        points=[[round(i*.02, 8), 69. if i < 75 else None, 1., 1] for i in range(100)],
        notes=[dict(a=.3, b=1.3, m=69., ignored=False)],
        unpitched=[dict(a=1.5, b=1.8, kind='scream')])


class Metrics(unittest.TestCase):
    def test_identity_and_low_confidence_boundary(self):
        r = reference(); result = score.score(r, run.baseline(r))
        self.assertEqual(result['words']['all']['within80'], 1.)
        self.assertEqual(result['words']['confident']['n'], 1)
        self.assertEqual(result['words']['pickup_all']['n'], 1)
        self.assertEqual(result['words']['pickup_confident']['n'], 0)
        self.assertEqual(result['pitch']['within50'], 1.)
        self.assertEqual(result['pitch']['false_unpitched'], 0.)

    def test_missing_words_remain_in_denominator_and_repeats_are_ordered(self):
        r = reference(); p = run.baseline(r); p['words'] = p['words'][1:]
        result = score.score(r, p)['words']['all']
        self.assertEqual(result['n'], 2); self.assertEqual(result['matched'], 1)
        self.assertEqual(result['within80'], .5)
        self.assertIsNone(result['median_ms'])
        self.assertEqual(score.matches([dict(w='xy'), dict(w='xy')], [dict(w='xy'), dict(w='xy')]), {0:0, 1:1})

    def test_optimal_text_matching_and_common_text_sensitivity(self):
        a, b = [dict(w=w) for w in 'abcbdab'], [dict(w=w) for w in 'bdcaba']
        self.assertEqual(len(score.matches(a,b)),4)
        r = reference(); old = copy.deepcopy(r); old['lyrics'][0]['words'] = old['lyrics'][0]['words'][1:]
        result = score.score(r,run.baseline(r),old)['words']
        self.assertEqual(result['all']['n'],2); self.assertEqual(result['common_all']['n'],1)

    def test_error_thresholds_and_missing_median(self):
        r = reference(); p = run.baseline(r)
        p['words'][0]['a'] += .08; p['words'][1]['a'] += .2
        result = score.score(r, p)['words']['all']
        self.assertEqual(result['within80'], .5); self.assertEqual(result['within200'], 1.)
        self.assertAlmostEqual(result['median_ms'], 140.)
        self.assertIsNone(score.word_metrics(dict(lyrics=[]), [])['median_ms'])

    def test_octaves_and_false_scream_contour(self):
        r = reference(); p = run.baseline(r)
        for item in p['pitch']:
            item.update(hz=880., voiced=True)
        result = score.score(r, p)['pitch']
        self.assertEqual(result['within50'], 0.)
        self.assertEqual(result['octave'], 1.)
        self.assertEqual(result['false_unpitched'], 1.)

    def test_unpitched_half_open_endpoints(self):
        r = reference(); p = run.baseline(r)
        for item in p['pitch']:
            if item['t'] in (1.5,1.78,1.8): item.update(hz=440.,voiced=True)
        result = score.score(r,p)['pitch']
        self.assertEqual(result['unpitched_frames'],15)
        self.assertEqual(result['false_unpitched_frames'],2)

    def test_pooling_uses_errors_and_frame_counts(self):
        r = reference(); a = run.baseline(r); b = run.baseline(r)
        a['words'][0]['a'] += .08; b['words'][0].update(a=.3,b=.5)
        pooled = score.pool_scores([score.score(r,a),score.score(r,b)])
        self.assertEqual(pooled['words']['all']['n'],4)
        self.assertAlmostEqual(pooled['words']['all']['median_ms'],40.)
        self.assertEqual(pooled['words']['all']['within80'],.75)
        self.assertEqual(pooled['pitch']['voiced_frames'],150)
        self.assertEqual(pooled['pitch']['within50'],1.)
        self.assertEqual(score.pool_scores([]),dict(words={},pitch=None))

    def test_fifty_cent_boundary_and_ordinary_pitch_error(self):
        r = reference(); p = run.baseline(r)
        for item in p['pitch']:
            if item['voiced']: item['hz'] *= 2**(.5/12)
        self.assertEqual(score.score(r,p)['pitch']['within50'], 1.)
        for item in p['pitch']:
            if item['voiced']: item['hz'] = 440*2**(2/12)
        result = score.score(r,p)['pitch']
        self.assertEqual(result['within50'], 0.)
        self.assertEqual(result['octave'], 0.)

    def test_internal_gap_and_wholly_missed_held_note(self):
        r = reference(); p = run.baseline(r)
        for i in range(30, 33): p['pitch'][i].update(hz=None, voiced=False)
        result = score.score(r, p)['pitch']
        self.assertEqual(result['broken_held'], 1); self.assertEqual(result['internal_gaps'], 1)
        self.assertEqual(result['gaps_ge60ms'],1)
        p=run.baseline(r); p['pitch'][30].update(hz=None,voiced=False)
        result=score.score(r,p)['pitch']
        self.assertEqual(result['broken_held'],1); self.assertEqual(result['gaps_ge60ms'],0)
        p['pitch'] = []
        result = score.score(r,p)['pitch']
        self.assertEqual(result['within50'], 0.)
        self.assertEqual(result['missed_held'], 1)
        self.assertEqual(result['broken_held'], 0)

    def test_existing_reference_gap_excludes_held_note(self):
        r = reference(); r['points'][30][1] = None
        result = score.score(r, run.baseline(r))['pitch']
        self.assertEqual(result['held_notes'], 0)

    def test_sparse_output_has_no_extrapolation(self):
        p = run.baseline(reference()); p['pitch'] = p['pitch'][:1]
        self.assertEqual(score.sample_pitch(p, [0., .02, 1.]), [69., None, None])

    def test_invalid_neutral_and_duration(self):
        p = run.baseline(reference())
        variants = []
        for key, value in [('duration', float('nan')), ('hop', 0), ('schema', 'other')]:
            bad = copy.deepcopy(p); bad[key] = value; variants.append(bad)
        for update in [dict(t=-1),dict(t=float('nan')),dict(voiced=False),dict(hz=-1),dict(voiced=1),
                       dict(confidence=float('nan')),dict(confidence=1.1)]:
            bad = copy.deepcopy(p); bad['pitch'][0].update(update); variants.append(bad)
        bad = copy.deepcopy(p); bad['pitch'][1]['t'] = 0; variants.append(bad)
        for bad in variants:
            with self.subTest(bad=bad), self.assertRaises(ValueError): score.validate(bad)
        p['duration'] = 3.
        with self.assertRaisesRegex(ValueError, 'duration mismatch'): score.score(reference(),p)

    def test_unrun_component_is_distinct_from_empty_prediction(self):
        p = run.baseline(reference()); p.update(words=None,pitch=None)
        self.assertEqual(score.score(reference(),p), dict(words=None,pitch=None))

    def test_no_reference_voicing_or_annotations_is_na(self):
        r=reference(); r['notes']=[]; r['unpitched']=[]
        for p in r['points']: p[1]=None
        result=score.score(r,run.baseline(r))['pitch']
        self.assertIsNone(result['within50']); self.assertIsNone(result['octave'])
        self.assertIsNone(result['false_unpitched'])
        self.assertIsNone(score.pool_scores([dict(words=None,pitch=result)])['pitch']['voiced_recall'])


class AcousticConfidence(unittest.TestCase):
    def align_stub(self, candidate, confidence):
        import numpy as np
        import torch
        import torchaudio
        from torchaudio.pipelines._wav2vec2 import utils
        bundle = (torchaudio.pipelines.MMS_FA if candidate == 'mms'
                  else torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H)
        labels = bundle.get_labels(star=None) if candidate == 'mms' else bundle.get_labels()
        token = labels.index('a' if candidate == 'mms' else 'A')
        probabilities = torch.full((1, 6, len(labels)), (1-confidence)/(len(labels)-1))
        probabilities[:, :, 0] = confidence
        probabilities[:, 2:4, 0] = (1-confidence)/(len(labels)-1)
        probabilities[:, 2:4, token] = confidence

        class Acoustic(torch.nn.Module):
            def forward(self, waveform, lengths=None):
                # Shifted logits catch missing normalization on the ASR branch.
                return probabilities.log()+7, lengths

        base = dict(duration=1.2, lyrics=[dict(words=[dict(w='a', a=.4, b=.8)])])
        # Exercise the installed bundle's real wrapper, CTC and merge logic.
        # Replacing just construction and weight retrieval prevents downloads.
        with patch.object(utils, '_get_model', return_value=Acoustic()), \
                patch.object(utils, '_get_state_dict', return_value={}), \
                patch.object(run, 'audio', return_value=np.zeros(19200, dtype=np.float32)), \
                patch.object(torchaudio.functional, 'forced_align',
                             wraps=torchaudio.functional.forced_align) as forced:
            proposals, _ = run.align(Path('.'), base['lyrics'], base, candidate, 'cpu')
        emission = forced.call_args.args[0]
        if candidate == 'mms':
            torch.testing.assert_close(emission[:, :, -1], torch.zeros(1, 6))
            normalized = emission[:, :, :-1].exp().sum(-1)
        else:
            normalized = emission.exp().sum(-1)
        torch.testing.assert_close(normalized, torch.ones(1, 6))
        return base, proposals

    def test_mms_native_scores_reach_word_gate_without_wildcard_renormalization(self):
        from tools.song_auto import run as command
        times = []
        for confidence in (.99, .2, .6001, .5999):
            with self.subTest(confidence=confidence):
                base, proposals = self.align_stub('mms', confidence)
                self.assertAlmostEqual(proposals[0]['confidence'], confidence, places=5)
                times.append((proposals[0]['a'], proposals[0]['b']))
                base['lyrics'], flags = command.map_words(base['lyrics'], proposals, base['duration'])
                self.assertEqual(flags, [])
                with patch.object(command, 'screen', return_value={'flags': []}), \
                        patch.object(command, 'detect', return_value=[]):
                    report = command.end_checks(base, {})
                self.assertEqual(report['review_required'], confidence < .6)
                stored = base['lyrics'][0]['words'][0]['c']
                self.assertAlmostEqual(stored, round(min(.4, confidence) if confidence < .6 else confidence, 3))
                self.assertEqual([f['type'] for f in report['flags']],
                                 ['word_confidence'] if confidence < .6 else [])
        self.assertEqual(len(times), 4)
        self.assertEqual(times, [times[0]]*len(times))

    def test_wav2vec2_logits_are_normalized_for_high_and_low_scores(self):
        for confidence in (.99, .2):
            with self.subTest(confidence=confidence):
                _, proposals = self.align_stub('wav2vec2', confidence)
                self.assertAlmostEqual(proposals[0]['confidence'], confidence, places=5)

    def test_high_mms_score_still_yields_to_word_and_span_qa(self):
        from tools.song_auto import run as command
        base, proposals = self.align_stub('mms', .99)
        for reason in ('word_start', 'alignment_order', 'repeat', 'unpitched', 'parallel'):
            with self.subTest(reason=reason):
                song = copy.deepcopy(base)
                song['lyrics'], _ = command.map_words(song['lyrics'], proposals, song['duration'])
                flag = dict(type=reason, a=proposals[0]['a'], b=proposals[0]['b'])
                if reason in ('word_start', 'alignment_order'):
                    flag['word'] = 0
                with patch.object(command, 'screen', return_value={'flags': []}), \
                        patch.object(command, 'detect', return_value=[]):
                    report = command.end_checks(song, {}, [flag])
                self.assertEqual(song['lyrics'][0]['words'][0]['c'], .4)
                self.assertTrue(report['review_required'])
                self.assertIn('word_confidence', [f['type'] for f in report['flags']])


class Harness(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pkg = self.root/'pkg'; self.pkg.mkdir()
        self.before = self.root/'before'; self.before.mkdir()
        self.scratch = self.root/'scratch'

    def test_seed_windows_do_not_read_corrected_timing(self):
        r = reference(); seed = copy.deepcopy(r)
        a = run.seed_windows(r['lyrics'], seed, 2.)
        for w in r['lyrics'][0]['words']: w.update(a=1000,b=1001)
        self.assertEqual(run.seed_windows(r['lyrics'], seed, 2.), a)
        seed['lyrics'] = []
        with self.assertRaisesRegex(ValueError, 'no seed text'): run.seed_windows(r['lyrics'], seed, 2.)

    def test_seed_window_budget_refuses(self):
        r = reference(); r['lyrics'][0]['words'][-1]['a'] = 100
        with self.assertRaisesRegex(ValueError, 'budget'): run.seed_windows(r['lyrics'], r, 200.)

    def test_instrumental_tail_does_not_inflate_window(self):
        r = reference(); r['lyrics'] = [dict(words=[dict(w='ab',a=1.,b=2.)]),dict(words=[dict(w='cd',a=100.,b=101.)])]
        self.assertEqual(run.seed_windows(r['lyrics'],r,120.)[0],(0.,5.))

    def test_crossing_proposals_are_scored_without_reordering(self):
        r = reference(); p = run.baseline(r)
        p['words'][0].update(a=1.,b=1.1)
        result = score.score(r,p)['words']['all']
        self.assertEqual(result['crossing_starts'],1)
        self.assertEqual(result['within80'],.5)

    def test_scratch_guards_resolve_symlinks(self):
        seed = self.before/'target.json'; seed.write_text('{}')
        self.assertEqual(run.safe_scratch(self.pkg,seed,self.scratch), self.scratch)
        link = self.root/'alias'; link.symlink_to(self.pkg, target_is_directory=True)
        for location in [self.pkg, self.pkg/'nested', self.before/'nested', self.root, link/'nested',
                         ROOT/'scratch',Path(sys.prefix)/'cache']:
            with self.subTest(location=location), self.assertRaises(ValueError): run.safe_scratch(self.pkg, seed, location)

    def test_real_process_guard_refuses_again_after_restart(self):
        seed=self.before/'target.json'; seed.write_text('{}')
        alias=self.root/'alias'; alias.symlink_to(self.pkg,target_is_directory=True)
        for _ in range(2):
            result=subprocess.run([sys.executable,'-m','tools.song_auto.bench.run',str(self.pkg),'baseline',
                                   '--seed-target',str(seed),'--scratch',str(alias/'out')],
                                  cwd=ROOT,capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(result.stdout,'')
            self.assertIn('disjoint',result.stderr)
            self.assertEqual(list(self.pkg.iterdir()),[])

    def test_real_process_cache_overrides_cannot_write_inputs(self):
        seed=self.before/'target.json'; seed.write_text('{}')
        alias=self.root/'cache-alias'; alias.symlink_to(self.pkg,target_is_directory=True)
        for variable in ('TORCH_HOME','HF_HOME','NUMBA_CACHE_DIR'):
            result=subprocess.run([sys.executable,'-m','tools.song_auto.bench.run',str(self.pkg),'baseline',
                                   '--seed-target',str(seed),'--scratch',str(self.scratch)],
                                  cwd=ROOT,capture_output=True,text=True,env={**os.environ,variable:str(alias/'cache')})
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(result.stdout,'')
            self.assertIn('disjoint',result.stderr)
            self.assertEqual(list(self.pkg.iterdir()),[])

    def test_changed_source_prevents_output_publication(self):
        r=reference(); target=self.pkg/'target.json'; seed=self.before/'target.json'
        target.write_text(json.dumps(r)); seed.write_text(json.dumps(r))
        (self.pkg/'vocals_44k.flac').write_bytes(b'synthetic audio bytes')
        original_digest=run.digest
        def inject_change(path):
            value=original_digest(path)
            if Path(path).name=='vocals_44k.flac':
                target.write_text(json.dumps(dict(r,method='changed during inference')))
            return value
        argv=['bench',str(self.pkg),'baseline','--seed-target',str(seed),'--scratch',str(self.scratch)]
        with patch.object(sys,'argv',argv),patch.dict(os.environ),patch.object(run,'digest',side_effect=inject_change):
            with self.assertRaisesRegex(ValueError,'input changed during run'): run.main()
        self.assertEqual(list(self.scratch.glob('baseline-*/output.json')),[])
        self.assertEqual(list(self.scratch.glob('baseline-*/provenance.json')),[])

    def test_real_process_baseline_roundtrip_is_read_only_and_fresh(self):
        import numpy as np
        import soundfile as sf
        r = reference()
        sf.write(self.pkg/'vocals_44k.flac', .2*np.sin(2*np.pi*440*np.arange(88200)/44100), 44100)
        for path in (self.pkg/'target.json', self.before/'target.json'): path.write_text(json.dumps(r))
        paths = [self.pkg/'target.json', self.pkg/'vocals_44k.flac', self.before/'target.json']
        original = [(p.read_bytes(),p.stat().st_mtime_ns) for p in paths]
        destinations = []
        for _ in range(2):
            result = subprocess.run([sys.executable, '-m', 'tools.song_auto.bench.run', str(self.pkg), 'baseline',
                                     '--seed-target', str(self.before/'target.json'), '--scratch', str(self.scratch)],
                                    cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            output = Path(json.loads(result.stdout)['output']); destinations.append(output)
            value = json.loads(output.read_text()); self.assertEqual(score.score(r,value)['pitch']['within50'],1.)
            scored = subprocess.run([sys.executable,'-m','tools.song_auto.bench.score', str(output),str(self.pkg/'target.json')],
                                    cwd=ROOT,capture_output=True,text=True)
            self.assertEqual(scored.returncode,0,scored.stderr)
            self.assertEqual(json.loads(scored.stdout)['words']['all']['median_ms'],0.)
        self.assertNotEqual(*destinations)
        self.assertEqual(original, [(p.read_bytes(),p.stat().st_mtime_ns) for p in paths])
        samples = run.audio(self.pkg,16000)
        self.assertEqual(len(samples),32000)
        self.assertGreater(float(np.max(samples)),.19)

    def test_stub_acoustic_output_preserves_compound_ownership(self):
        import numpy as np
        import torch
        import torchaudio
        r = reference(); r['duration'] = 3.
        fake = SimpleNamespace(get_model=lambda **kw: self_model,
                               get_dict=lambda **kw: {s:i for i,s in enumerate('-*abcdef')}, _path='synthetic')
        class Model:
            def to(self,device): return self
            def eval(self): return self
            def __call__(self, audio): return torch.zeros(1,30,8), None
        self_model = Model()
        aligned = [SimpleNamespace(start=i,end=i+1,score=.8) for i in range(8)]
        with patch.object(torchaudio.pipelines,'MMS_FA',fake), patch.object(run,'audio',return_value=np.zeros(48000,dtype=np.float32)), \
                patch.object(torchaudio.functional,'forced_align',return_value=(torch.zeros(1,30,dtype=torch.int64),torch.zeros(1,30))), \
                patch.object(torchaudio.functional,'merge_tokens',return_value=aligned):
            result,_ = run.align(self.pkg,r['lyrics'],r,'mms','cpu')
            with patch.object(torchaudio.functional,'merge_tokens',return_value=aligned[:-1]):
                with self.assertRaisesRegex(ValueError,'token count'):
                    run.align(self.pkg,r['lyrics'],r,'mms','cpu')
        self.assertEqual([w['w'] for w in result],['ab-cd','ef'])
        self.assertAlmostEqual(result[0]['a'],.1); self.assertAlmostEqual(result[0]['b'],.5)
        self.assertAlmostEqual(result[1]['a'],.5); self.assertAlmostEqual(result[1]['b'],.7)

    def test_stub_pitch_native_clock_voicing_and_chunk_seams(self):
        import numpy as np
        import torch
        for frequency in (440., 0.):
            class Model:
                def get_hop_size(self): return 160
                def get_model_sr(self): return 16000
                def infer(self, segment, **kwargs):
                    self.assertions = kwargs
                    return torch.full((1,segment.shape[1]//160+1,1),frequency)
            fake = SimpleNamespace(spawn_bundled_infer_model=lambda **kw: Model())
            with patch.dict(sys.modules, {'torchfcpe':fake}), \
                    patch.object(run,'audio',return_value=np.zeros(41*16000,dtype=np.float32)):
                points,hop,_ = run.pitch(self.pkg,'fcpe','cpu',41.)
            self.assertEqual(hop,.01); self.assertEqual(len(points),4100)
            self.assertEqual(points[2000]['t'],20.)
            self.assertEqual(points[-1]['t'],40.99)
            self.assertEqual(set(p['voiced'] for p in points),{frequency > 0})
            score.validate(dict(schema='song-auto-bench.v1',duration=41.,hop=hop,pitch=points,words=None))

    def test_sofa_array_output_and_ownership_refusal(self):
        import numpy as np
        owners=[dict(w='ab',target_token=0,target_w='ab-cd'),dict(w='cd',target_token=0,target_w='ab-cd')]
        row=run.sofa_row(0,owners,['ab','cd'],np.array(['ab','cd']),np.array([[.1,.2],[.2,.4]]),.7,2.)
        self.assertEqual(row['words'][0]['a'],2.1)
        self.assertEqual(row['words'][-1]['b'],2.4)
        for aligned,intervals in [(['ab'],[[.1,.2]]),(['ab','xx'],[[.1,.2],[.2,.4]])]:
            with self.assertRaisesRegex(ValueError,'ownership'): run.sofa_row(0,owners,['ab','cd'],aligned,intervals,.7,2.)


if __name__ == '__main__': unittest.main()
