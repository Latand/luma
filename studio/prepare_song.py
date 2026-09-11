#!/usr/bin/env python3
"""Turn one audio file into a standalone Luma trainer, entirely on this machine:

  FFmpeg decode -> official HTDemucs (fine-tuned) vocal separation -> pYIN + CREPE pitch on the vocal stem
  -> note map (draft, unverified) -> 1.0x / 0.8x stems -> optional word timings (Soniox API) -> single HTML file.

Usage:
  prepare_song.py song.m4a --title "Song" --artist "Artist" [--out songs] [--no-lyrics] [--lang en]

The only network traffic is the one-time Demucs weight download and, if enabled, the transcription request to Soniox
(set SONIOX_API_KEY or put the key in ~/.config/luma/soniox-api-key; otherwise lyrics are skipped).
"""
from __future__ import annotations
import argparse, hashlib, json, os, platform, subprocess, sys, time, uuid, urllib.request, urllib.error
from pathlib import Path
import numpy as np, soundfile as sf, librosa, scipy.ndimage as ndi

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'studio'))
from build_html import build as build_html

def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''): h.update(chunk)
    return h.hexdigest()
def ffmpeg(*a): subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', *map(str, a)], check=True)
def log(*a): print(time.strftime('%H:%M:%S'), *a, flush=True)
def runs(mask):
    edges = np.flatnonzero(np.diff(np.r_[False, mask, False].astype(int))); return list(zip(edges[::2], edges[1::2]))
def slugify(t: str) -> str: return ''.join(c if c.isalnum() else '_' for c in t).strip('_') or 'song'

# ---------------------------------------------------------------- Soniox (optional)
def soniox_key() -> str | None:
    k = os.environ.get('SONIOX_API_KEY')
    if k: return k.strip()
    f = Path.home() / '.config' / 'luma' / 'soniox-api-key'
    return f.read_text().strip() if f.exists() else None

def soniox_words(audio: Path, key: str, lang: str) -> list[dict]:
    api = 'https://api.soniox.com/v1'; auth = {'Authorization': 'Bearer ' + key}
    boundary = uuid.uuid4().hex; body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{audio.name}"\r\nContent-Type: application/octet-stream\r\n\r\n').encode() + audio.read_bytes() + f'\r\n--{boundary}--\r\n'.encode()
    def call(path, data=None, headers=None, method=None):
        req = urllib.request.Request(api + path, data=data, headers={**auth, **(headers or {})}, method=method)
        with urllib.request.urlopen(req, timeout=120) as r: return json.loads(r.read().decode())
    fid = call('/files', body, {'Content-Type': f'multipart/form-data; boundary={boundary}'}, 'POST')['id']
    tid = call('/transcriptions', json.dumps({'model': 'stt-async-v5', 'file_id': fid, 'language_hints': [lang], 'enable_speaker_diarization': False}).encode(), {'Content-Type': 'application/json'}, 'POST')['id']
    for _ in range(300):
        st = call(f'/transcriptions/{tid}')['status']
        if st == 'completed': break
        if st == 'error': raise RuntimeError('Soniox transcription failed')
        time.sleep(3)
    toks = call(f'/transcriptions/{tid}/transcript')['tokens']
    words = []
    for t in toks:
        tx = t['text']
        if not tx.strip(): continue
        a = t['start_ms'] / 1000; b = t['end_ms'] / 1000; c = t.get('confidence') or 0
        if words and not tx.startswith(' '):
            if tx.strip()[0] in '.,!?': words[-1]['w'] += tx.strip(); words[-1]['b'] = round(max(words[-1]['b'], b), 2)
            else: words[-1]['w'] += tx; words[-1]['b'] = round(max(words[-1]['b'], b), 2); words[-1]['c'] = round(min(words[-1]['c'], c), 2)
        else: words.append({'a': round(a, 2), 'b': round(b, 2), 'w': tx.strip(), 'c': round(c, 2)})
    return words

def group_lines(words: list[dict]) -> list[dict]:
    lines, cur = [], []
    for w in words:
        if cur and ((w['a'] - cur[-1]['b'] > 1.0) or (cur[-1]['w'][-1] in '.!?' and w['a'] - cur[-1]['b'] > .45) or len(cur) >= 9): lines.append(cur); cur = []
        cur.append(w)
    if cur: lines.append(cur)
    return [{'a': l[0]['a'], 'b': l[-1]['b'], 'words': l} for l in lines]

