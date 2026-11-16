#!/usr/bin/env python3
"""Make a compact montage of working windows, without a browser.
Usage: python tools/song_qa/sheets.py WINDOWS_DIRECTORY OUTPUT_DIRECTORY
"""
import argparse
from pathlib import Path
from PIL import Image

if __name__ == '__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('windows',type=Path); ap.add_argument('output',type=Path); a=ap.parse_args()
    files=sorted(a.windows.glob('w*.png'))
    if not files: raise ValueError('no windows to assemble')
    a.output.mkdir(parents=True,exist_ok=True)
    # Paginate to avoid one unbounded image for a long track.
    for page in range(0,len(files),8):
        images=[]
        for file in files[page:page+8]:
            with Image.open(file) as im:
                im.thumbnail((780,540)); images.append(im.convert('RGB'))
        width=780; height=540
        sheet=Image.new('RGB',(width*2,height*((len(images)+1)//2)),(7,9,13))
        for i,im in enumerate(images): sheet.paste(im,((i%2)*width,(i//2)*height))
        sheet.save(a.output/f'sheet-{page//8:02d}.jpg',quality=85)
