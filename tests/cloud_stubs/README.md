# cloud_stubs - only for cloud agents without PyPI

Tiny stand-ins for `openai`, `pydantic` and `mcp` so an agent in a sandbox that cannot install
LOKI's packages can still run the offline suites:

    PYTHONPATH=tests/cloud_stubs python tests/test_portal.py

Never used by LOKI itself, by `tools/ship.py`, or on the Mac/PC (they have the real packages).
Known stub-only failures (the same on master, not regressions): test_loki "an HTTP 400 still
fails over" and test_offline_e2e (needs the real OpenAI client against the fake Ollama). A real
machine run (`tools/ship.py --check`) stays the proof.
