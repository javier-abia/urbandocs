# HABITABILIDAD: measuring the silent OCR line drops

Resolves [#17](https://github.com/javier-abia/urbandocs/issues/17). Measures how much
rendered text the tuned docling OCR output for `HABITABILIDAD.pdf` (pp. 1–94) never
recorded, names every dropped line, and says what fixes it.

Ground truth throughout is **the rendered page**, not another extraction: a line that
has ink on the page and no OCR item covering it is lost, regardless of what any engine
reads there.

## Answer in one paragraph

**65 text lines on 34 of the 94 OCR'd pages are absent from the tuned JSON**, plus the
running header on 7 pages. 41 are articulado or commentary prose, 24 are structural: the
document's own index (pp. 31–33) and the Anexo II subsection titles (pp. 85–89). Eight of
the 65 carry a dimension (`1,20 m`, `1,80 m`, `2,40 m`, `0,20 m²`, `8 m`, `25 m`, `3 m`).
The loss is **not** figure-related and **not** page-position related; it is a line-level
failure of region-based OCR, and **58 of the 65 lines come back verbatim in the full-page
tesseract pass [#21](https://github.com/javier-abia/urbandocs/issues/21) already
requires** — so this is fixable at conversion time, by the pass that is already being
added, not by a patch list afterwards.

## Method

Two passes, both in `scripts/ocr_line_coverage.py` (the second supersedes the first;
both were run and merged for the numbers below).

1. **Row coverage.** Render each page at 150 dpi to grayscale PGM (`pdftoppm -gray`, no
   Python imaging dependency — the parser is 20 lines). Mark ink rows, subtract the row
   ranges of every `prov.bbox` on that page, group leftover ink rows into bands, crop
   each band and OCR it (`tesseract -l spa --psm 7`) to see what it says.
2. **Column coverage (2D).** Same, but coverage is per *pixel column* within each row.
   Needed because pass 1 marks a whole row covered when any item touches it, which hides
   losses that sit on a row the OCR did read — exactly the index case, where the marker
   `A.1.` survived and the title to its right did not.

Cost: 4.2 s/page, ~7 min for pp. 1–94, no GPU, no API, no docling.

**Deciding whether a band is a loss.** A band's OCR text is compared against the tuned
JSON's text for that page by *occurrence count*, not presence: this document repeats
whole headings verbatim (`3.2 Elementos y determinaciones que pueden ser exceptuados`
appears four times on p. 85 alone), and a presence test lets one surviving copy mask
three dropped ones. Figure line art was excluded by a text-shape gate plus hand review
of the residue (7 bands of diagram ink, 1 table row inside a figure).

**Precision check.** 8 bands were cropped from the render and read by eye against the
page: p. 38, p. 39 (×2), p. 48, p. 52, p. 79, p. 87, p. 31. All 8 are real losses, and in
every prose case the surviving neighbouring block begins mid-sentence, which corroborates
the geometry independently. No false positive was found in the hand-checked sample.

**Known recall limit.** A line dropped from the *middle* of a multi-line block is
invisible to this method, because the item's `prov.bbox` is the union over its own lines
and therefore spans the gap. So 65 is a floor, not a ceiling. An attempt to bound the
interior class by word-alignment against the full-page tesseract text was abandoned as
unsound — repeated boilerplate makes the alignment jump, producing "+321 words missing"
artifacts. The honest statement is: **all edge losses are enumerated; interior losses are
unmeasured.** The mitigation below removes the need to measure them.

## What the pattern is

| | |
|---|---|
| confirmed losses | **65 lines on 34 pages** (pp. 1–94) |
| whole line, nothing covering its rows | 48 — of which **38 the first line of a block**, 7 the last, 3 isolated |
| on a row the OCR did read (title lost, marker kept) | 17 |
| articulado / commentary prose | 41 |
| index titles (pp. 31–33) | 14 bands; **20 of the 83 index entries** are marker-only stubs (see below) |
| Anexo II subsection titles `n.n` (pp. 85–89) | 10 |
| carrying a dimension or threshold | 8 |
| running header dropped (furniture, harmless) | 7 pages |
| recovered verbatim by full-page tesseract | 58 / 65 |

**The "leading line of a block" story from [#11](https://github.com/javier-abia/urbandocs/issues/11) is mostly right and not exclusive.**
38 of the 48 whole-line drops are a block's first line — the failure mode that reads as
well-formed prose and therefore announces nothing. But 7 are the block's *last* line,
including #11's own example: p. 55's `…con una superficie mínima de 0,20 m² que tomará el
aire del exterior del edificio.` is the tail of `#/texts/850`, which ends mid-sentence at
`…un conducto de entrada de aire en la parte`. Any repair keyed on "check the first line"
would miss it.

**It does not correlate with figures or page position.** Only 4 of the whole-line drops
sit within 40 px of a `pictures[]` bbox, and only 13 are in the top quarter of the page.
The tight leading of the document is a plausible contributor but is uniform across pages
that lose nothing, so it does not discriminate either. What the drops share is
structural: they are at block boundaries, where a line's own detection has no
neighbouring line inside the same region to anchor it.

**The document's own table of contents is 24% titleless.** Independently of band
detection, counting the items directly: of the 83 index entries on pp. 31–33, **20 are
reduced to their marker** — `A.1.`, `A.1.1.`, `A.1.2.`, `A.2.`, `A.3.`, `A.4.`, `A.4.1.`,
`A.4.2.`, `B.1.2.`, `B.2.`, `B.2.1.1.`, `B.2.1.2.`, `B.2.1.3.`, `B.2.3.`, `B.2.4.`,
`B.2.6.`, `B.2.6.1.`, `B.2.6.3.`, `B.2.7.`, `B.3.` — with the title text beside them
dropped. The render says `A.1.CONDICIONES DE DISEÑO, CALIDAD Y SOSTENIBILIDAD`; the JSON
says `A.1.`. This **corrects #11's finding that the TOC rebuilds fine**: it rebuilds as a
tree of numbers with a quarter of its labels missing, which matters directly to
[#5](https://github.com/javier-abia/urbandocs/issues/5) if the index spine is to be
sourced from the document's own contents page. Same defect on p. 39, where two lines of a
provision are reduced to `-` (`#/texts/536`, `#/texts/537`) while the render reads
`La altura desde la parte inferior de la ventana … podrá ser superior a 1,20 m`.

## The fix: it belongs in the conversion, and the pass already exists

The tuned pipeline ran `force_full_page_ocr=false` with `confidence_threshold=0.5` and
`bitmap_area_threshold=0.05` (`HABITABILIDAD.pipeline.json`). With full-page OCR off,
EasyOCR is asked to find and read text region by region, and a region it either does not
propose or reads below 0.5 confidence is dropped without a trace. That is the mechanism
this measurement is looking at, and it is a **settings** failure, not an engine limit:

- **58 of the 65 lines are already present, verbatim, in the full-page tesseract text
  produced for #21** (`--oem 0`, `spa+equ`, 300 dpi, 8 min for pp. 1–94). Nothing new has
  to be built or paid for to recover them.
- The 7 that pass also missed are 3 index titles it read with different diacritics
  (`Areas` vs `Áreas` — matching artifacts, not losses), p. 38 and p. 39 lines it read
  with different spacing, p. 79 italic commentary, and p. 93's Galician form field.

**Recommendation for the ingest script** (this is the concrete constraint #17 hands to the
conversion work in the map's *Not yet specified*):

1. For the `ocr` profile, **take the text from a full-page pass, not from region-based
   OCR.** #21 already requires a full-page tesseract legacy pass over pp. 1–94 to recover
   `≥`/`≤` in prose, spliced back by bbox. That same pass is the line-coverage fix. One
   pass, two defects closed — do not add a second engine.
2. If EasyOCR output is kept for anything, set `force_full_page_ocr=true` for this
   document and re-measure; the region path is what loses lines.
3. **Gate the ingest on coverage.** `scripts/ocr_line_coverage.py` is cheap enough
   (4.2 s/page) to run as an acceptance check after conversion: uncovered ink that reads
   as text should fail the build for that document. This is what makes the unmeasured
   interior-drop class moot — coverage is checked against the render every time, rather
   than trusted once.

**If a residue survives the above**, what the engine owes the user is *disclosure at the
citation*, consistent with the axis-level trust vector already in the map: an OCR-derived
passage adjacent to known uncovered ink must be flagged so the agent says "this passage
may be incomplete" rather than quoting it as the provision. A per-document known-gaps
list keyed by page is enough, and this document's list is the table below. It is a
fallback, not the plan.

## p. 95, the ADENDA divider

Docling emits **one `picture` and zero text items** for p. 95, so the boundary between the
articulado and the ADENDA is invisible in the JSON — confirmed. It needs no special
handling: plain `tesseract -l spa` on a 300 dpi render reads it exactly, with no
inversion and no contrast work.

```
ADENDA. Fichas gráficas de diseño de edificios de viviendas en Galicia
```

Inverting first (`-negate -threshold 55%`) produces the identical string, so the
white-on-blue treatment is not in fact an obstacle — the page was simply never OCR'd,
being classified whole as a picture. Either let the full-page pass cover p. 95 too, or
hand-enter this one line as the section boundary.

## Full inventory

The dropped lines, as read from the render. `kind` is `leading` / `trailing` / `isolated`
for whole-line drops (position within the block it was cut from) and `same-row` where the
OCR read part of the line and dropped the rest. Text is the tesseract reading, so its own
OCR slips (`v` for `y`, `m?` for `m²`, `C.70` for `C.10`) are present — the authority for
wording is the page.

| p. | kind | line missing from the tuned JSON (tesseract reading of the render) |
|---:|---|---|
| 5 | leading | Asesor de Habitabilidad. (DOG n* 19, de 28.01.2011) |
| 10 | leading | El 20 de enero de 2021, el Pleno del Observatorio de la Vivienda de Galicia firmó el Pacto de Galicia |
| 11 | leading | En esta línea, se sometió a consulta pública, así como al trámite de información pública v audiencia, |
| 15 | leading | En estos suelos, la modificación del planeamiento que implique la variación de la ordenación |
| 17 | same-row | Obras de adecuación estructural: son las obras que tienen por objeto proporcionar al edificio |
| 17 | leading | seguridad constructiva garantizando su estabilidad y resistencia mecánica. |
| 19 | leading | 3. En cualquiera caso, cuando les sean de aplicación, podrá solicitarse o acogerse a la no aplicación |
| 24 | leading | b) Cuando existan motivos urbanísticos o derivados de la necesidad de protección del patrimonio |
| 24 | leading | b) Recoger los espacios, públicos o privados, que se consideran espacios exteriores y por lo tanto |
| 25 | trailing | innovación tipológica y constructiva, en el campo tanto de la obra nueva como de la rehabilitación. |
| 31 | same-row | CONDICIONES DE DISEÑO, CALIDAD Y SOSTENIBILIDAD |
| 31 | same-row | Condiciones de vivienda exterior. |
| 31 | same-row | Iluminación, ventilación natural y relación con el exterior. |
| 31 | same-row | CONDICIÓNS ESPACIAIS E DIMENSIONAIS |
| 31 | same-row | CONDICIONES DOTACIONALES DE LAS VIVIENDAS |
| 31 | same-row | Dotación mínima en la vivienda. |
| 31 | same-row | Equipamiento de los servicios. |
| 32 | same-row | ES GENERALES DEL EDIFICIO EN RELACIÓN CON EL ESPACIO EXTERIOR Y SUS |
| 32 | same-row | Vuelos y cuerpos salientes en la edificación. |
| 32 | same-row | CONDICIONES DE LOS ESPACIOS DEL EDIFICIO |
| 32 | same-row | Areas de acceso a ascensores y escaleras. |
| 32 | same-row | Area de acceso y espera. |
| 32 | same-row | Otros espacios del edificio. |
| 32 | same-row | INSTALACIONES DEL EDIFICIO |
| 34 | leading | \| fachada a una distancia de 3 m.; de acuerdo con la definición C.70 Luz directa. |
| 35 | leading | d) Para garantizar la protección de vistas desde calles, plazas o espacios libres públicos a las piezas |
| 38 | leading | e) Cuando la pieza vividera se ilumine a través de una terraza cubierta de profundidad superior a 2 |
| 39 | same-row | La altura desde la parte inferior de la ventana hasta el pavimento rematado de la estancia no |
| 39 | isolated | podrá ser superior a 1,20 m |
| 39 | same-row | La altura desde la parte superior de la ventana hasta el pavimento rematado de la estancia no |
| 39 | leading | podrá ser inferior a2m. |
| 41 | leading | \| de las cocinas, escalones, barandillas, etc. no pueden invadir este cuadrado base. |
| 43 | leading | d) Aquella área de las piezas vivideras que no cumpla el ancho mínimo establecido para cada caso, |
| 43 | leading | e) Se entenderá que se cumple el ancho mínimo exigible a la pieza, en aquella parte de esta en la |
| 44 | trailing | tendedero y un espacio de almacenamiento. |
| 45 | leading | a) Siempre que sea compatible con el planeamiento y la normativa de protección del patrimonio |
| 48 | leading | Cc) Excepcionalmente, en el caso de solares de geometría irregular con un frente de fachada inferior |
| 50 | trailing | mínimo entre paramentos de 1,80 m libre de obstáculos. (GRAFICO 18) |
| 52 | leading | q) Cuando la cocina se integre en un único espacio con la estancia mayor, la superficie de dicho |
| 52 | leading | espacio será como mínimo la suma de las superficies mínimas establecidas para cada una de estas |
| 55 | trailing | inferior del patio con una superficie mínima de 0,20 m? que tomará el aire del exterior del edificio. |
| 56 | leading | d) Cuando la ventilación sea mecánica, el tendedero deberá contar con calefacción, las paredes irán |
| 56 | trailing | edificación (en adelante, CTE), para aseos y cuartos de baño. (GRAFICO 24) |
| 61 | leading | d) Cuando el vuelo esté constituido por una galería, conforme a la definición C.12 de este anexo, los |
| 65 | leading | Deberá, además, tener una altura libre mínima de 2,40 m. La comunicación de esta zona con |
| 66 | leading | b) Será preciso que exista un itinerario accesible para personas con movilidad reducida desde el |
| 69 | leading | b) Excepcionalmente, cuando la puerta de acceso a todas las viviendas esté situada a menos de 8 m |
| 69 | leading | d) Si el desnivel es de 25 m o mayor, el número mínimo de ascensores será de dos, excepto que el |
| 79 | leading | \| tabiques. Así mismo, conviene tener en cuenta lo siguiente: |
| 79 | leading | \| — tabiques y con las dimensiones mínimas que se indican. |
| 85 | trailing | 3.1. Condiciones determinantes de la excepción. |
| 85 | isolated | 3.2. Elementos y determinaciones que pueden ser exceptuados. |
| 85 | trailing | 3.3. Condiciones determinantes de la excepción. |
| 85 | isolated | 3.4. Elementos y determinaciones que pueden ser exceptuados. |
| 86 | leading | 2.1. Condiciones determinantes de la excepción. |
| 87 | leading | 2.2. Elementos y determinaciones que pueden ser exceptuados. |
| 87 | leading | a) Cuando la configuración del solar no permita la condición de vivienda exterior, ya que es imposible |
| 87 | leading | b) Cuando la superficie edificable del solar, descontando la superficie de las escaleras v elementos |
| 87 | leading | 3.1. Condiciones determinantes de la excepción. |
| 87 | leading | b) Cuando las condiciones de los espacios públicos, patios de manzana o patios de parcela existentes |
| 88 | leading | 9) Cuando la configuración del solar o el edificio no permita la condición de vivienda exterior, ya que |
| 88 | leading | 3.2. Elementos y determinaciones que pueden ser exceptuados. |
| 89 | leading | 4.1.Condiciones determinantes de la excepción. |
| 89 | leading | 4.2.Elementos y determinaciones que pueden ser exceptuados. |
| 93 | leading | \| - XUSTIFICACIÓN DO CARÁCTER INNOVADOR DA ACTUACIÓN NO RELATIVO Á TIPOLOXÍA ARQUITECTÓNICA. l |

## Reproducing

```bash
export TESSDATA_PREFIX=/path/to/tessdata   # needs spa.traineddata
python3 scripts/ocr_line_coverage.py 1-94  # ~7 min, writes report-1-94.json
```

Each report row is a band of ink no `prov.bbox` covers: page, pixel band, x extent,
whether it falls inside a `pictures[]`/`tables[]` bbox, and the OCR of the crop.
