"""End-to-end eval harness for urbandocs (#85).

A `pydantic-ai` agent connects to `urbandocs.server` as a real MCP client,
routed through LiteLLM on a dedicated eval key, graded pass/fail by a second
model acting as judge, tracked as a LangSmith Dataset + Experiment. See
`evals/README.md`.
"""
