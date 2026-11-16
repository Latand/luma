#!/usr/bin/env python3
"""Convert the Progress tab's exported history to an optional picture layer.
Usage: python tools/song_qa/attempts.py PACKAGE HISTORY.json OUTPUT.json
No browser or profile is accessed. Only runs for this package are retained.
"""
import argparse
import base64
import json
import math
from pathlib import Path
import numpy as np
from common import write_json


def convert(song, data):
    if data.get('schema') != 'luma.history.v1':
        raise ValueError('expected luma.history.v1 export')
    key = song.get('sourceId') or song['id']
    runs = {r['id']: r for r in data['runs'] if r['songHash'] == key}
    result = {'traces': []}
    for trace in data['traces']:
        run = runs.get(trace['runId'])
        if run is None: continue
        hop = trace['hop']; speed = run['speed']; start = run['a']
        if not all(isinstance(v,(float,int)) and math.isfinite(v) for v in (hop,speed,start)) or not 0 < hop <= 1 or not 0 < speed <= 4:
            raise ValueError('invalid attempt clock')
        points = []
        for segment in trace['segments']:
            cents = np.frombuffer(base64.b64decode(segment['cents'],validate=True),dtype='<i2')
            conf = np.frombuffer(base64.b64decode(segment['conf'],validate=True),dtype='u1')
            db = np.frombuffer(base64.b64decode(segment['db'],validate=True),dtype='i1')
            if len(cents) != len(conf) or len(cents) != len(db): raise ValueError('attempt channels differ')
            if not math.isfinite(segment['t0']) or segment['t0'] < 0: raise ValueError('invalid segment clock')
            for i, (m,c,level) in enumerate(zip(cents,conf,db)):
                t = start + (segment['t0']+i*hop)*speed
                if m != -32768 and c >= 204 and level >= -48 and 0 <= t <= song['duration']:
                    points.append([round(t,3),float(m)/100])
        result['traces'].append({'points':points})
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('package',type=Path); ap.add_argument('history',type=Path); ap.add_argument('output',type=Path)
    a=ap.parse_args()
    result=convert(json.loads((a.package/'target.json').read_text()),json.loads(a.history.read_text()))
    write_json(a.output,result)
    print(f"{len(result['traces'])} matching traces")

if __name__ == '__main__': main()
