"""Synthetic audio and stubbed model outputs; no model downloads.

Usage: python tests/song_auto_test.py
"""
import copy
import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.song_auto import run
from tools.song_auto.bench import score


def target():
    points = [[round(i*.02, 3), 69. if 10 <= i < 70 else None,
               .95 if 10 <= i < 70 else 0., int(10 <= i < 70)] for i in range(100)]
    notes, phrases, metrics, initial, _ = run.derive(points, 2., [])
    return dict(schema='luma.song.v1', duration=2., hop=.02, title='Synthetic', artist='',
                id='0123456789abcdef0123', sourceId='synthetic', points=points,
                notes=notes, phrases=phrases, metrics=metrics, initialTime=initial,
                waveform=[0.]*1000, lyrics=[dict(a=.2, b=1.2, words=[
                    dict(w='ab-cd', a=.2, b=.5, c=.9), dict(w='ef', a=.6, b=1.2, c=.9)])])


def proposals():
    return [dict(w='ab-cd', a=.2, b=.5, confidence=.9), dict(w='ef', a=.6, b=1.2, confidence=.9)]


def package(root):
    pkg = root/'package'; pkg.mkdir()
    run.write_json(pkg/'target.json', target())
    t = np.arange(88200)/44100
    y = .2*np.sin(2*np.pi*440*t)
    y[t < .2] = 0
    sf.write(pkg/'vocals_44k.flac', y, 44100)
    for name in ('foreground.mp3', 'backing.mp3', 'foreground_80.mp3', 'backing_80.mp3'):
        (pkg/name).write_bytes(b'synthetic audio asset')
    return pkg


class Words(unittest.TestCase):
    def test_compound_token_ownership_uses_shared_helper(self):
        from fa_align import model_word_owners, sheet_hints
        owners = model_word_owners('ab-cd ef')
        self.assertEqual([o['target_token'] for o in owners], [0, 0, 1])
        aligned = [dict(**o, a=a, b=b) for o, a, b in zip(owners, [.2,.3,.6], [.3,.5,1.2])]
        hints = sheet_hints(target()['lyrics'], [dict(line=0, words=aligned)])
        self.assertEqual(hints[0, 0], (.2, .5))
        mapped, flags = run.map_words(target()['lyrics'], proposals(), 2.)
        self.assertEqual([w['w'] for w in mapped[0]['words']], ['ab-cd', 'ef'])
        self.assertEqual(flags, [])
        aligned[1]['target_token'] = 1
        with self.assertRaises(ValueError):
            sheet_hints(target()['lyrics'], [dict(line=0, words=aligned)])

    def test_crossing_starts_repair_without_reordering_text(self):
        p = proposals(); p[0].update(a=.8,b=1.); p[1].update(a=.6,b=1.2)
        mapped, flags = run.map_words(target()['lyrics'], p, 2.)
        words = mapped[0]['words']
        self.assertEqual([w['w'] for w in words], ['ab-cd','ef'])
        self.assertEqual([w['a'] for w in words], [.68, .72])
        self.assertLessEqual(words[0]['b'], words[1]['a'])
        self.assertTrue(all(w['c'] <= .4 for w in words))
        self.assertEqual(len(flags), 2)

    def test_projection_bounds_and_infeasible_duration(self):
        self.assertEqual(run.ordered_starts([0, 0, 1.999], 2.), [0., .04, 1.96])
        with self.assertRaises(ValueError): run.ordered_starts([.1]*60, 2.)
        with self.assertRaises(ValueError): run.ordered_starts([float('nan')], 2.)

    def test_rejects_missing_extra_wrong_tokens_bad_spans_and_confidence(self):
        for p in (proposals()[:1], proposals()+proposals(),
                  [dict(w='other',a=.2,b=.5,confidence=.9),proposals()[1]]):
            with self.assertRaises(ValueError): run.map_words(target()['lyrics'],p,2.)
        for key, value in [('a',-1),('a',float('nan')),('b',.1),('b',3),('confidence',1.1)]:
            p=proposals(); p[0][key]=value
            with self.subTest(key=key,value=value), self.assertRaises(ValueError):
                run.map_words(target()['lyrics'],p,2.)

    def test_low_acoustic_confidence_is_doubtful(self):
        p=proposals(); p[0]['confidence']=.59
        mapped,_=run.map_words(target()['lyrics'],p,2.)
        self.assertLessEqual(mapped[0]['words'][0]['c'],.4)


