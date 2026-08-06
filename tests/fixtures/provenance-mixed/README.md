# A provenance sidecar with an `ocr` range

Hand-written, and the only hand-written fixture in the repo. Everything in
`tests/fixtures/corpus/` is excerpted from the real corpus; this cannot be,
because the shape it carries no longer exists there.

#41 retired the OCR pipeline. Every range in the real `corpus.provenance.tsv` now
reads `native`, and `check_corpus` asserts exactly that. So a fixture excerpted
from the real corpus can only ever exercise one side of #27's fidelity
disclosure -- the side that says "this page was extracted natively, read it as
printed". The branch that discloses an OCR'd page would be unreachable from the
tests, and unreachable code rots.

The shape is the retired `HABITABILIDAD` edition's, which is where the disclosure
was designed: pages 1-94 OCR'd, a native tail. `doc` is deliberately
`retired-doc` and not `HABITABILIDAD` -- ingest leaves the `HAB` id prefix dead on
purpose (#41), and a fixture reusing the real name would invite a test that
resolves an id which must never resolve.

Nothing here is a claim about the current corpus. It exists so the disclosure
logic can be tested across both of its answers.
