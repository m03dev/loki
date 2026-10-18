"""Write a file so it is never seen half-written, and two writers never collide.

The plain `tmp = path.with_suffix(".tmp"); os.replace(tmp, path)` pattern crashes when the same
file is written from two threads at once (a background refresh and a foreground one): both use
the SAME temp name, the first `os.replace` consumes it and the second fails with
`FileNotFoundError`. `write_text`/`write_json` use a unique temp per writer instead.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def write_text(path: Path, text: str, encoding: str = "utf-8") -> Path:
    """Replace `path` with `text` atomically. Any error removes the temp file and re-raises."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    except BaseException:
        try:
            os.unlink(name)
        except OSError:
            pass
        raise
    return path


def write_json(path: Path, data, **kwargs) -> Path:
    """write_text() of `json.dumps(data, ensure_ascii=False, **kwargs)`."""
    return write_text(path, json.dumps(data, ensure_ascii=False, **kwargs))
