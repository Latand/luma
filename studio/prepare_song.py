#!/usr/bin/env python3
"""Turn one audio file into a standalone Luma trainer, entirely on this machine:

  FFmpeg decode -> official HTDemucs (fine-tuned) vocal separation -> pYIN + CREPE pitch on the vocal stem
  -> note map (draft, unverified) -> 44.1 kHz 1.0x / 0.8x stems -> optional word timings (Soniox API on the vocal stem, then
  snapped to the voice offline) -> single HTML file.

Usage:
  prepare_song.py song.m4a --title "Song" --artist "Artist" [--out songs] [--no-lyrics] [--lang en] [--lyrics-from vocal|mix]

The only network traffic is the one-time Demucs weight download and, if enabled, the transcription request to Soniox
(set SONIOX_API_KEY or put the key in ~/.config/luma/soniox-api-key; otherwise lyrics are skipped).
"""
from __future__ import annotations
import argparse, hashlib, json, os, platform, shutil, subprocess, sys, time, uuid, urllib.request, urllib.error
from pathlib import Path
import numpy as np, soundfile as sf, librosa, scipy.ndimage as ndi

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'studio'))
from build_html import build as build_html
import stems
from align_lyrics import context as align_context, realign, save_transcript, aligned_note

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

def soniox_tokens(audio: Path, key: str, lang: str, transcription_id: str | None = None) -> list[dict]:
    """One paid transcription: upload, poll, return the tokens exactly as Soniox sent them. `transcription_id`
    fetches a transcription that was already paid for instead of starting a new one."""
    api = 'https://api.soniox.com/v1'; auth = {'Authorization': 'Bearer ' + key}
    boundary = uuid.uuid4().hex; body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{audio.name}"\r\nContent-Type: application/octet-stream\r\n\r\n').encode() + audio.read_bytes() + f'\r\n--{boundary}--\r\n'.encode()
    def call(path, data=None, headers=None, method=None):
        req = urllib.request.Request(api + path, data=data, headers={**auth, **(headers or {})}, method=method)
        with urllib.request.urlopen(req, timeout=120) as r: return json.loads(r.read().decode())
    tid = transcription_id
    if not tid:
        fid = call('/files', body, {'Content-Type': f'multipart/form-data; boundary={boundary}'}, 'POST')['id']
        tid = call('/transcriptions', json.dumps({'model': 'stt-async-v5', 'file_id': fid, 'language_hints': [lang], 'enable_speaker_diarization': False}).encode(), {'Content-Type': 'application/json'}, 'POST')['id']
    try:
        for _ in range(300):
            st = call(f'/transcriptions/{tid}')['status']
            if st == 'completed': break
            if st == 'error': raise RuntimeError('Soniox transcription failed')
            time.sleep(3)
        return call(f'/transcriptions/{tid}/transcript')['tokens']
    except Exception as e:
        raise RuntimeError(f'{type(e).__name__}: {e} (transcription {tid} is already paid for; fetch it again with --transcription-id)') from e

def merge_tokens(toks: list[dict]) -> list[dict]:
    """Sub-word tokens into words. A token that does not start with a space continues the previous word, but it may
    only push that word's end forward when it is sung next to it: Soniox timestamps sentence punctuation where it
    decided the sentence ends, which used to stretch a single word over half a minute of silence."""
    words = []
    for t in toks:
        tx = t['text']
        if not tx.strip(): continue
        a = t['start_ms'] / 1000; b = t['end_ms'] / 1000; c = t.get('confidence') or 0
        if words and not tx.startswith(' '):
            punctuation = tx.strip()[0] in '.,!?'; w = words[-1]
            w['w'] += tx.strip() if punctuation else tx
            if a - w['b'] <= .4: w['b'] = round(max(w['b'], b), 2)
            if not punctuation: w['c'] = round(min(w['c'], c), 2)
        else: words.append({'a': round(a, 2), 'b': round(b, 2), 'w': tx.strip(), 'c': round(c, 2)})
    return words

def soniox_words(audio: Path, key: str, lang: str) -> list[dict]:
    return merge_tokens(soniox_tokens(audio, key, lang))

def group_lines(words: list[dict]) -> list[dict]:
    """The transcript's own grouping, kept as the record of what Soniox returned; align_lyrics regroups it at the
    real silences of the voice before the trainer ever sees it."""
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
    inrange = np.isfinite(midi) & (midi >= 36) & (midi <= 90)  # C2..F#6: low male voices included
    strong = inrange & (pdg > .45) & (db > -43)
    # rough / breathy passages: CREPE keeps a stable pitch while its periodicity drops; accept them as draft when loud enough
    med = ndi.median_filter(np.nan_to_num(midi, nan=0), size=11); stable = np.abs(midi - med) < 1.0
    weak = inrange & (pdg > .25) & (db > -34) & stable
    for a, b in runs(weak):
        if b - a < 8: weak[a:b] = False
    valid = strong | weak
    for a, b in runs(valid):
        if b - a < 5: valid[a:b] = False
    reliable = strong & (pdg >= .70) & (db > -38) & ((np.isfinite(agree) & (agree < 50)) | (pdg >= .85))
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