class Voicing(unittest.TestCase):
    def test_audible_aperiodic_absence_only_and_half_open_spans(self):
        song=target(); n=len(song['points']); t=np.arange(n)*.02
        F=dict(qa_t=t,qa_db=np.full(n,-20.),qa_periodicity=np.zeros(n),qa_concentration=np.zeros(n))
        F['qa_db'][:5]=-100 # silence
        F['qa_periodicity'][80:]=.9 # harmonic with no pitch estimate
        run.unpitched(song,F)
        self.assertEqual(song['unpitched'],[dict(a=1.4,b=1.6,kind='noise')])
        self.assertEqual(run.validate(song),[])
        self.assertIsNone(song['points'][70][1])
        self.assertEqual(song['points'][69][1],69.)
        # The shared explicit-clear writer must use the same grid boundary.
        from apply_edits import apply_melody
        explicit=target()
        explicit['points'][70]=[1.4,69.,.9,1]
        op=dict(op='clear',a=1.4,b=1.6,kind='noise')
        apply_melody(Path('.'),explicit['points'],[op])
        run.update_unpitched(explicit,[op])
        self.assertIsNone(explicit['points'][70][1])
        self.assertEqual(explicit['unpitched'],[dict(a=1.4,b=1.6,kind='noise')])

    def test_short_gaps_and_silence_do_not_become_noise(self):
        song=target(); n=len(song['points'])
        F=dict(qa_t=np.arange(n)*.02,qa_db=np.full(n,-100.),
               qa_periodicity=np.zeros(n),qa_concentration=np.zeros(n))
        F['qa_db'][70:75]=-20
        run.unpitched(song,F)
        self.assertEqual(song['unpitched'],[])

    def test_synthetic_features_and_real_end_checks(self):
        with tempfile.TemporaryDirectory() as d:
            pkg=package(Path(d)); base=target()
            with patch.object(run.bench,'align',return_value=(proposals(),{})):
                song,report=run.place(pkg,base,base,'cpu',pitch_song=target())
            types={f['type'] for f in report['flags']}
            self.assertIn('word_start',types)
            self.assertIn('word_confidence',types)
            self.assertTrue(report['review_required'])
            self.assertEqual(run.validate(song),[])
            # Real writer output passes the previous stage's reader/scorer.
            neutral=run.bench.baseline(song); neutral.update(runtime_s=0.,candidate='song_auto',measured_component='both')
            run.bench.validate(neutral)
            self.assertEqual(score.score(base,neutral)['words']['all']['within80'],1.)

    def test_end_checks_keep_octave_broken_and_repeat_candidates(self):
        with tempfile.TemporaryDirectory() as d:
            pkg=package(Path(d)); base=target()
            flags=[dict(type=k,a=.4,b=.8) for k in ('octave','broken','repeat')]
            with patch.object(run.bench,'align',return_value=(proposals(),{})), patch.object(run,'detect',return_value=flags):
                song,report=run.place(pkg,base,base,'cpu',pitch_song=target())
            self.assertTrue({'octave','broken','repeat'} <= {f['type'] for f in report['flags']})
            self.assertLessEqual(song['lyrics'][0]['words'][1]['c'],.4)


