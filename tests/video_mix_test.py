"""Constant karaoke gains through the production composer, including encoded AAC true peaks."""
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'studio'))
import video

FF = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y']


class Mix(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='mix-'))
        self.game = self.tmp / 'game.h264'
        subprocess.run([*FF, '-f', 'lavfi', '-i', 'color=s=320x180:r=30:d=8',
                        '-c:v', 'libx264', '-threads', '2', '-f', 'h264', str(self.game)], check=True)
        self.take = {'back': .75, 'segments': [{'when': 10, 'stop': 18, 'a': 0, 'speed': 1}]}
        t = np.arange(8 * video.SR) / video.SR
        # Harmonic phrases with deterministic gaps and soft/loud passages. Independent backing.
        envelope = np.minimum(1, np.maximum(0, np.sin(np.pi * (t % 2)))) ** .5
        self.voice = envelope * (.6 + .4 * (t >= 4)) * (np.sin(2*np.pi*223*t) + .35*np.sin(2*np.pi*446*t))
        self.back = self.tmp / 'back.wav'
        sf.write(self.back, .17 * (np.sin(2*np.pi*137*t) + .4*np.sin(2*np.pi*587*t)), video.SR, subtype='FLOAT')

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def measure_file(self, path):
        return video.loudness(['-i', str(path)], ['[0:a]anull[source]'], 'source')

    def render(self, voices, stem):
        out = self.tmp / 'out.mp4'
        video.compose_media(self.game, None, voices, stem, self.take, 0, out)
        return out

    def test_quiet_normal_loud(self):
        rows = []
        back_level = self.measure_file(self.back)['lufs']
        for label, deficit in [('A (quiet)', -8.64), ('B (normal)', 0), ('C (loud)', 12)]:
            voice = self.tmp / 'voice.wav'
            sf.write(voice, self.voice * .1, video.SR, subtype='FLOAT')
            level = self.measure_file(voice)['lufs']
            # Match the old mix's voice/backing margin; quiet reproduces the observed deficit.
            scale = 10 ** ((back_level + 20*math.log10(.75) + deficit - level - 20*math.log10(.9)) / 20)
            sf.write(voice, self.voice * .1 * scale, video.SR, subtype='FLOAT')
            plan = video.mix_plan([voice], self.back, self.take)
            after = {}
            for role in ('voice', 'backing'):
                after[role] = video.loudness(*video.audio_track([voice], self.back, self.take, role, plan['gainDB'][role]), role)
            out = self.render([voice], self.back)
            mix = self.measure_file(out)
            margin = after['voice']['lufs'] - after['backing']['lufs']
            self.assertAlmostEqual(margin, 3, delta=.15)
            self.assertLess(mix['truePeak'], -1)
            # Every sample gets one constant gain. In particular, the loud input is attenuated without compression.
            self.assertTrue(all(math.isfinite(x) for x in plan['gainDB'].values()))
            # The actual AAC waveform retains the quieter/louder phrase ratio. Compare its
            # voice coefficient against the sources in both halves, allowing coding error.
            decoded = video.decode(out); source = video.decode(voice); backing = video.decode(self.back)
            coefficients = []
            for lo, hi in [(video.SR//2, 3*video.SR), (4*video.SR+video.SR//2, 7*video.SR)]:
                design = np.stack([source[lo:hi], backing[lo:hi]], axis=1)
                coefficients.append(np.linalg.lstsq(design, decoded[lo:hi], rcond=None)[0])
            self.assertAlmostEqual(coefficients[0][0]/coefficients[1][0], 1, delta=.02)
            # Both fixture sources are mono and follow the same upmix/downmix, so their
            # fitted coefficient ratio also verifies the balance in the actual AAC mix.
            for voice_coefficient, backing_coefficient in coefficients:
                encoded_margin = (plan['measured']['voice']['lufs'] - plan['measured']['backing']['lufs']
                                  + 20*math.log10(voice_coefficient/backing_coefficient))
                self.assertAlmostEqual(encoded_margin, 3, delta=.15)
            self.assertGreater(plan['gainDB']['voice'], 0) if deficit < 0 else None
            self.assertLess(plan['gainDB']['voice'], 0) if deficit > 0 else None
            # Render the old fixed gains and limiter through the same timeline for an encoded before comparison.
            old = video.compose_cmd(self.game, None, [voice], self.back, self.take, 0, self.tmp / 'before.mp4',
                                    {'gainDB': {'voice': 20*math.log10(.9), 'backing': 20*math.log10(.75)}})
            gi = old.index('-filter_complex') + 1
            old[gi] = old[gi].replace('duration=longest[a]', 'duration=longest,alimiter=limit=0.95:level=false:latency=true,apad[a]')
            subprocess.run(old, check=True, capture_output=True)
            before = {role: video.loudness(*video.audio_track([voice], self.back, self.take, role, gain), role)
                      for role, gain in [('voice', 20*math.log10(.9)), ('backing', 20*math.log10(.75))]}
            before['mix'] = self.measure_file(self.tmp / 'before.mp4')
            after['mix'] = mix
            rows.append({'case': label, 'before': before, 'after': after, 'marginLU': margin, 'gainDB': plan['gainDB']})
        if os.environ.get('LUMA_MIX_EVIDENCE'):
            Path(os.environ['LUMA_MIX_EVIDENCE']).write_text(json.dumps(rows, indent=2) + '\n')

    def test_silence_missing_backing_and_muted_backing(self):
        voice = self.tmp / 'voice.wav'; sf.write(voice, np.zeros(8 * video.SR), video.SR)
        plan = video.mix_plan([voice], self.back, self.take)
        self.assertEqual(plan['gainDB']['voice'], min(0, plan['gainDB']['voice']))
        self.assertLess(self.measure_file(self.render([voice], self.back))['truePeak'], -1)
        sf.write(voice, self.voice * .1, video.SR)
        for stem, back in [(None, .75), (self.back, 0)]:
            self.take['back'] = back
            plan = video.mix_plan([voice], stem, self.take)
            self.assertFalse(math.isfinite(plan['measured']['backing']['lufs']))
            self.assertLess(self.measure_file(self.render([voice], stem))['truePeak'], -1)
        sf.write(voice, np.zeros(8 * video.SR), video.SR)
        self.assertFalse(math.isfinite(self.measure_file(self.render([voice], None))['lufs']))

    def test_unmeasurable_short_loud_signal_does_not_retry_without_gain(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        reply = SimpleNamespace(stderr=b'{"input_i":"-inf","input_tp":"-0.5"}')
        with patch.object(video, 'run', return_value=reply) as run:
            measured = video.loudness([], [], 'source')
        self.assertEqual(run.call_count, 1)
        self.assertEqual(measured['truePeak'], -.5)
        self.assertFalse(math.isfinite(measured['lufs']))

    def test_aac_overshoot_retry_and_refusal(self):
        # Exercise the output verification around real encoded files, with deterministic
        # measurement injection only at the encoded result (the source measurements stay real).
        from unittest.mock import patch
        voice = self.tmp / 'voice.wav'; sf.write(voice, self.voice*.1, video.SR)
        real = video.loudness
        peaks = iter([-.7, -1.6]); gains = []
        def measured(inputs, graph, label, preamp=0):
            if label == 'encoded': return {'lufs': -18, 'truePeak': next(peaks)}
            return real(inputs, graph, label, preamp)
        original = video.compose_cmd
        def command(*args):
            gains.append(dict(args[-1]['gainDB'])); return original(*args)
        with patch.object(video, 'loudness', measured), patch.object(video, 'compose_cmd', command):
            self.render([voice], self.back)
        self.assertEqual(len(gains), 2)
        for role in gains[0]: self.assertAlmostEqual(gains[1][role]-gains[0][role], -.8)
        peaks = iter([-.7, -.5])
        with patch.object(video, 'loudness', measured):
            with self.assertRaises(video.Failed): self.render([voice], self.back)

    def test_high_crest_factor_uses_shared_attenuation(self):
        voice = self.tmp / 'voice.wav'
        samples = self.voice*.01; samples[2*video.SR] = .95
        sf.write(voice, samples, video.SR, subtype='FLOAT')
        plan = video.mix_plan([voice], self.back, self.take)
        self.assertLess(plan['gainDB']['voice'], video.VOICE_LUFS-plan['measured']['voice']['lufs'])
        levels = {role: video.loudness(*video.audio_track([voice],self.back,self.take,role,plan['gainDB'][role]),role)
                  for role in ('voice','backing')}
        self.assertAlmostEqual(levels['voice']['lufs']-levels['backing']['lufs'],3,delta=.15)
        self.assertLess(self.measure_file(self.render([voice],self.back))['truePeak'],-1)

    def test_below_gate_and_missing_input(self):
        voice = self.tmp / 'voice.wav'; sf.write(voice, self.voice * 1e-5, video.SR, subtype='FLOAT')
        plan = video.mix_plan([voice], self.back, self.take)
        self.assertGreater(plan['gainDB']['voice'], 60)
        self.assertLess(self.measure_file(self.render([voice], self.back))['truePeak'], -1)
        with self.assertRaises(subprocess.CalledProcessError):
            video.mix_plan([self.tmp / 'absent.wav'], self.back, self.take)


if __name__ == '__main__':
    unittest.main()
