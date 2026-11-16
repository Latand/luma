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
Output: [{"line": i, "lrc": seconds, "words": [{"w", "a", "b", "score", "target_token", "target_w"}]}].
Row and target-token indices are zero-based. Sub-words retain their owner so the
sheet can validate the complete mapping and combine each target token's span.
"""
import json, math, re, sys, unicodedata
from pathlib import Path
from common import write_json
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'studio'))
from lyric_tokens import tokenize

def lrc_rows(text):
    rows = []
    for line in text.splitlines():
        m = re.match(r'\s*\[(\d+):(\d+(?:\.\d+)?)\]\s*(.*)$', line)
        if m: rows.append((int(m.group(1)) * 60 + float(m.group(2)), m.group(3).strip()))
    return rows

def norm(w):
    return ''.join(c for c in unicodedata.normalize('NFC', w.lower().replace('’', "'"))
                   if c.isalnum() or unicodedata.category(c).startswith("M") or c == "'").strip("'")


def refuse(row, token, reason):
    raise ValueError(f'row {row + 1}, token {token + 1}: {reason}; '
                     'use the manual word-sheet and picture path')


def token_groups(line, row=0):
    """Every project target token owns its complete, ordered model-word group."""
    targets = tokenize(line)
    if not targets: refuse(row, 0, 'no target words to align')
    groups = []
    for k, target in enumerate(targets):
        parts = [w for w in re.split(r'[—–-]+', target) if norm(w)]
        if not parts or any(not re.fullmatch("[a-z']+", norm(w)) for w in parts):
            refuse(row, k, 'unsupported forced-alignment token')
        groups.append((target, parts))
    return groups


def model_words(line):
    return [part for _, parts in token_groups(line) for part in parts]


def model_word_owners(line, row=0):
    return [dict(w=part, target_token=k, target_w=target)
            for k, (target, parts) in enumerate(token_groups(line, row)) for part in parts]


def sheet_hints(lyrics, alignment):
    """Validate the entire proposal before returning hints keyed by (row, token).

    Older proposals lack ownership fields; accept them only when every row's
    exact model-word sequence matches the groups derived from the target.
    """
    if not isinstance(alignment, list): refuse(0, 0, 'alignment must be a row list')
    hints = {}
    for i in range(max(len(lyrics), len(alignment))):
        if i >= len(lyrics) or i >= len(alignment): refuse(i, 0, 'alignment row count differs')
        targets = [w['w'] for w in lyrics[i]['words']]
        groups = token_groups(' '.join(targets), i)
        if [w for w, _ in groups] != targets: refuse(i, 0, 'target tokenizer mismatch')
        row = alignment[i]
        if not isinstance(row, dict) or type(row.get('line')) is not int or row['line'] != i:
            refuse(i, 0, 'alignment row identity differs')
        words = row.get('words')
        if not isinstance(words, list): refuse(i, 0, 'alignment words must be a list')
        owned = any(isinstance(w, dict) and ('target_token' in w or 'target_w' in w) for w in words)
        cursor = 0
        previous_end = -1
        for k, (target, parts) in enumerate(groups):
            group = []
            for part in parts:
                if cursor >= len(words): refuse(i, k, 'missing alignment sub-word')
                word = words[cursor]
                if not isinstance(word, dict) or not isinstance(word.get('w'), str) or norm(word['w']) != norm(part):
                    refuse(i, k, 'alignment sub-word differs')
                if owned and (type(word.get('target_token')) is not int or word['target_token'] != k
                              or word.get('target_w') != target):
                    refuse(i, k, 'alignment target ownership differs')
                a, b = word.get('a'), word.get('b')
                if (any(type(t) not in (int, float) or not math.isfinite(t) for t in (a, b))
                        or not 0 <= a < b or a < previous_end):
                    refuse(i, k, 'invalid or unordered alignment span')
                previous_end = b
                group.append(word)
                cursor += 1
            hints[i, k] = (group[0]['a'], group[-1]['b'])
        if cursor != len(words): refuse(i, len(groups) - 1, 'extra alignment sub-word')
    return hints

def checked_lines(text, lrc):
    rows = lrc_rows(lrc)
    text_lines = [line.strip() for line in text.splitlines() if line.strip()]
    sung = [(t,s) for t,s in rows if s]
    if len(sung) != len(text_lines):
        refuse(min(len(sung), len(text_lines)), 0, 'text/synced row count differs')
    for i, ((_, synced), line) in enumerate(zip(sung,text_lines)):
        left, right = tokenize(synced), tokenize(line)
        for k in range(max(len(left), len(right))):
            if k >= len(left) or k >= len(right) or norm(left[k]) != norm(right[k]):
                refuse(i, k, 'text/synced content differs')
    for i, line in enumerate(text_lines): token_groups(line, i)
    if not text_lines: refuse(0, 0, 'no words to align')
    return rows,text_lines,sung


def main():
    import argparse
    ap=argparse.ArgumentParser(description=__doc__)
    for field in ('package','text','synced','output'): ap.add_argument(field,type=Path)
    ap.add_argument('--pad-before',type=float,default=1.5); ap.add_argument('--pad-after',type=float,default=1.)
    args=ap.parse_args(); pkg,txt,lrc,out=args.package,args.text,args.synced,args.output
    before,after=args.pad_before,args.pad_after
    rows,text_lines,sung=checked_lines(txt.read_text(),lrc.read_text())
    ownership = [model_word_owners(line, i) for i, line in enumerate(text_lines)]
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
        owners = ownership[i]
        words = [owner['w'] for owner in owners]
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
        for owner, (s, e) in zip(owners, spans):
            part = runs[s:e]; n = sum(r.end - r.start for r in part)
            item['words'].append({**owner,
                                  'a': round(w0 + part[0].start * ratio, 3), 'b': round(w0 + part[-1].end * ratio, 3),
                                  'score': round(float(sum(r.score * (r.end - r.start) for r in part) / max(1, n)), 3)})
        res.append(item)
    sheet_hints([{'words': [{'w': token} for token in tokenize(line)]} for line in text_lines], res)
    write_json(out,res)
    n = sum(len(r['words']) for r in res); low = sum(1 for r in res for w in r['words'] if w['score'] < .3)
    print(f'{out}: {len(res)} lines, {n} words, {low} with score < 0.3')

if __name__ == '__main__':
    try: main()
    except ValueError as error: raise SystemExit(str(error))
