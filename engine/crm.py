"""LOKI's built-in CRM: contacts, companies, deals, interactions and tasks in one SQLite file.

The database lives in LOKI's data folder (harness_data/crm.sqlite3, or $LOKI_DATA), never
in the repo. Standard library only (sqlite3), so it works the same on macOS and Windows.

    store = CRM(DATA_DIR / "crm.sqlite3")
    cid = store.add("companies", {"name": "Acme"})["id"]
    store.add("contacts", {"name": "Ada", "email": "ada@acme.test", "company_id": cid})
    store.add("deals", {"title": "Pilot", "company_id": cid, "stage": "proposal", "value": 5000})
    store.log({"contact_id": 1, "kind": "call", "summary": "intro call"})
    store.pipeline()      # deals per stage, open value, won/lost, overdue tasks

Every public function takes plain dicts and returns plain dicts, so the agent tools
(loki.crm_*), the bridge (GET /crm, POST /crm/<op>) and the tests share one code path.
"""
from __future__ import annotations

import contextlib
import sqlite3
import threading
import time
from pathlib import Path

STAGES = ("lead", "qualified", "proposal", "negotiation", "won", "lost")
OPEN_STAGES = ("lead", "qualified", "proposal", "negotiation")
INTERACTION_KINDS = ("note", "call", "email", "meeting", "message")