class WritePath(unittest.TestCase):
    def setUp(self):
        clock=patch.object(run,'datetime'); frozen=clock.start(); self.addCleanup(clock.stop)
        frozen.now.side_effect=[datetime(2020,1,1,tzinfo=timezone.utc)+timedelta(seconds=i) for i in range(20)]
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.pkg=package(self.root)
        self.trainer=self.root/'trainer.html'; self.trainer.write_text('old trainer')
        run.write_json(self.pkg/'manifest.json',dict(html=dict(path=str(self.trainer))))
        self.before={p:p.read_bytes() for p in (self.pkg/'target.json',self.trainer,self.pkg/'manifest.json')}
        self.expected=run.bench.digest(self.pkg/'target.json')
        self.song=target(); self.song['id']='fedcba98765432100123'
        self.out=self.root/'output'; self.out.mkdir()
        self.html=run.full_build(self.pkg,self.song,self.out)

    def test_backup_precedes_write_and_full_build_uses_package(self):
        real=run.build_trainer
        def build(pkg,song,html):
            backups=list((self.root/'backups').glob('song-auto-*/*'))
            self.assertEqual(len(backups),1)
            self.assertEqual((backups[0]/'target.json').read_bytes(),self.before[self.pkg/'target.json'])
            self.assertEqual((backups[0]/'trainer.html').read_bytes(),b'old trainer')
            self.assertEqual(pkg,self.pkg)
            return real(pkg,song,html)
        with patch.object(run,'build_trainer',side_effect=build):
            backup=run.apply(self.pkg,self.song,self.html,self.trainer,self.expected)
        from build_html import embedded_song
        self.assertEqual(json.loads(embedded_song(self.trainer)),self.song)
        self.assertEqual(run.bench.read(self.pkg/'target.json'),self.song)
        self.assertTrue((backup/'restore.json').exists())

    def test_failures_after_each_mutation_restore_all_records(self):
        for failure in ('target','build','trainer','manifest'):
            with self.subTest(failure=failure):
                original_json,original_text=run.write_json,run.atomic_text
                fired=[False]
                def write(path,data):
                    result=original_json(path,data)
                    if not fired[0] and ((failure=='target' and path==self.pkg/'target.json') or (failure=='manifest' and path==self.pkg/'manifest.json')):
                        fired[0]=True; raise OSError('injected failure')
                    return result
                def text(path,data):
                    result=original_text(path,data)
                    if failure=='trainer' and path==self.trainer and not fired[0]:
                        fired[0]=True; raise OSError('injected failure')
                    return result
                build=patch.object(run,'build_trainer',side_effect=OSError('injected failure')) if failure=='build' else patch.object(run,'build_trainer',wraps=run.build_trainer)
                with patch.object(run,'write_json',side_effect=write),patch.object(run,'atomic_text',side_effect=text),build:
                    with self.assertRaises(OSError): run.apply(self.pkg,self.song,self.html,self.trainer,self.expected)
                self.assertEqual({p:p.read_bytes() for p in self.before},self.before)

    def test_backup_failure_and_stale_target_write_nothing(self):
        with patch.object(run.shutil,'copy2',side_effect=OSError('backup failed')):
            with self.assertRaises(OSError): run.apply(self.pkg,self.song,self.html,self.trainer,self.expected)
        self.assertEqual({p:p.read_bytes() for p in self.before},self.before)
        with self.assertRaises(ValueError): run.apply(self.pkg,self.song,self.html,self.trainer,'stale')
        self.assertEqual({p:p.read_bytes() for p in self.before},self.before)

    def test_missing_trainer_and_manifest_rollback_to_absence(self):
        self.trainer.unlink(); (self.pkg/'manifest.json').unlink()
        with patch.object(run,'build_trainer',side_effect=OSError('build failed')):
            with self.assertRaises(OSError): run.apply(self.pkg,self.song,self.html,self.trainer,self.expected)
        self.assertFalse(self.trainer.exists()); self.assertFalse((self.pkg/'manifest.json').exists())
        self.assertEqual((self.pkg/'target.json').read_bytes(),self.before[self.pkg/'target.json'])

    def test_trainer_manifest_paths_are_bounded(self):
        self.assertEqual(run.trainer_path(self.pkg),self.trainer)
        run.write_json(self.pkg/'manifest.json',dict(html=dict(path=str(self.root.parent/'outside.html'))))
        with self.assertRaises(ValueError): run.trainer_path(self.pkg)

    def test_concurrent_auto_writer_is_refused_without_mutation(self):
        with open(self.pkg/'.song-auto.lock','a') as lock:
            run.fcntl.flock(lock,run.fcntl.LOCK_EX | run.fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                run.apply(self.pkg,self.song,self.html,self.trainer,self.expected)
        self.assertEqual({p:p.read_bytes() for p in self.before},self.before)

    def test_build_failure_leaves_source_unchanged(self):
        (self.pkg/'backing.mp3').unlink()
        out=self.root/'failed'; out.mkdir()
        with self.assertRaises(FileNotFoundError): run.full_build(self.pkg,self.song,out)
        self.assertEqual({p:p.read_bytes() for p in self.before},self.before)


class Process(unittest.TestCase):
    def test_one_time_provisioning_is_explicit_and_uses_external_cache(self):
        import torchaudio, torchcrepe
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ,{},clear=False), \
                patch.object(torchaudio.pipelines.MMS_FA,'get_model') as mms, \
                patch.object(torchcrepe.load,'model') as crepe, contextlib.redirect_stdout(io.StringIO()):
            run.main(['--download-models','--model-cache',d])
            mms.assert_called_once_with(with_star=True)
            crepe.assert_called_once_with('cpu','full')
            self.assertEqual(os.environ['TORCH_HOME'],str(Path(d).resolve()))
            for cache in (ROOT,Path(sys.prefix)):
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    run.main(['--download-models','--model-cache',str(cache)])
            self.assertEqual(mms.call_count,1)

    def test_offline_blocks_network_and_restores_socket(self):
        previous=socket.create_connection
        with run.offline():
            with self.assertRaises(RuntimeError): socket.create_connection(('127.0.0.1',9))
            with socket.socket() as sock:
                with self.assertRaises(RuntimeError): sock.connect(('127.0.0.1',9))
        self.assertIs(socket.create_connection,previous)

    def test_real_process_scratch_defaults_restarts_and_scoring(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); pkg=package(root)
            before={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in pkg.iterdir()}
            runner=root/'stub.py'
            runner.write_text('import sys\nsys.path.insert(0,'+repr(str(ROOT))+')\n'
                'from tools.song_auto import run\n'
                'run.bench.align=lambda *a: ('+repr(proposals())+', {})\n'
                'run.pitch_target=lambda package,base,device: base\n'
                'run.main()\n')
            outputs=[]
            for _ in range(2):
                env={**os.environ,'TMPDIR':str(root)}
                result=subprocess.run([sys.executable,str(runner),str(pkg),'--device','cpu',
                    '--model-cache',str(root/'models'),'--word-refinement','boundary'],env=env,capture_output=True,text=True,timeout=60)
                self.assertEqual(result.returncode,0,result.stderr)
                response=json.loads(result.stdout.splitlines()[-1]); output=Path(response['output'])
                outputs.append(output)
                neutral=run.bench.read(output)
                self.assertEqual(score.score(target(),neutral)['words']['all']['within80'],1.)
                self.assertTrue((output.parent/'trainer.html').exists())
                self.assertIn('QA:',result.stdout)
                self.assertEqual(run.bench.read(output.parent/'checks.json')['refinement'],'boundary')
            self.assertNotEqual(outputs[0],outputs[1])
            self.assertEqual(run.bench.read(outputs[0])['pitch'],run.bench.read(outputs[1])['pitch'])
            self.assertEqual({p:(p.read_bytes(),p.stat().st_mtime_ns) for p in before},before)

    def test_hostile_scratch_and_symlink_fail_privately_across_restarts(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); pkg=package(root)
            link=root/'link'; link.symlink_to(pkg,target_is_directory=True)
            for scratch in (pkg,link):
                for _ in range(2):
                    result=subprocess.run([sys.executable,'-m','tools.song_auto.run',str(pkg),
                        '--scratch',str(scratch)],cwd=ROOT,capture_output=True,text=True,timeout=30)
                    self.assertNotEqual(result.returncode,0)
                    self.assertNotIn(str(pkg),result.stdout+result.stderr)
                    self.assertIn('song_auto failed:',result.stderr)


