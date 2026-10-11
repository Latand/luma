#!/usr/bin/env python3
"""Summarize the activity log into a compact Markdown digest an analysis agent can read before the raw JSONL.

  activity_report.py [--songs DIR] [--days N] [--since YYYY-MM-DD]

Reads songs/logs/activity/<day>.jsonl (docs/ACTIVITY_LOG.md) and prints, for the chosen days: sessions and time per page,
the most used controls and keys, setting changes, toasts and errors, and every attempt grouped by song with its match
trend and its weakest phrases. Standard library only; reads, never writes.
"""
from __future__ import annotations
import argparse, collections, datetime, json, statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(folder: Path, since: str) -> tuple[list[dict], int]:
    events, bad = [], 0
    for f in sorted(folder.glob('*.jsonl')):
        if f.stem < since: continue
        for line in f.read_text(encoding='utf-8', errors='replace').splitlines():
            try:
                e = json.loads(line)
                if isinstance(e, dict) and isinstance(e.get('data'), dict): events.append(e)
                else: bad += 1
            except ValueError: bad += 1
    events.sort(key=lambda e: (str(e.get('ts')), str(e.get('session')), e.get('seq') or 0))
    return events, bad


def minutes(ms) -> str: return f'{(ms or 0) / 1000:.0f} s' if (ms or 0) < 90000 else f'{ms / 60000:.1f} min'


