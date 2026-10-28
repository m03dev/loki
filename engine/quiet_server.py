"""One HTTP server class for every local server LOKI runs (the bridge, the model proxy, peers, the phone link).

A client that hangs up mid-request or mid-reply (OpenCode cancelling a slow model call, a closed window, a peer that
went to sleep) is not an error: Python's socketserver prints a full ConnectionResetError traceback for it, and on the
PC those tracebacks ended up at the bottom of failed jobs' output (2026-10-28: "they're coming back failed and
nonsense") - burying the one line that said what really went wrong. Every other error is still printed.
"""
from __future__ import annotations

import sys
from http.server import ThreadingHTTPServer

HANGUPS = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError)


class QuietHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):  # noqa: D401
        if isinstance(sys.exc_info()[1], HANGUPS):
            return
        super().handle_error(request, client_address)
