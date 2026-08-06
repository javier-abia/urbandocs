# scripts/ — frozen evidence

These nine scripts are **evidence for decisions already made**, not a maintained
library. They produced the measurements cited in `docs/research/` and on the
issues they name; they are kept so those numbers can be re-derived, and for no
other reason.

They are deliberately excluded from every gate — no lint, no type check, no
tests (#46). Retrofitting those onto frozen evidence would churn files whose
whole value is that they still read as what was actually run.

**Nothing here is imported by anything.** Each is a standalone stdlib
executable. Expect some to reference paths that have since moved: they were
correct when run, and rewriting them would falsify the record rather than fix it.

## What moved out

The two scripts that are *live* now live in the package, where the gates reach
them:

| was | is |
| --- | --- |
| `scripts/ingest.py` | `uv run -m urbandocs.ingest` |
| `scripts/check_corpus.py` | `uv run -m urbandocs.check_corpus` |

Stage 2 rebuilds `corpus/corpus.tsv`; the gate asserts the bands over it. Both
run on a clean checkout with no third-party dependencies.

## The nine

| script | what it is evidence for |
| --- | --- |
| `build_navigable_index.py` | the two-level navigable index, deleted at every tier by #32 |
| `eval_index_routing.py` | the routing evaluation that killed it |
| `count_pointers.py` | cross-document pointer counts (#9) |
| `ocr_line_coverage.py` | OCR line-coverage measurement (#17, #21) |
| `ocr_operator_probe.py` | comparison operators lost by EasyOCR (#39) |
| `recover_list_markers.py` | list-marker recovery (#18) |
| `repair_ocr.py` | the three post-pass repairs docling could not make (#28) |
| `section_geometry.py` | section bbox geometry (#8) |
| `prototype_sweep_rank.py` | the ranking sweep prototype |

The OCR programme these last several belong to was **retired** by #41, which
rebuilt the corpus on the natively-extracted DOG decree. They record why.