def report(events: list[dict], bad: int, top: int = 15) -> str:
    out = []; w = out.append
    if not events: return '# Luma activity digest\n\nNo events in the chosen period.\n'
    days = sorted({str(e['ts'])[:10] for e in events})
    w(f'# Luma activity digest\n\n{len(events)} events, {days[0]} … {days[-1]} (UTC dates)' + (f'; {bad} unreadable lines skipped' if bad else '') + '\n')

    # Sessions: one page load each. Time comes from page_close; a tab that never closed cleanly counts its last visibility event.
    sessions: dict[str, dict] = {}
    for e in events:
        s = sessions.setdefault(e['session'], {'page': e['page'], 'start': e['ts'], 'end': e['ts'], 'open': 0, 'visible': 0, 'events': 0, 'kind': None})
        s['end'] = e['ts']; s['events'] += 1; d = e['data']
        if e['type'] == 'page_open': s['kind'] = d.get('kind')
        if e['type'] in ('page_close', 'visibility'):
            s['visible'] = max(s['visible'], d.get('visibleMs') or 0)
            if e['type'] == 'page_close': s['open'] = max(s['open'], d.get('openMs') or 0)
    per_page = collections.defaultdict(lambda: [0, 0, 0])
    for s in sessions.values():
        p = per_page['studio' if s['page'] == 'studio' else s['page']]; p[0] += 1; p[1] += s['open']; p[2] += s['visible']
    w('## Pages\n\n| page | sessions | open | visible |\n|---|---|---|---|')
    for page, (n, o, v) in sorted(per_page.items(), key=lambda kv: -kv[1][2]): w(f'| {page} | {n} | {minutes(o)} | {minutes(v)} |')

    def counted(kind, key, title):
        c = collections.Counter(key(e) for e in events if e['type'] == kind)
        if not c: return
        w(f'\n## {title}\n')
        for k, n in c.most_common(top): w(f'- {n}× {k}')
    page_kind = lambda e: 'studio' if e['page'] == 'studio' else 'trainer'
    counted('click', lambda e: f"{page_kind(e)} · {e['data'].get('id')} «{e['data'].get('label', '')}»" + (f" → {e['data']['href']}" if e['data'].get('href') else ''), 'Most clicked controls')
    counted('key', lambda e: f"{page_kind(e)} · " + (e['data'].get('mods', '') + '+' if e['data'].get('mods') else '') + str(e['data'].get('key')), 'Keys')
    counted('change', lambda e: f"{page_kind(e)} · {e['data'].get('id')} = {json.dumps(e['data'].get('value', '…'), ensure_ascii=False)}", 'Setting changes')
    states, opened = collections.Counter(), set()
    for e in events:
        if e['type'] != 'state': continue
        if e['session'] not in opened: opened.add(e['session']); continue   # the first state of a page is where it started
        for k, v in e['data'].items():
            if k not in ('range', 'review', 'mode'): states[f'{k} → {json.dumps(v, ensure_ascii=False)}'] += 1
    if states:
        w('\n## Trainer state switches (not counting the opening state)\n')
        for k, n in states.most_common(top): w(f'- {n}× {k}')
    modes = collections.Counter(e['data']['mode'] for e in events if e['type'] == 'state' and 'mode' in e['data'])
    if modes: w('\nModes entered: ' + ', '.join(f'{m} {n}×' for m, n in modes.most_common()))
    seeks = [e for e in events if e['type'] == 'seek']
    if seeks: w(f"Seeks: {len(seeks)} ({sum(1 for e in seeks if e['data'].get('mode') == 'idle')} while stopped)")
    counted('toast', lambda e: e['data'].get('text', ''), 'Toasts shown')
    counted('error', lambda e: e['data'].get('text', ''), 'Errors shown')
    counted('notice', lambda e: e['data'].get('text') or e['data'].get('id'), 'Studio notices')
    counted('js_error', lambda e: f"{e['page']}: {e['data'].get('message')}", 'Script errors')

    # Singing: every attempt, grouped by song, in time order.
    by_song = collections.defaultdict(list)
    for e in events:
        if e['type'] == 'attempt' and e['data'].get('match') is not None: by_song[(e['page'], e['data'].get('songHash'))].append(e)
    if by_song:
        w('\n## Singing\n')
        for (page, song), runs in sorted(by_song.items(), key=lambda kv: -len(kv[1])):
            matches = [r['data']['match'] for r in runs]; sung = sum(r['data'].get('duration') or 0 for r in runs)
            w(f"### {page}  ({len(runs)} attempt{'s' if len(runs) > 1 else ''}, {minutes(1000 * sung)} sung)\n")
            w(f"match % first → last: {matches[0]:.1f} → {matches[-1]:.1f}; best {max(matches):.1f}; median {statistics.median(matches):.1f}")
            levels = collections.Counter(f"{r['data'].get('level')}/{r['data'].get('view')}/×{r['data'].get('speed')}" for r in runs)
            w('settings: ' + ', '.join(f'{k} {n}×' for k, n in levels.most_common()))
            cents = [r['data']['medianCents'] for r in runs if isinstance(r['data'].get('medianCents'), int) and r['data']['medianCents'] >= 0]
            if cents: w(f'median |Δ| per attempt: {min(cents)}–{max(cents)} ¢ (median {statistics.median(cents):.0f} ¢)')
            phrases = collections.defaultdict(lambda: [0, 0, 0, []])
            for r in runs:
                for pid, target, hit, sung_f, med in r['data'].get('phrases') or []:
                    q = phrases[pid]; q[0] += target; q[1] += hit; q[2] += 1
                    if med is not None and med >= 0: q[3].append(med)
            ranked = sorted(((q[1] / q[0], pid, q) for pid, q in phrases.items() if q[0] >= 75), key=lambda x: x[0])
            if ranked:
                fmt = lambda x: f"#{x[1]} {100 * x[0]:.0f}% over {x[2][2]} attempts" + (f", median {statistics.median(x[2][3]):.0f} ¢" if x[2][3] else '')
                w('weakest phrases: ' + '; '.join(fmt(x) for x in ranked[:5]))
                w('strongest phrases: ' + '; '.join(fmt(x) for x in ranked[::-1][:3]))
            w('')
    return '\n'.join(out) + '\n'


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--songs', default=str(ROOT / 'songs')); ap.add_argument('--days', type=int, default=30); ap.add_argument('--since')
    a = ap.parse_args()
    since = a.since or (datetime.date.today() - datetime.timedelta(days=a.days - 1)).isoformat()
    print(report(*load(Path(a.songs).expanduser() / 'logs' / 'activity', since)), end='')
