"""Lyric target tokens, shared without importing audio or model dependencies."""
import re

ANNOTATION = re.compile(r'^\s*[\[(].*[\])]\s*$')


def tokenize(text: str) -> list[str]:
    lines = [ln for ln in text.splitlines() if not ANNOTATION.match(ln)]
    return [t for t in ' '.join(lines).split() if t]