# table -> (columns the caller may set, the column that names a row)
TABLES: dict[str, tuple[tuple[str, ...], str]] = {
    "companies": (("name", "website", "industry", "notes"), "name"),
    "contacts": (("name", "email", "phone", "title", "company_id", "notes", "tags"), "name"),
    "deals": (("title", "company_id", "contact_id", "stage", "value", "currency", "close_date", "notes"), "title"),
    "interactions": (("contact_id", "company_id", "deal_id", "kind", "summary", "at"), "summary"),
    "tasks": (("title", "due", "done", "contact_id", "company_id", "deal_id", "notes"), "title"),
}
ALIASES = {"company": "companies", "contact": "contacts", "deal": "deals", "interaction": "interactions",
           "note": "interactions", "task": "tasks", "people": "contacts", "person": "contacts"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (id INTEGER PRIMARY KEY, name TEXT NOT NULL, website TEXT DEFAULT '',
    industry TEXT DEFAULT '', notes TEXT DEFAULT '', created TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS contacts (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT DEFAULT '',
    phone TEXT DEFAULT '', title TEXT DEFAULT '', company_id INTEGER REFERENCES companies(id) ON DELETE SET NULL,
    notes TEXT DEFAULT '', tags TEXT DEFAULT '', created TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS deals (id INTEGER PRIMARY KEY, title TEXT NOT NULL,
    company_id INTEGER REFERENCES companies(id) ON DELETE SET NULL,
    contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL, stage TEXT DEFAULT 'lead',
    value REAL DEFAULT 0, currency TEXT DEFAULT 'USD', close_date TEXT DEFAULT '', notes TEXT DEFAULT '',
    created TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS interactions (id INTEGER PRIMARY KEY,
    contact_id INTEGER REFERENCES contacts(id) ON DELETE CASCADE,
    company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
    deal_id INTEGER REFERENCES deals(id) ON DELETE CASCADE, kind TEXT DEFAULT 'note', summary TEXT NOT NULL,
    at TEXT, created TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY, title TEXT NOT NULL, due TEXT DEFAULT '',
    done INTEGER DEFAULT 0, contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    company_id INTEGER REFERENCES companies(id) ON DELETE SET NULL,
    deal_id INTEGER REFERENCES deals(id) ON DELETE SET NULL, notes TEXT DEFAULT '', created TEXT, updated TEXT);
"""
MAX_TEXT = 4000
MAX_LIST = 500


class CRMError(ValueError):
    """A readable reason a CRM request cannot be done."""


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def table_name(kind: str) -> str:
    key = str(kind or "").strip().lower()
    key = ALIASES.get(key, key)
    if key not in TABLES:
        raise CRMError("unknown CRM record type %r (use: %s)" % (kind, ", ".join(TABLES)))
    return key


def _clean(table: str, fields: dict, creating: bool) -> dict:
    allowed, label = TABLES[table]
    out: dict = {}
    for key, value in (fields or {}).items():
        if key not in allowed:
            continue
        if key.endswith("_id"):
            if value in (None, "", 0, "0"):
                out[key] = None
                continue
            try:
                out[key] = int(value)
            except (TypeError, ValueError):
                raise CRMError("%s must be a record id (a number)" % key) from None
        elif key == "value":
            try:
                out[key] = float(value or 0)
            except (TypeError, ValueError):
                raise CRMError("value must be a number") from None
        elif key == "done":
            out[key] = 1 if str(value).strip().lower() in ("1", "true", "yes", "done", "on") or value is True else 0
        else:
            out[key] = str(value if value is not None else "").strip()[:MAX_TEXT]
    if "stage" in out:
        out["stage"] = out["stage"].lower() or "lead"
        if out["stage"] not in STAGES:
            raise CRMError("stage must be one of " + ", ".join(STAGES))
    if "kind" in out:
        out["kind"] = out["kind"].lower() or "note"
        if out["kind"] not in INTERACTION_KINDS:
            raise CRMError("kind must be one of " + ", ".join(INTERACTION_KINDS))
    if "currency" in out:
        out["currency"] = (out["currency"] or "USD").upper()[:8]
    if creating and not str(out.get(label) or "").strip():
        raise CRMError("a %s needs a %s" % (table[:-1] if table != "companies" else "company", label))
    if not creating and label in out and not str(out[label]).strip():
        raise CRMError("%s cannot be empty" % label)
    return out


class CRM:
    """One SQLite file. Thread-safe (one connection per call, a lock around writes)."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(SCHEMA)

    @contextlib.contextmanager
    def _connect(self):
        """A connection that commits on success and is always CLOSED (Windows keeps an open
        SQLite file locked, so a lingering connection would block deleting the data folder)."""
        db = sqlite3.connect(str(self.path), timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ------------------------------------------------------------- CRUD
    def add(self, kind: str, fields: dict) -> dict:
        table = table_name(kind)
        row = _clean(table, fields, creating=True)
        if table == "interactions":
            row.setdefault("kind", "note")
            row["at"] = row.get("at") or _now()
        if table == "deals":
            row.setdefault("stage", "lead")
            row.setdefault("currency", "USD")
        row["created"] = row["updated"] = _now()
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        with self.lock, self._connect() as db:
            try:
                cur = db.execute("INSERT INTO %s (%s) VALUES (%s)" % (table, cols, marks), list(row.values()))
            except sqlite3.IntegrityError as exc:
                raise CRMError("that refers to a record that does not exist (%s)" % exc) from None
            new_id = cur.lastrowid
        return self.get(table, new_id)

    def get(self, kind: str, record_id: int) -> dict:
        table = table_name(kind)
        with self._connect() as db:
            row = db.execute("SELECT * FROM %s WHERE id = ?" % table, (int(record_id),)).fetchone()
        if row is None:
            raise CRMError("no %s with id %s" % (table, record_id))
        return dict(row)

    def update(self, kind: str, record_id: int, fields: dict) -> dict:
        table = table_name(kind)
        row = _clean(table, fields, creating=False)
        if not row:
            raise CRMError("nothing to change (fields: %s)" % ", ".join(TABLES[table][0]))
        self.get(table, record_id)
        row["updated"] = _now()
        sets = ", ".join("%s = ?" % k for k in row)
        with self.lock, self._connect() as db:
            try:
                db.execute("UPDATE %s SET %s WHERE id = ?" % (table, sets), [*row.values(), int(record_id)])
            except sqlite3.IntegrityError as exc:
                raise CRMError("that refers to a record that does not exist (%s)" % exc) from None
        return self.get(table, record_id)

    def delete(self, kind: str, record_id: int) -> bool:
        table = table_name(kind)
        with self.lock, self._connect() as db:
            return db.execute("DELETE FROM %s WHERE id = ?" % table, (int(record_id),)).rowcount > 0

    def list(self, kind: str, limit: int = 100, stage: str = "", open_only: bool = False) -> list[dict]:
        table = table_name(kind)
        limit = max(1, min(int(limit or 100), MAX_LIST))
        where, args = [], []
        if table == "deals" and stage:
            where.append("stage = ?")
            args.append(stage.lower())
        if table == "tasks" and open_only:
            where.append("done = 0")
        order = {"interactions": "at DESC, id DESC", "tasks": "done, CASE WHEN due = '' THEN 1 ELSE 0 END, due, id",
                 "deals": "updated DESC, id DESC"}.get(table, "name COLLATE NOCASE, id")
        sql = "SELECT * FROM %s%s ORDER BY %s LIMIT ?" % (table, (" WHERE " + " AND ".join(where)) if where else "", order)
        with self._connect() as db:
            return [dict(r) for r in db.execute(sql, [*args, limit]).fetchall()]

    def find(self, query: str, kind: str = "", limit: int = 25) -> list[dict]:
        """Case-insensitive substring search over the text columns. [{type, ...row}]"""
        text = str(query or "").strip()
        if not text:
            raise CRMError("find needs some words to look for")
        tables = [table_name(kind)] if kind else list(TABLES)
        like = "%" + text.replace("%", r"\%").replace("_", r"\_") + "%"
        found: list[dict] = []
        with self._connect() as db:
            for table in tables:
                cols = [c for c in TABLES[table][0] if not c.endswith("_id") and c not in ("value", "done")]
                where = " OR ".join("%s LIKE ? ESCAPE '\\'" % c for c in cols)
                rows = db.execute("SELECT * FROM %s WHERE %s LIMIT ?" % (table, where),
                                  [like] * len(cols) + [int(limit)]).fetchall()
                found += [dict(r, type=table) for r in rows]
        return found[:int(limit)]

    def log(self, fields: dict) -> dict:
        """Record a note / call / email / meeting against a contact, company or deal."""
        if not any((fields or {}).get(k) for k in ("contact_id", "company_id", "deal_id")):
            raise CRMError("log needs contact_id, company_id or deal_id")
        return self.add("interactions", fields)

    def history(self, kind: str, record_id: int, limit: int = 50) -> list[dict]:
        table = table_name(kind)
        column = {"contacts": "contact_id", "companies": "company_id", "deals": "deal_id"}.get(table)
        if not column:
            raise CRMError("history is kept for contacts, companies and deals")
        with self._connect() as db:
            return [dict(r) for r in db.execute(
                "SELECT * FROM interactions WHERE %s = ? ORDER BY at DESC, id DESC LIMIT ?" % column,
                (int(record_id), int(limit))).fetchall()]

    # ------------------------------------------------------------- summary
    def pipeline(self, today: str = "") -> dict:
        today = today or time.strftime("%Y-%m-%d")
        with self._connect() as db:
            rows = db.execute("SELECT stage, currency, COUNT(*) AS n, COALESCE(SUM(value), 0) AS total "
                              "FROM deals GROUP BY stage, currency").fetchall()
            counts = {t: db.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] for t in TABLES}
            open_tasks = db.execute("SELECT COUNT(*) FROM tasks WHERE done = 0").fetchone()[0]
            overdue = [dict(r) for r in db.execute(
                "SELECT * FROM tasks WHERE done = 0 AND due != '' AND due < ? ORDER BY due LIMIT 20",
                (today,)).fetchall()]
        stages = {s: {"count": 0, "value": {}} for s in STAGES}
        open_value: dict = {}
        won_value: dict = {}
        for r in rows:
            stage = r["stage"] if r["stage"] in stages else "lead"
            stages[stage]["count"] += r["n"]
            stages[stage]["value"][r["currency"]] = round(stages[stage]["value"].get(r["currency"], 0) + r["total"], 2)
            bucket = open_value if stage in OPEN_STAGES else won_value if stage == "won" else None
            if bucket is not None:
                bucket[r["currency"]] = round(bucket.get(r["currency"], 0) + r["total"], 2)
        won, lost = stages["won"]["count"], stages["lost"]["count"]
        return {"stages": stages, "open_value": open_value, "won_value": won_value,
                "open_deals": sum(stages[s]["count"] for s in OPEN_STAGES),
                "win_rate": round(won / (won + lost), 3) if (won + lost) else None,
                "counts": counts, "open_tasks": open_tasks, "overdue_tasks": overdue}

    def snapshot(self, limit: int = 100) -> dict:
        """Everything the Settings > CRM panel shows, in one call (GET /crm)."""
        return {"pipeline": self.pipeline(), "stages": list(STAGES), "kinds": list(INTERACTION_KINDS),
                "companies": self.list("companies", limit), "contacts": self.list("contacts", limit),
                "deals": self.list("deals", limit), "tasks": self.list("tasks", limit, open_only=False),
                "interactions": self.list("interactions", 30)}


def _money(values: dict) -> str:
    return ", ".join("%s %s" % (cur, ("%.2f" % v).rstrip("0").rstrip(".")) for cur, v in sorted(values.items())) or "0"


def render_pipeline(p: dict) -> str:
    lines = ["CRM pipeline: %d open deal(s) worth %s; won %s; win rate %s" % (
        p["open_deals"], _money(p["open_value"]), _money(p["won_value"]),
        "n/a" if p["win_rate"] is None else "%d%%" % round(p["win_rate"] * 100))]
    for stage, info in p["stages"].items():
        if info["count"]:
            lines.append("- %s: %d (%s)" % (stage, info["count"], _money(info["value"])))
    c = p["counts"]
    lines.append("%d contacts, %d companies, %d open task(s)" % (c["contacts"], c["companies"], p["open_tasks"]))
    for t in p["overdue_tasks"]:
        lines.append("  OVERDUE #%d %s (due %s)" % (t["id"], t["title"], t["due"]))
    return "\n".join(lines)


def render_rows(rows: list[dict]) -> str:
    if not rows:
        return "(nothing found)"
    out = []
    for r in rows:
        kind = r.get("type", "")
        label = r.get("name") or r.get("title") or r.get("summary") or ""
        extra = [("%s=%s" % (k, r[k])) for k in ("email", "stage", "value", "currency", "due", "done", "kind", "at",
                                                "company_id", "contact_id", "deal_id") if r.get(k) not in (None, "", 0)]
        out.append("%s#%s %s%s" % ((kind + " ") if kind else "", r.get("id"), label, (" (" + ", ".join(extra) + ")") if extra else ""))
    return "\n".join(out)


# ------------------------------------------------------------------ bridge
def handle(store: CRM, method: str, op: str, data: dict | None = None) -> tuple[int, dict]:
    """GET /crm and POST /crm/<op>: add | update | delete | find | log | list | pipeline | history.

    data: {"type": "contacts", "id": 3, "fields": {...}, "query": "...", ...}. Pure over a CRM,
    so the tests drive it without an HTTP server."""
    data = data if isinstance(data, dict) else {}
    try:
        if method == "GET" or op in ("", "snapshot"):
            return 200, {"ok": True, **store.snapshot()}
        kind = str(data.get("type") or data.get("kind_of") or "")
        fields = data.get("fields") if isinstance(data.get("fields"), dict) else {
            k: v for k, v in data.items() if k not in ("type", "id")}
        if op == "add":
            return 200, {"ok": True, "record": store.add(kind, fields)}
        if op == "update":
            return 200, {"ok": True, "record": store.update(kind, int(data.get("id") or 0), fields)}
        if op == "delete":
            gone = store.delete(kind, int(data.get("id") or 0))
            return (200 if gone else 404), {"ok": gone, **({} if gone else {"error": "no such record"})}
        if op == "find":
            return 200, {"ok": True, "results": store.find(str(data.get("query", "")), kind)}
        if op == "log":
            return 200, {"ok": True, "record": store.log(fields)}
        if op == "list":
            return 200, {"ok": True, "records": store.list(kind, int(data.get("limit") or 100),
                                                           str(data.get("stage") or ""))}
        if op == "pipeline":
            return 200, {"ok": True, "pipeline": store.pipeline()}
        if op == "history":
            return 200, {"ok": True, "records": store.history(kind, int(data.get("id") or 0))}
    except (CRMError, ValueError, TypeError) as exc:
        return 400, {"ok": False, "error": str(exc)}
    return 404, {"ok": False, "error": "unknown CRM operation %r" % op}
