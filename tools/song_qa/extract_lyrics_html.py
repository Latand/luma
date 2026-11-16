#!/usr/bin/env python3
"""Extract saved HTML using a named container, or a reviewer-selected attribute.
Usage: python tools/song_qa/extract_lyrics_html.py PAGE.html OUTPUT.txt [--attribute NAME --value VALUE]
Supports data-lyrics-container=true and itemprop=text. Unknown layouts refuse;
select a specific container after inspecting the saved page, or transcribe it.
"""
import argparse
from html.parser import HTMLParser
from pathlib import Path
from common import atomic_text


VOID_TAGS = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
             'link', 'meta', 'param', 'source', 'track', 'wbr'}


class Extractor(HTMLParser):
    def __init__(self, attribute=None, value=None):
        super().__init__(convert_charrefs=True)
        self.attribute=attribute; self.value=value; self.depth=0; self.text=[]; self.found=0
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        selected=(attrs.get(self.attribute)==self.value if self.attribute else
                  attrs.get('data-lyrics-container')=='true' or attrs.get('itemprop')=='text')
        if self.depth:
            if tag in ('br','p','div'): self.text.append('\n')
            if tag not in VOID_TAGS: self.depth+=1
        elif selected and tag not in VOID_TAGS:
            self.depth=1; self.found+=1; self.text.append('\n')
    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS: self.handle_endtag(tag)
    def handle_endtag(self,tag):
        if tag in VOID_TAGS: return
        if self.depth:
            if tag in ('p','div'): self.text.append('\n')
            self.depth-=1
    def handle_data(self,data):
        if self.depth: self.text.append(data)


def extract(src,attribute=None,value=None):
    parser=Extractor(attribute,value); parser.feed(src)
    result='\n'.join(l.strip() for l in ''.join(parser.text).splitlines() if l.strip())
    if not parser.found or not result: raise ValueError('no lyric container; select its attribute or transcribe the saved page')
    return result+'\n'


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('page',type=Path); ap.add_argument('output',type=Path)
    ap.add_argument('--attribute'); ap.add_argument('--value')
    a=ap.parse_args()
    if bool(a.attribute) != bool(a.value): ap.error('--attribute and --value are required together')
    atomic_text(a.output,extract(a.page.read_text(),a.attribute,a.value))

if __name__ == '__main__': main()
