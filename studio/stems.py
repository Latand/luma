"""Playback stems: the audio a Luma trainer actually plays.

The trainer mixes two stems, the Demucs vocal ("foreground") and the rest of the mix ("backing" = mix − vocal), at 1.0x
and at 0.8x. They are cut here from full-rate float audio and stay 44.1 kHz stereo; the 22 kHz signals that pitch analysis
and transcription read never pass through this module.

  1.0x   MP3 CBR 256 kb/s: each stem keeps its own waveform within about −41 dB, which matters because the trainer plays
         the stems at any balance and the backing alone when the voice is off.
  0.8x   MP3 VBR -q:a 2. Time stretching reshapes the waveform far more than this encoder does, and these files are 1.25x
         longer, so they take the smaller setting.
  tempo  ffmpeg's rubberband filter with both channels stretched together (stereo image kept, the two stems stay within
         a few ms of each other); atempo only when this ffmpeg was built without librubberband.

docs/AUDIO_QUALITY.md has the measurements behind these choices and what they cost in trainer HTML size.
"""
from __future__ import annotations
import functools, json, subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np

SAMPLE_RATE = 44100
ROLES = ('foreground', 'backing')
SPEEDS = ((1.0, '', ('-b:a', '256k')), (0.8, '_80', ('-q:a', '2')))
FILES = tuple(role + suffix + '.mp3' for role in ROLES for _, suffix, _ in SPEEDS)
ENCODER = 'libmp3lame 44.1 kHz stereo: 1.0x CBR 256 kb/s, 0.8x VBR -q:a 2'

def ffmpeg(*a): subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', *map(str, a)], check=True)

@functools.cache
def tempo_engine() -> str:
    """'rubberband' when the local ffmpeg has librubberband, otherwise 'atempo'."""
    out = subprocess.run(['ffmpeg', '-hide_banner', '-filters'], capture_output=True, text=True).stdout
    return 'rubberband' if any(line.split()[1:2] == ['rubberband'] for line in out.splitlines()) else 'atempo'

def tempo_filter(speed: float) -> str:
    return f'rubberband=tempo={speed}:channels=together' if tempo_engine() == 'rubberband' else f'atempo={speed}'

def decode(path: Path, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Any audio file as float32 stereo at `sr`, the same samples prepare_song's decode step writes to mix.wav."""
    raw = subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-i', str(path), '-vn', '-ar', str(sr), '-ac', '2', '-f', 'f32le', '-'],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype='<f4').reshape(-1, 2).copy()

def joint_gain(*signals: np.ndarray) -> float:
    """One gain for both stems, so their balance and their sum survive; the louder peak lands at 0.97 or below."""
    return min(1.0, .97 / max([float(np.max(np.abs(s))) for s in signals] + [1.0]))

def encode(sources: dict[str, Path], duration: float, out_dir: Path) -> dict:
    """foreground / backing audio files -> the four trainer MP3s in `out_dir`, each 44.1 kHz stereo and padded or trimmed
    to exactly duration / speed, so both stems of one speed always have the same length."""
    jobs = []
    for role in ROLES:
        for speed, suffix, quality in SPEEDS:
            chain = [f'aresample={SAMPLE_RATE}'] + ([tempo_filter(speed)] if speed != 1 else []) + ['apad', f'atrim=duration={duration / speed:.9f}']
            jobs.append(('-i', sources[role], '-af', ','.join(chain), '-ac', '2', '-c:a', 'libmp3lame', *quality, '-write_xing', '1', out_dir / f'{role}{suffix}.mp3'))
    with ThreadPoolExecutor(len(jobs)) as pool: list(pool.map(lambda job: ffmpeg(*job), jobs))
    return {'sample_rate': SAMPLE_RATE, 'channels': 2, 'encoder': ENCODER, 'tempo': tempo_filter(0.8)}

def probe(path: Path) -> dict:
    """Codec, sample rate, channels, duration and average bitrate (from the file size) of an audio file."""
    out = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a:0', '-show_entries', 'stream=codec_name,sample_rate,channels:format=duration', '-of', 'json', str(path)],
                         check=True, capture_output=True, text=True).stdout
    d = json.loads(out); s = d['streams'][0]; duration = float(d['format']['duration']); size = path.stat().st_size
    return {'codec': s['codec_name'], 'sample_rate': int(s['sample_rate']), 'channels': int(s['channels']), 'duration': duration, 'kbps': round(size * 8 / duration / 1000), 'bytes': size}

def shifted(x: np.ndarray, lag: int, n: int) -> np.ndarray:
    """`n` frames of `x` starting at frame `lag` (negative: leading silence), zero-padded at either end."""
    out = np.zeros((n, x.shape[1]), dtype=x.dtype); src = x[max(lag, 0):]; at = max(-lag, 0); k = max(0, min(len(src), n - at))
    out[at:at + k] = src[:k]; return out

def alignment(mix: np.ndarray, vocal: np.ndarray, sr: int = SAMPLE_RATE, blocks: int = 8) -> dict:
    """Where a stored vocal stem sits inside a decoded mix, measured before anything is subtracted.

    The blocks where the vocal is loudest are cross-correlated with the mix over ±100 ms. `lag` is the frame of the mix
    that matches the first frame of the vocal. `gain` is the least-squares amount of that vocal inside the mix at the lag,
    and `gain_1ms` the same one millisecond later. A Demucs vocal of this very mix measures a little above 1 at the lag
    (the estimate runs slightly quiet, so some of the voice stays in the rest of the mix and adds to the projection; 1.05 to
    1.27 on real songs) and near 0 a millisecond away, which is what "sample-exact" means here. `ok` requires every block
    to agree on one lag, a gain between 0.8 and 1.5 there, and less than half of it a millisecond off."""
    n = min(len(mix), len(vocal)); block = min(1 << 17, n // 4); max_lag = min(sr // 10, block // 4); off = sr // 1000
    if block < sr // 2: return {'ok': False, 'reason': 'too short to measure'}
    starts = np.linspace(max_lag, n - block - max_lag - off, 40).astype(int)
    vm = vocal.mean(1); mm = mix.mean(1)
    loud = sorted(starts, key=lambda i: -float(np.dot(vm[i:i + block], vm[i:i + block])))[:blocks]
    lags = []
    for i in loud:
        v = vm[i:i + block]; m = mm[i - max_lag:i + block + max_lag]
        c = np.fft.irfft(np.fft.rfft(m, len(m)) * np.conj(np.fft.rfft(v, len(m))), len(m))   # c[k] = sum m[j + k] v[j]
        lags.append(int(np.argmax(c[:2 * max_lag + 1])) - max_lag)
    lag = max(set(lags), key=lags.count)
    def gain(at):
        num = den = 0.0
        for i in loud:
            v = vocal[i:i + block]; m = shifted(mix, i + at, block); num += float(np.sum(m * v)); den += float(np.sum(v * v))
        return num / den if den > 0 else 0.0
    g, g1 = gain(lag), gain(lag + off)
    ok = len(set(lags)) == 1 and .8 <= g <= 1.5 and g1 < .5 * g
    return {'ok': ok, 'lag': lag, 'blocks': len(lags), 'agree': lags.count(lag), 'gain': round(g, 4), 'gain_1ms': round(g1, 4)}

def split(mix: np.ndarray, vocal: np.ndarray, lag: int) -> tuple[np.ndarray, np.ndarray]:
    """foreground = the stored vocal, backing = the aligned original minus it, both on the vocal's timeline."""
    return vocal, shifted(mix, lag, len(vocal)) - vocal
