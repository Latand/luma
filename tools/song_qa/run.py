#!/usr/bin/env python3
"""Run the mechanical song pass on an isolated scratch copy.
Usage: python tools/song_qa/run.py PACKAGE --scratch DIRECTORY [--dry-run]
       [--base TARGET.json] [--words WORDS.txt] [--melody MELODY.json]
       [--attempts HISTORY.json] [--recorded-edits MELODY.json]

The input package is always read-only. Outputs (including a rebuilt trainer,
windows, sheets, reports and the original backup) are written under --scratch.
Candidates never become edits automatically. See docs/SONG_QA.md.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from common import write_json

HERE=Path(__file__).resolve().parent


def fingerprint(package):
    result={}
    for file in sorted(package.rglob('*')):
        if file.is_file():
            digest=hashlib.sha256()
            with file.open('rb') as stream:
                for block in iter(lambda:stream.read(1024*1024),b''): digest.update(block)
            result[str(file.relative_to(package))]=digest.hexdigest()
    return result


def benchmark(candidates, edits):
    """Event recall; no reference edit is provided to a detector.

    A hit needs >=80 ms overlap (or half of a shorter edit), matching category,
    octave direction, and the fill's pitch band within two semitones. Every clear is scored:
    unpitched candidates cover noise, and broken-note candidates can locate a
    pitched interruption that the reviewer cleared before filling the lead.
    """
    groups={'octave':[], 'clear':[], 'broken':[]}
    details=[]
    for i,edit in enumerate(edits):
        category={'octave':'octave','clear':'clear','fill':'broken'}.get(edit['op'])
        if category is None: continue
        matches=[]
        for candidate in candidates:
            if candidate['type'] not in ({'unpitched','broken'} if category=='clear' else {category}): continue
            if category=='octave' and candidate['shift'] != edit['shift']: continue
            if category=='broken' and abs(candidate['m']-edit['m']) > 2: continue
            overlap=min(candidate['b'],edit['b'])-max(candidate['a'],edit['a'])
            if overlap >= min(.08,(edit['b']-edit['a'])/2)-1e-6: matches.append(candidate)
        hit=bool(matches); groups[category].append(hit)
        details.append({'edit':i,'type':category,'a':edit['a'],'b':edit['b'],'hit':hit,'candidate_types':sorted({c['type'] for c in matches})})
    result={k:{'hits':sum(v),'edits':len(v),'rate':round(sum(v)/len(v),4) if v else None}
            for k,v in groups.items()}
    values=[v for vs in groups.values() for v in vs]
    result['total']={'hits':sum(values),'edits':len(values),
                     'rate':round(sum(values)/len(values),4) if values else None}
    result['candidate_counts']={k:sum(c['type']==k for c in candidates)
                                for k in ('octave','unpitched','broken','repeat')}
    result['events']=details
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('package',type=Path); ap.add_argument('--scratch',required=True,type=Path)
    for name in ('base','words','melody','attempts','recorded-edits'): ap.add_argument('--'+name,type=Path)
    ap.add_argument('--dry-run',action='store_true',help='record read-only acceptance intent; outputs stay in scratch in either mode')
    a=ap.parse_args(); source=a.package.resolve(); scratch=a.scratch.resolve()
    if scratch==source or source in scratch.parents or scratch in source.parents:
        ap.error('scratch and package must be separate directory trees')
    if not (source/'target.json').is_file(): ap.error('package requires target.json')
    # Refuse symlinks before copying: no scratch writer may follow one back into
    # the library, including a pre-existing target or nested lyrics directory.
    if any(p.is_symlink() for p in source.rglob('*')): ap.error('package symlinks are unsupported')
    before=fingerprint(source)
    scratch.mkdir(parents=True,exist_ok=True)
    work=Path(tempfile.mkdtemp(prefix='qa-',dir=scratch)); package=work/'package'
    shutil.copytree(source,package)
    if a.base: shutil.copyfile(a.base,package/'target.json')
    shutil.copytree(package,work/'before')
    # Independent phases run in separate processes, bounding peak memory.
    def call(script,*args):
        subprocess.run([sys.executable,str(HERE/script),*map(str,args)],check=True)
    features=work/'features.npz'
    call('features.py',package,features)
    candidates=work/'candidates.json'
    call('candidates.py',package,features,candidates)
    sung=[]
    if a.attempts:
        call('attempts.py',package,a.attempts,work/'attempts.json')
        sung=['--sung',work/'attempts.json']
    call('draw_windows.py',package,features,work/'windows'/'before','--step',12,*sung)
    with (work/'words.txt').open('w') as output:
        subprocess.run([sys.executable,str(HERE/'make_sheet.py'),str(package/'target.json')],stdout=output,check=True)
    edits=[]
    if a.words: edits+=['--words',a.words]
    if a.melody: edits+=['--melody',a.melody]
    call('apply_edits.py',package,features,'--base',package/'target.json','--report',work/'apply-report.json',*edits)
    call('finish_song.py',package,work/'trainer.html')
    call('draw_windows.py',package,features,work/'windows'/'after','--step',12,*sung)
    call('sheets.py',work/'windows'/'before',work/'sheets'/'before')
    call('sheets.py',work/'windows'/'after',work/'sheets'/'after')
    with (work/'onset-check.txt').open('w') as output:
        subprocess.run([sys.executable,str(HERE/'check_onsets.py'),str(package)],stdout=output,check=True)
    report={'dry_run':a.dry_run,'source_unchanged':fingerprint(source)==before,
            'embedded_target_equal':True,'windows':len(list((work/'windows'/'before').glob('*.png')))}
    if a.recorded_edits:
        report['benchmark']=benchmark(json.loads(candidates.read_text()),json.loads(a.recorded_edits.read_text()))
    write_json(work/'checks.json',report)
    if not report['source_unchanged']: raise RuntimeError('source package changed during pass')
    print(json.dumps({'output':str(work),**report}))

if __name__ == '__main__': main()
