#!/usr/bin/env python3
"""A first proposal for word times: CTC forced alignment of the verified lyrics on the vocal stem.
Usage: python tools/song_qa/fa_align.py --help


  TORCH_HOME=<scratch> fa_align.py <package_dir> <verified.txt> <lines.lrc> <out.json> [--pad-before 1.5] [--pad-after 1.0]

Model: torchaudio's MMS_FA bundle (a 1.2 GB download on first use; point TORCH_HOME at scratch so nothing lands in
the home cache). Each synced line is aligned alone inside a window from a little before its own timestamp to a
little after the next timestamp, with a free "star" token at both ends that swallows whatever else is sung there, so
a wrong neighbour never drags a line. The LRC gives line starts only; the words of each line come from the verified
text, matched to the LRC rows in order (the two files must hold the same lines).

The result is a proposal and nothing more: frames are 20 ms, sung vowels stretch far past what the speech model
expects, and screamed lines align poorly. Every word is then judged by eye on the spectrogram (draw_windows.py).
Output: [{"line": i, "lrc": seconds, "words": [{"w", "a", "b", "score"}]}].
"""
import json, re, sys, unicodedata
from pathlib import Path
from common import write_json

def lrc_rows(text):
    rows = []
    for line in text.splitlines():
        m = re.match(r'\s*\[(\d+):(\d+(?:\.\d+)?)\]\s*(.*)$', line)
        if m: rows.append((int(m.group(1)) * 60 + float(m.group(2)), m.group(3).strip()))
    return rows

def norm(w):
    return ''.join(c for c in unicodedata.normalize('NFC', w.lower().replace('’', "'"))
                   if c.isalpha() or unicodedata.category(c).startswith("M") or c == "'").strip("'")


def model_words(line):
    words = [w for w in re.split(r'[\s—–-]+', line) if norm(w)]
    if not words or any(not re.fullmatch("[a-z']+", norm(w)) for w in words):
        raise ValueError('unsupported forced-alignment letters; use the manual word-sheet and picture path')
    return words

def checked_lines(text, lrc):
    rows = lrc_rows(lrc)
    text_lines = [line.strip() for line in text.splitlines() if line.strip()]
    sung = [(t,s) for t,s in rows if s]
    if len(sung) != len(text_lines):
        raise ValueError('text/synced row count differs; reflow verified text to synced boundaries without changing tokens')
    for i, ((_, synced), line) in enumerate(zip(sung,text_lines)):
        if [norm(w) for w in synced.split()] != [norm(w) for w in line.split()]:
            raise ValueError(f'text/synced content differs at row {i}; fix or omit forced alignment')
    for line in text_lines: model_words(line)
    if not text_lines: raise ValueError("no words to align; use the manual word-sheet and picture path")
    return rows,text_lines,sung


def main():
    import argparse
    ap=argparse.ArgumentParser(description=__doc__)
    for field in ('package','text','synced','output'): ap.add_argument(field,type=Path)
    ap.add_argument('--pad-before',type=float,default=1.5); ap.add_argument('--pad-after',type=float,default=1.)
    args=ap.parse_args(); pkg,txt,lrc,out=args.package,args.text,args.synced,args.output
    before,after=args.pad_before,args.pad_after
    rows,text_lines,sung=checked_lines(txt.read_text(),lrc.read_text())
    import soundfile as sf, torch, torchaudio
    stamps = [t for t, _ in rows]
    y, sr = sf.read(pkg / 'vocals_44k.flac', dtype='float32', always_2d=True); y = torch.from_numpy(y.mean(axis=1)); dur = len(y) / sr
    y16 = torchaudio.functional.resample(y, sr, 16000)
    bundle = torchaudio.pipelines.MMS_FA; dev = 'cuda' if torch.cuda.is_available() else 'cpu'
    model = bundle.get_model(with_star=True).to(dev).eval(); D = bundle.get_dict(star='*')
    res = []
    for i, ((t0, _), line) in enumerate(zip(sung, text_lines)):
        nxt = next((s for s in stamps if s > t0 + .05), dur)
        w0 = max(0.0, t0 - before); w1 = min(dur, max(nxt + after, t0 + 2.5)); w1 = min(w1, w0 + 24)
        words = model_words(line)
        tokens = [D['*']]; spans = []
        for w in words:
            ids = [D[c] for c in norm(w)]; spans.append((len(tokens), len(tokens) + len(ids))); tokens += ids
        tokens.append(D['*'])
        seg = y16[int(w0 * 16000):int(w1 * 16000)]; seg = seg / (seg.abs().max() + 1e-6) * .7
        with torch.inference_mode(): em, _ = model(seg[None].to(dev))
        al, sc = torchaudio.functional.forced_align(em.cpu(), torch.tensor([tokens]), blank=0)
        runs = torchaudio.functional.merge_tokens(al[0], sc[0].exp())  # one span per token of `tokens`, in order
        if len(runs) != len(tokens): raise SystemExit(f'line {i}: {len(runs)} aligned spans for {len(tokens)} tokens')
        ratio = (w1 - w0) / em.shape[1]
        item = {'line': i, 'lrc': round(t0, 2), 'window': [round(w0, 2), round(w1, 2)], 'words': []}
        for w, (s, e) in zip(words, spans):
            if e == s: item['words'].append({'w': w, 'a': None, 'b': None, 'score': 0}); continue
            part = runs[s:e]; n = sum(r.end - r.start for r in part)
            item['words'].append({'w': w, 'a': round(w0 + part[0].start * ratio, 3), 'b': round(w0 + part[-1].end * ratio, 3),
                                  'score': round(float(sum(r.score * (r.end - r.start) for r in part) / max(1, n)), 3)})
        res.append(item)
    write_json(out,res)
    n = sum(len(r['words']) for r in res); low = sum(1 for r in res for w in r['words'] if w['score'] < .3)
    print(f'{out}: {len(res)} lines, {n} words, {low} with score < 0.3')

if __name__ == '__main__': main()
