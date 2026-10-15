# cloud_stubs - only for cloud agents without PyPI

Tiny stand-ins for `openai`, `pydantic` and `mcp` so an agent in a sandbox that cannot install
LOKI's packages can still run the offline suites:

    PYTHONPATH=tests/cloud_stubs python tools/ship.py --check

Background jobs start their own Python, which does not inherit PYTHONPATH. In a throwaway
sandbox, register the folder once instead:

    echo "$PWD/tests/cloud_stubs" > "$(python3 -c 'import site;print(site.getsitepackages()[0])')/loki_cloud_stubs.pth"

Never used by LOKI itself, by `tools/ship.py`, or on the Mac/PC (they have the real packages).
The `openai` stub speaks the chat-completions wire format over urllib, so requests really reach
the fake Ollama (and any OpenAI-compatible server) and every suite, including test_offline_e2e,
runs for real. A real machine run (`tools/ship.py --check`) stays the proof.
