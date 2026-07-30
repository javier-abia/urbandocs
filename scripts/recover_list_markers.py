#!/usr/bin/env python3
"""Recover the list markers that address every normative provision.

docling's EasyOCR pass over HABITABILIDAD pp.1-94 drops most list markers: the
glyph is legible in the raster but never reaches `ListItem.marker`. This script
reads the marker column with a second OCR engine (tesseract) and splices each
marker back onto the docling item that starts on the same line.

Two outputs:

  markers   one recovered marker per docling list_item, keyed by `self_ref`
  orphans   markers printed on the page where *no* docling item starts -- these
            are provisions whose leading line was silently dropped by the OCR
            (see issue #17), and the dropped line took the marker with it

Marker recovery is a closed-vocabulary problem (digits, single letters, `.`/`)`),
so OCR confusables collapse deterministically and the result can be validated by
ordinal continuity. Nothing here guesses an ordinal: an item whose marker cannot
be read stays unmarked rather than being numbered by position.

Usage:
    python3 scripts/recover_list_markers.py \
        --pdf documentos/HABITABILIDAD.pdf \
        --json documentos/documentos-docling/docling-tuned/HABITABILIDAD.json \
        --last-page 94 --out markers.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import tempfile
from collections import defaultdict

DPI = 200
PT = 72.0 / DPI

# the marker alphabet is tiny and known, so these collapse without ambiguity
CONFUSABLES = str.maketrans({
    '¢': 'c', '©': 'c', '€': 'c', '{': 'c', '(': 'c',
    'º': 'o', '°': 'o', '»': 'o',
    '|': 'l', 'I': 'l', '!': 'l',
    '}': ')', ']': ')', '>': ')',
    '·': '.', ',': '.',
})
# bare (unpunctuated) markers are real in this corpus -- DccSUA prints "1 ", and
# HABITABILIDAD's annex indices print "1"/"2" -- but a bare single letter is far
# more often the Spanish "o"/"y"/"a", so only digits may go unpunctuated.
MARKER = re.compile(r'^(?:\d{1,2}[.)]?|[a-z][.)]|[ivx]{1,4}[.)])$')

# the marker column: left of the body text, right of the page edge
GUTTER = (60.0, 140.0)
# a marker belongs to the item starting on its line, and sits at or left of it
DY_TOL = 8.0
DX_RANGE = (-8.0, 45.0)


def normalise(token: str) -> str | None:
    t = token.strip().translate(CONFUSABLES).lower()
    return t if MARKER.match(t) else None


def render(pdf: str, page: int, workdir: str) -> str:
    png = os.path.join(workdir, f'p{page}.png')
    if not os.path.exists(png):
        stem = os.path.join(workdir, f'r{page}')
        subprocess.run(['pdftoppm', '-f', str(page), '-l', str(page), '-r', str(DPI),
                        '-png', pdf, stem], check=True)
        produced = next(f for f in os.listdir(workdir)
                        if f.startswith(f'r{page}-') and f.endswith('.png'))
        os.rename(os.path.join(workdir, produced), png)
    return png


def line_heads(png: str, lang: str) -> list[dict]:
    """Leftmost word of each tesseract line -- the only place a marker can be."""
    tsv = subprocess.run(['tesseract', png, 'stdout', '-l', lang, '--psm', '6', 'tsv'],
                         capture_output=True, text=True).stdout
    heads: dict[tuple, dict] = {}
    for row in csv.DictReader(tsv.splitlines(), delimiter='\t', quoting=csv.QUOTE_NONE):
        try:
            conf = float(row['conf'])
        except (TypeError, ValueError):
            continue
        text = (row['text'] or '').strip()
        if conf < 0 or not text:
            continue
        key = (row['block_num'], row['par_num'], row['line_num'])
        word = {'text': text, 'l': int(row['left']) * PT, 'top': int(row['top']) * PT}
        if key not in heads or word['l'] < heads[key]['l']:
            heads[key] = word
    return list(heads.values())


def recover(pdf: str, doc: dict, last_page: int, lang: str, workdir: str) -> dict:
    pages = {int(k): v for k, v in doc['pages'].items()}

    list_items: dict[int, list] = defaultdict(list)
    anchors: dict[int, list] = defaultdict(list)   # everything that can own a line
    for item in doc['texts']:
        prov = item.get('prov')
        if not prov or prov[0]['page_no'] > last_page:
            continue
        if item['label'] == 'list_item':
            list_items[prov[0]['page_no']].append(item)
        if item['label'] in ('list_item', 'text', 'section_header'):
            anchors[prov[0]['page_no']].append(item)

    markers, orphans = {}, []
    for page in sorted(list_items):
        heads = line_heads(render(pdf, page, workdir), lang)
        candidates = []
        for word in heads:
            if not GUTTER[0] < word['l'] < GUTTER[1]:
                continue
            mark = normalise(word['text'])
            if mark:
                candidates.append((mark, word))

        height = pages[page]['size']['height']
        # docling bboxes are bottom-origin; tesseract is top-origin
        tops = [(height - a['prov'][0]['bbox']['t'], a) for a in anchors[page]]

        for item in list_items[page]:
            box = item['prov'][0]['bbox']
            y = height - box['t']
            best = None
            for mark, word in candidates:
                dy = abs(word['top'] - y)
                dx = box['l'] - word['l']
                if dy <= DY_TOL and DX_RANGE[0] < dx < DX_RANGE[1]:
                    if best is None or dy < best[0]:
                        best = (dy, mark)
            if best:
                markers[item['self_ref']] = {'marker': best[1], 'page': page}

        for mark, word in candidates:
            if not MARKER.match(mark) or mark[-1] not in '.)':
                continue  # unpunctuated bare markers are too noisy to call orphans
            starts_here = any(abs(y - word['top']) <= DY_TOL
                              and a['prov'][0]['bbox']['l'] - word['l'] > DX_RANGE[0]
                              for y, a in tops)
            if not starts_here:
                orphans.append({'page': page, 'marker': mark, 'top': round(word['top'], 1)})

    return {'markers': markers, 'orphans': orphans}


ALPHA = 'abcdefghijklmnopqrstuvwxyz'


def ordinal(mark: str) -> int | None:
    body = mark.rstrip('.)')
    if body.isdigit():
        return int(body)
    return ALPHA.index(body) + 1 if len(body) == 1 and body in ALPHA else None


def check_continuity(doc: dict, markers: dict) -> list[dict]:
    """Adjacent recovered markers should increment by one, or restart at one.

    A break means either a dropped sibling (see #17) or a defect in the source
    itself -- HABITABILIDAD p.85 genuinely prints its index as 1, 2, 2, 3.
    """
    def level(left: float) -> int:
        return 1 if left < 92 else (2 if left < 108 else 3)

    groups: dict[tuple, list] = defaultdict(list)
    for item in doc['texts']:
        rec = markers.get(item.get('self_ref', ''))
        if not rec:
            continue
        box = item['prov'][0]['bbox']
        groups[(rec['page'], level(box['l']))].append((-box['t'], rec['marker'], item))

    breaks = []
    for (page, lvl), rows in groups.items():
        rows.sort()
        for (_, prev, _), (_, cur, item) in zip(rows, rows[1:]):
            a, b = ordinal(prev), ordinal(cur)
            if a is None or b is None or b in (a + 1, 1):
                continue
            breaks.append({'page': page, 'level': lvl, 'from': prev, 'to': cur,
                           'text': item['text'][:60]})
    return breaks


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--pdf', required=True)
    ap.add_argument('--json', required=True, help='docling-tuned DoclingDocument JSON')
    ap.add_argument('--last-page', type=int, default=94,
                    help='last OCR-rendered page; the native tail needs no recovery')
    ap.add_argument('--lang', default='eng',
                    help='tesseract model; markers are language-neutral, so eng suffices')
    ap.add_argument('--workdir', default=None, help='cache for rendered pages')
    ap.add_argument('--out', default='-')
    args = ap.parse_args()

    doc = json.load(open(args.json))
    workdir = args.workdir or tempfile.mkdtemp(prefix='markers-')
    os.makedirs(workdir, exist_ok=True)

    result = recover(args.pdf, doc, args.last_page, args.lang, workdir)
    result['continuity_breaks'] = check_continuity(doc, result['markers'])

    total = sum(1 for t in doc['texts']
                if t['label'] == 'list_item' and t.get('prov')
                and t['prov'][0]['page_no'] <= args.last_page)
    result['summary'] = {
        'list_items': total,
        'markers_recovered': len(result['markers']),
        'orphan_markers': len(result['orphans']),
        'continuity_breaks': len(result['continuity_breaks']),
    }

    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out == '-':
        print(payload)
    else:
        open(args.out, 'w').write(payload)
        print(json.dumps(result['summary'], indent=2))


if __name__ == '__main__':
    main()
