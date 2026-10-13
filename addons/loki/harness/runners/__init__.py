"""Isolated runners for optional third-party libraries.

Each runner is executed as `python -I runners/<name>.py` by conductor.py with a JSON job on
stdin and prints one JSON object on stdout. Heavy, optional dependencies (crawl4ai,
scrapling, browser-use, hindsight-client) are imported only here, in a child process with
a timeout, so a missing or misbehaving library can never take down the Loki engine.
"""
