#!/usr/bin/env python3
"""Before/after sheets the operator can flip through: the stem's spectrogram over the real trainer's picture.
Usage: python tools/song_qa/contact_sheets.py --help


  contact_sheets.py <shots_dir> <features.npz> <target.json> <out_dir> [--sung sung.json] [--label before|after]

<shots_dir> comes from shoot_trainer.mjs (PNG per window + meta.json); <target.json> must be the data those shots
were taken from (the backup for "before", the package for "after"). For every window one PNG: on top the
spectrogram of the vocal stem (log frequency, 70 Hz .. 4 kHz) cut to exactly the trainer's time window and laid over
the trainer's own plot edges, with the contour of that target.json in cyan (solid = confident, dashed = draft) and,
when --sung is given, the singer's own attempts in green; below it the trainer's screenshot untouched except for
the same word-start lines. Yellow lines are word starts (label = the word), short ticks under the spectrogram are
word ends, white ticks are the detected onset candidates. An overview montage of all windows is written beside them.
The pictures show the song's words, so they stay on the machine.
"""
import json, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import matplotlib; matplotlib.use('Agg')
from matplotlib import cm, font_manager

def hz(m): return 440.0 * 2 ** ((m - 69) / 12)

def main():
    a = sys.argv[1:]
    if '--help' in a: print(__doc__); return
    pos = []; o = {}; i = 0
    while i < len(a):
        if a[i].startswith('--'): o[a[i][2:]] = a[i + 1]; i += 2
        else: pos.append(a[i]); i += 1
    if len(pos) != 4: raise SystemExit(__doc__)
    shots, feat, target, out = Path(pos[0]), pos[1], Path(pos[2]), Path(pos[3]); out.mkdir(parents=True, exist_ok=True)
    meta = json.loads((shots / 'meta.json').read_text()); song = json.loads(target.read_text(encoding='utf-8')); F = dict(np.load(feat))
    sung = sorted((x, m) for t in json.loads(Path(o['sung']).read_text())['traces'] for x, m in t['points']) if 'sung' in o else []
    label = o.get('label', '')
    font = ImageFont.truetype(font_manager.findfont('DejaVu Sans'), 13); small = ImageFont.truetype(font_manager.findfont('DejaVu Sans'), 11)
    logf = F['logf']; t = F['t']; H = 330; cmap = matplotlib.colormaps['magma']
    yf = lambda f: H - 1 - np.interp(np.log(f), np.log(logf), np.arange(len(logf))) / (len(logf) - 1) * (H - 1)
    words = [(w, li) for li, l in enumerate(song.get('lyrics') or []) for w in l['words']]
    made = []
    for s in meta['shots']:
        shot = Image.open(shots / s['file']).convert('RGB'); W = shot.width; sc = W / s['canvas']['cssW']
        x0, x1 = s['plot']['left'] * sc, s['plot']['right'] * sc; ta, tb = s['a'], s['b']
        X = lambda tt: x0 + (tt - ta) / (tb - ta) * (x1 - x0)
        top = Image.new('RGB', (W, H + 46), (7, 9, 13)); d = ImageDraw.Draw(top)
        i0, i1 = np.searchsorted(t, [max(0, ta), min(float(t[-1]), tb)])
        if i1 > i0 + 1:
            pic = F['pic'][::-1, i0:i1].astype(np.float32); pic = np.clip((pic - 30) / 225, 0, 1)
            im = Image.fromarray((cmap(pic)[:, :, :3] * 255).astype(np.uint8)).resize((max(1, int(X(t[i1 - 1]) - X(t[i0]))), H), Image.BILINEAR)
            top.paste(im, (int(X(t[i0])), 0))
        for f in (100, 200, 500, 1000, 2000, 4000): d.text((4, min(H - 14, yf(f) - 7)), f'{f} Hz', fill=(160, 170, 185), font=small); d.line([(x0 - 4, yf(f)), (x0, yf(f))], fill=(160, 170, 185))
        last = None
        for p in song['points']:
            if p[0] < ta - .05: continue
            if p[0] > tb + .05: break
            if p[1] is None: last = None; continue
            if last is not None and p[0] - last[0] < .05 and abs(p[1] - last[1]) < 8:
                xa, xb = X(last[0]), X(p[0])
                if xb >= x0 and xa <= x1:
                    seg = [(xa, yf(hz(last[1]))), (xb, yf(hz(p[1])))]; d.line(seg, fill=(0, 0, 0), width=5)
                    if p[3] or int(p[0] / .02) % 3 != 0: d.line(seg, fill=(0, 229, 255) if p[3] else (255, 255, 255), width=2)
            last = p
        for x, m in sung:
            if ta <= x <= tb: xx, yy = X(x), yf(hz(m)); d.rectangle([xx - 1, yy - 1, xx + 1, yy + 1], fill=(93, 255, 122))
        for ot in F['onset_start']:
            if ta <= ot <= tb: d.line([(X(ot), H), (X(ot), H + 5)], fill=(235, 235, 235))
        for g in np.arange(np.ceil(ta), tb + 1e-6, 1):
            d.line([(X(g), H + 6), (X(g), H + 12)], fill=(160, 170, 185)); d.text((X(g) - 14, H + 13), f'{int(g) // 60}:{g % 60:02.0f}', fill=(160, 170, 185), font=small)
        ds = ImageDraw.Draw(shot, 'RGBA'); row = 0
        for w, li in words:
            if w['b'] < ta or w['a'] > tb: continue
            if ta <= w['a'] <= tb:
                xx = X(w['a']); d.line([(xx, 0), (xx, H + 5)], fill=(255, 225, 74), width=1)
                d.rectangle([xx + 2, 3 + 16 * (row % 3), xx + 4 + d.textlength(w['w'], font=font), 18 + 16 * (row % 3)], fill=(0, 0, 0)); d.text((xx + 3, 3 + 16 * (row % 3)), w['w'], fill=(255, 243, 160), font=font); row += 1
                ds.line([(xx, s['plot']['top'] * sc), (xx, s['plot']['bottom'] * sc)], fill=(255, 225, 74, 150), width=1)
            if ta <= w['b'] <= tb: d.line([(X(w['b']), H - 10), (X(w['b']), H + 5)], fill=(255, 150, 60), width=1)
        title = f"{song['title']} — {label} — window {s['k']}: {int(max(0, ta)) // 60}:{max(0, ta) % 60:04.1f} .. {int(tb) // 60}:{tb % 60:04.1f}   (yellow = word starts, cyan/white = target contour, green = your attempt)"
        d.text((x0, H + 29), title, fill=(207, 214, 228), font=font)
        sheet = Image.new('RGB', (W, top.height + shot.height), (7, 9, 13)); sheet.paste(top, (0, 0)); sheet.paste(shot, (0, top.height))
        name = f"{label + '_' if label else ''}{s['file']}"; sheet.save(out / name); made.append(sheet)
    if made:
        cols = 2; tw = 850; th = int(made[0].height * tw / made[0].width); rows = (len(made) + cols - 1) // cols
        mont = Image.new('RGB', (cols * tw, rows * th), (7, 9, 13))
        for k, im in enumerate(made): mont.paste(im.resize((tw, th), Image.LANCZOS), ((k % cols) * tw, (k // cols) * th))
        mont.save(out / f"{label or 'sheet'}_overview.jpg", quality=82)
    print(f'{len(made)} sheets -> {out}')

if __name__ == '__main__': main()
