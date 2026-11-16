"""Synthetic audio/packages for the offline QA pass; no library fixtures.
Usage: python tests/song_qa_test.py
"""
import base64
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import soundfile as sf

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'/'song_qa'))
import apply_edits as apply
import attempts
import candidates
import common
import compare_sources
import extract_lyrics_html as extract
import fa_align
import run as runner


def target(midi=57.,duration=2.):
    points=[[round(float(t),3),midi,.9,1] for t in np.arange(0,duration,.02)]
    notes,phrases,metrics,initial,_=apply.derive(points,duration,[])
    return dict(schema='luma.song.v1',title='Synthetic',artist='',id='0'*20,
                sourceId='1'*64,method='synthetic',duration=duration,hop=.02,
                a4=440,points=points,notes=notes,phrases=phrases,metrics=metrics,
                initialTime=initial,lyrics=[],lyricsSource='synthetic',createdBy='synthetic',waveform=[0]*1000)


def make_package(root,noise=False,silence=False):
    package=root/'package'; package.mkdir()
    t=np.arange(32000)/16000
    y=sum(.3/h*np.sin(2*np.pi*220*h*t) for h in range(1,7))
    if noise: y=np.random.default_rng(17).normal(0,.15,len(t))
    if silence: y[:]=0
    sf.write(package/'vocals_44k.flac',y,16000)
    (package/'target.json').write_text(json.dumps(target()))
    (package/'manifest.json').write_text('{}')
    return package