class Preparation(unittest.TestCase):
    def test_option_default_reuses_fresh_pitch_and_propagates_failure(self):
        sys.path.insert(0,str(ROOT/'studio'))
        import prepare_song as prepare
        for mode in ('default','auto','refined','failure'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as d:
                root=Path(d); src=root/'input.wav'
                sf.write(src,np.zeros((88200,2)),44100)
                args=['prepare_song.py',str(src),'--title','Synthetic','--out',str(root/'songs'),'--device','cpu']
                if mode!='default': args.append('--auto-place')
                if mode=='refined': args.extend(['--word-refinement','boundary'])
                raw=[dict(text=' ab-cd',start_ms=200,end_ms=500,confidence=.9),
                     dict(text=' ef',start_ms=600,end_ms=1200,confidence=.9)]
                seen=[]
                def placement(pkg,base,seed,device,pitch_song=None,refinement='none'):
                    seen.append(pitch_song)
                    self.assertIs(pitch_song,base)
                    self.assertIs(seed,base)
                    self.assertEqual(refinement,'boundary' if mode=='refined' else 'none')
                    if mode=='failure': raise RuntimeError('offline cache miss')
                    song=copy.deepcopy(base); song['id']='abcdef01234567890123'
                    return song,dict(flags=[],review_required=False)
                with contextlib.ExitStack() as stack:
                    stack.enter_context(patch.dict(os.environ,{},clear=False))
                    stack.enter_context(patch.object(sys,'argv',args))
                    stack.enter_context(patch.object(prepare,'separate',side_effect=lambda x,*a:(x,dict(device='cpu'))))
                    stack.enter_context(patch.object(prepare,'track_pitch',return_value=(None,None,None,None,{})))
                    stack.enter_context(patch.object(prepare,'build_map',side_effect=lambda *a:target()))
                    stack.enter_context(patch.object(prepare.covers,'extract',return_value=None))
                    stack.enter_context(patch.object(prepare.stems,'joint_gain',return_value=1.))
                    stack.enter_context(patch.object(prepare,'soniox_key',return_value='synthetic credential'))
                    stack.enter_context(patch.object(prepare,'soniox_tokens',return_value=raw))
                    stack.enter_context(patch.object(prepare,'align_context',return_value={}))
                    stack.enter_context(patch.object(prepare,'realign',return_value=target()['lyrics']))
                    stack.enter_context(patch.object(run,'place',side_effect=placement))
                    stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                    if mode=='failure':
                        with self.assertRaisesRegex(RuntimeError,'offline cache miss'): prepare.main()
                    else: prepare.main()
                pkg=root/'songs/Synthetic'
                if mode=='failure':
                    self.assertFalse((pkg/'target.json').exists())
                    self.assertFalse((root/'songs/Luma_Synthetic.html').exists())
                else:
                    manifest=run.bench.read(pkg/'manifest.json')
                    song=run.bench.read(pkg/'target.json')
                    self.assertEqual('auto_place' in manifest['steps'],mode!='default')
                    self.assertEqual(song['id'],'abcdef01234567890123' if mode!='default' else target()['id'])
                    self.assertEqual(manifest['map']['id'],song['id'])
                    from build_html import embedded_song
                    self.assertEqual(json.loads(embedded_song(root/'songs/Luma_Synthetic.html')),song)
                self.assertEqual(len(seen),0 if mode=='default' else 1)


if __name__ == '__main__':
    unittest.main()
