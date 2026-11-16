#!/usr/bin/env python3
"""Working pictures for the eye pass: the vocal stem's spectrogram over the trainer's data, on one time axis.
Usage: python tools/song_qa/draw_windows.py --help


  draw_windows.py <package_dir> <features.npz> <out_dir> [--target other_target.json] [--fa proposal.json] [--sung sung.json]
                  [--from 0] [--to <duration>] [--win 12] [--step 11] [--rows 2] [--only k,k,...]

One PNG per window (w00_000.png, ...). A window of --win seconds is cut into --rows strips stacked top to bottom, so
12 s drawn as two 6 s strips gives about 250 px per second: 80 ms is 20 px, enough to place a word on its onset.
Each strip holds, on a shared time axis:
  1. the spectrogram, log frequency 70 Hz .. 4 kHz, with the target contour (the pitch frames of `points`, joined
     the way the trainer's «Контур» view joins them) drawn at its own frequency: cyan solid = confident frames,
     white dashed = draft frames, nothing = no target. The contour is what the singer follows, so it is the thing
     judged: where the lowest bright partial goes on and the line stops, the melody breaks off on screen; where the
     line sits on the 2nd partial or under the lowest one, it is an octave off. Yellow lines are word starts
     with the word and its running index, thin dotted yellow lines are word ends; white brackets at the very top
     are the lyric lines. Magenta triangles at the bottom edge are the forced-alignment proposal (--fa).
  2. a strip with the onset strength (white), the broadband level (green), the 4..10 kHz level (orange, which shows
     s, sh, t, k that the 4 kHz picture cuts off) and the detected onset candidates: red ticks, taller = stronger,
     each with its number in the song. `onsets.py` prints the exact time of a numbered candidate, and the edit files
     name a word start by that number ("o123"), so a start is never read off the axis by eye alone.
  3. the trainer's data as the singer sees it in the contour view: the contour on a semitone scale (solid or
     dashed), the note bars derived from it as faint outlines, and each word at its start above its pitch.
Green dots (--sung, from attempts.py) are the singer's own attempts, in both panels: a hint only. He sings what he
hears, so a green line that runs on where the target stops, or holds an octave away from it, points at the target.
Major time ticks every second, minor every 0.1 s.
"""
import json, sys
from pathlib import Path
import numpy as np
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
def hz(m): return 440.0 * 2 ** ((m - 69) / 12)
def name(n): return f'{NAMES[int(n) % 12]}{int(n) // 12 - 1}'

def args():
    a = sys.argv[1:]
    if '--help' in a: print(__doc__); raise SystemExit(0)
    pos = []; o = {}
    i = 0
    while i < len(a):
        if a[i].startswith('--'): o[a[i][2:]] = a[i + 1]; i += 2
        else: pos.append(a[i]); i += 1
    if len(pos) != 3: raise SystemExit(__doc__)
    return pos, o

def contour_segments(song, t0, t1):
    """The contour as the trainer draws it: consecutive frames are joined when they are under 0.05 s and under 8
    semitones apart; a confident frame is solid, a draft frame dashed. Returns [(ok, [t...], [midi...])]."""
    out = []; last = None; cur = None
    for p in song['points']:
        if p[0] < t0 - .05: continue
        if p[0] > t1 + .05: break
        if p[1] is None: last = None; cur = None; continue
        if last is not None and p[0] - last[0] < .05 and abs(p[1] - last[1]) < 8:
            if cur is not None and cur[0] == bool(p[3]): cur[1].append(p[0]); cur[2].append(p[1])
            else: cur = (bool(p[3]), [last[0], p[0]], [last[1], p[1]]); out.append(cur)
        else: cur = None
        last = p
    return out

