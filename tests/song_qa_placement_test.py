"""Synthetic placement screens and CLI; no private fixtures.
Usage: python tests/song_qa_placement_test.py
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import numpy as np
import soundfile as sf

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/song_qa'))
import placement
import features


def fixture(duration=8., onsets=()):
    t=np.arange(0,duration,.02)
    song=dict(duration=duration,points=[[round(float(at),3),60.,.9,1] for at in t],lyrics=[])
    F=dict(t=t,env=np.ones(len(t)),onset_start=np.array(onsets,dtype=float),
           onset_strength=np.ones(len(onsets)),qa_t=t,qa_db=np.full(len(t),-20.),
           qa_periodicity=np.ones(len(t)),qa_concentration=np.ones(len(t)))
    return song,F


def words(song, starts):
    song['lyrics']=[dict(a=a,b=a+.2,words=[dict(w='zuv',a=a,b=a+.2,c=.95)]) for a in starts]


class Placement(unittest.TestCase):
    def test_strong_threshold_and_weak_tick_rejection(self):
        song,F=fixture(onsets=[1,2,3]); F['env'][:]=4; F['onset_strength']=np.array([.999,1,2])
        E=placement.Evidence(song,F)
        self.assertEqual(E.strong_threshold,1.)
        self.assertEqual(E.signs(1),[])
        self.assertIn('burst',E.signs(2))
        self.assertIn('burst',E.signs(2.06))
        self.assertEqual(E.signs(2.061),[])
        F['env'][:]=0
        self.assertEqual(len(placement.Evidence(song,F).strong),0)

    def test_gaps_steps_and_level_hold(self):
        song,F=fixture()
        for p in song['points']:
            if 1 <= p[0] < 1.04: p[1]=None
            if p[0]>=2: p[1]=60.8
        E=placement.Evidence(song,F)
        self.assertIn('gap',E.signs(1.12))
        self.assertNotIn('gap',E.signs(1.121))
        self.assertIn('step',E.signs(2))
        self.assertTrue(E.level(3)); self.assertFalse(E.signs(3))
        self.assertTrue(any(abs(t-1.04)<1e-6 for t in E.starts))
        self.assertTrue(any(abs(t-2)<1e-6 for t in E.starts))
        for p in song['points']: p[1]=None
        self.assertEqual(placement.Evidence(song,F).signs(3),[])

    def test_short_pickups_keep_each_discrete_step(self):
        song,F=fixture()
        for p in song['points']:
            if p[0]>=.1: p[1]=62.
            if p[0]>=.2: p[1]=64.
        starts=placement.Evidence(song,F).starts
        self.assertTrue(any(abs(t-.1)<1e-6 for t in starts))
        self.assertTrue(any(abs(t-.2)<1e-6 for t in starts))

    def test_screen_threshold_and_unplaced_origins(self):
        song,F=fixture(onsets=[1,2,3,4]); words(song,[1,2,3,4,5])
        out=placement.screen(song,F)
        self.assertEqual(out['without_boundary_share'],.2); self.assertFalse(out['review_required'])
        song['lyrics'][0]['words'][0]['c']=.3
        song['lyrics'][1]['words'][0]['timing_source']='vocal_stem_energy'
        song['lyrics'][2]['words'][0]['a']=2.5
        out=placement.screen(song,F)
        self.assertTrue(out['review_required'])
        self.assertEqual(sum('unplaced_origin' in f.get('reasons',[]) for f in out['flags']),2)
        self.assertTrue(any('inside_level_note' in f.get('reasons',[]) for f in out['flags']))

    def test_reviewed_placement_replaces_energy_origin_only_for_explicit_rows(self):
        import apply_edits
        song,F=fixture(onsets=[1.])
        words(song,[.5,2.])
        for line in song['lyrics']: line['words'][0].update(c=.3,timing_source='vocal_stem_energy')
        base=copy.deepcopy(song)
        rows=[dict(k=i,w='zuv',a='1.0' if i==0 else '=',b='1.2' if i==0 else '=',doubt=False,first=True) for i in range(2)]
        song['lyrics'],_=apply_edits.build_lyrics(song['lyrics'],rows,F,8.)
        self.assertEqual(song['lyrics'][0]['words'][0]['timing_source'],'reviewed_spectrogram')
        self.assertEqual(song['lyrics'][1],base['lyrics'][1])
        flags=placement.screen(song,F,base=base)['flags']
        self.assertFalse(any(f.get('word')==0 and 'unplaced_origin' in f.get('reasons',[]) for f in flags))
        self.assertTrue(any(f.get('word')==1 and 'unplaced_origin' in f.get('reasons',[]) for f in flags))

    def test_articulation_bands_and_hopping(self):
        for rate,band in [(.5,'sparse'),(1.,'uncertain'),(1.5,'articulated')]:
            song,F=fixture(onsets=np.arange(0,4,1/rate))
            for p in song['points']: p[1]=60+2*(int(p[0]/.2)%2)
            out=placement.Evidence(song,F).span(0,4)
            self.assertEqual(out['band'],band); self.assertTrue(out['hopping'])
        song,F=fixture(onsets=[0,.6,1.2]); E=placement.Evidence(song,F)
        self.assertEqual(E.span(0,5)['band'],'sparse')  # exactly 0.6/s
        self.assertFalse(E.span(0,5)['hopping'])

    def test_first_word_needs_bursts_and_harmonics(self):
        song,F=fixture(onsets=[.2,.6,1.,1.5])
        out=placement.screen(song,F,synced=[dict(a=1.8,text='zuv')])
        first=out['first_word_candidates'][0]
        self.assertEqual(first['a'],.2); self.assertEqual(first['delta'],-1.6)
        F['qa_concentration'][:]=0
        self.assertFalse(placement.screen(song,F)['first_word_candidates'])
        F['onset_strength'][:]=.1; F['env'][:]=4
        self.assertFalse(placement.screen(song,F)['first_word_candidates'])

    def test_held_tail_is_candidate_until_harmonics_stop(self):
        song,F=fixture(); words(song,[1])
        F['qa_concentration'][F['qa_t']>=2]=0
        out=placement.screen(song,F)
        tails=[f for f in out['flags'] if f['type']=='held_word_tail']
        self.assertEqual(len(tails),1); self.assertAlmostEqual(tails[0]['b'],2,places=2)
        F['qa_concentration'][:]=0
        self.assertFalse(any(f['type']=='held_word_tail' for f in placement.screen(song,F)['flags']))

    def test_clock_stamp_stands_and_prefers_strong(self):
        song,F=fixture(onsets=[2.4])
        for p in song['points']:
            if 2<=p[0]<2.04: p[1]=None
        E=placement.Evidence(song,F)
        out=placement.clock_check(E,dict(a=1,b=3,synced=2,burst_start=1,syllables=1))
        self.assertEqual(out['decision'],'keep_nearest_sign'); self.assertEqual(out['chosen'],2.4)

    def test_clock_override_requires_all_three_conditions(self):
        song,F=fixture()
        for p in song['points']:
            if p[0]<1: p[1]=None
        spec=dict(a=1,b=2,synced=3,burst_start=1,syllables=1,witness=dict(kind='recognizer',a=1.3))
        E=placement.Evidence(song,F)
        out=placement.clock_check(E,spec)
        self.assertEqual(out['decision'],'override_candidate')
        self.assertLessEqual(out['a'],out['b']); self.assertEqual(out['synced'],3)
        for field,value in [('witness',{}),('syllables',2),('synced',4.01),('witness',dict(kind='recognizer',a=1.301)),('witness',dict(kind='unknown',a=1)),('burst_start',2.5),('witness',True)]:
            changed={**spec,field:value}
            self.assertEqual(placement.clock_check(E,changed)['decision'],'keep_stamp_doubtful',field)
        self.assertEqual(placement.clock_check(E,{**spec,'synced':4})['decision'],'override_candidate')

    def test_response_room_articulation_and_lead_veto(self):
        song,F=fixture(onsets=[2,2.2,2.4]); span=dict(role='response',a=2,b=2.5,syllables=5)
        def response(s): return next(f for f in placement.screen(song,F,[s])['flags'] if f['type']=='response')
        self.assertFalse(response(span)['room']); self.assertTrue(response(span)['lead_continues'])
        roomy={**span,'b':2.75}; self.assertTrue(response(roomy)['room'])
        self.assertEqual(response(roomy)['decision'],'exclude_if_absent_from_synced')
        for p in song['points']:
            if 2<=p[0]<2.75: p[1]=None
        accepted=response(roomy)
        self.assertTrue(accepted['articulation']); self.assertFalse(accepted['lead_continues'])
        self.assertEqual(accepted['decision'],'inspect_independent_lead')
        F['onset_strength'][:]=0
        self.assertFalse(response(roomy)['articulation'])

    def test_scream_every_start_doubtful_even_on_burst(self):
        song,F=fixture(onsets=[2]); words(song,[2,3,5])
        song['unpitched']=[dict(a=1.9,b=4,kind='scream')]
        out=placement.screen(song,F)
        scream=[f for f in out['flags'] if 'scream_doubtful' in f.get('reasons',[])]
        self.assertEqual([f['a'] for f in scream],[2,3])
        self.assertIn('no_boundary',scream[1]['reasons'])
        song.pop('unpitched')
        self.assertFalse(any('scream_doubtful' in f.get('reasons',[]) for f in placement.screen(song,F)['flags']))

    def test_moved_words_and_mismatched_base(self):
        song,F=fixture(onsets=[1]); words(song,[1,2]); base=copy.deepcopy(song)
        base['lyrics'][0]['words'][0]['a']=.5
        moved=[f for f in placement.screen(song,F,base=base)['flags'] if f['type']=='moved_word']
        self.assertEqual(len(moved),1); self.assertEqual(moved[0]['signs'],['burst'])
        base['lyrics'][0]['words'][0]['w']='ploq'
        self.assertFalse(placement.screen(song,F,base=base)['base_comparable'])

    def test_synced_disagreement_matching_and_unmatched_rows(self):
        song,F=fixture(); words(song,[1,4])
        rows=[dict(a=2.5,text='Zuv!'),dict(a=4.5,text='zuv'),dict(a=6,text='ploq')]
        out=placement.screen(song,F,synced=rows)
        conflicts=[f for f in out['flags'] if f['type']=='synced_disagreement']
        self.assertEqual(len(conflicts),1); self.assertEqual(conflicts[0]['delta'],-1.5)
        self.assertTrue(any(f['type']=='synced_unmatched' for f in out['flags']))
        partial=placement.screen(song,F,synced=rows[:1])
        self.assertTrue(any(f['type']=='target_unsynced' for f in partial['flags']))
        self.assertNotIn('Zuv',json.dumps(out))

    def test_parallel_harmonics_require_independent_non_octave_comb(self):
        song,F=fixture(); n=len(F['qa_t'])
        F.update(qa_midi=np.array([60.,67.,72.]),qa_sal=np.tile([[1.],[.7],[.1]],(1,n)),qa_ratio=np.ones((3,n)))
        out=placement.parallel_candidates(F,song['duration'])
        self.assertEqual(len(out),1); self.assertEqual(out[0]['pitches'],[60.,67.])
        F['qa_sal'][1,:]=.54
        self.assertFalse(placement.parallel_candidates(F,song['duration']))
        F['qa_sal'][2,:]=.8
        self.assertFalse(placement.parallel_candidates(F,song['duration']))
        F['qa_sal'][1,:]=.7; F['qa_ratio'][1,:]=0
        self.assertFalse(placement.parallel_candidates(F,song['duration']))
        F['qa_ratio'][1,:]=1; F['qa_periodicity'][:]=0
        self.assertFalse(placement.parallel_candidates(F,song['duration']))

    def test_invalid_review_refused(self):
        song,F=fixture(); valid=dict(role='intro',a=0,b=2,syllables=4)
        for bad in [{**valid,'b':9},{**valid,'a':float('nan')},{**valid,'syllables':0},{**valid,'syllables':True},{**valid,'synced':1},{**valid,'role':'unknown'}]:
            with self.assertRaises(ValueError): placement.screen(song,F,[bad])
        self.assertEqual(placement.screen(song,F,[valid]),placement.screen(song,F,[valid]))

    def test_cli_real_audio_roundtrip_read_only_and_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); pkg=root/'package'; pkg.mkdir(); song,F=fixture(duration=4)
            words(song,[.5,2]); target=pkg/'target.json'; target.write_text(json.dumps(song)); before=target.read_bytes()
            t=np.arange(4*16000)/16000
            tone=sum(.2/h*np.sin(2*np.pi*220*h*t) for h in range(1,5))
            envelope=sum(np.exp(-((t-a)/.08)**2) for a in [.3,.7,1.1,1.5])
            sf.write(pkg/'vocals_44k.flac',tone*envelope,16000)
            cache=root/'features.npz'; np.savez_compressed(cache,**features.compute(pkg))
            lrc=root/'source.lrc'; lrc.write_text('[00:02.00]zuv\n[00:00.50]zuv\n')
            self.assertEqual(len(placement.read_synced(lrc)),2)
            command=[sys.executable,str(ROOT/'tools/song_qa/placement.py'),str(pkg),str(cache),str(root/'out.json'),'--synced',str(lrc)]
            result=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr); self.assertEqual(target.read_bytes(),before)
            report=json.loads((root/'out.json').read_text()); self.assertEqual(report['words'],2)
            dangerous=command.copy(); dangerous[4]=str(target)
            refused=subprocess.run(dangerous,capture_output=True,text=True)
            self.assertNotEqual(refused.returncode,0); self.assertEqual(target.read_bytes(),before)
            review=root/'bad.json'; review.write_text('[{}]')
            result=subprocess.run(command+['--review',str(review)],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0); self.assertEqual(target.read_bytes(),before)
            lrc.write_text('[metadata]')
            with self.assertRaises(ValueError): placement.read_synced(lrc)

if __name__=='__main__': unittest.main()
