# Recovering HABITABILIDAD's comparison operators

Resolves [#21](https://github.com/javier-abia/urbandocs/issues/21). Measured 2026-07-29 against
`documentos/HABITABILIDAD.pdf` (106 pp.) and the tuned artifacts in
`documentos/documentos-docling/docling-tuned/`.

## The question

[#14](https://github.com/javier-abia/urbandocs/issues/14) found **zero `≥`, zero `≤`, zero `m²`**
across the 94 OCR'd pages of HABITABILIDAD, against 92 / 40 / 103 in its 12 natively-parsed pages.
The loss is silent: `superficie útil ≥ 12 m²` extracts as `superficie útil 2 12 m?`, and a deleted
`<` leaves grammatical Spanish stating a different rule. Three options were on the table:
re-OCR with an operator-inclusive config, a different engine, or accept-and-disclose.

## Answer in one line

**Option 1 is impossible, option 2 works on prose and only on prose, and option 3 is still required
for `²` and for every non-prose region.** `≥` and `≤` come back on the articulado's body text via
tesseract's *legacy* engine plus `equ.traineddata`, at 8 minutes and 143 MB for all 94 pages. `²`
comes back from no engine tested. Operator recovery must be gated to prose regions, because on
line art the same pass **manufactures** operators.

## 1. Why option 1 cannot work

EasyOCR's recognition alphabet is fixed by the model. `latin_g2`'s `characters` string (upstream
`easyocr/config.py`) contains `<`, `>`, `=` — and **no `≥`, no `≤`, no `²`**. A character allowlist
can only *restrict* a charset, never extend it, so no EasyOCR configuration recovers these glyphs;
only a retrained recognition head would. This also explains the substitution seen in #14: `≥` → `2`
is the nearest in-charset shape.

Tesseract's LSTM models are the same story — `spa.traineddata` (tessdata_best) has a **109-character**
unicharset, `eng` 112; neither contains `≥`, `≤` or `²`.

The one model tested that *does* contain them is `equ.traineddata` (330 characters, math/equation
model): `≥` ✅, `≤` ✅, `²` ❌, and notably **no `<` or `>`**. It is a **legacy** model — usable only
with `--oem 0`. Confirmed empirically: with `--oem 3`, `1`, or the default, `-l spa+equ` yields zero
`≥`; only `--oem 0` recovers them.

```
tesseract page.png out -l spa+equ --oem 0 --psm 6     # spa here = tessdata (legacy+LSTM), not tessdata_best
```

## 2. What comes back on prose — p. 49, the ticket's own example

Ground truth read from the rendered page image. "current" = tuned `HABITABILIDAD.json`.

| ground truth (p. 49) | current (EasyOCR) | tesseract legacy + equ |
|---|---|---|
| `superficie útil ≥ 12 m²` | `superficie útil 2 12 m?` | `superficie útil ≥ 12 m2` ✅ |
| `de superficie útil < 12 m² y aquellas que tengan ≥ 12 m²` | `de superficie útil 12 m? y aquellas que tengan 2 12 m?` | `de superficie útil < 12 m2 y aquellas que tengan ≥ 12 m2` ✅ |
| `desviación mínima ≥ 15º` (p. 48) | `desviación mínima 2 15"` | `desviación mínima ≥ 15º` ✅ |

Every operator on every hand-verified prose page came back in the right place with the right
direction: pp. 48, 49, 65, 68, 76 — **0 inversions, 0 operators invented in prose, 0 dropped**.
Pages 65, 68 and 76 are controls: their prose contains no `≥`/`≤` and the pass added none.

Two side effects, both benign:

- `m²` → `m2`, which folds cleanly under the unit rule already settled in #14 (`m²`≡`m2`≡`m?`) —
  and is what the source itself writes in places (pp. 68, 76 print a literal `m2`).
- `×` → `><` (5 occurrences over 94 pp.), a deterministic artifact: `><` is never valid, so it
  repairs to `×` unambiguously. It is the only source of spurious `<`/`>` found in prose.

## 3. What comes back over the whole articulado

Full re-OCR of pp. 1–94, 300 dpi grayscale, `-l spa+equ --oem 0 --psm 6`
(`scripts/ocr_operator_probe.py`):

| | current tuned output | legacy + equ |
|---|---|---|
| `≥` | 0 | 24 |
| `≤` | 0 | 17 |
| `<` | 0 | 16 (+5 from `×`) |
| `>` | 0 | 7 (+5 from `×`) |
| `²` | 0 | 0 |
| words | 23,770 | 25,089 |
| cost | 9 m 22 s (EasyOCR, #11) | **8 m 02 s, 143 MB peak RSS** |

Cost is the headline non-finding: this runs on a 6 GB laptop with no GPU, no API and no docling
install — ~5 s per A4 page, 143 MB. Nothing about the recovery is expensive.

**The operators are rarer in the articulado than the #14 headline suggests.** Of the 41 recovered
`≥`/`≤`, only ~6 sit on prose lines; the rest are figure labels (`P ≥ 2.00 m` in GRÁFICO 7,
`capacidad ≤ 100 vehículos` in GRÁFICO 36) — correctly transcribed, but figure-interior text, which
is out of scope. The articulado overwhelmingly states its thresholds **in words**: p. 72 prose says
*"capacidad menor o igual a 100 vehículos … ancho mayor o igual a 15 m"* and puts the symbols only
in the diagram. The symbolic density lives in the natively-parsed tail (92 `≥` in pp. 97–101),
which is already exact.

## 4. Where it fails: line art manufactures operators

Measured against exact ground truth — pp. 97–101 have a text layer, so the PDF's own text is truth.
These are dense A3 tables, rendered at 200 dpi and put through both engines:

| pp. 97–101 (9,453 words) | truth | tesseract LSTM `spa` | legacy `spa+equ` |
|---|---|---|---|
| `≥` | 92 | 0 | 35 |
| `≤` | 40 | 0 | **105** |
| `<` | 21 | 111 | 76 |
| `>` | 13 | 134 | 49 |
| `²` | 103 | 0 | 0 |
| time | — | 92 s | 418 s |

`≤` at 105 against a truth of 40 is the finding: table rules and diagram leader lines get read as
comparison operators. Both engines do it (LSTM's 111 `<` / 134 `>` is the same defect wearing
different glyphs). Character error rate on these pages is ~77 % (LSTM) / ~83 % (legacy), though that
figure is inflated by multi-column reading order against a linearized ground truth and should not be
read as a prose-quality number.

So the recovery pass is only sound where the region is prose. Gating is not optional: an ungated
run would inject dozens of fabricated thresholds into exactly the tables an architect would trust.
The gate is already available — #11's planned rule of dropping text whose bbox falls inside a
`pictures[]` bbox, plus excluding table regions.

## 5. `²` is unrecoverable

No tested model has `²` in its charset: EasyOCR `latin_g2` ❌, tesseract `spa` ❌, `eng` ❌, `equ` ❌.
Every engine degrades it to `m2`, `m?` or `m”`. This is not a problem worth another engine: unit
folding was already settled in #14, the unit is inferable from context (`superficie` → m²), and
unlike an operator, a wrong unit does not silently invert a rule.

## 6. Constraints on the ingest pipeline

- **docling cannot express this OCR call.** `TesseractCliOcrOptions` / `TesseractOcrOptions` expose
  `lang`, `psm`, `path`, `tesseract_cmd` — there is **no `--oem` field and no passthrough for extra
  CLI args**, and `lang=["spa","equ"]` under the default engine mode yields zero operators. So the
  recovery cannot be a docling OCR-options tweak. It has to be either a custom docling OCR plugin or
  a separate pass whose output is spliced back by bbox — a decision that belongs to whatever the
  ingest script (#4 fog) turns out to be.
- **Do not repair `>` → `≥` blindly.** The corpus genuinely uses the strict operators: 21 `<` and
  13 `>` in the native pages, and p. 48's GRÁFICO 15 carries a real `α > ± 15°`. A blind rewrite
  would invert roughly one threshold in eight.
- **Disclosure is still required.** Even with the pass, recovered operators come from a *second*
  engine on prose regions only; tables and figures on pp. 1–94 stay threshold-unreliable. The
  per-axis fidelity flag (#4 / #8) is not retired by this — its value changes from "no operators
  anywhere" to "operators in prose, verified glyph-exact; nothing in tables or figures".

## 7. Side finding — the silent clause drops

Legacy tesseract did **not** reproduce the silent clause drops of [#17](https://github.com/javier-abia/urbandocs/issues/17)
on any page checked. On p. 49 the leading clause EasyOCR dropped (*"Siempre que la superficie de la
cocina se incremente en…"*) is present in full, and over pp. 1–94 the pass yields **1,319 more
words** than the tuned output (25,089 vs 23,770), with tesseract LSTM and legacy agreeing on word
count page by page. That points at the drops being an EasyOCR/region-detection artifact rather than
an unreadable source — a lead for #17, not a resolution: it was not verified clause by clause.

## Reproducing

```bash
# Spanish + equation data (not packaged on Arch)
curl -sLO https://github.com/tesseract-ocr/tessdata/raw/main/spa.traineddata      # legacy+LSTM
curl -sLO https://github.com/tesseract-ocr/tessdata/raw/main/equ.traineddata
export TESSDATA_PREFIX=$PWD

python3 scripts/ocr_operator_probe.py            # pp.1-94, ~8 min, writes ocr_operator_probe.json
```
