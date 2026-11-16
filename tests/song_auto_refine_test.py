"""Fixed synthetic contour/onset fixtures and real audio; no model downloads."""
import copy
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.song_auto import run, refine


def fixture(starts=(.37, 1.37), names=('go', 'home'), pitches=None):
    t = np.round(np.arange(150)*.02, 3)
    m = np.full(len(t), np.nan) if pitches is None else np.asarray(pitches)
    if pitches is None:
        m[(t >= .2) & (t < .9)] = 60
        m[(t >= 1.2) & (t < 2.8)] = 64
    song = dict(duration=3., hop=.02, points=[[float(at), None if np.isnan(p) else float(p), .9, 1]
                                           for at,p in zip(t,m)],
                lyrics=[dict(a=starts[0], b=2.7, words=[dict(w=w,a=a,b=(starts[i+1] if i+1 < len(starts) else 2.7),c=.9)
                                                      for i,(w,a) in enumerate(zip(names,starts))])])
    F = dict(qa_t=t, qa_db=np.full(len(t),-20.), qa_periodicity=np.ones(len(t)),
             qa_concentration=np.ones(len(t)), env=np.ones(100),
             onset_start=np.array([]), onset_strength=np.array([]))
    return song,F


class Refinement(unittest.TestCase):
    def test_contour_edges_radius_and_no_mutation(self):
        song,F = fixture(); before=copy.deepcopy(song)
        result,audit = refine.refine(song,F)
        self.assertEqual([w['a'] for w in result['lyrics'][0]['words']],[.2,1.2])
        self.assertEqual(song,before)
        self.assertFalse(any(a['doubtful'] for a in audit))
        song,F = fixture(starts=(.45,1.45))
        result,_=refine.refine(song,F)
        self.assertEqual([w['a'] for w in result['lyrics'][0]['words']],[.2,1.2])
        song,F = fixture(starts=(.451,1.451))
        result,audit=refine.refine(song,F)
        self.assertEqual([w['a'] for w in result['lyrics'][0]['words']],[.451,1.451])
        self.assertTrue(all(a['doubtful'] for a in audit))
        self.assertTrue(all(w['c']<=.4 for w in result['lyrics'][0]['words']))

    def test_absent_contour_has_no_edge_and_no_sign_keeps_time(self):
        song,F=fixture(pitches=np.full(150,np.nan))
        result,audit=refine.refine(song,F)
        self.assertEqual([w['a'] for w in result['lyrics'][0]['words']],[.37,1.37])
        self.assertTrue(all('no_boundary_in_reach' in f['reasons'] for f in audit))

    def test_strong_onset_threshold_and_held_note_exclusion(self):
        for strength,expected in ((.249,.37),(.25,.3)):
            song,F=fixture(pitches=np.full(150,np.nan))
            F.update(onset_start=np.array([.3]),onset_strength=np.array([strength]))
            result,_=refine.refine(song,F)
            self.assertEqual(result['lyrics'][0]['words'][0]['a'],expected)
        song,F=fixture(starts=(.6,1.8))
        F.update(onset_start=np.array([.58,1.78]),onset_strength=np.ones(2))
        result,audit=refine.refine(song,F)
        self.assertEqual([w['a'] for w in result['lyrics'][0]['words']],[.6,1.8])
        self.assertTrue(all('inside_level_note' in f['reasons'] for f in audit))

    def test_pitch_step_threshold_and_vibrato(self):
        for step,expected in ((.8,.8),(.79,.87)):
            m=np.full(150,60.); m[40:]+=step
            song,F=fixture(starts=(.87,),names=('go',),pitches=m)
            result,_=refine.refine(song,F)
            self.assertAlmostEqual(result['lyrics'][0]['words'][0]['a'],expected)
        t=np.arange(150)*.02
        for amplitude in (.4,.9):
            song,F=fixture(starts=(1.01,),names=('go',),pitches=60+amplitude*np.sin(2*np.pi*5*t))
            signs,segments=refine.boundaries(run.screen.__globals__['Evidence'](song,F))
            self.assertFalse(any(.5 < s < 2.5 for s in segments))
            result,audit=refine.refine(song,F)
            self.assertEqual(result['lyrics'][0]['words'][0]['a'],1.01)
            self.assertTrue(audit[0]['doubtful'])

    def test_quantized_candidate_cannot_land_inside_level_note(self):
        song,F=fixture(starts=(.37,),names=('go',),pitches=np.full(150,60.))
        F.update(onset_start=np.array([.2496]),onset_strength=np.ones(1))
        result,audit=refine.refine(song,F)
        self.assertEqual(result['lyrics'][0]['words'][0]['a'],.37)
        self.assertTrue(audit[0]['doubtful'])

    def test_syllable_count_first_syllable_compound_full_span(self):
        m=np.full(150,np.nan); m[10:30]=60; m[35:60]=62; m[65:140]=65
        song,F=fixture(starts=(.38,1.4),names=('sun-light','go'),pitches=m)
        with patch.object(refine,'syllables',side_effect=[2,1]):
            result,audit=refine.refine(song,F)
        ws=result['lyrics'][0]['words']
        self.assertEqual([w['a'] for w in ws],[.2,1.3])
        self.assertEqual(ws[0]['b'],1.3)
        self.assertEqual(audit[0]['decision'],'syllable_first')
        self.assertEqual(audit[0]['word_syllables'],2)
        self.assertEqual(audit[0]['phrase_syllables'],3)
        self.assertEqual(audit[0]['contour_segments'],3)
        self.assertEqual(refine.syllables('sun-light'),2)
        self.assertEqual(refine.syllables('moving'),2)
        self.assertIsNone(refine.syllables('zxqv'))
        self.assertIsNone(refine.syllables('go2'))

    def test_multisyllable_start_precedes_last_long_note(self):
        m=np.full(150,np.nan); m[10:17]=60; m[20:140]=64
        song,F=fixture(starts=(.41,),names=('moving',),pitches=m)
        result,audit=refine.refine(song,F)
        self.assertEqual(result['lyrics'][0]['words'][0]['a'],.2)
        self.assertEqual(result['lyrics'][0]['words'][0]['b'],2.7)
        self.assertEqual(audit[0]['decision'],'syllable_first')
        song,F=fixture(starts=(1.37,),names=('moving',))
        result,audit=refine.refine(song,F)
        self.assertIn('syllable_unresolved',audit[0]['reasons'])
        self.assertLessEqual(result['lyrics'][0]['words'][0]['c'],.4)

    def test_global_order_and_no_projection_off_boundary(self):
        song,F=fixture(starts=(.3,.34),pitches=np.full(150,np.nan))
        F.update(onset_start=np.array([.25,.32,.4]),onset_strength=np.ones(3))
        result,_=refine.refine(song,F)
        ws=result['lyrics'][0]['words']
        self.assertGreaterEqual(ws[1]['a']-ws[0]['a'],.04-1e-6)
        self.assertLessEqual(ws[0]['b'],ws[1]['a'])
        self.assertTrue(all(w['a'] in (.25,.32,.4) for w in ws))
        song['lyrics'][0]['words'][1]['a']=.29
        with self.assertRaises(ValueError): refine.refine(song,F)

    def test_collision_falls_back_unchanged_and_marks_doubtful(self):
        song,F=fixture(starts=(.3,.34),pitches=np.full(150,np.nan))
        F.update(onset_start=np.array([.32]),onset_strength=np.ones(1))
        result,audit=refine.refine(song,F)
        self.assertEqual([w['a'] for w in result['lyrics'][0]['words']],[.3,.34])
        self.assertTrue(all(a['doubtful'] for a in audit))

    def test_baseline_fallback_requires_matching_text_near_sign_and_order(self):
        song,F=fixture(starts=(.37,1.37)); base=copy.deepcopy(song)
        base['lyrics'][0]['words'][0]['a']=.23
        result,audit=refine.refine(song,F,base)
        self.assertEqual(result['lyrics'][0]['words'][0]['a'],.23)
        self.assertEqual(audit[0]['decision'],'baseline_boundary')
        for w,a in (('different',.23),('go',.8),('go',.1)):
            base['lyrics'][0]['words'][0].update(w=w,a=a)
            result,_=refine.refine(song,F,base)
            self.assertEqual(result['lyrics'][0]['words'][0]['a'],.2)

    def test_empty_lyrics(self):
        song,F=fixture(); song['lyrics']=[]
        result,audit=refine.refine(song,F)
        self.assertEqual(result['lyrics'],[]); self.assertEqual(audit,[])

    def test_real_synthetic_audio_stubbed_aligner_and_command_wiring(self):
        from song_auto_test import target, proposals, package
        with tempfile.TemporaryDirectory() as d:
            pkg=package(Path(d)); base=target()
            # A burst inside an uninterrupted synthetic sine is no boundary.
            with patch.object(run.bench,'align',return_value=(proposals(),{})):
                song,report=run.place(pkg,base,base,'cpu',pitch_song=base,refinement='boundary')
            self.assertEqual(report['refinement'],'boundary')
            self.assertEqual(len(report['refinement_audit']),2)
            self.assertLessEqual(song['lyrics'][0]['words'][1]['c'],.4)
            self.assertEqual(run.validate(song),[])
            self.assertEqual(run.bench.baseline(song)['words'][0]['w'],'ab-cd')
            p=proposals(); p[0]['a']=.35
            with patch.object(run.bench,'align',return_value=(p,{})):
                song,report=run.place(pkg,base,base,'cpu',pitch_song=base,refinement='boundary-baseline')
            self.assertEqual(report['refinement_audit'][0]['decision'],'baseline_boundary')
            self.assertEqual(song['lyrics'][0]['words'][0]['a'],.2)

    def test_preparation_refinement_requires_auto_option_before_any_write(self):
        from studio import prepare_song
        with tempfile.TemporaryDirectory() as d:
            output=Path(d)/'songs'
            argv=['prepare_song.py',str(Path(d)/'absent.wav'),'--title','Synthetic',
                  '--out',str(output),'--word-refinement','boundary']
            with patch.object(sys,'argv',argv),contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error: prepare_song.main()
            self.assertEqual(error.exception.code,2)
            self.assertFalse(output.exists())


if __name__=='__main__': unittest.main()
