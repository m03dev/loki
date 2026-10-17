"""Data analysis in a sandbox, and SQL over spreadsheets (session 29: documents & data).

    analyze(files, question, code="", workspace=..., timeout=60, memory_mb=1536)
        -> {"ok", "finding", "stdout", "tables": [markdown], "charts": [workspace paths], "run_dir", "error"}
    sql(query, files, workspace=...) -> {"ok", "columns", "rows", "markdown", "engine", "error"}

`analyze` runs pandas (+ matplotlib for charts) in a CHILD Python process:
  - no network: an audit hook (sys.addaudithook - code cannot remove it) refuses every socket connect /
    getaddrinfo, subprocess, os.system/exec/spawn/fork and ctypes; proxies are unset;
  - writes only inside its run folder (workspace/analysis/<stamp>/) and the temp folder (the same hook
    refuses any open() for writing elsewhere, and os.remove/rename/rmdir outside it);
  - a time limit (killed with its process group) and a memory limit (RLIMIT_AS on Linux, and on every OS a
    watchdog that reads the child's resident memory and kills it over the limit);
  - only the few environment variables Python needs (no keys).
Without `code` it profiles the data itself (shape, types, missing values, statistics, top categories, the
strongest correlation, a trend over a date column) and draws up to four charts; with `code` (written by the
model) `df` / `dfs` are already loaded and `chart(name)` saves the current matplotlib figure, `show(df)` prints
a table. Without pandas (the data-analysis add-on) a standard-library profile still answers, without charts.

`sql` uses DuckDB when the data-analysis add-on installed it (tables loaded, then external access switched off
and the configuration locked before the query runs), else SQLite in memory (query_only). Both: one read-only
statement (SELECT / WITH), a row cap, a time limit. Standard library only at import time.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

MARK = "\n<<<LOKI-DATA-RESULT>>>\n"
DEFAULT_TIMEOUT = int(os.getenv("LOKI_DATA_TIMEOUT", "90"))
DEFAULT_MEMORY_MB = int(os.getenv("LOKI_DATA_MEMORY_MB", "1536"))
MAX_ROWS_OUT = 200
DATA_SUFFIXES = {".csv", ".tsv", ".tab", ".xlsx", ".xlsm", ".xls", ".json", ".jsonl", ".parquet"}


def has_pandas() -> bool:
    import importlib.util  # pylint: disable=import-outside-toplevel
    return importlib.util.find_spec("pandas") is not None


def has_duckdb() -> bool:
    import importlib.util  # pylint: disable=import-outside-toplevel
    return importlib.util.find_spec("duckdb") is not None


def sandbox_env(run_dir: Path) -> dict:
    keep = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL", "COMSPEC", "PATHEXT", "HOME",
            "USERPROFILE", "LOCALAPPDATA", "APPDATA")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env.update(PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", MPLBACKEND="Agg",
               MPLCONFIGDIR=str(run_dir / ".mpl"), OPENBLAS_NUM_THREADS="2", OMP_NUM_THREADS="2",
               NO_PROXY="*", no_proxy="*")
    tmp = run_dir / ".tmp"
    if tmp.is_dir():
        env["TMPDIR"] = env["TEMP"] = env["TMP"] = str(tmp)
    return env


# The child: an audit hook first, then the data, then the analysis. Runs with `python -I -c` (no user
# site-packages, no current folder on sys.path).
CHILD = r'''
import json, os, sys, io, re, math, traceback
ARGS = json.loads(sys.stdin.read())
RUN = os.path.realpath(ARGS["run_dir"])
ALLOWED = [RUN, os.path.realpath(ARGS["tmp"])] + [os.path.realpath(p) for p in ARGS.get("write_ok", [])]
MARK = ARGS["mark"]

def _inside(path):
    try:
        p = os.path.realpath(os.fsdecode(path))
    except Exception:
        return False
    return any(p == a or p.startswith(a + os.sep) for a in ALLOWED)

def _hook(event, args):
    if event in ("socket.connect", "socket.getaddrinfo", "socket.gethostbyname", "socket.bind", "socket.sendto",
                 "subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork", "os.forkpty",
                 "ctypes.dlopen", "ctypes.cdata", "webbrowser.open", "os.startfile", "winreg.OpenKey"):
        raise PermissionError("blocked in LOKI's data sandbox: " + event)
    if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
        mode = args[1] if len(args) > 1 and isinstance(args[1], str) else "r"
        flags = args[2] if len(args) > 2 and isinstance(args[2], int) else 0
        writing = any(c in mode for c in "wax+") or (flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND))
        if writing and not _inside(args[0]):
            raise PermissionError("the data sandbox only writes in its run folder: " + os.fsdecode(args[0]))
    if event in ("os.remove", "os.rename", "os.rmdir", "os.mkdir", "shutil.rmtree", "os.chmod", "os.symlink", "os.link"):
        if args and isinstance(args[0], (str, bytes, os.PathLike)) and not _inside(args[0]):
            raise PermissionError("the data sandbox only changes files in its run folder")
# The data libraries load first (on Windows/macOS their imports may load DLLs through ctypes); the hook then
# guards everything the analysis itself does.
for _m in ("numpy", "pandas", "matplotlib", "matplotlib.pyplot"):
    try:
        if _m.startswith("matplotlib"):
            import matplotlib
            matplotlib.use("Agg")
        __import__(_m)
    except Exception:
        pass
sys.addaudithook(_hook)

out = {"ok": False, "finding": "", "tables": [], "charts": [], "error": "", "facts": {}}
CHARTS = []

def show(obj, rows=40):
    try:
        import pandas as pd
        if isinstance(obj, pd.Series):
            obj = obj.to_frame()
        if isinstance(obj, pd.DataFrame):
            frame = obj.head(rows)
            text = _md(frame)
            out["tables"].append(text)
            print(text)
            return
    except ImportError:
        pass
    print(obj)

def _md(frame):
    cols = [str(c) for c in ([frame.index.name or ""] + list(frame.columns))]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for idx, row in frame.iterrows():
        vals = [idx] + list(row.values)
        lines.append("| " + " | ".join(_fmt(v) for v in vals) + " |")
    return "\n".join(lines)

def _fmt(v):
    try:
        if isinstance(v, float):
            if math.isnan(v):
                return ""
            return ("%.4g" % v) if abs(v) < 1e6 else ("{:,.0f}".format(v))
    except Exception:
        pass
    return str(v).replace("|", "\\|").replace("\n", " ")

def chart(name="chart", fig=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", str(name)).strip("_") or "chart"
    path = os.path.join(RUN, safe + ".png")
    n = 2
    while os.path.exists(path):
        path = os.path.join(RUN, "%s_%d.png" % (safe, n)); n += 1
    (fig or plt.gcf()).tight_layout()
    (fig or plt.gcf()).savefig(path, dpi=130)
    plt.close(fig or plt.gcf())
    CHARTS.append(path)
    return path

def _load(path, sheet=None):
    import pandas as pd
    s = os.path.splitext(path)[1].lower()
    if s in (".csv", ".tsv", ".tab"):
        try:
            return pd.read_csv(path, sep=None, engine="python")
        except Exception:
            return pd.read_csv(path, sep="\t" if s != ".csv" else ",", encoding_errors="replace")
    if s in (".xlsx", ".xlsm", ".xls"):
        return pd.read_excel(path, sheet_name=sheet if sheet else 0)
    if s == ".json":
        try:
            return pd.read_json(path)
        except ValueError:
            return pd.read_json(path, lines=True)
    if s == ".jsonl":
        return pd.read_json(path, lines=True)
    if s == ".parquet":
        return pd.read_parquet(path)
    raise ValueError("cannot load " + s)

def _style():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"figure.figsize": (7.5, 4.2), "axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "grid.alpha": 0.25, "axes.titleweight": "bold", "font.size": 10,
                         "axes.prop_cycle": matplotlib.cycler(color=["#3b6fd4", "#e0803a", "#3a9e6f", "#c24a6a", "#7a5cc4", "#5a6b7d"])})
    return plt

def _profile(df, name, charts=True):
    import pandas as pd
    facts, lines = {}, []
    facts["rows"], facts["columns"] = int(df.shape[0]), int(df.shape[1])
    lines.append("%s: %d rows x %d columns." % (name, df.shape[0], df.shape[1]))
    # parse date-looking text columns
    def _texty(c):   # text only (an Excel column can mix text, numbers and dates: not a category)
        if pd.api.types.is_string_dtype(df[c]) and df[c].dtype != object:
            return True
        return df[c].dtype == object and bool(df[c].dropna().map(lambda v: isinstance(v, str)).all())
    for c in df.columns:
        if _texty(c) and df[c].notna().any():
            sample = df[c].dropna().astype(str).head(50)
            if sample.str.match(r"^\d{4}-\d{1,2}-\d{1,2}|^\d{1,2}/\d{1,2}/\d{2,4}").mean() > 0.8:
                try:
                    df[c] = pd.to_datetime(df[c], errors="coerce")
                except Exception:
                    pass
    num = df.select_dtypes("number")
    dates = [c for c in df.columns if str(df[c].dtype).startswith("datetime")]
    cats = [c for c in df.columns if _texty(c) and 1 < df[c].nunique() <= max(30, len(df) // 20)]
    missing = df.isna().sum()
    miss = missing[missing > 0]
    if len(miss):
        lines.append("Missing values: " + ", ".join("%s %d (%.0f%%)" % (c, v, 100.0 * v / max(1, len(df))) for c, v in miss.head(8).items()) + ".")
    else:
        lines.append("No missing values.")
    if not num.empty:
        desc = num.describe().T[["mean", "min", "max"]]
        totals = num.sum(numeric_only=True)
        out["tables"].append(_md(num.describe().T.round(3)))
        for c in list(num.columns)[:6]:
            lines.append("%s: total %s, mean %s, range %s to %s." % (c, _fmt(float(totals[c])), _fmt(float(desc.loc[c, "mean"])),
                                                                     _fmt(float(desc.loc[c, "min"])), _fmt(float(desc.loc[c, "max"]))))
        if num.shape[1] >= 2:
            corr = num.corr(numeric_only=True)
            best, pair = 0.0, None
            for i, a in enumerate(corr.columns):
                for b in corr.columns[i + 1:]:
                    v = corr.loc[a, b]
                    if v == v and abs(v) > abs(best):
                        best, pair = float(v), (a, b)
            if pair and abs(best) >= 0.5:
                lines.append("Strongest link: %s and %s move %s (r = %.2f)." % (pair[0], pair[1], "together" if best > 0 else "in opposite directions", best))
                facts["correlation"] = [pair[0], pair[1], round(best, 3)]
    for c in cats[:2]:
        try:
            top = df[c].value_counts().head(5)
            lines.append("Most common %s: %s." % (c, ", ".join("%s (%d)" % (k, v) for k, v in top.items())))
            if not num.empty:
                val = num.columns[0]
                grp = df.groupby(c)[val].sum().sort_values(ascending=False)
                lines.append("Largest %s by %s: %s (%s of %s total)." % (val, c, grp.index[0], _fmt(float(grp.iloc[0])), _fmt(float(grp.sum()))))
                facts.setdefault("top_group", [c, str(grp.index[0]), float(grp.iloc[0])])
        except Exception as exc:   # one odd column never stops the profile
            lines.append("(%s: %s)" % (c, type(exc).__name__))
    if dates and not num.empty:
        try:
            d, val = dates[0], num.columns[0]
            series = df[[d, val]].dropna().sort_values(d)
            if len(series) >= 3:
                first, last = float(series[val].iloc[0]), float(series[val].iloc[-1])
                change = (last - first) / abs(first) * 100 if first else 0.0
                lines.append("%s from %s to %s: %s -> %s (%+.0f%%)." % (val, series[d].iloc[0].date(), series[d].iloc[-1].date(), _fmt(first), _fmt(last), change))
                facts["trend"] = [val, round(change, 1)]
        except Exception:
            dates = []
    if charts:
        try:
            plt = _style()
            made = 0
            if dates and not num.empty:
                d = dates[0]
                s = df[[d] + list(num.columns[:3])].dropna(subset=[d]).sort_values(d).set_index(d)
                ax = s.plot(marker="o" if len(s) < 40 else None)
                ax.set_title("%s over time" % ", ".join(map(str, num.columns[:3]))); ax.set_xlabel("")
                chart("%s_trend" % name); made += 1
            if cats and not num.empty:
                c, val = cats[0], num.columns[0]
                g = df.groupby(c)[val].sum().sort_values(ascending=False).head(12)
                ax = g.plot(kind="barh"); ax.invert_yaxis(); ax.set_title("%s by %s" % (val, c)); ax.set_ylabel("")
                chart("%s_%s_by_%s" % (name, val, c)); made += 1
            for col in list(num.columns)[:max(0, 2 - made) + 1]:
                if made >= 4:
                    break
                ax = num[col].dropna().plot(kind="hist", bins=min(30, max(5, int(len(num) ** 0.5))))
                ax.set_title("Distribution of %s" % col)
                chart("%s_%s_hist" % (name, col)); made += 1
        except ImportError:
            lines.append("(Charts need matplotlib - the data-analysis add-on.)")
        except Exception as exc:   # a chart that cannot be drawn is skipped, the finding stays
            lines.append("(a chart could not be drawn: %s)" % type(exc).__name__)
    return lines, facts

try:
    import pandas as pd
    pd.set_option("display.width", 160)
    dfs = {}
    for f in ARGS["files"]:
        key = re.sub(r"[^A-Za-z0-9_]+", "_", os.path.splitext(os.path.basename(f))[0]).strip("_") or "data"
        dfs[key] = _load(f, ARGS.get("sheet") or None)
    df = next(iter(dfs.values())) if dfs else None
    if ARGS.get("code"):
        ns = {"pd": pd, "df": df, "dfs": dfs, "show": show, "chart": chart, "RUN_DIR": RUN, "__name__": "__loki__"}
        try:
            import numpy as np
            ns["np"] = np
        except ImportError:
            pass
        try:
            ns["plt"] = _style()
        except ImportError:
            pass
        exec(compile(ARGS["code"], "<analysis>", "exec"), ns)
        if ns.get("finding"):
            out["finding"] = str(ns["finding"])
    else:
        found = []
        for key, frame in dfs.items():
            lines, facts = _profile(frame, key, charts=ARGS.get("charts", True))
            found += lines
            out["facts"][key] = facts
        out["finding"] = "\n".join(found)
    out["ok"] = True
except BaseException as exc:
    if isinstance(exc, SystemExit) and not exc.code:
        out["ok"] = True
    else:
        tb = traceback.format_exc().strip().splitlines()
        out["error"] = (tb[-1] if tb else repr(exc))[:600]
        out["trace"] = "\n".join(tb[-6:])[:1500]
out["charts"] = CHARTS
sys.stdout.flush()
sys.stdout.write(MARK + json.dumps(out, default=str))
'''


def _rss_mb(pid: int) -> float:
    """Resident memory of a process in MB (0 when unknown)."""
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/%d/status" % pid, encoding="ascii", errors="replace") as fh:
                for line in fh:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1]) / 1024.0
        elif sys.platform == "darwin":
            out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True, timeout=5)
            return int((out.stdout or "0").strip() or 0) / 1024.0
        elif sys.platform == "win32":
            import ctypes  # pylint: disable=import-outside-toplevel
            from ctypes import wintypes  # pylint: disable=import-outside-toplevel

            class PMC(ctypes.Structure):  # PROCESS_MEMORY_COUNTERS
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.OpenProcess.restype = wintypes.HANDLE
            handle = k32.OpenProcess(0x1000 | 0x0010, False, pid)   # QUERY_LIMITED_INFORMATION | VM_READ
            if not handle:
                return 0.0
            try:
                pmc = PMC()
                pmc.cb = ctypes.sizeof(PMC)
                if k32.K32GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb):
                    return max(pmc.WorkingSetSize, pmc.PagefileUsage) / 1048576.0
            finally:
                k32.CloseHandle(handle)
    except (OSError, ValueError, subprocess.SubprocessError, AttributeError):
        return 0.0
    return 0.0


def _limits(memory_mb: int):
    if sys.platform.startswith("linux"):
        def apply():   # runs in the child before Python starts
            import resource  # pylint: disable=import-outside-toplevel
            try:
                limit = int(memory_mb) * 1048576 * 2   # address space is larger than RSS (thread stacks, mmaps)
                resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
            except (ValueError, OSError):
                pass
        return apply
    return None


def run_child(args: dict, cwd: Path, timeout: int, memory_mb: int, python: str = "") -> tuple:
    """(returncode or None, stdout, stderr, why_killed)"""
    run_dir = Path(args["run_dir"])
    argv = [python or sys.executable, "-I", "-c", CHILD]
    kwargs: dict = {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "cwd": str(cwd),
                    "env": sandbox_env(run_dir)}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
        pre = _limits(memory_mb)
        if pre is not None:
            kwargs["preexec_fn"] = pre
    proc = subprocess.Popen(argv, **kwargs)   # no shell
    killed = {"why": ""}

    def watch():
        while proc.poll() is None:
            if _rss_mb(proc.pid) > memory_mb:
                killed["why"] = "memory"
                _kill(proc)
                return
            time.sleep(0.25)
    threading.Thread(target=watch, daemon=True).start()
    try:
        out, err = proc.communicate(json.dumps(args).encode("utf-8"), timeout=timeout)
    except subprocess.TimeoutExpired:
        killed["why"] = "time"
        _kill(proc)
        out, err = proc.communicate()
    return proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"), killed["why"]


def _kill(proc) -> None:
    try:
        if sys.platform == "win32":
            proc.kill()
        else:
            import signal  # pylint: disable=import-outside-toplevel
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        try:
            proc.kill()
        except OSError:
            pass


def _run_folder(workspace: Path, out_dir: str = "analysis") -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = Path(workspace) / (out_dir or "analysis")
    folder = base / stamp
    n = 2
    while folder.exists():
        folder = base / ("%s-%d" % (stamp, n))
        n += 1
    folder.mkdir(parents=True, exist_ok=True)
    (folder / ".mpl").mkdir(exist_ok=True)
    return folder


def analyze(files: list, question: str = "", code: str = "", workspace: Path | None = None, sheet: str = "",
            timeout: int = 0, memory_mb: int = 0, charts: bool = True, out_dir: str = "analysis", python: str = "") -> dict:
    workspace = Path(workspace or os.getcwd())
    files = [str(Path(f).resolve()) for f in files or []]
    missing = [f for f in files if not Path(f).is_file()]
    if missing:
        return {"ok": False, "error": "no such file: %s" % ", ".join(Path(m).name for m in missing)}
    if not has_pandas():
        if code:
            return {"ok": False, "error": "running analysis code needs pandas - install the data-analysis add-on "
                                          "(Settings > Add-ons > data-analysis). Without it LOKI can still profile the "
                                          "data (no code) and answer SQL questions (data_sql)."}
        return profile_stdlib(files, workspace)
    run_dir = _run_folder(workspace, out_dir)
    tmp = run_dir / ".tmp"          # the child's own temp folder (TMPDIR points here); removed afterwards
    tmp.mkdir(exist_ok=True)
    args = {"files": files, "code": code or "", "question": question or "", "sheet": sheet or "", "run_dir": str(run_dir),
            "tmp": str(tmp), "mark": MARK, "charts": bool(charts)}
    started = time.monotonic()
    code_rc, out, err, why = run_child(args, workspace, int(timeout or DEFAULT_TIMEOUT), int(memory_mb or DEFAULT_MEMORY_MB), python)
    result = {"ok": False, "finding": "", "stdout": "", "tables": [], "charts": [], "run_dir": _rel(run_dir, workspace),
              "seconds": round(time.monotonic() - started, 2), "error": ""}
    if MARK in out:
        printed, raw = out.split(MARK, 1)
        try:
            got = json.loads(raw)
        except ValueError:
            got = {"error": "the analysis printed something LOKI could not read"}
        result.update({k: v for k, v in got.items() if k in ("ok", "finding", "tables", "error", "trace", "facts")})
        result["charts"] = [_rel(Path(c), workspace) for c in got.get("charts") or []]
        result["stdout"] = printed.strip()[-6000:]
    else:
        result["stdout"] = out.strip()[-3000:]
        if why == "time":
            result["error"] = "the analysis ran longer than %ss and was stopped" % int(timeout or DEFAULT_TIMEOUT)
        elif why == "memory" or "MemoryError" in err:
            result["error"] = "the analysis used more than %d MB of memory and was stopped" % int(memory_mb or DEFAULT_MEMORY_MB)
        else:
            lines = [ln for ln in err.strip().splitlines() if ln.strip()]
            result["error"] = (lines[-1] if lines else "the analysis process ended (exit %s)" % code_rc)[:600]
    shutil.rmtree(run_dir / ".mpl", ignore_errors=True)
    shutil.rmtree(run_dir / ".tmp", ignore_errors=True)
    try:   # nothing made: no empty folder left behind
        if not any(run_dir.iterdir()):
            run_dir.rmdir()
            result["run_dir"] = ""
    except OSError:
        pass
    return result


def _rel(path: Path, workspace: Path) -> str:
    try:
        return Path(path).resolve().relative_to(Path(workspace).resolve()).as_posix()
    except ValueError:
        return str(path)


# --------------------------------------------------------------------------- without pandas
def load_rows(path: Path, sheet: str = "") -> tuple:
    """(columns, rows) with the standard library: CSV/TSV, XLSX (doc_read), JSON (a list of objects)."""
    import doc_read  # pylint: disable=import-outside-toplevel
    path = Path(path)
    s = path.suffix.lower()
    if s in (".csv", ".tsv", ".tab"):
        rows, _total, _d = doc_read.csv_rows(path)
    elif s in (".xlsx", ".xlsm"):
        sheets = doc_read.xlsx_tables(path)
        chosen = next((x for x in sheets if x["name"] == sheet), sheets[0] if sheets else {"rows": []})
        rows = chosen["rows"]
    elif s in (".json", ".jsonl"):
        text = doc_read.read_text_file(path)
        try:
            data = json.loads(text)
        except ValueError:
            data = [json.loads(ln) for ln in text.splitlines() if ln.strip()]
        if isinstance(data, dict):
            data = next((v for v in data.values() if isinstance(v, list)), [data])
        cols = []
        for item in data:
            for k in (item.keys() if isinstance(item, dict) else []):
                if k not in cols:
                    cols.append(k)
        return cols, [[(item.get(c) if isinstance(item, dict) else None) for c in cols] for item in data]
    else:
        raise ValueError("cannot read %s without the data-analysis add-on" % s)
    if not rows:
        return [], []
    header = [str(c).strip() or "col%d" % (i + 1) for i, c in enumerate(rows[0])]
    return header, [r + [""] * (len(header) - len(r)) for r in rows[1:]]


def _num(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    s = str(v or "").strip().replace(",", "")
    s = s[1:] if s[:1] in "$€£" else s
    try:
        return float(s.rstrip("%"))
    except ValueError:
        return None


def profile_stdlib(files: list, workspace: Path) -> dict:
    import statistics  # pylint: disable=import-outside-toplevel
    import doc_read  # pylint: disable=import-outside-toplevel
    lines, tables = [], []
    for f in files:
        try:
            cols, rows = load_rows(Path(f))
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        name = Path(f).stem
        lines.append("%s: %d rows x %d columns." % (name, len(rows), len(cols)))
        stats = [["column", "kind", "filled", "total", "mean", "min", "max"]]
        for i, c in enumerate(cols):
            vals = [r[i] for r in rows if i < len(r) and str(r[i]).strip() != ""]
            nums = [x for x in (_num(v) for v in vals) if x is not None]
            if vals and len(nums) >= 0.9 * len(vals):
                stats.append([c, "number", len(vals), "%g" % sum(nums), "%.4g" % statistics.fmean(nums), "%g" % min(nums), "%g" % max(nums)])
                lines.append("%s: total %g, mean %.4g, range %g to %g." % (c, sum(nums), statistics.fmean(nums), min(nums), max(nums)))
            else:
                counts: dict = {}
                for v in vals:
                    counts[str(v)] = counts.get(str(v), 0) + 1
                top = sorted(counts.items(), key=lambda kv: -kv[1])[:3]
                stats.append([c, "text", len(vals), "", "", "", ""])
                if top and len(counts) < max(30, len(rows) // 2):
                    lines.append("Most common %s: %s." % (c, ", ".join("%s (%d)" % kv for kv in top)))
        tables.append(doc_read.md_table(stats))
    return {"ok": True, "finding": "\n".join(lines), "tables": tables, "charts": [], "stdout": "", "run_dir": "",
            "engine": "standard library", "note": "install the data-analysis add-on (pandas, matplotlib) for charts and custom analysis"}


# --------------------------------------------------------------------------- SQL
_READ_ONLY = re.compile(r"^\s*(select|with)\b", re.I)
_FORBIDDEN = re.compile(r"\b(attach|detach|pragma|insert|update|delete|drop|alter|create|replace|copy|export|import|"
                        r"install|load|set|call|vacuum|checkpoint|load_extension|readfile|writefile|edit|"
                        r"read_text|read_blob|read_csv|read_csv_auto|read_json|read_json_auto|read_parquet|glob|"
                        r"sniff_csv|getenv)\b", re.I)


def table_name(path: Path, used: set) -> str:
    base = re.sub(r"[^a-z0-9_]+", "_", Path(path).stem.lower()).strip("_") or "data"
    if base[0].isdigit():
        base = "t_" + base
    name, n = base, 2
    while name in used:
        name = "%s_%d" % (base, n)
        n += 1
    used.add(name)
    return name


def _check_query(query: str) -> str:
    q = str(query or "").strip().rstrip(";").strip()
    if not q:
        return "give a SQL query (SELECT ...)"
    if ";" in q.replace("';'", ""):
        return "one statement only"
    if not _READ_ONLY.match(q):
        return "only read-only queries (SELECT or WITH ...)"
    stripped = re.sub(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"", "''", q)
    bad = _FORBIDDEN.search(stripped)
    if bad:
        return "%s is not allowed - read-only queries only" % bad.group(1).upper()
    return ""


def sql(query: str, files: list, workspace: Path | None = None, limit: int = MAX_ROWS_OUT, timeout: float = 30.0,
        engine: str = "auto") -> dict:
    """Run one read-only SQL query over CSV/XLSX/JSON files; each file is a table named after it."""
    import doc_read  # pylint: disable=import-outside-toplevel
    why = _check_query(query)
    if why:
        return {"ok": False, "error": why}
    paths = [Path(f) for f in files or []]
    missing = [p.name for p in paths if not p.is_file()]
    if missing or not paths:
        return {"ok": False, "error": "no such file: %s" % ", ".join(missing) if missing else "give the data files"}
    used: set = set()
    names = {table_name(p, used): p for p in paths}
    q = str(query).strip().rstrip(";")
    use_duck = engine in ("auto", "duckdb") and has_duckdb()
    if engine == "duckdb" and not use_duck:
        return {"ok": False, "error": "DuckDB is not installed (the data-analysis add-on)"}
    try:
        if use_duck:
            cols, rows, total = _sql_duckdb(q, names, limit, timeout)
            used_engine = "duckdb"
        else:
            cols, rows, total = _sql_sqlite(q, names, limit, timeout)
            used_engine = "sqlite"
    except Exception as exc:  # noqa: BLE001 - the error goes back to the model to fix its query
        return {"ok": False, "error": "%s: %s" % (type(exc).__name__, str(exc)[:400]), "tables": sorted(names)}
    md = doc_read.md_table([cols] + [list(r) for r in rows])
    if total > len(rows):
        md += "\n\n(%d rows - the first %d are shown)" % (total, len(rows))
    return {"ok": True, "columns": cols, "rows": [list(r) for r in rows], "total": total, "markdown": md,
            "engine": used_engine, "tables": sorted(names)}


def _sql_sqlite(query: str, names: dict, limit: int, timeout: float) -> tuple:
    con = sqlite3.connect(":memory:")
    try:
        for name, path in names.items():
            cols, rows = load_rows(path)
            cols = _unique_cols(cols)
            kinds = []
            for i in range(len(cols)):
                vals = [r[i] for r in rows if i < len(r) and str(r[i]).strip() != ""]
                nums = [_num(v) for v in vals]
                numeric = bool(vals) and all(n is not None for n in nums)
                kinds.append(("INTEGER" if all(float(n).is_integer() for n in nums) else "REAL") if numeric else "TEXT")
            con.execute("CREATE TABLE \"%s\" (%s)" % (name, ", ".join('"%s" %s' % (c.replace('"', '""'), k) for c, k in zip(cols, kinds))))
            conv = [(lambda v, k=k: (None if v is None or str(v).strip() == "" else
                                     (int(_num(v)) if k == "INTEGER" else _num(v)) if k != "TEXT" else str(v))) for k in kinds]
            con.executemany("INSERT INTO \"%s\" VALUES (%s)" % (name, ", ".join("?" * len(cols))),
                            [[conv[i](r[i] if i < len(r) else None) for i in range(len(cols))] for r in rows])
        con.execute("PRAGMA query_only = ON")
        deadline = time.monotonic() + timeout
        con.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
        cur = con.execute(query)
        cols = [d[0] for d in cur.description or []]
        rows = cur.fetchmany(limit + 1)
        total = len(rows)
        if total > limit:
            total += len(cur.fetchall())
        return cols, rows[:limit], total
    finally:
        con.close()


def _unique_cols(cols: list) -> list:
    out, seen = [], set()
    for c in cols:
        base = str(c).strip() or "col"
        name, n = base, 2
        while name.lower() in seen:
            name = "%s_%d" % (base, n)
            n += 1
        seen.add(name.lower())
        out.append(name)
    return out


def _sql_duckdb(query: str, names: dict, limit: int, timeout: float) -> tuple:
    import duckdb  # type: ignore # pylint: disable=import-outside-toplevel
    con = duckdb.connect(":memory:")
    try:
        for name, path in names.items():
            s = path.suffix.lower()
            p = str(path).replace("'", "''")
            if s in (".csv", ".tsv", ".tab"):
                con.execute("CREATE TABLE \"%s\" AS SELECT * FROM read_csv_auto('%s')" % (name, p))
            elif s == ".parquet":
                con.execute("CREATE TABLE \"%s\" AS SELECT * FROM read_parquet('%s')" % (name, p))
            elif s in (".json", ".jsonl"):
                con.execute("CREATE TABLE \"%s\" AS SELECT * FROM read_json_auto('%s')" % (name, p))
            else:   # xlsx and the rest: through the standard-library loader
                cols, rows = load_rows(path)
                cols = _unique_cols(cols)
                con.execute("CREATE TABLE \"%s\" (%s)" % (name, ", ".join('"%s" VARCHAR' % c.replace('"', '""') for c in cols)))
                if rows:
                    con.executemany("INSERT INTO \"%s\" VALUES (%s)" % (name, ", ".join("?" * len(cols))),
                                    [[None if v in ("", None) else str(v) for v in r[:len(cols)]] for r in rows])
        con.execute("SET enable_external_access = false")
        con.execute("SET lock_configuration = true")
        timer = threading.Timer(timeout, con.interrupt)
        timer.start()
        try:
            cur = con.execute(query)
            cols = [d[0] for d in cur.description or []]
            rows = cur.fetchmany(limit + 1)
            total = len(rows)
            if total > limit:
                total += len(cur.fetchall())
        finally:
            timer.cancel()
        return cols, rows[:limit], total
    finally:
        con.close()