def draw_strip(fig, gs_spec, gs_on, gs_roll, t0, t1, song, F, fa_words, widx):
    t = F['t']; i0, i1 = np.searchsorted(t, [t0, t1]); logf = F['logf']
    ax = fig.add_subplot(gs_spec)
    if i1 > i0: ax.imshow(F['pic'][:, i0:i1], origin='lower', aspect='auto', cmap='magma', extent=[t[i0], t[min(i1, len(t) - 1)], 0, len(logf)], vmin=30, vmax=255, interpolation='bilinear')
    yf = lambda f: np.interp(np.log(f), np.log(logf), np.arange(len(logf)))
    ax.set_facecolor('#07090d'); ax.set_xlim(t0, t1); ax.set_ylim(0, len(logf))
    ticks = [100, 200, 300, 500, 1000, 2000, 4000]; ax.set_yticks([yf(f) for f in ticks]); ax.set_yticklabels([str(f) for f in ticks], fontsize=7)
    segs = contour_segments(song, t0, t1)
    for ok, xs, ms in segs:
        ys = [yf(hz(m)) for m in ms]
        ax.plot(xs, ys, color='black', lw=3.4, zorder=4, solid_capstyle='butt')
        ax.plot(xs, ys, color='#00e5ff' if ok else '#ffffff', lw=1.5, ls='-' if ok else (0, (2, 1.4)), zorder=5, solid_capstyle='butt')
    sung = [(x, m) for x, m in song.get('_sung', []) if t0 <= x <= t1]
    if sung: ax.scatter([x for x, _ in sung], [yf(hz(m)) for _, m in sung], s=2.2, c='#5dff7a', linewidths=0, zorder=6, alpha=.9)
    ax2 = fig.add_subplot(gs_on, sharex=ax)
    env = F['env'][i0:i1]; ax2.plot(t[i0:i1], env / (np.percentile(F['env'], 99.5) + 1e-9), color='white', lw=.6)
    hfw = F['hf'][i0:i1]; top = np.percentile(F['hf'], 99.9); hfn = np.clip((hfw - (top - 60)) / 60, 0, 1); ax2.plot(t[i0:i1], hfn, color='#ff9a3c', lw=.6)
    lvl = np.clip((F['rms'][i0:i1] - (np.percentile(F['rms'], 99.9) - 60)) / 60, 0, 1); ax2.plot(t[i0:i1], lvl, color='#59d98e', lw=.6)
    smax = (np.percentile(F['onset_strength'], 95) if len(F['onset_strength']) else 1) + 1e-9
    for oi, (ot, os_) in enumerate(zip(F['onset_start'], F['onset_strength'])):
        if t0 <= ot <= t1:
            ax2.plot([ot, ot], [0, .2 + .5 * min(1, os_ / smax)], color='#ff3b3b', lw=.9)
            ax2.text(ot, .98 - .17 * (oi % 2), str(oi), color='#ff8f8f', fontsize=5.6, ha='center', va='top', clip_on=True)
    ax2.set_ylim(0, 1.05); ax2.set_yticks([]); ax2.set_facecolor('#101018')
    ax3 = fig.add_subplot(gs_roll, sharex=ax); ax3.set_facecolor('#0c111a')
    ns = [n for n in song['notes'] if n['b'] >= t0 and n['a'] <= t1]
    sm = [m for x, m in song.get('_sung', []) if t0 <= x <= t1]
    lo = min([n['m'] for n in ns] + sm, default=60) - 2.5; hi = max([n['m'] for n in ns] + sm, default=64) + 4.5
    if hi - lo < 12: mid = (hi + lo) / 2; lo, hi = mid - 6, mid + 6
    for m in range(int(np.floor(lo)), int(np.ceil(hi)) + 1): ax3.axhline(m, color='#1c2636', lw=.4)
    for n in ns:
        ax3.add_patch(plt.Rectangle((n['a'], n['m'] - .42), n['b'] - n['a'], .84, facecolor='none', edgecolor='#5d5490', lw=.6, ls='-' if n['ok'] else '--'))
    if sung: ax3.scatter([x for x, _ in sung], [m for _, m in sung], s=2.5, c='#5dff7a', linewidths=0, zorder=5, alpha=.9)
    for ok, xs, ms in segs:
        ax3.plot(xs, ms, color='#c9baf4' if ok else '#aaa4c4', lw=2.2 if ok else 1.6, ls='-' if ok else (0, (2, 1.6)), solid_capstyle='round', zorder=4)
    ax3.set_ylim(lo, hi); yt = [m for m in range(int(np.ceil(lo)), int(hi) + 1) if m % 12 in (0, 4, 7)]; ax3.set_yticks(yt); ax3.set_yticklabels([name(m) for m in yt], fontsize=6)
    def target_m(w):
        ms = [n['m'] for n in song['notes'] if n['a'] <= w['b'] and n['b'] >= w['a']]
        if ms: return float(np.median(ms))
        near = [(min(abs(n['a'] - w['b']), abs(n['b'] - w['a'])), n['m']) for n in song['notes']]; near = [x for x in near if x[0] <= .6]
        return min(near)[1] if near else (lo + hi) / 2
    used = []
    for li, line in enumerate(song.get('lyrics') or []):
        if line['b'] < t0 - 1 or line['a'] > t1 + 1: continue
        ax.plot([max(t0, line['a']), min(t1, line['b'])], [len(logf) - 2] * 2, color='white', lw=2.2, zorder=7, solid_capstyle='butt')
        if t0 <= line['a'] <= t1: ax.plot([line['a']] * 2, [len(logf) - 12, len(logf)], color='white', lw=2.2, zorder=7); ax.text(line['a'], len(logf) - 13, f'L{li}', color='white', fontsize=6, va='top', ha='right', zorder=8)
        if t0 <= line['b'] <= t1: ax.plot([line['b']] * 2, [len(logf) - 12, len(logf)], color='white', lw=2.2, zorder=7)
        for w in line['words']:
            k = widx[id(w)]
            if w['b'] < t0 or w['a'] > t1: continue
            for axx in (ax, ax2, ax3):
                if t0 <= w['a'] <= t1: axx.axvline(w['a'], color='#ffe14a', lw=.9, zorder=6)
                if t0 <= w['b'] <= t1: axx.axvline(w['b'], color='#ffe14a', lw=.6, ls=(0, (1, 2.5)), zorder=6)
            if t0 <= w['a'] <= t1:
                row = k % 3
                ax.text(w['a'] + .012, len(logf) - 24 - 15 * row, f"{k}·{w['w']}", color='#fff3a0', fontsize=7.5, va='top', ha='left', zorder=9, bbox=dict(facecolor='black', alpha=.55, pad=.6, lw=0), clip_on=True)
                y = target_m(w) + 1.1
                while any(abs(w['a'] - ux) < .32 and abs(y - uy) < 1.0 for ux, uy in used): y += 1.05
                used.append((w['a'], y)); ax3.text(w['a'], min(y, hi - .9), w['w'], color='#e8eef8', fontsize=7.5, va='bottom', ha='left', clip_on=True)
    for fw in fa_words:
        if fw['a'] is None or not (t0 <= fw['a'] <= t1): continue
        ax.plot([fw['a']], [4], marker='^', color='#ff4dd2', ms=5, zorder=9); ax.text(fw['a'] + .01, 9, fw['w'], color='#ff9be8', fontsize=6, va='bottom', ha='left', zorder=9, clip_on=True, bbox=dict(facecolor='black', alpha=.5, pad=.4, lw=0))
        if t0 <= fw['b'] <= t1: ax.plot([fw['b']], [4], marker='|', color='#ff4dd2', ms=5, zorder=9)
    for axx in (ax, ax2, ax3):
        axx.set_xticks(np.arange(np.ceil(t0), t1 + 1e-6, 1)); axx.set_xticks(np.arange(np.ceil(t0 * 10) / 10, t1 + 1e-6, .1), minor=True)
        axx.tick_params(axis='x', which='minor', length=2, color='#888'); axx.tick_params(axis='x', which='major', length=5, labelsize=8)
        for g in np.arange(np.ceil(t0 * 2) / 2, t1 + 1e-6, .5): axx.axvline(g, color='white', lw=.25, alpha=.35, zorder=2)
    plt.setp(ax.get_xticklabels(), visible=False); plt.setp(ax2.get_xticklabels(), visible=False)
    ax3.set_xticklabels([f'{int(x) // 60}:{x % 60:04.1f} ({x:.0f})' for x in ax3.get_xticks()], fontsize=7.5)