class Numeric(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.pkg=make_package(Path(self.tmp.name)); self.F=candidates.audio_features(self.pkg)

    def test_octave_down_found_and_correct_octave_absent(self):
        bad=candidates.melody_candidates(target(69.),self.F)
        self.assertTrue(any(c['type']=='octave' and c['shift']==-12 for c in bad))
        good=candidates.melody_candidates(target(57.),self.F)
        self.assertFalse(any(c['type']=='octave' for c in good))
        self.assertFalse(any(c['type']=='unpitched' for c in good))

    def test_octave_up_found(self):
        self.assertTrue(any(c['type']=='octave' and c['shift']==12
                            for c in candidates.melody_candidates(target(45.),self.F)))

    def test_unpitched_noise_and_silence(self):
        for name,noise,silence,expected in [('noise',True,False,True),('silence',False,True,False)]:
            root=Path(self.tmp.name)/name; root.mkdir(); pkg=make_package(root,noise,silence)
            result=candidates.melody_candidates(target(),candidates.audio_features(pkg))
            self.assertEqual(any(c['type']=='unpitched' for c in result),expected)

    def test_held_gap_and_no_gap(self):
        song=target()
        for p in song['points']:
            if .8<=p[0]<1.1: p[1:]=[None,0,0]
        result=candidates.melody_candidates(song,self.F)
        self.assertTrue(any(c['type']=='broken' and c['a']<1.1 and c['b']>.8 for c in result))
        self.assertFalse(any(c['type']=='broken' for c in candidates.melody_candidates(target(),self.F)))

    def test_held_note_interrupted_by_wrong_partial_and_single_frame_gaps(self):
        song=target()
        for p in song['points']:
            if .82<=p[0]<.98: p[1]=62.
            if p[0] in (.8,.98): p[1:]=[None,0,0]
        found=candidates.melody_candidates(song,self.F)
        self.assertTrue(any(c['type']=='broken' and c['b']-c['a']>=.1 and c['a']<.98 and c['b']>.8 for c in found))

    def test_silent_gap_is_not_a_held_note(self):
        self.F['db'][:]=-100
        song=target(); song['points'][40:55]=[[p[0],None,0,0] for p in song['points'][40:55]]
        self.assertFalse(any(c['type']=='broken' for c in candidates.melody_candidates(song,self.F)))

    def test_repeat_outlier_and_consistent_repeat(self):
        t=np.arange(0,26,.02); db=np.full(len(t),-65.)
        for start in (3,11,19):
            for offset,amp in ((0,22),(.5,15),(1.3,29),(2,12),(3.1,25)):
                db+=amp*np.exp(-((t-start-offset)/.08)**2)
        def line(a): return {'a':a,'b':a+3.5,'words':[{'w':'flim'},{'w':'borp'}]}
        song={'lyrics':[line(3),line(11),line(20.4)]}
        audio_t=np.arange(26*16000)/16000
        amplitude=10**(np.interp(audio_t,t,db)/20)
        sf.write(self.pkg/'vocals_44k.flac',amplitude*np.sin(2*np.pi*220*audio_t),16000,subtype='PCM_24')
        result=candidates.repeat_candidates(song,candidates.audio_features(self.pkg))
        self.assertTrue(any(c['line']==2 and abs(c['shift']+1.4)<.11 for c in result))
        self.assertFalse(any(c['line']==1 for c in result))
        song['lyrics'][0]['words']=[{'w':w} for w in ('flim','borp','nuv','dax')]
        song['lyrics'][2]['words']=[{'w':w} for w in ('flim','borp','nuv','rek','plim')]
        split=candidates.repeat_candidates(song,candidates.audio_features(self.pkg))
        self.assertTrue(any(c['line']==2 and abs(c['shift']+1.4)<.11 for c in split))

    def test_deterministic_and_read_only(self):
        song=target(69); original=copy.deepcopy(song)
        self.assertEqual(candidates.detect(song,self.F),candidates.detect(song,self.F))
        self.assertEqual(song,original)


class Apply(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.pkg=make_package(Path(self.tmp.name))
        self.F={'t':np.arange(0,2,.01),'rms':np.full(200,-10),'onset_start':np.array([.5])}
        self.lines=[{'a':.3,'b':1.3,'words':[{'w':'flim','a':.3,'b':.45,'c':.6},
                                                  {'w':'borp','a':.55,'b':1.3,'c':.7}]}]

    def row(self,i,start,end=None):
        return dict(k=i,w=['flim','borp'][i],a=start,b=end,doubt=False,first=i==0)

    def test_snapping_collision_falls_back_to_eye_times(self):
        lines,report=apply.build_lyrics(self.lines,[self.row(0,'~0.46'),self.row(1,'~0.54')],self.F,2)
        self.assertEqual([w['a'] for w in lines[0]['words']],[.46,.54])
        self.assertEqual(report['collisions'],[0,1])

    def test_explicit_collision_refuses(self):
        with self.assertRaisesRegex(ValueError,'collide'):
            apply.build_lyrics(self.lines,[self.row(0,'.5'),self.row(1,'.5')],self.F,2)

    def test_untouched_words_keep_values(self):
        rows=[self.row(0,'=','='),self.row(1,'=','=')]
        self.assertEqual(apply.build_lyrics(self.lines,rows,self.F,2)[0],self.lines)
        rows[1]['a']='~.6'; rows[1]['b']=None
        result=apply.build_lyrics(self.lines,rows,self.F,2)[0]
        self.assertEqual(result[0]['words'][0],self.lines[0]['words'][0])

    def test_doubt_marks_unchanged_time_and_invalid_onset_refuses(self):
        rows=[self.row(0,'=','='),self.row(1,'=','=')]; rows[0]['doubt']=True
        words=apply.build_lyrics(self.lines,rows,self.F,2)[0][0]['words']
        self.assertEqual(words[0]['a'],.3); self.assertEqual(words[0]['b'],.45)
        self.assertEqual(words[0]['c'],.4)
        for value in ('o-1','o2','ox'):
            with self.assertRaisesRegex(ValueError,'onset index'): apply.resolve(value,self.F,'start')

    def test_empty_onsets_and_sheet_mismatch(self):
        self.F['onset_start']=np.array([])
        self.assertEqual(apply.resolve('~.5',self.F,'start'),(.5,'eye'))
        with self.assertRaisesRegex(ValueError,'count'): apply.build_lyrics(self.lines,[],self.F,2)

    def test_clear_writes_valid_unpitched_and_real_reader_roundtrip(self):
        song=target(); ops=[{'op':'clear','a':.4,'b':1.2,'kind':'scream'}]
        apply.apply_melody(self.pkg,song['points'],ops); apply.update_unpitched(song,ops)
        song['notes'],song['phrases'],song['metrics'],song['initialTime'],_=apply.derive(song['points'],2,[])
        self.assertEqual(apply.validate(song),[])
        self.assertEqual(song['unpitched'],[{'a':.4,'b':1.2,'kind':'scream'}])
        common.write_json(self.pkg/'target.json',song)
        self.assertEqual(apply.validate(json.loads((self.pkg/'target.json').read_text())),[])
        sys.path.insert(0,str(ROOT/'studio'))
        from build_html import build, embedded_song
        for name in ('foreground.mp3','backing.mp3','foreground_80.mp3','backing_80.mp3'):
            (self.pkg/name).write_bytes(b'synthetic')
        html=Path(self.tmp.name)/'trainer.html'; build(self.pkg,html)
        self.assertEqual(json.loads(embedded_song(html))['unpitched'],song['unpitched'])

    def test_accepts_actual_aligner_line_rounding_but_refuses_wrong_bounds(self):
        sys.path.insert(0,str(ROOT/'studio')); import align_lyrics
        words=[{'a':.303,'b':.503,'w':'flim','c':.9},{'a':.903,'b':1.103,'w':'borp','c':.9}]
        ctx={'voiced':np.ones(100,bool),'onsets':np.array([.303,.903]),'duration':2.,'regions':[(0.,2.)]}
        song=target(); song['lyrics']=align_lyrics.realign(words,ctx)
        self.assertNotEqual(song['lyrics'][0]['a'],song['lyrics'][0]['words'][0]['a'])
        self.assertEqual(apply.validate(song),[])
        song['lyrics'][0]['a']+=.02
        self.assertTrue(apply.validate(song))

    def test_non_grid_scream_has_no_intersecting_note(self):
        song=target(); ops=[{'op':'clear','a':.413,'b':1.217,'kind':'noise'}]
        apply.apply_melody(self.pkg,song['points'],ops); apply.update_unpitched(song,ops)
        song['notes'],song['phrases'],song['metrics'],song['initialTime'],_=apply.derive(song['points'],2,[])
        self.assertEqual(apply.validate(song),[])

    def test_apply_cli_backup_dry_run_idempotence_and_invalid_no_write(self):
        base=self.pkg/'target.json'; original=base.read_bytes()
        feature=Path(self.tmp.name)/'features.npz'; np.savez(feature,**self.F)
        melody=Path(self.tmp.name)/'melody.json'
        melody.write_text(json.dumps([{'op':'clear','a':.4,'b':1.2,'kind':'noise'}]))
        command=[sys.executable,str(ROOT/'tools/song_qa/apply_edits.py'),str(self.pkg),str(feature),
                 '--base',str(base),'--melody',str(melody)]
        subprocess.run(command+['--dry-run'],check=True,capture_output=True)
        self.assertEqual(base.read_bytes(),original)
        subprocess.run(command,check=True,capture_output=True)
        after=base.read_bytes(); subprocess.run(command,check=True,capture_output=True)
        self.assertEqual(base.read_bytes(),after)
        self.assertTrue(any(p.read_bytes()==original for p in (self.pkg/'.song-qa-backups').rglob('target.json')))
        melody.write_text(json.dumps([{'op':'clear','a':.4,'b':1.2,'kind':'whisper'}]))
        self.assertNotEqual(subprocess.run(command,capture_output=True).returncode,0)
        self.assertEqual(base.read_bytes(),after)

    def test_invalid_melody_intervals_kinds_and_octaves(self):
        for op in ({'op':'clear','a':-1,'b':1},{'op':'clear','a':1,'b':.5},
                   {'op':'clear','a':0,'b':float('nan')},{'op':'clear','a':0,'b':3},
                   {'op':'clear','a':0,'b':1,'kind':'whisper'},
                   {'op':'clear','a':0,'b':1,'kind':'scream','lo':50},
                   {'op':'octave','a':0,'b':1,'shift':7},
                   {'op':'fill','a':0,'b':1,'m':float('nan')},
                   {'op':'fill','a':0,'b':1,'m':57,'tol':0},
                   {'op':'fill','a':0,'b':1,'m':57,'tol':13},
                   {'op':'fill','a':.001,'b':.002,'m':57}):
            with self.subTest(op=op), self.assertRaises(ValueError):
                apply.apply_melody(self.pkg,target()['points'],[op])

    def test_schema_refuses_bad_unpitched(self):
        for spans in (None,[{'a':0,'b':1,'kind':'whisper'}],[{'a':1,'b':.5,'kind':'noise'}],
                      [{'a':0,'b':float('nan'),'kind':'scream'}],
                      [{'a':0,'b':1,'kind':'scream'}]):
            song=target(); song['unpitched']=spans
            self.assertTrue(apply.validate(song))

    def test_fill_updates_annotations_and_preserves_other_spans(self):
        song=target(); song['unpitched']=[{'a':.1,'b':1.8,'kind':'noise'}]
        apply.update_unpitched(song,[{'op':'fill','a':.5,'b':1.}])
        self.assertEqual(song['unpitched'],[{'a':.1,'b':.5,'kind':'noise'},{'a':1.,'b':1.8,'kind':'noise'}])

    def test_atomic_failure_keeps_original(self):
        file=self.pkg/'target.json'; original=file.read_bytes()
        with patch('common.os.replace',side_effect=OSError('injected')):
            with self.assertRaises(OSError): common.write_json(file,{'changed':True})
        self.assertEqual(file.read_bytes(),original)
        self.assertEqual(list(self.pkg.glob('*.tmp')),[])

    def test_failed_rebuild_preserves_existing_html(self):
        import finish_song
        html=Path(self.tmp.name)/'trainer.html'; html.write_text('previous')
        with self.assertRaises(FileNotFoundError): finish_song.finish(self.pkg,html)
        self.assertEqual(html.read_text(),'previous')
        self.assertFalse(html.with_name('trainer.html.new').exists())

    def test_metadata_write_failures_leave_recoverable_backups(self):
        import set_artist
        for failure in (1,2,None):
            with self.subTest(failure=failure):
                common.write_json(self.pkg/'target.json',target())
                common.write_json(self.pkg/'manifest.json',{'artist':'','map':{'id':'0'*20}})
                originals={name:(self.pkg/name).read_bytes() for name in ('target.json','manifest.json')}
                calls=[]
                def write(path,data):
                    calls.append(path)
                    if len(calls)==failure: raise OSError('injected write failure')
                    common.write_json(path,data)
                with patch.object(sys,'argv',['set_artist.py',str(self.pkg),'Synthetic']), patch('set_artist.write_json',side_effect=write):
                    if failure:
                        with self.assertRaises(OSError): set_artist.main()
                    else: set_artist.main()
                for name,original in originals.items():
                    self.assertTrue(any(p.read_bytes()==original for p in (self.pkg/'.song-qa-backups').rglob(name)))
                if failure==1: self.assertEqual((self.pkg/'target.json').read_bytes(),originals['target.json'])
                if not failure:
                    saved=json.loads((self.pkg/'target.json').read_text())
                    manifest=json.loads((self.pkg/'manifest.json').read_text())
                    self.assertEqual(saved['artist'],manifest['artist'])
                    self.assertEqual(saved['id'],manifest['map']['id'])

    def test_derive_matches_preparation_rule(self):
        sys.path.insert(0,str(ROOT/'studio')); import prepare_song
        t=np.arange(0,2,.02); f=np.full(len(t),220.); p=np.full(len(t),.95)
        P=np.c_[t,f,p,np.full(len(t),.2),f]
        song=prepare_song.build_map(t,f,p,P,np.ones((44100,2))*.1,2.,'Synthetic','','synthetic')
        points=copy.deepcopy(song['points'])
        notes,phrases,metrics,initial,_=apply.derive(points,2.,[])
        self.assertEqual(notes,song['notes']); self.assertEqual(phrases,song['phrases'])
        self.assertEqual(metrics,song['metrics']); self.assertEqual(initial,song['initialTime'])


class Inputs(unittest.TestCase):
    def test_apostrophes_echoes_and_extraction(self):
        self.assertEqual(compare_sources.words("flim’s [echo] (echo) borp"),["flim's",'borp'])
        self.assertEqual(extract.extract('<div data-lyrics-container="true">flim <b>borp</b><br>nuv</div>'),'flim borp\nnuv\n')
        self.assertEqual(extract.extract('<div itemprop="text">flim</div>'),'flim\n')
        self.assertEqual(extract.extract('<article id="verse">borp</article>','id','verse'),'borp\n')
        with self.assertRaises(ValueError): extract.extract('<div>unknown</div>')

    def test_fa_mismatched_rows_and_words_refuse_before_model(self):
        self.assertEqual(fa_align.checked_lines('flim borp','[00:01] flim borp')[1],['flim borp'])
        for text,lrc in [('flim\nborp','[00:01] flim borp'),('flim','[00:01] borp')]:
            with self.assertRaises(ValueError): fa_align.checked_lines(text,lrc)

    def test_attempt_export_clock_filter_and_bad_channels(self):
        def b64(values,dtype): return base64.b64encode(np.array(values,dtype=dtype).tobytes()).decode()
        segment={'t0':.2,'cents':b64([5700,5800],'<i2'),'conf':b64([255,255],'u1'),'db':b64([-20,-20],'i1')}
        data={'schema':'luma.history.v1','runs':[{'id':'take-1','songHash':'1'*64,'a':.5,'speed':.8}],
              'traces':[{'runId':'take-1','hop':.1,'segments':[segment]}]}
        result=attempts.convert(target(),data)
        self.assertEqual(result['traces'][0]['points'],[[.66,57.],[.74,58.]])
        self.assertEqual(attempts.convert({**target(),'sourceId':'2'*64},data),{'traces':[]})
        segment['conf']=''
        with self.assertRaises(ValueError): attempts.convert(target(),data)
        with self.assertRaises(ValueError): attempts.convert(target(),{'schema':'other'})

    def test_benchmark_matches_category_direction_band_and_overlap(self):
        edits=[{'op':'octave','a':1.,'b':2.,'shift':-12},{'op':'fill','a':3.,'b':4.,'m':57}]
        matches=[{'type':'octave','a':1.1,'b':1.4,'shift':-12},{'type':'broken','a':3.,'b':3.2,'m':57}]
        self.assertEqual(runner.benchmark(matches,edits)['total']['hits'],2)
        matches[0]['shift']=12; matches[1]['m']=70
        self.assertEqual(runner.benchmark(matches,edits)['total']['hits'],0)
    def test_clear_of_pitched_interruption_uses_broken_candidate(self):
        edit=[{'op':'clear','a':1.,'b':1.3}]
        candidate={'type':'broken','a':1.02,'b':1.25,'m':57}
        result=runner.benchmark([candidate],edit)
        self.assertEqual(result['clear']['hits'],1)
        self.assertEqual(result['events'][0]['candidate_types'],['broken'])
        candidate['type']='octave'; candidate['shift']=-12
        self.assertEqual(runner.benchmark([candidate],edit)['clear']['hits'],0)


class CommandLines(unittest.TestCase):
    def test_scripts_compile_and_have_help(self):
        directory=ROOT/'tools/song_qa'
        for script in sorted(directory.glob('*.py')):
            with self.subTest(script=script.name):
                compile(script.read_text(),str(script),'exec')
                if script.name in ('common.py','__init__.py'): continue
                result=subprocess.run([sys.executable,str(script),'--help'],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertIn('usage',result.stdout.lower())

    def test_entry_is_read_only_and_rejects_symlink_and_nested_scratch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); package=make_package(root)
            for name in ('foreground.mp3','backing.mp3','foreground_80.mp3','backing_80.mp3'):
                (package/name).write_bytes(b'synthetic')
            before=runner.fingerprint(package)
            command=[sys.executable,str(ROOT/'tools/song_qa/run.py'),str(package),'--dry-run','--scratch']
            result=subprocess.run(command+[str(root/'out')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            checks=json.loads(next((root/'out').glob('qa-*/checks.json')).read_text())
            self.assertTrue(checks['source_unchanged']); self.assertTrue(checks['embedded_target_equal'])
            self.assertEqual(checks['windows'],1); self.assertEqual(runner.fingerprint(package),before)
            result=subprocess.run(command+[str(package/'nested')],capture_output=True)
            self.assertNotEqual(result.returncode,0); self.assertFalse((package/'nested').exists())
            (package/'alias').symlink_to(package/'target.json')
            result=subprocess.run(command+[str(root/'out2')],capture_output=True)
            self.assertNotEqual(result.returncode,0); self.assertFalse((root/'out2').exists())

    def test_generated_sheet_preserves_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            song=target(); song['lyrics']=[{'a':.3,'b':.7,'words':[{'w':'flim','a':.3,'b':.7,'c':.6}]}]
            file=Path(tmp)/'target.json'; file.write_text(json.dumps(song))
            result=subprocess.run([sys.executable,str(ROOT/'tools/song_qa/make_sheet.py'),str(file)],capture_output=True,text=True,check=True)
            sheet=Path(tmp)/'words.txt'; sheet.write_text(result.stdout)
            self.assertEqual(apply.parse_sheet(sheet)[0]['a'],'=')


if __name__=='__main__': unittest.main(verbosity=2)