# ---------------------------------------------------------------- separation
def separate(x: np.ndarray, model_name: str = 'htdemucs_ft', device: str = 'auto') -> tuple[np.ndarray, dict]:
    """Official Demucs on a 44.1 kHz stereo float mix: the vocal stem at the same rate and length, and a record of the run."""
    t1 = time.time()
    import torch
    from demucs.pretrained import get_model
    from demucs.apply import apply_model
    device = ('cuda' if torch.cuda.is_available() else 'cpu') if device == 'auto' else device
    os.environ['TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD'] = '1'  # official Demucs zoo archives only; never point this at untrusted checkpoints
    try: model = get_model(model_name).eval()
    finally: os.environ.pop('TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD', None)
    wav = torch.from_numpy(x.T.copy()); ref = wav.mean(0); mu = ref.mean(); std = ref.std()
    if float(std) < 1e-8: raise SystemExit('input audio is silent')
    with torch.inference_mode(): pred = apply_model(model, ((wav - mu) / std)[None], device=device, shifts=1, split=True, overlap=.25, progress=False, num_workers=0)[0]
    vocal = (pred[model.sources.index('vocals')].cpu() * std + mu).T.numpy()
    return vocal, {'model': model_name, 'device': device, 'gpu': torch.cuda.get_device_name(0) if device == 'cuda' else None, 'max_vram_mib': round(torch.cuda.max_memory_allocated() / 2**20) if device == 'cuda' else None, 'seconds': round(time.time() - t1, 1), 'torch': torch.__version__}

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('audio'); ap.add_argument('--title', required=True); ap.add_argument('--artist', default=''); ap.add_argument('--out', default=str(ROOT / 'songs'))
    ap.add_argument('--model', default='htdemucs_ft', choices=['htdemucs', 'htdemucs_ft']); ap.add_argument('--device', default='auto', choices=['auto', 'cpu', 'cuda'])
    ap.add_argument('--no-lyrics', action='store_true'); ap.add_argument('--lang', default='en'); ap.add_argument('--out-html')
    ap.add_argument('--lyrics-from', default='vocal', choices=['vocal', 'mix'], help='audio sent to Soniox: the separated vocal stem (default) or the full mix')
    a = ap.parse_args(); src = Path(a.audio).expanduser().resolve()
    if not src.is_file(): ap.error('audio file not found')
    slug = slugify(a.title); pkg = Path(a.out).expanduser().resolve() / slug; work = pkg / 'work'; pkg.mkdir(parents=True, exist_ok=True); work.mkdir(exist_ok=True)
    out_html = Path(a.out_html).expanduser().resolve() if a.out_html else pkg.parent / f'Luma_{slug}.html'
    manifest = {'source': str(src), 'source_sha256': sha256(src), 'title': a.title, 'artist': a.artist, 'started': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'host': platform.node(), 'steps': {}}
    T0 = time.time()

    log('[1/8] decode'); ffmpeg('-i', src, '-vn', '-ar', '44100', '-ac', '2', '-c:a', 'pcm_f32le', work / 'mix.wav')
    x, sr = sf.read(work / 'mix.wav', dtype='float32', always_2d=True); duration = len(x) / sr; manifest['duration'] = duration
    if not 1 <= duration <= 600: raise SystemExit('songs must be between 1 and 600 seconds')
    original = pkg / ('original' + (src.suffix.lower() or '.audio'))  # the upload itself, for later audio upgrades
    for old in pkg.glob('original.*'):
        if old not in (original, src): old.unlink()
    if src != original: shutil.copyfile(src, original)
    manifest['original'] = original.name

    log('[2/8] separation', a.model)
    vocal, manifest['steps']['separation'] = separate(x, a.model, a.device); device = manifest['steps']['separation']['device']; back = x - vocal
    sf.write(work / 'vocals44.wav', vocal, sr, subtype='FLOAT')
    gain = stems.joint_gain(vocal, back)  # joint scaling keeps the stem balance
    # pitch analysis and transcription read this 22 kHz copy; playback is built from the full-rate stems next to it
    sf.write(work / 'vocal22.wav', librosa.resample(vocal.T, orig_sr=sr, target_sr=22050).T * gain, 22050, subtype='FLOAT')
    sf.write(work / 'foreground.wav', vocal * gain, sr, subtype='FLOAT'); sf.write(work / 'backing.wav', back * gain, sr, subtype='FLOAT')
    del back
    ffmpeg('-i', work / 'mix.wav', '-ar', '22050', '-c:a', 'pcm_f32le', work / 'mix22.wav')

    log('[3/8] pYIN'); t2 = time.time()
    y, sr2 = sf.read(work / 'vocal22.wav', dtype='float32', always_2d=True); y = y.mean(axis=1); rows = []; hop = 256
    for start in np.arange(0, duration, 25):
        lo = max(0, int(round((start - .5) * sr2))); hi = min(len(y), int(round((start + 25.5) * sr2))); z = y[lo:hi]
        f, _, prob = librosa.pyin(z, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('E6'), sr=sr2, frame_length=4096, hop_length=hop, fill_na=np.nan)
        yf = librosa.yin(z, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('E6'), sr=sr2, frame_length=4096, hop_length=hop)
        rms = librosa.feature.rms(y=z, frame_length=2048, hop_length=hop)[0]; tt = lo / sr2 + np.arange(len(f)) * hop / sr2; keep = (tt >= start) & (tt < min(start + 25, duration))
        rows.extend(zip(tt[keep], f[keep], prob[keep], rms[keep], yf[keep]))
    P = np.array(rows); manifest['steps']['pyin_s'] = round(time.time() - t2, 1)

    log('[4/8] CREPE'); t3 = time.time()
    import torch, torchcrepe
    y16 = librosa.resample(vocal.mean(1), orig_sr=sr, target_sr=16000)
    f0, pd = torchcrepe.predict(torch.from_numpy(y16)[None], 16000, hop_length=160, fmin=50, fmax=1500, model='full', batch_size=1024, device=device, return_periodicity=True, decoder=torchcrepe.decode.viterbi)
    pd = torchcrepe.filter.median(pd, 3); f0 = torchcrepe.filter.mean(f0, 3); f0 = f0[0].cpu().numpy(); pd = pd[0].cpu().numpy(); ct = np.arange(len(f0)) * 160 / 16000
    manifest['steps']['crepe'] = {'model': 'torchcrepe full', 'seconds': round(time.time() - t3, 1)}

    log('[5/8] map'); mix22, _ = sf.read(work / 'mix22.wav', dtype='float32', always_2d=True)
    method = f'{a.model} (official Demucs weights) + CREPE full (torchcrepe, Viterbi) cross-checked with pYIN'
    song = build_map(ct, f0, pd, P, mix22, duration, a.title, a.artist, method); song['sourceId'] = manifest['source_sha256']
    manifest['map'] = {'id': song['id'], 'metrics': song['metrics'], 'notes': len(song['notes']), 'ok_notes': sum(n['ok'] for n in song['notes'])}

    log('[6/8] stems'); t4 = time.time()
    manifest['audio'] = {**stems.encode({'foreground': work / 'foreground.wav', 'backing': work / 'backing.wav'}, duration, pkg), 'source': 'demucs', 'gain': round(gain, 6)}
    ffmpeg('-i', work / 'vocals44.wav', '-c:a', 'flac', pkg / 'vocals_44k.flac')
    manifest['steps']['encode_s'] = round(time.time() - t4, 1)

    log('[7/8] lyrics'); key = None if a.no_lyrics else soniox_key()
    if key:
        t5 = time.time()
        try:
            # the clean vocal, not the mix: under the band the model drops the first syllables of most phrases
            source = work / ('vocal22.wav' if a.lyrics_from == 'vocal' else 'mix22.wav')
            ffmpeg('-i', source, '-ac', '1', '-c:a', 'libmp3lame', '-b:a', '96k', work / 'lyrics_mono.mp3')
            words = merge_tokens(soniox_tokens(work / 'lyrics_mono.mp3', key, a.lang))
            heard = 'the Demucs vocal stem' if a.lyrics_from == 'vocal' else 'the full mix'
            note = f'Soniox stt-async-v5 on {heard}, {time.strftime("%Y-%m-%d")}, automatic word timings'
            save_transcript(pkg, a.lyrics_from, group_lines(words), note)
            song['lyrics'] = realign(words, align_context(pkg, song)); song['lyricsSource'] = aligned_note(note)
            manifest['steps']['lyrics'] = {'seconds': round(time.time() - t5, 1), 'audio': a.lyrics_from, 'words': len(words), 'lines': len(song['lyrics'])}
        except (urllib.error.URLError, RuntimeError, KeyError) as e:
            log('  lyrics skipped:', e); song['lyrics'] = []; manifest['steps']['lyrics'] = {'error': str(e)}
    else:
        song['lyrics'] = []; manifest['steps']['lyrics'] = {'skipped': 'no Soniox key' if not a.no_lyrics else 'disabled'}
    (pkg / 'target.json').write_text(json.dumps(song, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')

    log('[8/8] html'); build_html(pkg, out_html)
    manifest['html'] = {'path': str(out_html), 'bytes': out_html.stat().st_size, 'sha256': sha256(out_html)}
    manifest['finished'] = time.strftime('%Y-%m-%dT%H:%M:%S%z'); manifest['total_s'] = round(time.time() - T0, 1)
    (pkg / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')
    for f in ['mix.wav', 'vocals44.wav', 'vocal22.wav', 'foreground.wav', 'backing.wav', 'mix22.wav', 'lyrics_mono.mp3']:
        (work / f).unlink(missing_ok=True)
    log('DONE', json.dumps({'html': str(out_html), 'map': manifest['map'], 'lyrics': manifest['steps']['lyrics'], 'total_s': manifest['total_s']}, ensure_ascii=False))

if __name__ == '__main__':
    try: main()
    except KeyboardInterrupt: sys.exit(130)
