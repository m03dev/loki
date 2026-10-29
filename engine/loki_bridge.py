"""Hand-over shim for machines still running the previous LOKI.

The old window restarts its engine from this path after an update. This shim keeps that old
window from rolling the update back (it answers the old health check), starts the new launcher
(`app/loki_app.py`), and closes the old window. It is removed once both machines run the new LOKI.
"""
import http.server
import os
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def arg(name: str) -> str:
    try:
        return sys.argv[sys.argv.index(name) + 1]
    except (ValueError, IndexError):
        return ""


def main() -> None:
    token = secrets.token_hex(16)
    secret_file = arg("--secret-file")
    port = int(os.environ.get("LOKI_PORT") or 8767)

    class Health(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            ok = self.headers.get("Authorization", "") == "Bearer " + token
            self.send_response(200 if ok else 401)
            self.end_headers()
            self.wfile.write(b'{"ok":true,"handover":true}')

        def log_message(self, *a):  # quiet
            pass

    try:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Health)
        threading.Thread(target=server.serve_forever, daemon=True).start()
    except OSError:
        server = None
    if secret_file:
        try:
            Path(secret_file).parent.mkdir(parents=True, exist_ok=True)
            Path(secret_file).write_text(token, encoding="utf-8")
        except OSError:
            pass

    old_app = os.environ.get("LOKI_APP_PID", "")
    python = Path(sys.executable)
    if sys.platform == "win32" and (python.parent / "pythonw.exe").is_file():
        python = python.parent / "pythonw.exe"
    env = dict(os.environ)
    for k in ("LOKI_SUPERVISED", "LOKI_PORT", "LOKI_APP_PID"):
        env.pop(k, None)
    if old_app.isdigit():
        env["LOKI_APP_WAIT_PID"] = old_app
    kw = {"cwd": str(REPO), "env": env, "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        kw["creationflags"] = 0x00000008 | 0x00000200
    else:
        kw["start_new_session"] = True
    subprocess.Popen([str(python), str(REPO / "app" / "loki_app.py")], **kw)  # noqa: S603

    time.sleep(4)   # the old window sees a healthy engine, so it does not roll back
    if old_app.isdigit():
        pid = int(old_app)
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, creationflags=0x08000000)
        else:
            try:
                os.kill(pid, 15)
            except OSError:
                pass
    time.sleep(1)
    if server:
        server.shutdown()


if __name__ == "__main__":
    main()
