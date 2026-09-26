# cadastro fixture

Minimal fixture repository for the `bench/llm_ab` LLM A/B benchmark: a
single HTML registration page (`cadastro.html`) created and then edited by
the benchmarked model. No Python application code -- `tests/check_cadastro.py`
is the harness-owned, stdlib-only acceptance checker (never written by the
model) shared by every arm and every quality lane.