# ---------------------------------------------------------------- map (CREPE pitch, pYIN cross-check)
def build_map(ct, f0, pd, P, mix22, duration, title, artist, method):
    hop = .02; ts = np.arange(0, duration, hop)
    def nearest(src_t, vals):
        ii = np.clip(np.searchsorted(src_t, ts), 1, len(src_t) - 1); ii -= abs(src_t[ii - 1] - ts) < abs(src_t[ii] - ts); return vals[ii]
    fc = nearest(ct, f0); pdg = nearest(ct, pd); fp = nearest(P[:, 0], P[:, 1]); rms = nearest(P[:, 0], P[:, 3])
    with np.errstate(divide='ignore', invalid='ignore'):
        midi = 69 + 12 * np.log2(fc / 440); mp = 69 + 12 * np.log2(fp / 440); db = 20 * np.log10(rms + 1e-12); agree = np.abs(midi - mp) * 100
    valid = np.isfinite(midi) & (pdg > .45) & (db > -43) & (midi >= 43) & (midi <= 90)
    for a, b in runs(valid):
        if b - a < 5: valid[a:b] = False
    reliable = valid & (pdg >= .70) & (db > -38) & ((np.isfinite(agree) & (agree < 50)) | (pdg >= .85))
    for a, b in runs(valid): reliable[a:min(a + 2, b)] = False; reliable[max(a, b - 2):b] = False
    smooth = np.full(len(ts), np.nan)
    for a, b in runs(valid): smooth[a:b] = ndi.median_filter(midi[a:b], size=5, mode='nearest')
    notes = []
    for a, b in runs(valid):
        cur = int(round(smooth[a])); start = a
        for i in range(a + 1, b + 1):
            if i == b or abs(smooth[i] - cur) > .72:
                if i - start >= 4:
                    center = float(np.median(midi[start:i])); elig = float(np.mean(reliable[start:i]))
                    notes.append({'id': len(notes), 'a': round(ts[start], 3), 'b': round(min(duration, ts[i - 1] + hop), 3), 'm': round(center, 3), 'n': int(round(center)), 'q': round(float(np.median(pdg[start:i])), 3), 'ok': elig >= .55, 'ignored': False})
                if i < b: cur = int(round(smooth[i])); start = i
    intervals = []
    for n in notes:
        if not intervals or n['a'] - intervals[-1][1] > .85: intervals.append([n['a'], n['b']])
        else: intervals[-1][1] = n['b']
    phrases = []
    for a, b in intervals:
        if b - a < .65: continue
        chunks = max(1, int(np.ceil((b - a) / 8)))
        for k in range(chunks):
            aa = a + (b - a) * k / chunks; bb = a + (b - a) * (k + 1) / chunks
            if k and phrases and aa - phrases[-1]['b'] < 0: aa = phrases[-1]['b']
            phrases.append({'id': len(phrases) + 1, 'a': round(max(0, aa - .45), 2), 'b': round(min(duration, bb + .45), 2), 'label': f'Фрагмент {len(phrases)+1:02d}', 'verified': False})
    peaks = [round(float(np.max(z)), 3) for z in np.array_split(np.max(abs(mix22), axis=1), 1000)]
    points = [[round(float(t), 3), round(float(m), 3) if v else None, round(float(q), 3) if v else 0, int(ok)] for t, m, q, v, ok in zip(ts, midi, pdg, valid, reliable)]
    comparable = float(reliable.sum() * hop); initial = next((n['a'] for n in notes if n['ok'] and n['b'] - n['a'] > .2), 0)
    song = {'schema': 'luma.song.v1', 'title': title, 'artist': artist, 'duration': duration, 'a4': 440, 'hop': hop, 'status': 'unverified_draft', 'neuralSeparation': True, 'method': method,
            'warning': 'Автоматична чернетка. Можливі інструментальні та октавні помилки. Перевір фразу перед оцінюванням.', 'points': points, 'notes': notes, 'phrases': phrases, 'waveform': peaks, 'initialTime': max(0, initial - .75),
            'metrics': {'notes': len(notes), 'candidateSeconds': round(float(valid.sum() * hop), 2), 'comparableSeconds': round(comparable, 2), 'comparablePercentOfTrack': round(100 * comparable / duration, 1)},
            'createdBy': 'Luma Studio offline preparation; no human note-by-note verification'}
    song['id'] = hashlib.sha256((title + artist + str(duration) + method).encode()).hexdigest()[:20]
    return song

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('audio'); ap.add_argument('--title', required=True); ap.add_argument('--artist', default=''); ap.add_argument('--out', default=str(ROOT / 'songs'))
    ap.add_argument('--model', default='htdemucs_ft', choices=['htdemucs', 'htdemucs_ft']); ap.add_argument('--device', default='auto', choices=['auto', 'cpu', 'cuda'])
    ap.add_argument('--no-lyrics', action='store_true'); ap.add_argument('--lang', default='en'); ap.add_argument('--out-html')
    a = ap.parse_args(); src = Path(a.audio).expanduser().resolve()
    if not src.is_file(): ap.error('audio file not found')
    slug = slugify(a.title); pkg = Path(a.out).expanduser().resolve() / slug; work = pkg / 'work'; pkg.mkdir(parents=True, exist_ok=True); work.mkdir(exist_ok=True)
    out_html = Path(a.out_html).expanduser().resolve() if a.out_html else pkg.parent / f'Luma_{slug}.html'
    manifest = {'source': str(src), 'source_sha256': sha256(src), 'title': a.title, 'artist': a.artist, 'started': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'host': platform.node(), 'steps': {}}
    T0 = time.time()

    log('[1/8] decode'); ffmpeg('-i', src, '-vn', '-ar', '44100', '-ac', '2', '-c:a', 'pcm_f32le', work / 'mix.wav')
    x, sr = sf.read(work / 'mix.wav', dtype='float32', always_2d=True); duration = len(x) / sr; manifest['duration'] = duration
    if not 1 <= duration <= 600: raise SystemExit('songs must be between 1 and 600 seconds')

    log('[2/8] separation', a.model); t1 = time.time()
    import torch
    from demucs.pretrained import get_model
    from demucs.apply import apply_model
    device = ('cuda' if torch.cuda.is_available() else 'cpu') if a.device == 'auto' else a.device
    os.environ['TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD'] = '1'  # official Demucs zoo archives only; never point this at untrusted checkpoints
    try: model = get_model(a.model).eval()
    finally: os.environ.pop('TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD', None)
    wav = torch.from_numpy(x.T.copy()); ref = wav.mean(0); mu = ref.mean(); std = ref.std()
    if float(std) < 1e-8: raise SystemExit('input audio is silent')
    with torch.inference_mode(): pred = apply_model(model, ((wav - mu) / std)[None], device=device, shifts=1, split=True, overlap=.25, progress=False, num_workers=0)[0]
    pred = pred.cpu() * std + mu; vocal = pred[model.sources.index('vocals')].T.numpy(); back = x - vocal
    manifest['steps']['separation'] = {'model': a.model, 'device': device, 'gpu': torch.cuda.get_device_name(0) if device == 'cuda' else None, 'max_vram_mib': round(torch.cuda.max_memory_allocated() / 2**20) if device == 'cuda' else None, 'seconds': round(time.time() - t1, 1), 'torch': torch.__version__}
    del model, pred, wav
    sf.write(work / 'vocals44.wav', vocal, sr, subtype='FLOAT')
    peak = max(float(np.max(abs(vocal))), float(np.max(abs(back))), 1); gain = min(1, .97 / peak)  # joint scaling keeps the stem balance
    sf.write(work / 'vocal22.wav', librosa.resample(vocal.T, orig_sr=sr, target_sr=22050).T * gain, 22050, subtype='FLOAT')
    sf.write(work / 'back22.wav', librosa.resample(back.T, orig_sr=sr, target_sr=22050).T * gain, 22050, subtype='FLOAT')
    ffmpeg('-i', work / 'mix.wav', '-ar', '22050', '-c:a', 'pcm_f32le', work / 'mix22.wav')

    log('[3/8] pYIN'); t2 = time.time()
    y, sr2 = sf.read(work / 'vocal22.wav', dtype='float32', always_2d=True); y = y.mean(axis=1); rows = []; hop = 256
    for start in np.arange(0, duration, 25):
        lo = max(0, int(round((start - .5) * sr2))); hi = min(len(y), int(round((start + 25.5) * sr2))); z = y[lo:hi]
        f, _, prob = librosa.pyin(z, fmin=librosa.note_to_hz('G2'), fmax=librosa.note_to_hz('E6'), sr=sr2, frame_length=2048, hop_length=hop, fill_na=np.nan)
        yf = librosa.yin(z, fmin=librosa.note_to_hz('G2'), fmax=librosa.note_to_hz('E6'), sr=sr2, frame_length=2048, hop_length=hop)
        rms = librosa.feature.rms(y=z, frame_length=2048, hop_length=hop)[0]; tt = lo / sr2 + np.arange(len(f)) * hop / sr2; keep = (tt >= start) & (tt < min(start + 25, duration))
        rows.extend(zip(tt[keep], f[keep], prob[keep], rms[keep], yf[keep]))
    P = np.array(rows); manifest['steps']['pyin_s'] = round(time.time() - t2, 1)

    log('[4/8] CREPE'); t3 = time.time()
    import torchcrepe
    y16 = librosa.resample(vocal.mean(1), orig_sr=sr, target_sr=16000)
    f0, pd = torchcrepe.predict(torch.from_numpy(y16)[None], 16000, hop_length=160, fmin=80, fmax=1500, model='full', batch_size=1024, device=device, return_periodicity=True, decoder=torchcrepe.decode.viterbi)
    pd = torchcrepe.filter.median(pd, 3); f0 = torchcrepe.filter.mean(f0, 3); f0 = f0[0].cpu().numpy(); pd = pd[0].cpu().numpy(); ct = np.arange(len(f0)) * 160 / 16000
    manifest['steps']['crepe'] = {'model': 'torchcrepe full', 'seconds': round(time.time() - t3, 1)}

    log('[5/8] map'); mix22, _ = sf.read(work / 'mix22.wav', dtype='float32', always_2d=True)
    method = f'{a.model} (official Demucs weights) + CREPE full (torchcrepe, Viterbi) cross-checked with pYIN'
    song = build_map(ct, f0, pd, P, mix22, duration, a.title, a.artist, method); song['sourceId'] = manifest['source_sha256']
    manifest['map'] = {'id': song['id'], 'metrics': song['metrics'], 'notes': len(song['notes']), 'ok_notes': sum(n['ok'] for n in song['notes'])}

    log('[6/8] stems'); t4 = time.time()
    for role, source in [('foreground', work / 'vocal22.wav'), ('backing', work / 'back22.wav')]:
        for speed, suffix in [(1, ''), (.8, '_80')]:
            ffmpeg('-i', source, '-af', f'atempo={speed},apad,atrim=duration={duration/speed:.9f}', '-c:a', 'libmp3lame', '-b:a', '128k', '-write_xing', '1', pkg / (role + suffix + '.mp3'))
    ffmpeg('-i', work / 'vocals44.wav', '-c:a', 'flac', pkg / 'vocals_44k.flac')
    manifest['steps']['encode_s'] = round(time.time() - t4, 1)

    log('[7/8] lyrics'); key = None if a.no_lyrics else soniox_key()
    if key:
        t5 = time.time()
        try:
            ffmpeg('-i', work / 'mix22.wav', '-ac', '1', '-c:a', 'libmp3lame', '-b:a', '96k', work / 'mix_mono.mp3')
            words = soniox_words(work / 'mix_mono.mp3', key, a.lang); song['lyrics'] = group_lines(words)
            song['lyricsSource'] = f'Soniox stt-async-v5, {time.strftime("%Y-%m-%d")}, automatic word timings'
            manifest['steps']['lyrics'] = {'seconds': round(time.time() - t5, 1), 'words': len(words), 'lines': len(song['lyrics'])}
        except (urllib.error.URLError, RuntimeError, KeyError) as e:
            log('  lyrics skipped:', e); song['lyrics'] = []; manifest['steps']['lyrics'] = {'error': str(e)}
    else:
        song['lyrics'] = []; manifest['steps']['lyrics'] = {'skipped': 'no Soniox key' if not a.no_lyrics else 'disabled'}
    (pkg / 'target.json').write_text(json.dumps(song, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')

    log('[8/8] html'); build_html(pkg, out_html)
    manifest['html'] = {'path': str(out_html), 'bytes': out_html.stat().st_size, 'sha256': sha256(out_html)}
    manifest['finished'] = time.strftime('%Y-%m-%dT%H:%M:%S%z'); manifest['total_s'] = round(time.time() - T0, 1)
    (pkg / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')
    for f in ['mix.wav', 'vocals44.wav', 'vocal22.wav', 'back22.wav', 'mix22.wav', 'mix_mono.mp3']:
        (work / f).unlink(missing_ok=True)
    log('DONE', json.dumps({'html': str(out_html), 'map': manifest['map'], 'lyrics': manifest['steps']['lyrics'], 'total_s': manifest['total_s']}, ensure_ascii=False))

if __name__ == '__main__':
    try: main()
    except KeyboardInterrupt: sys.exit(130)