def main():
    (pkg, feat, out), o = args(); pkg = Path(pkg); out = Path(out); out.mkdir(parents=True, exist_ok=True)
    song = json.loads(Path(o.get('target', pkg / 'target.json')).read_text(encoding='utf-8')); F = dict(np.load(feat))
    if 'sung' in o: song['_sung'] = sorted((x, m) for t in json.loads(Path(o['sung']).read_text())['traces'] for x, m in t['points'])
    fa = [w for r in json.loads(Path(o['fa']).read_text())for w in r['words']] if 'fa' in o else []
    widx = {}; k = 0
    for line in song.get('lyrics') or []:
        for w in line['words']: widx[id(w)] = k; k += 1
    win, step, rows = float(o.get('win', 12)), float(o.get('step', 11)), int(o.get('rows', 2))
    t_from, t_to = max(0, float(o.get('from', 0))), min(song['duration'], float(o.get('to', song['duration']))); only = {int(x) for x in o['only'].split(',')} if 'only' in o else None
    if win <= 0 or step <= 0 or rows < 1: raise ValueError('window, step and rows must be positive')
    made = 0; a = t_from; kwin = 0
    while a < t_to:
        if only is None or kwin in only:
            fig = plt.figure(figsize=(15.6, 5.3 * rows), dpi=100, facecolor='#07090d')
            gs = GridSpec(rows * 4, 1, figure=fig, height_ratios=[3.1, .75, 1.4, .28] * rows, hspace=.04, left=.035, right=.995, top=.975, bottom=.01)
            for r in range(rows):
                if a + r * win / rows >= t_to: continue
                draw_strip(fig, gs[r * 4], gs[r * 4 + 1], gs[r * 4 + 2], a + r * win / rows, min(t_to, a + (r + 1) * win / rows), song, F, fa, widx)
            for axx in fig.axes:
                axx.tick_params(colors='#cfd6e4'); [sp.set_color('#39424f') for sp in axx.spines.values()]
            fig.suptitle(f"{song['title']} — window {kwin}: {a:.2f}..{min(t_to, a + win):.2f} s", color='#cfd6e4', fontsize=9, y=.995)
            fig.savefig(out / f'w{kwin:02d}_{a:03.0f}.png'); plt.close(fig); made += 1
        a += step; kwin += 1
    print(f'{made} windows -> {out}')

if __name__ == '__main__': main()
