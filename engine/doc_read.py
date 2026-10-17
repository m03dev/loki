"""Read anything into clean Markdown with page / section anchors (session 29: documents & data).

    convert(path) -> {"ok", "path", "format", "title", "markdown", "sections", "pages", "backend",
                      "warnings", "error"}

Every section has an ANCHOR the index and the chat cite: `p3` (PDF page 3), `slide-4`, `sheet-sales`,
`s2-introduction` (a DOCX/HTML heading), `ch-5` (an EPUB chapter), `msg` / `att-1` (an email and its
attachments), `img`. The Markdown carries them as Pandoc heading attributes - `## Page 3 {#p3}` -
so the text stays readable and a citation `report.pdf#p3` points at one place.

What reads what (first that is installed wins; the standard-library readers always work):

    .pdf     docling (opt-in, LOKI_DOCLING=1) > pdfplumber (text + tables) > pypdf > pypdfium2 > a small
             built-in reader; a page with no text is a SCAN -> rendered (pypdfium2 / PyMuPDF) and OCR'd
    .docx    built-in OOXML reader (headings, lists, bold/italic, links, tables, alt text, page breaks)
    .xlsx    built-in OOXML reader (shared strings, dates, formulas' cached values, one table per sheet)
    .pptx    built-in OOXML reader (slides in order, shapes top-left first, tables, charts as tables,
             picture alt text, speaker notes) - the shape order and chart tables follow MarkItDown
    .csv .tsv, .html .htm, .epub, .eml, images (OCR + an optional description by a vision model),
    .ipynb, text/Markdown/code; .doc/.xls/.ppt/.rtf/.odt through LibreOffice when it is installed;
    anything else through MarkItDown when the `documents` add-on installed it.

OCR: RapidOCR (the `ocr` add-on: pip rapidocr onnxruntime) > the tesseract program on PATH > none
(the page is marked "scanned - install the OCR add-on"). Ported ideas: MarkItDown (MIT, Microsoft) -
`_to_markdown_table`, the MasterFormat ".1" line merge, the PPTX shape order / chart table / notes; see
docs/THIRD_PARTY.md. Standard library only at import time; every optional package is imported lazily.
"""
from __future__ import annotations

import csv
import email
import email.policy
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
import zlib
from pathlib import Path
from xml.etree import ElementTree as ET

MAX_FILE_BYTES = int(os.getenv("LOKI_DOC_MAX_BYTES", str(300 * 1024 * 1024)))
MAX_ZIP_BYTES = 800 * 1024 * 1024        # a zip bomb guard for docx/xlsx/pptx/epub
MAX_TABLE_ROWS = int(os.getenv("LOKI_DOC_TABLE_ROWS", "400"))
MAX_PAGES = int(os.getenv("LOKI_DOC_MAX_PAGES", "2000"))
SCAN_CHARS = 25                          # a PDF page with fewer real characters is treated as a scan
OCR_PAGES = int(os.getenv("LOKI_OCR_MAX_PAGES", "60"))

PDF = {".pdf"}
DOCX = {".docx", ".docm", ".dotx"}
XLSX = {".xlsx", ".xlsm", ".xltx"}
PPTX = {".pptx", ".pptm", ".potx"}
CSVS = {".csv", ".tsv", ".tab"}
HTML = {".html", ".htm", ".xhtml"}
EPUB = {".epub"}
EML = {".eml"}
IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
NOTEBOOK = {".ipynb"}
LEGACY = {".doc", ".xls", ".ppt", ".rtf", ".odt", ".ods", ".odp"}
TEXT = {".md", ".markdown", ".txt", ".rst", ".log", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".xml",
        ".py", ".js", ".ts", ".css", ".sql", ".sh", ".bat", ".ps1", ".c", ".h", ".cpp", ".java", ".go", ".rs",
        ".swift", ".kt", ".rb", ".php", ".lua", ".tex", ".org", ".srt", ".vtt"}
# What LOKI calls a "document": converted (not read as plain text) by the index and read_document.
DOCUMENT_SUFFIXES = PDF | DOCX | XLSX | PPTX | CSVS | EPUB | EML | IMAGES | NOTEBOOK | LEGACY | HTML
TABLE_SUFFIXES = CSVS | XLSX | {".json", ".parquet", ".xls"}

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
    "dc": "http://purl.org/dc/elements/1.1/",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "opf": "http://www.idpf.org/2007/opf",
    "cn": "urn:oasis:names:tc:opendocument:xmlns:container",
}
W = "{%s}" % NS["w"]
R_ID = "{%s}id" % NS["r"]
R_EMBED = "{%s}embed" % NS["r"]


class DocError(Exception):
    pass


# --------------------------------------------------------------------------- small helpers
def slug(text: str, limit: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return s[:limit].strip("-") or "x"


def md_table(rows: list, header: bool = True, limit: int = 0) -> str:
    """A 2-D list as a Markdown pipe table (MarkItDown's `_to_markdown_table`, padded columns,
    empty rows dropped, None -> ""); | and newlines inside cells are escaped."""
    clean = []
    for row in rows or []:
        cells = ["" if c is None else str(c) for c in row]
        cells = [" ".join(c.replace("|", "\\|").split()) for c in cells]
        if any(c.strip() for c in cells):
            clean.append(cells)
    if not clean:
        return ""
    width = max(len(r) for r in clean)
    clean = [r + [""] * (width - len(r)) for r in clean]
    more = 0
    if limit and len(clean) > limit + 1:
        more = len(clean) - limit - 1
        clean = clean[:limit + 1]
    cols = [min(40, max(3, max(len(c) for c in col))) for col in zip(*clean)]

    def fmt(row):
        return "| " + " | ".join(c.ljust(w) for c, w in zip(row, cols)) + " |"
    if header:
        out = [fmt(clean[0]), "| " + " | ".join("-" * w for w in cols) + " |"] + [fmt(r) for r in clean[1:]]
    else:
        out = [fmt(r) for r in clean]
    if more:
        out.append("\n(... %d more rows)" % more)
    return "\n".join(out)


def merge_partial_numbering(text: str) -> str:
    """MarkItDown: a line that is only ".1" (MasterFormat numbering) is joined to the next line."""
    lines, out, i = text.split("\n"), [], 0
    while i < len(lines):
        if re.match(r"^\.\d+$", lines[i].strip()):
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines):
                out.append("%s %s" % (lines[i].strip(), lines[j].strip()))
                i = j + 1
                continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def _clean_text(text: str) -> str:
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _section(anchor: str, title: str, text: str, level: int = 2, page: int = 0) -> dict:
    return {"anchor": anchor, "title": title, "level": level, "page": page, "text": _clean_text(text)}


def build_markdown(title: str, sections: list) -> str:
    parts = ["# %s" % title] if title else []
    for s in sections:
        head = "%s %s {#%s}" % ("#" * max(2, min(6, int(s.get("level") or 2))), s.get("title") or s["anchor"], s["anchor"])
        parts.append(head + ("\n\n" + s["text"] if s.get("text") else ""))
    return "\n\n".join(parts).strip() + "\n"


def strip_anchors(markdown: str) -> str:
    """The Markdown without the {#anchor} marks (for showing it)."""
    return re.sub(r"[ \t]+\{#[a-z0-9_-]+\}[ \t]*$", "", str(markdown or ""), flags=re.M)


def _has(module: str) -> bool:
    import importlib.util  # pylint: disable=import-outside-toplevel
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _zip(path: Path) -> zipfile.ZipFile:
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise DocError("not a valid %s file (the zip inside is broken)" % path.suffix) from exc
    if sum(i.file_size for i in z.infolist()) > MAX_ZIP_BYTES:
        z.close()
        raise DocError("the file unpacks to more than %d MB - refused" % (MAX_ZIP_BYTES // 1048576))
    return z


def _xml(z: zipfile.ZipFile, name: str):
    try:
        data = z.read(name)
    except KeyError:
        return None
    if b"<!ENTITY" in data[:4096]:   # no entity expansion games, ever
        raise DocError("%s declares XML entities - refused" % name)
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        return None


def _rels(z: zipfile.ZipFile, part: str) -> dict:
    """{rId: (target path inside the zip or URL, type, external)} for one part."""
    folder, _, base = part.rpartition("/")
    root = _xml(z, "%s/_rels/%s.rels" % (folder, base) if folder else "_rels/%s.rels" % base)
    out = {}
    if root is None:
        return out
    for rel in root.findall("pr:Relationship", NS):
        target, kind = rel.get("Target", ""), rel.get("Type", "").rsplit("/", 1)[-1]
        external = rel.get("TargetMode") == "External"
        if not external:
            if target.startswith("/"):
                target = target.lstrip("/")
            else:
                parts = (folder.split("/") if folder else []) + target.split("/")
                stack = []
                for piece in parts:
                    if piece == "..":
                        stack.pop() if stack else None
                    elif piece and piece != ".":
                        stack.append(piece)
                target = "/".join(stack)
        out[rel.get("Id", "")] = (target, kind, external)
    return out


def _core_title(z: zipfile.ZipFile) -> str:
    root = _xml(z, "docProps/core.xml")
    if root is None:
        return ""
    node = root.find("dc:title", NS)
    return " ".join((node.text or "").split()) if node is not None and node.text else ""


# --------------------------------------------------------------------------- OCR + vision
def ocr_engines() -> list:
    out = []
    if _has("rapidocr") or _has("rapidocr_onnxruntime"):
        out.append("rapidocr")
    if shutil.which("tesseract"):
        out.append("tesseract")
    return out


_RAPID = None


def ocr_image(data: bytes, engine: str = "") -> dict:
    """{"ok", "text", "engine", "error"} - text in a picture (PNG/JPEG bytes)."""
    engines = [engine] if engine else ocr_engines()
    if not engines:
        return {"ok": False, "text": "", "engine": "", "error": "no OCR engine - install the OCR add-on "
                "(Settings > Add-ons > ocr) or the tesseract program"}
    last = ""
    for name in engines:
        try:
            if name == "rapidocr":
                global _RAPID  # pylint: disable=global-statement
                if _RAPID is None:
                    try:
                        from rapidocr import RapidOCR  # type: ignore # pylint: disable=import-outside-toplevel
                    except ImportError:
                        from rapidocr_onnxruntime import RapidOCR  # type: ignore # pylint: disable=import-outside-toplevel
                    _RAPID = RapidOCR()
                result = _RAPID(data)
                texts = getattr(result, "txts", None)
                if texts is None:     # rapidocr_onnxruntime 1.x: (list of [box, text, score], elapse)
                    raw = result[0] if isinstance(result, tuple) else result
                    texts = [r[1] for r in (raw or [])]
                return {"ok": True, "text": "\n".join(str(t) for t in texts or []), "engine": "rapidocr", "error": ""}
            if name == "tesseract":
                exe = shutil.which("tesseract")
                if not exe:
                    continue
                with tempfile.TemporaryDirectory(prefix="loki-ocr-") as tmp:
                    src = Path(tmp) / "page.png"
                    src.write_bytes(data)
                    proc = subprocess.run([exe, str(src), "stdout"], capture_output=True, timeout=120,
                                          **_no_window())
                if proc.returncode == 0:
                    return {"ok": True, "text": proc.stdout.decode("utf-8", "replace"), "engine": "tesseract", "error": ""}
                last = proc.stderr.decode("utf-8", "replace")[-200:]
        except Exception as exc:  # noqa: BLE001 - one engine failing tries the next
            last = "%s: %s" % (type(exc).__name__, exc)
    return {"ok": False, "text": "", "engine": "", "error": last or "OCR failed"}


def _no_window() -> dict:
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if sys.platform == "win32" else {}


def image_size(data: bytes) -> tuple:
    """(width, height) from PNG/JPEG/GIF headers, (0, 0) when unknown."""
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")
        if data[:2] == b"\xff\xd8":
            i = 2
            while i < len(data) - 9:
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in (0xC0, 0xC1, 0xC2):
                    return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
                i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
    except (IndexError, ValueError):
        pass
    return 0, 0


def _to_png(data: bytes) -> bytes:
    """WebP/TIFF/BMP -> PNG for OCR engines and vision models (Pillow when present)."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" or data[:2] == b"\xff\xd8":
        return data
    try:
        from PIL import Image  # pylint: disable=import-outside-toplevel
        img = Image.open(io.BytesIO(data))
        out = io.BytesIO()
        img.convert("RGB").save(out, "PNG")
        return out.getvalue()
    except Exception:  # noqa: BLE001
        return data


# --------------------------------------------------------------------------- PDF
def _pdf_render_page(path: Path, index: int, scale: float = 2.0) -> bytes:
    """PNG bytes of one PDF page (0-based) - pypdfium2 or PyMuPDF; b"" when neither is installed."""
    if _has("pypdfium2"):
        try:
            import pypdfium2 as pdfium  # type: ignore # pylint: disable=import-outside-toplevel
            pdf = pdfium.PdfDocument(str(path))
            try:
                page = pdf[index]
                bitmap = page.render(scale=scale)
                img = bitmap.to_pil()
                out = io.BytesIO()
                img.save(out, "PNG")
                return out.getvalue()
            finally:
                pdf.close()
        except Exception:  # noqa: BLE001 - try the next renderer
            pass
    if _has("fitz"):
        try:
            import fitz  # type: ignore # pylint: disable=import-outside-toplevel
            with fitz.open(str(path)) as doc:
                return doc[index].get_pixmap(matrix=fitz.Matrix(scale, scale)).tobytes("png")
        except Exception:  # noqa: BLE001
            pass
    return b""


def can_render_pdf() -> bool:
    return _has("pypdfium2") or _has("fitz")


def _pdf_pages_pdfplumber(path: Path, password: str, tables: bool = True) -> list:
    import logging  # pylint: disable=import-outside-toplevel
    import pdfplumber  # type: ignore # pylint: disable=import-outside-toplevel
    logging.getLogger("pdfminer").setLevel(logging.ERROR)   # standard-14 fonts without a FontBBox: harmless noise
    pages = []
    with pdfplumber.open(str(path), password=password or None) as pdf:
        for n, page in enumerate(pdf.pages[:MAX_PAGES]):
            text = page.extract_text() or ""
            found = []
            if tables:
                try:
                    for t in page.extract_tables() or []:
                        if t and len(t) >= 2 and max(len(r) for r in t) >= 2:
                            found.append(md_table(t))
                except Exception:  # noqa: BLE001 - tables are a bonus
                    pass
            pages.append(text + ("\n\n" + "\n\n".join(f for f in found if f) if found else ""))
            if hasattr(page, "close"):
                page.close()
    return pages


def _pdf_pages_pypdf(path: Path, password: str) -> list:
    import pypdf  # type: ignore # pylint: disable=import-outside-toplevel
    reader = pypdf.PdfReader(str(path))
    if reader.is_encrypted:
        if not reader.decrypt(password or ""):
            raise DocError("the PDF is password protected - give its password")
    return [(page.extract_text() or "") for page in reader.pages[:MAX_PAGES]]


def _pdf_pages_pdfium(path: Path, password: str) -> list:
    import pypdfium2 as pdfium  # type: ignore # pylint: disable=import-outside-toplevel
    pdf = pdfium.PdfDocument(str(path), password=password or None)
    try:
        out = []
        for i in range(min(len(pdf), MAX_PAGES)):
            tp = pdf[i].get_textpage()
            out.append(tp.get_text_range() or "")
        return out
    finally:
        pdf.close()


def _pdf_title(path: Path) -> str:
    if _has("pypdf"):
        try:
            import pypdf  # type: ignore # pylint: disable=import-outside-toplevel
            meta = pypdf.PdfReader(str(path)).metadata
            if meta and meta.title and str(meta.title).strip():
                return " ".join(str(meta.title).split())
        except Exception:  # noqa: BLE001
            pass
    return ""


# The built-in reader: enough for simple PDFs (LOKI's own, most generated reports) when no PDF
# package is installed. It reads every object, follows Pages/Kids/Contents in order, inflates
# Flate streams and takes the text of Tj/TJ/'/" with Td/T*/Tm line breaks. No object streams,
# no CID fonts without ToUnicode: those need pypdf (in engine/requirements.txt).
_OBJ = re.compile(rb"(\d+)\s+(\d+)\s+obj\b(.*?)endobj", re.S)


def _pdf_objects(raw: bytes) -> dict:
    objs = {}
    for m in _OBJ.finditer(raw):
        objs[int(m.group(1))] = m.group(3)
    return objs


def _pdf_stream(body: bytes) -> bytes:
    m = re.search(rb"stream\r?\n", body)
    if not m:
        return b""
    data = body[m.end():]
    end = data.rfind(b"endstream")
    data = data[:end] if end >= 0 else data
    if re.search(rb"/FlateDecode", body[:m.start()]):
        try:
            return zlib.decompress(data.rstrip(b"\r\n"))
        except zlib.error:
            try:
                return zlib.decompressobj().decompress(data)
            except zlib.error:
                return b""
    return data


def _pdf_unescape(s: bytes) -> str:
    out, i = bytearray(), 0
    while i < len(s):
        ch = s[i]
        if ch == 0x5C and i + 1 < len(s):   # backslash
            nxt = s[i + 1]
            simple = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12, ord("("): 40,
                      ord(")"): 41, 0x5C: 0x5C}
            if nxt in simple:
                out.append(simple[nxt])
                i += 2
                continue
            if 48 <= nxt <= 55:
                j = i + 1
                while j < len(s) and j < i + 4 and 48 <= s[j] <= 55:
                    j += 1
                out.append(int(s[i + 1:j], 8) & 0xFF)
                i = j
                continue
            if nxt in (10, 13):
                i += 2
                continue
            i += 1
            continue
        out.append(ch)
        i += 1
    return bytes(out).decode("cp1252", "replace")


_TOKENS = re.compile(rb"\((?:\\.|[^\\)])*\)|<[0-9A-Fa-f\s]*>|\[|\]|/[^\s/\[\]()<>]+|[-+]?\d*\.?\d+|[A-Za-z'\"*]+", re.S)


def _pdf_content_text(stream: bytes) -> str:
    out, operands = [], []
    for tok in _TOKENS.findall(stream):
        if tok.startswith(b"("):
            operands.append(_pdf_unescape(tok[1:-1]))
        elif tok.startswith(b"<") and not tok.startswith(b"<<"):
            hexs = re.sub(rb"\s", b"", tok[1:-1])
            try:
                operands.append(bytes.fromhex(hexs.decode() + ("0" if len(hexs) % 2 else "")).decode("cp1252", "replace"))
            except ValueError:
                pass
        elif tok in (b"[", b"]"):
            operands.append(tok.decode())
        elif re.match(rb"^[-+]?\d*\.?\d+$", tok):
            operands.append(float(tok))
        elif tok.startswith(b"/"):
            operands.append(tok.decode("latin-1"))
        else:
            op = tok.decode("latin-1")
            if op in ("Tj", "'", '"'):
                if op != "Tj":
                    out.append("\n")
                out.append("".join(o for o in operands if isinstance(o, str) and o not in ("[", "]") and not o.startswith("/")))
            elif op == "TJ":
                piece = ""
                for o in operands:
                    if isinstance(o, float) and o < -200:
                        piece += " "
                    elif isinstance(o, str) and o not in ("[", "]") and not o.startswith("/"):
                        piece += o
                out.append(piece)
            elif op in ("Td", "TD") and len(operands) >= 2 and isinstance(operands[-1], float) and operands[-1] != 0:
                out.append("\n")
            elif op in ("T*",):
                out.append("\n")
            elif op == "Tm":
                out.append("\n")
            elif op == "ET":
                out.append("\n")
            operands = []
    text = "".join(out)
    return re.sub(r"\n\s*\n+", "\n", text)


def _pdf_pages_builtin(path: Path) -> list:
    raw = path.read_bytes()
    if b"/Encrypt" in raw:
        raise DocError("the PDF is encrypted - install pypdf (engine/requirements.txt) to read it")
    objs = _pdf_objects(raw)

    def ref(body: bytes, key: bytes):
        m = re.search(rb"/" + key + rb"\s+(\d+)\s+0\s+R", body)
        return int(m.group(1)) if m else None
    root = None
    for m in re.finditer(rb"/Root\s+(\d+)\s+0\s+R", raw):
        root = int(m.group(1))
    pages_root = ref(objs.get(root, b""), b"Pages") if root else None
    order = []

    def walk(num, depth=0):
        body = objs.get(num, b"")
        if depth > 30 or not body:
            return
        if re.search(rb"/Type\s*/Pages\b", body):
            kids = re.search(rb"/Kids\s*\[([^\]]*)\]", body)
            for k in re.findall(rb"(\d+)\s+0\s+R", kids.group(1) if kids else b""):
                walk(int(k), depth + 1)
        elif re.search(rb"/Type\s*/Page\b", body):
            order.append(num)
    if pages_root:
        walk(pages_root)
    if not order:   # no usable tree: every page object in file order
        order = [n for n, b in sorted(objs.items()) if re.search(rb"/Type\s*/Page\b", b)]
    pages = []
    for num in order[:MAX_PAGES]:
        body = objs[num]
        refs = []
        m = re.search(rb"/Contents\s*\[([^\]]*)\]", body)
        if m:
            refs = [int(x) for x in re.findall(rb"(\d+)\s+0\s+R", m.group(1))]
        else:
            one = ref(body, b"Contents")
            refs = [one] if one else []
        text = "".join(_pdf_content_text(_pdf_stream(objs.get(r, b""))) for r in refs)
        pages.append(text)
    return pages


def pdf_page_count(path: Path) -> int:
    for fn in (_pdf_count_pypdf, _pdf_count_pdfium):
        try:
            n = fn(path)
            if n:
                return n
        except Exception:  # noqa: BLE001
            continue
    try:
        return len(_pdf_pages_builtin(path))
    except Exception:  # noqa: BLE001
        return 0


def _pdf_count_pypdf(path: Path) -> int:
    if not _has("pypdf"):
        return 0
    import pypdf  # type: ignore # pylint: disable=import-outside-toplevel
    return len(pypdf.PdfReader(str(path)).pages)


def _pdf_count_pdfium(path: Path) -> int:
    if not _has("pypdfium2"):
        return 0
    import pypdfium2 as pdfium  # type: ignore # pylint: disable=import-outside-toplevel
    pdf = pdfium.PdfDocument(str(path))
    try:
        return len(pdf)
    finally:
        pdf.close()


def read_pdf(path: Path, ocr: str = "auto", password: str = "", engine: str = "", **_kw) -> dict:
    warnings, pages, backend = [], None, ""
    want = (engine or os.getenv("LOKI_PDF_ENGINE", "")).strip().lower()
    if (want == "docling" or os.getenv("LOKI_DOCLING", "") == "1") and _has("docling"):
        try:
            from docling.document_converter import DocumentConverter  # type: ignore # pylint: disable=import-outside-toplevel
            result = DocumentConverter().convert(str(path))
            doc = result.document
            n = len(getattr(doc, "pages", {}) or {}) or 1
            pages = [doc.export_to_markdown(page_no=i + 1) for i in range(n)]
            backend = "docling"
        except Exception as exc:  # noqa: BLE001
            warnings.append("docling failed (%s), used the next reader" % type(exc).__name__)
            pages = None
    order = [("pdfplumber", _pdf_pages_pdfplumber), ("pypdf", _pdf_pages_pypdf), ("pypdfium2", _pdf_pages_pdfium)]
    if want in ("pypdf", "pypdfium2", "pdfplumber"):
        order.sort(key=lambda x: x[0] != want)
    for name, fn in order:
        if pages is not None:
            break
        if not _has(name):
            continue
        try:
            pages = fn(path, password)
            backend = name
        except DocError:
            raise
        except Exception as exc:  # noqa: BLE001 - a broken PDF for one reader may open in the next
            msg = str(exc).lower()
            if "password" in msg or "encrypt" in msg:
                raise DocError("the PDF is password protected - give its password") from exc
            warnings.append("%s could not read it (%s)" % (name, type(exc).__name__))
    if pages is None:
        pages = _pdf_pages_builtin(path)
        backend = "built-in"
    title = _pdf_title(path) or ""
    sections, scanned, ocred = [], [], 0
    use_ocr = str(ocr or "auto").lower() not in ("0", "off", "false", "no")
    for i, text in enumerate(pages):
        text = merge_partial_numbering(_clean_text(text))
        if len(re.sub(r"\s", "", text)) < SCAN_CHARS:
            if use_ocr and ocred < OCR_PAGES and ocr_engines() and can_render_pdf():
                png = _pdf_render_page(path, i)
                got = ocr_image(png) if png else {"ok": False}
                if got.get("ok") and got.get("text", "").strip():
                    text = _clean_text(got["text"])
                    ocred += 1
                    backend = backend + "+ocr:" + got["engine"] if "+ocr" not in backend else backend
                else:
                    scanned.append(i + 1)
            else:
                scanned.append(i + 1)
        sections.append(_section("p%d" % (i + 1), "Page %d" % (i + 1), text, 2, i + 1))
    if scanned and len(scanned) == len(pages) and not any(s["text"] for s in sections):
        why = ("no OCR engine is installed (Settings > Add-ons > ocr)" if not ocr_engines() else
               "pages cannot be rendered for OCR (install the documents add-on: pypdfium2)" if not can_render_pdf()
               else "OCR found no text")
        warnings.append("this PDF looks scanned (no text layer): %s" % why)
    elif scanned:
        warnings.append("page(s) %s have no text layer (scans or pictures)%s" % (
            _ranges(scanned), "" if ocr_engines() and can_render_pdf() else " - the OCR add-on would read them"))
    if ocred:
        warnings.append("%d page(s) read with OCR - check names and numbers" % ocred)
    return {"title": title, "sections": sections, "pages": len(pages), "backend": backend, "warnings": warnings}


def _ranges(nums: list) -> str:
    out, start, prev = [], None, None
    for n in sorted(nums):
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append(str(start) if start == prev else "%d-%d" % (start, prev))
            start = prev = n
    if start is not None:
        out.append(str(start) if start == prev else "%d-%d" % (start, prev))
    return ", ".join(out)


# --------------------------------------------------------------------------- DOCX
def _docx_styles(z) -> dict:
    root = _xml(z, "word/styles.xml")
    out = {}
    if root is None:
        return out
    for st in root.findall("w:style", NS):
        sid = st.get(W + "styleId", "")
        name = st.find("w:name", NS)
        out[sid] = (name.get(W + "val") if name is not None else sid) or sid
    return out


def _docx_numbering(z) -> dict:
    """{numId: {ilvl: "bullet"|"decimal"|...}}"""
    root = _xml(z, "word/numbering.xml")
    if root is None:
        return {}
    abstract = {}
    for a in root.findall("w:abstractNum", NS):
        levels = {}
        for lvl in a.findall("w:lvl", NS):
            fmt = lvl.find("w:numFmt", NS)
            levels[lvl.get(W + "ilvl", "0")] = fmt.get(W + "val") if fmt is not None else "bullet"
        abstract[a.get(W + "abstractNumId")] = levels
    out = {}
    for num in root.findall("w:num", NS):
        ref = num.find("w:abstractNumId", NS)
        if ref is not None:
            out[num.get(W + "numId")] = abstract.get(ref.get(W + "val"), {})
    return out


def _on(node, tag: str) -> bool:
    el = node.find(tag, NS) if node is not None else None
    return el is not None and el.get(W + "val", "true") not in ("0", "false", "none")


def read_docx(path: Path, **_kw) -> dict:
    with _zip(path) as z:
        body_root = _xml(z, "word/document.xml")
        if body_root is None:
            raise DocError("this .docx has no word/document.xml")
        styles, numbering, rels = _docx_styles(z), _docx_numbering(z), _rels(z, "word/document.xml")
        title = _core_title(z)
    body = body_root.find("w:body", NS)
    state = {"page": 1, "counters": {}}
    blocks = []   # (kind, level, text, page)

    def runs_text(p) -> str:
        out = []
        for child in p:
            tag = child.tag.split("}")[-1]
            if tag == "r":
                out.append(run_text(child))
            elif tag == "hyperlink":
                inner = "".join(run_text(r) for r in child.findall(".//w:r", NS))
                rid = child.get(R_ID)
                target = rels.get(rid, ("", "", False))[0] if rid else ""
                out.append("[%s](%s)" % (inner, target) if target and inner.strip() else inner)
            elif tag in ("ins", "smartTag", "sdt", "fldSimple"):
                out.append("".join(run_text(r) for r in child.findall(".//w:r", NS)))
        return "".join(out)

    def run_text(r) -> str:
        pieces = []
        for child in r:
            tag = child.tag.split("}")[-1]
            if tag == "t":
                pieces.append(child.text or "")
            elif tag == "tab":
                pieces.append("\t")
            elif tag in ("br", "cr"):
                if child.get(W + "type") == "page":
                    state["page"] += 1
                else:
                    pieces.append("\n")
            elif tag == "lastRenderedPageBreak":
                state["page"] += 1
            elif tag == "drawing":
                doc_pr = child.find(".//wp:docPr", NS)
                alt = (doc_pr.get("descr") or doc_pr.get("title") or doc_pr.get("name") or "image") if doc_pr is not None else "image"
                pieces.append("![%s](image)" % " ".join(alt.split()))
        text = "".join(pieces)
        if not text.strip() or text.startswith("!["):
            return text
        rpr = r.find("w:rPr", NS)
        core = text.strip()
        lead, tail = text[:len(text) - len(text.lstrip())], text[len(text.rstrip()):]
        if _on(rpr, "w:b"):
            core = "**%s**" % core
        if _on(rpr, "w:i"):
            core = "*%s*" % core
        return lead + core + tail

    def para(p):
        ppr = p.find("w:pPr", NS)
        style_id = ""
        if ppr is not None:
            ps = ppr.find("w:pStyle", NS)
            style_id = ps.get(W + "val", "") if ps is not None else ""
        name = styles.get(style_id, style_id).lower()
        text = runs_text(p).replace("****", "")
        level = 0
        m = re.match(r"heading\s*(\d)", name)
        if m:
            level = int(m.group(1))
        elif name in ("title",):
            level = 1
        elif ppr is not None and ppr.find("w:outlineLvl", NS) is not None:
            try:
                level = int(ppr.find("w:outlineLvl", NS).get(W + "val", "9")) + 1
            except ValueError:
                level = 0
            level = level if level <= 6 else 0
        if level and text.strip():
            blocks.append(("heading", level, re.sub(r"\*+", "", text).strip(), state["page"]))
            return
        num = ppr.find("w:numPr", NS) if ppr is not None else None
        if num is not None and text.strip():
            ilvl = num.find("w:ilvl", NS)
            nid = num.find("w:numId", NS)
            lvl = ilvl.get(W + "val", "0") if ilvl is not None else "0"
            fmt = numbering.get(nid.get(W + "val") if nid is not None else "", {}).get(lvl, "bullet")
            indent = "  " * int(lvl or 0)
            if fmt in ("bullet", "none", ""):
                blocks.append(("item", 0, "%s- %s" % (indent, text.strip()), state["page"]))
            else:
                key = (nid.get(W + "val") if nid is not None else "", lvl)
                state["counters"][key] = state["counters"].get(key, 0) + 1
                blocks.append(("item", 0, "%s%d. %s" % (indent, state["counters"][key], text.strip()), state["page"]))
            return
        lm = re.match(r"list\s*(bullet|number|paragraph)?\s*(\d)?", name)
        if lm and text.strip():
            indent = "  " * max(0, int(lm.group(2) or 1) - 1)
            if lm.group(1) == "number":
                key = ("style", indent)
                state["counters"][key] = state["counters"].get(key, 0) + 1
                blocks.append(("item", 0, "%s%d. %s" % (indent, state["counters"][key], text.strip()), state["page"]))
            else:
                blocks.append(("item", 0, "%s- %s" % (indent, text.strip()), state["page"]))
            return
        if text.strip():
            state["counters"].pop(("style", ""), None)   # a numbered list ends at the next normal paragraph
        blocks.append(("para", 0, text, state["page"]))

    def table(tbl):
        rows = []
        for tr in tbl.findall("w:tr", NS):
            cells = []
            for tc in tr.findall("w:tc", NS):
                text = "<br>".join(runs_text(p).strip() for p in tc.findall(".//w:p", NS) if runs_text(p).strip())
                cells.append(re.sub(r"\*\*(.+?)\*\*", r"\1", text) if not rows else text)
            rows.append(cells)
        blocks.append(("table", 0, md_table(rows), state["page"]))

    def walk(node):
        for child in node:
            tag = child.tag.split("}")[-1]
            if tag == "p":
                para(child)
            elif tag == "tbl":
                table(child)
            elif tag in ("sdt", "sdtContent", "customXml"):
                walk(child)
    if body is not None:
        walk(body)
    return _sections_from_blocks(blocks, title or path.stem)


def _sections_from_blocks(blocks: list, title: str) -> dict:
    """Headings start sections (anchor s<n>-<slug>); text before the first heading is the start."""
    sections, cur, n = [], None, 0
    lines = []

    def close():
        if cur is not None:
            text, prev = "", None
            for kind, line in lines:
                if not text:
                    text = line
                elif kind == "item" and prev == "item":
                    text += "\n" + line
                else:
                    text += "\n\n" + line
                prev = kind
            cur["text"] = _clean_text(text)
            if cur["text"] or cur["title"] != "Start":
                sections.append(cur)
    for kind, level, text, page in blocks:
        if kind == "heading":
            close()
            n += 1
            cur = _section("s%d-%s" % (n, slug(text)), text, "", min(6, level + 1), page)
            lines = []
            continue
        if cur is None:
            cur = _section("start", "Start", "", 2, page)
            lines = []
        if kind == "para" and not text.strip():
            continue
        lines.append((kind, text))
    close()
    pages = max([s.get("page") or 1 for s in sections] or [1])
    return {"title": title, "sections": sections, "pages": pages, "backend": "built-in docx", "warnings": []}


# --------------------------------------------------------------------------- XLSX
_BUILTIN_DATE_FMTS = set(range(14, 23)) | {27, 30, 36, 45, 46, 47, 50, 57}


def _xlsx_date_styles(z) -> set:
    root = _xml(z, "xl/styles.xml")
    if root is None:
        return set()
    custom = {}
    fmts = root.find("s:numFmts", NS)
    for f in (fmts.findall("s:numFmt", NS) if fmts is not None else []):
        custom[int(f.get("numFmtId", "0"))] = f.get("formatCode", "")
    out = set()
    xfs = root.find("s:cellXfs", NS)
    for i, xf in enumerate(xfs.findall("s:xf", NS) if xfs is not None else []):
        fid = int(xf.get("numFmtId", "0") or 0)
        code = re.sub(r'"[^"]*"|\[[^\]]*\]', "", custom.get(fid, "")).lower()
        if fid in _BUILTIN_DATE_FMTS or (code and re.search(r"[dy]|mm?:|h", code) and not re.search(r"^[#0.,%e+-]+$", code)):
            out.add(i)
    return out


def _excel_date(value: float) -> str:
    import datetime  # pylint: disable=import-outside-toplevel
    base = datetime.datetime(1899, 12, 30)
    when = base + datetime.timedelta(days=float(value))
    return when.strftime("%Y-%m-%d") if when.hour == when.minute == when.second == 0 else when.strftime("%Y-%m-%d %H:%M")


def _col_index(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def xlsx_tables(path: Path, max_rows: int = 0) -> list:
    """[{"name", "rows": [[...]], "formulas": {"B5": "SUM(B2:B4)"}, "total_rows"}] per sheet - values as
    Python str/float/int (dates as ISO text), standard library only."""
    max_rows = max_rows or 1_000_000
    with _zip(path) as z:
        wb = _xml(z, "xl/workbook.xml")
        if wb is None:
            raise DocError("this .xlsx has no xl/workbook.xml")
        rels = _rels(z, "xl/workbook.xml")
        shared = []
        sst = _xml(z, "xl/sharedStrings.xml")
        for si in (sst.findall("s:si", NS) if sst is not None else []):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["s"])))
        dates = _xlsx_date_styles(z)
        out = []
        sheets = wb.find("s:sheets", NS)
        for sh in (sheets.findall("s:sheet", NS) if sheets is not None else []):
            target = rels.get(sh.get(R_ID), ("", "", False))[0]
            root = _xml(z, target) if target else None
            if root is None:
                continue
            grid, formulas, total = {}, {}, 0
            data = root.find("s:sheetData", NS)
            for row in (data.findall("s:row", NS) if data is not None else []):
                total += 1
                if total > max_rows:
                    continue
                r = int(row.get("r", total)) - 1
                for c in row.findall("s:c", NS):
                    ref = c.get("r", "")
                    col = _col_index(ref) if ref else len(grid.get(r, {}))
                    kind, v, f = c.get("t", "n"), c.find("s:v", NS), c.find("s:f", NS)
                    text = v.text if v is not None else None
                    if f is not None and f.text:
                        formulas[ref] = f.text
                    if kind == "s" and text is not None:
                        value = shared[int(text)] if int(text) < len(shared) else ""
                    elif kind == "inlineStr":
                        value = "".join(t.text or "" for t in c.iter("{%s}t" % NS["s"]))
                    elif kind == "b":
                        value = "TRUE" if text == "1" else "FALSE"
                    elif kind in ("str", "e"):
                        value = text or ""
                    elif text is None:
                        value = ("=" + f.text) if f is not None and f.text else None
                    else:
                        try:
                            num = float(text)
                            if int(c.get("s", "0") or 0) in dates:
                                value = _excel_date(num)
                            else:
                                value = int(num) if num.is_integer() and abs(num) < 1e15 else num
                        except ValueError:
                            value = text
                    if value is not None:
                        grid.setdefault(r, {})[col] = value
            rows = []
            if grid:
                top, bottom = min(grid), max(grid)
                left = min(min(cols) for cols in grid.values())
                right = max(max(cols) for cols in grid.values())
                for r in range(top, bottom + 1):
                    cells = grid.get(r, {})
                    rows.append([cells.get(c, "") for c in range(left, right + 1)])
            out.append({"name": sh.get("name", "Sheet"), "rows": rows, "formulas": formulas, "total_rows": total})
        return out


def read_xlsx(path: Path, **_kw) -> dict:
    with _zip(path) as z:
        title = _core_title(z)
    sheets = xlsx_tables(path, max_rows=MAX_TABLE_ROWS + 1)
    sections, warnings = [], []
    for sh in sheets:
        rows = sh["rows"]
        text = md_table(rows, limit=MAX_TABLE_ROWS) if rows else "(empty sheet)"
        if sh["total_rows"] > MAX_TABLE_ROWS + 1:
            text += "\n\n(%d rows in this sheet - the first %d are shown; analyze_data reads them all)" % (
                sh["total_rows"], MAX_TABLE_ROWS)
        if sh["formulas"]:
            shown = list(sh["formulas"].items())[:12]
            text += "\n\nFormulas: " + "; ".join("%s = %s" % (k, v) for k, v in shown) + (
                " ..." if len(sh["formulas"]) > 12 else "")
        sections.append(_section("sheet-" + slug(sh["name"]), "Sheet: %s" % sh["name"], text, 2))
    return {"title": title or path.stem, "sections": sections, "pages": len(sections), "backend": "built-in xlsx",
            "warnings": warnings}


# --------------------------------------------------------------------------- PPTX
def _pptx_text(node) -> str:
    paras = []
    for p in node.iter("{%s}p" % NS["a"]):
        line = "".join((t.text or "") for t in p.iter("{%s}t" % NS["a"]))
        if line.strip():
            lvl = 0
            ppr = p.find("a:pPr", NS)
            if ppr is not None:
                try:
                    lvl = int(ppr.get("lvl", "0"))
                except ValueError:
                    lvl = 0
            paras.append(("  " * lvl) + line)
    return "\n".join(paras)


def _pptx_pos(shape) -> tuple:
    off = shape.find(".//a:off", NS)
    if off is None:
        return (float("-inf"), float("-inf"))
    try:
        return (int(off.get("y", 0)), int(off.get("x", 0)))
    except ValueError:
        return (0, 0)


def _pptx_chart(z, part: str) -> str:
    root = _xml(z, part)
    if root is None:
        return ""
    title = " ".join(t.text or "" for t in root.findall(".//c:title//a:t", NS)).strip()
    series = []
    cats = []
    for ser in root.iter("{%s}ser" % NS["c"]):
        name = " ".join(v.text or "" for v in ser.findall("c:tx//c:v", NS)).strip() or "Series %d" % (len(series) + 1)
        vals = [v.text for v in ser.findall("c:val//c:pt/c:v", NS)] or [v.text for v in ser.findall("c:yVal//c:pt/c:v", NS)]
        c = [v.text for v in ser.findall("c:cat//c:pt/c:v", NS)] or [v.text for v in ser.findall("c:xVal//c:pt/c:v", NS)]
        cats = cats or c
        series.append((name, vals))
    if not series:
        return "### Chart%s\n\n[unsupported chart]" % (": " + title if title else "")
    rows = [["Category"] + [s[0] for s in series]]
    for i in range(max(len(cats), max(len(s[1]) for s in series))):
        rows.append([cats[i] if i < len(cats) else str(i + 1)] + [s[1][i] if i < len(s[1]) else "" for s in series])
    return "### Chart%s\n\n%s" % (": " + title if title else "", md_table(rows))


def read_pptx(path: Path, **_kw) -> dict:
    sections = []
    with _zip(path) as z:
        pres = _xml(z, "ppt/presentation.xml")
        if pres is None:
            raise DocError("this .pptx has no ppt/presentation.xml")
        title = _core_title(z)
        rels = _rels(z, "ppt/presentation.xml")
        ids = pres.find("p:sldIdLst", NS)
        slides = [rels.get(s.get(R_ID), ("", "", False))[0] for s in (ids.findall("p:sldId", NS) if ids is not None else [])]
        for n, part in enumerate(slides, 1):
            root = _xml(z, part) if part else None
            if root is None:
                continue
            srels = _rels(z, part)
            tree = root.find(".//p:spTree", NS)
            slide_title, body = "", []

            def shapes(container):
                for shape in sorted([c for c in container if c.tag.split("}")[-1] in ("sp", "pic", "graphicFrame", "grpSp")],
                                    key=_pptx_pos):
                    yield shape

            def visit(container):
                nonlocal slide_title
                for shape in shapes(container):
                    tag = shape.tag.split("}")[-1]
                    if tag == "grpSp":
                        visit(shape)
                    elif tag == "pic":
                        pr = shape.find(".//p:cNvPr", NS)
                        alt = (pr.get("descr") or pr.get("name") or "picture") if pr is not None else "picture"
                        body.append("![%s](picture)" % re.sub(r"[\r\n\[\]]", " ", alt).strip())
                    elif tag == "graphicFrame":
                        tbl = shape.find(".//a:tbl", NS)
                        if tbl is not None:
                            rows = [[" ".join((t.text or "") for t in tc.iter("{%s}t" % NS["a"])) for tc in tr.findall("a:tc", NS)]
                                    for tr in tbl.findall("a:tr", NS)]
                            body.append(md_table(rows))
                        chart = shape.find(".//c:chart", NS)
                        if chart is not None:
                            target = srels.get(chart.get(R_ID), ("", "", False))[0]
                            if target:
                                body.append(_pptx_chart(z, target))
                    elif tag == "sp":
                        ph = shape.find(".//p:nvPr/p:ph", NS)
                        text = _pptx_text(shape)
                        if not text.strip():
                            continue
                        if ph is not None and ph.get("type") in ("title", "ctrTitle") and not slide_title:
                            slide_title = " ".join(text.split())
                        elif ph is not None and ph.get("type") == "sldNum":
                            continue
                        else:
                            body.append(text)
            if tree is not None:
                visit(tree)
            notes = ""
            for target, kind, external in srels.values():
                if kind == "notesSlide" and not external:
                    nroot = _xml(z, target)
                    if nroot is not None:
                        parts = []
                        for sp in nroot.iter("{%s}sp" % NS["p"]):
                            ph = sp.find(".//p:nvPr/p:ph", NS)
                            if ph is not None and ph.get("type") in ("sldNum", "sldImg", "hdr", "ftr", "dt"):
                                continue
                            parts.append(_pptx_text(sp))
                        notes = "\n".join(p for p in parts if p.strip())
            text = "\n\n".join(b for b in body if b.strip())
            if notes:
                text += "\n\n### Notes\n\n" + notes
            sections.append(_section("slide-%d" % n, "Slide %d%s" % (n, ": " + slide_title if slide_title else ""), text, 2, n))
    return {"title": title or path.stem, "sections": sections, "pages": len(sections), "backend": "built-in pptx",
            "warnings": []}


# --------------------------------------------------------------------------- CSV, HTML, EPUB, EML
def read_text_file(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def csv_rows(path: Path, max_rows: int = 0) -> tuple:
    """(rows, total_rows, delimiter)"""
    text = read_text_file(path)
    sample = text[:20000]
    delim = "\t" if path.suffix.lower() in (".tsv", ".tab") else ","
    try:
        delim = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        pass
    rows, total = [], 0
    for row in csv.reader(io.StringIO(text), delimiter=delim):
        total += 1
        if not max_rows or len(rows) < max_rows:
            rows.append(row)
    return rows, total, delim


def read_csv(path: Path, **_kw) -> dict:
    rows, total, delim = csv_rows(path, MAX_TABLE_ROWS + 1)
    text = md_table(rows, limit=MAX_TABLE_ROWS) if rows else "(empty)"
    if total > MAX_TABLE_ROWS + 1:
        text += "\n\n(%d rows - the first %d are shown; analyze_data and data_sql read them all)" % (total - 1, MAX_TABLE_ROWS)
    cols = len(rows[0]) if rows else 0
    return {"title": path.stem, "sections": [_section("table", "Table (%d rows, %d columns)" % (max(0, total - 1), cols), text)],
            "pages": 1, "backend": "built-in csv (%r)" % delim, "warnings": []}


def html_sections(html: str, fallback_title: str = "", prefix: str = "s") -> dict:
    import web_reader  # pylint: disable=import-outside-toplevel
    got = web_reader.to_markdown(html)
    md, title = got.get("markdown", ""), got.get("title", "") or fallback_title
    return {"title": title, "sections": _split_markdown(md, prefix), "backend": "built-in html"}


def _split_markdown(md: str, prefix: str = "s") -> list:
    """Sections at Markdown headings (# .. ######) - outside fenced code."""
    sections, cur_title, cur_level, buf, n, fence = [], "Start", 2, [], 0, False
    for line in str(md or "").split("\n"):
        if line.strip().startswith("```"):
            fence = not fence
        m = None if fence else re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if m:
            if "".join(buf).strip() or cur_title != "Start":
                sections.append((cur_title, cur_level, "\n".join(buf)))
            cur_title, cur_level, buf = re.sub(r"\s*\{#[^}]*\}$", "", m.group(2)), len(m.group(1)), []
            continue
        buf.append(line)
    if "".join(buf).strip() or cur_title != "Start":
        sections.append((cur_title, cur_level, "\n".join(buf)))
    out = []
    for title, level, text in sections:
        if title == "Start":
            out.append(_section("start", "Start", text, 2))
        else:
            n += 1
            out.append(_section("%s%d-%s" % (prefix, n, slug(title)), title, text, min(6, level + 1)))
    return out


def read_html(path: Path, **_kw) -> dict:
    got = html_sections(read_text_file(path), path.stem)
    return {**got, "pages": 1, "warnings": []}


def read_epub(path: Path, **_kw) -> dict:
    sections, warnings = [], []
    with _zip(path) as z:
        cont = _xml(z, "META-INF/container.xml")
        rootfile = cont.find(".//cn:rootfile", NS) if cont is not None else None
        opf_path = rootfile.get("full-path") if rootfile is not None else ""
        opf = _xml(z, opf_path) if opf_path else None
        if opf is None:
            raise DocError("this .epub has no readable package file")
        folder = opf_path.rpartition("/")[0]
        title_el = opf.find(".//dc:title", NS)
        title = " ".join((title_el.text or "").split()) if title_el is not None and title_el.text else path.stem
        manifest = {item.get("id"): item.get("href", "") for item in opf.findall(".//opf:manifest/opf:item", NS)}
        spine = [it.get("idref") for it in opf.findall(".//opf:spine/opf:itemref", NS)]
        n = 0
        for idref in spine:
            href = manifest.get(idref, "")
            if not href:
                continue
            name = (folder + "/" + href) if folder else href
            try:
                html = z.read(name.split("#")[0]).decode("utf-8", "replace")
            except KeyError:
                warnings.append("missing chapter file %s" % href)
                continue
            got = html_sections(html)
            text = "\n\n".join(("#" * min(6, s["level"] + 1) + " " + s["title"] + "\n\n" if s["title"] != "Start" else "")
                               + s["text"] for s in got["sections"]).strip()
            if not text:
                continue
            n += 1
            head = got["title"] or next((s["title"] for s in got["sections"] if s["title"] != "Start"), "") or "Chapter %d" % n
            sections.append(_section("ch-%d" % n, head, text, 2, n))
    return {"title": title, "sections": sections, "pages": len(sections), "backend": "built-in epub", "warnings": warnings}


def read_eml(path: Path, attachments: bool = True, depth: int = 0, **kw) -> dict:
    msg = email.message_from_bytes(path.read_bytes(), policy=email.policy.default)
    head = []
    for key in ("From", "To", "Cc", "Date", "Subject"):
        if msg.get(key):
            head.append("**%s:** %s" % (key, " ".join(str(msg.get(key)).split())))
    body = msg.get_body(preferencelist=("plain", "html"))
    text = ""
    if body is not None:
        try:
            content = body.get_content()
        except (LookupError, ValueError):
            content = (body.get_payload(decode=True) or b"").decode("utf-8", "replace")
        if body.get_content_type() == "text/html":
            got = html_sections(str(content))
            text = "\n\n".join(s["text"] for s in got["sections"])
        else:
            text = str(content)
    sections = [_section("msg", str(msg.get("Subject") or "Message"), "\n".join(head) + "\n\n" + text, 2)]
    listed, warnings, n = [], [], 0
    for part in msg.iter_attachments():
        name = part.get_filename() or "attachment"
        data = part.get_payload(decode=True) or b""
        n += 1
        listed.append("- %s (%s, %d KB)" % (name, part.get_content_type(), max(1, len(data) // 1024)))
        suffix = Path(name).suffix.lower()
        if attachments and depth < 1 and suffix in (DOCUMENT_SUFFIXES | TEXT) - IMAGES and len(data) < 30 * 1048576:
            with tempfile.TemporaryDirectory(prefix="loki-eml-") as tmp:
                f = Path(tmp) / ("att" + suffix)
                f.write_bytes(data)
                inner = convert(f, depth=depth + 1, ocr=kw.get("ocr", "auto"))
            if inner.get("ok"):
                sections.append(_section("att-%d" % n, "Attachment: %s" % name,
                                         strip_anchors("\n\n".join(s["text"] for s in inner["sections"])), 2))
            else:
                warnings.append("attachment %s: %s" % (name, inner.get("error")))
    if listed:
        sections[0]["text"] += "\n\nAttachments:\n" + "\n".join(listed)
    return {"title": str(msg.get("Subject") or path.stem), "sections": sections, "pages": 1, "backend": "built-in eml",
            "warnings": warnings}


def read_image(path: Path, ocr: str = "auto", describe: bool = False, vision=None, **_kw) -> dict:
    data = path.read_bytes()
    w, h = image_size(data)
    if not w:
        try:
            from PIL import Image  # pylint: disable=import-outside-toplevel
            w, h = Image.open(io.BytesIO(data)).size
        except Exception:  # noqa: BLE001
            pass
    warnings, parts, backend = [], ["Picture %s%s" % (path.name, " (%dx%d)" % (w, h) if w else "")], "image"
    png = _to_png(data)
    if str(ocr or "auto").lower() not in ("0", "off", "false", "no"):
        got = ocr_image(png)
        if got.get("ok"):
            backend += "+ocr:" + got["engine"]
            if got["text"].strip():
                parts.append("### Text in the picture\n\n" + _clean_text(got["text"]))
            else:
                parts.append("(no text found in the picture)")
        else:
            warnings.append(got.get("error", "OCR failed"))
    if describe:
        if vision is None:
            warnings.append("no vision model to describe the picture (set LOKI_VISION_MODEL)")
        else:
            try:
                said = vision(png, "Describe this picture for someone who cannot see it: what it shows, any text, "
                                   "charts or tables (give their numbers). Be concise and factual.")
                parts.append("### Description\n\n" + _clean_text(said))
                backend += "+vision"
            except Exception as exc:  # noqa: BLE001
                warnings.append("the vision model failed: %s" % str(exc)[:160])
    return {"title": path.stem, "sections": [_section("img", "Picture", "\n\n".join(parts), 2)], "pages": 1,
            "backend": backend, "warnings": warnings}


def read_notebook(path: Path, **_kw) -> dict:
    try:
        nb = json.loads(read_text_file(path))
    except ValueError as exc:
        raise DocError("not a valid notebook (bad JSON)") from exc
    sections, n = [], 0
    for cell in nb.get("cells", []):
        src = "".join(cell.get("source", [])) if isinstance(cell.get("source"), list) else str(cell.get("source", ""))
        n += 1
        if cell.get("cell_type") == "markdown":
            text = src
        else:
            outs = []
            for o in cell.get("outputs", []) or []:
                t = o.get("text") or (o.get("data") or {}).get("text/plain") or ""
                outs.append("".join(t) if isinstance(t, list) else str(t))
            text = "```python\n%s\n```" % src + ("\n\nOutput:\n```\n%s\n```" % "\n".join(outs)[:3000] if any(outs) else "")
        sections.append(_section("cell-%d" % n, "Cell %d (%s)" % (n, cell.get("cell_type", "code")), text, 2))
    return {"title": path.stem, "sections": sections, "pages": len(sections), "backend": "built-in ipynb", "warnings": []}


def read_plain(path: Path, **_kw) -> dict:
    text = read_text_file(path)
    if path.suffix.lower() in (".md", ".markdown"):
        sections = _split_markdown(text)
    else:
        sections = [_section("text", path.name, text, 2)]
    return {"title": path.stem, "sections": sections, "pages": 1, "backend": "text", "warnings": []}


def read_legacy(path: Path, **kw) -> dict:
    """.doc/.xls/.ppt/.rtf/.odt -> LibreOffice (soffice --headless --convert-to) -> the OOXML reader."""
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe and sys.platform == "darwin" and Path("/Applications/LibreOffice.app/Contents/MacOS/soffice").exists():
        exe = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    if not exe and sys.platform == "win32":
        for base in (os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")):
            cand = Path(base) / "LibreOffice" / "program" / "soffice.exe"
            if base and cand.exists():
                exe = str(cand)
    target = {".doc": "docx", ".rtf": "docx", ".odt": "docx", ".xls": "xlsx", ".ods": "xlsx", ".ppt": "pptx",
              ".odp": "pptx"}[path.suffix.lower()]
    if not exe:
        if _has("markitdown"):
            return read_markitdown(path)
        raise DocError("%s files need LibreOffice (free, libreoffice.org) or the documents add-on" % path.suffix)
    with tempfile.TemporaryDirectory(prefix="loki-lo-") as tmp:
        profile = Path(tmp) / "profile"
        argv = [exe, "-env:UserInstallation=" + profile.as_uri(), "--headless", "--convert-to", target,
                "--outdir", tmp, str(path)]
        try:
            subprocess.run(argv, capture_output=True, timeout=180, **_no_window())
        except subprocess.TimeoutExpired as exc:
            raise DocError("LibreOffice took too long to convert it") from exc
        out = Path(tmp) / (path.stem + "." + target)
        if not out.is_file():
            raise DocError("LibreOffice could not convert %s" % path.name)
        got = READERS["." + target](out, **kw)
    got["backend"] = "libreoffice+" + got.get("backend", "")
    return got


def read_markitdown(path: Path, **_kw) -> dict:
    from markitdown import MarkItDown  # type: ignore # pylint: disable=import-outside-toplevel
    result = MarkItDown().convert(str(path))
    md = getattr(result, "markdown", None) or getattr(result, "text_content", "") or ""
    slides = re.split(r"<!-- Slide number: (\d+) -->", md)
    if len(slides) > 2:
        sections = [_section("slide-%s" % slides[i], "Slide %s" % slides[i], slides[i + 1], 2, int(slides[i]))
                    for i in range(1, len(slides) - 1, 2)]
    else:
        sections = _split_markdown(md)
    return {"title": getattr(result, "title", None) or path.stem, "sections": sections, "pages": len(sections),
            "backend": "markitdown", "warnings": []}


READERS = {}
for _s in PDF:
    READERS[_s] = read_pdf
for _s in DOCX:
    READERS[_s] = read_docx
for _s in XLSX:
    READERS[_s] = read_xlsx
for _s in PPTX:
    READERS[_s] = read_pptx
for _s in CSVS:
    READERS[_s] = read_csv
for _s in HTML:
    READERS[_s] = read_html
for _s in EPUB:
    READERS[_s] = read_epub
for _s in EML:
    READERS[_s] = read_eml
for _s in IMAGES:
    READERS[_s] = read_image
for _s in NOTEBOOK:
    READERS[_s] = read_notebook
for _s in LEGACY:
    READERS[_s] = read_legacy
for _s in TEXT:
    READERS[_s] = read_plain


def kind_of(path) -> str:
    s = Path(path).suffix.lower()
    for name, group in (("pdf", PDF), ("docx", DOCX), ("xlsx", XLSX), ("pptx", PPTX), ("csv", CSVS), ("html", HTML),
                        ("epub", EPUB), ("email", EML), ("image", IMAGES), ("notebook", NOTEBOOK), ("office", LEGACY)):
        if s in group:
            return name
    if s in (".md", ".markdown"):
        return "markdown"
    if s in TEXT:
        return "text"
    return "other"


def convert(path, ocr: str = "auto", describe: bool = False, vision=None, password: str = "", engine: str = "",
            depth: int = 0) -> dict:
    """Any file -> {"ok", "path", "format", "title", "markdown", "sections", "pages", "backend", "warnings",
    "error", "seconds"}. Never raises."""
    started = time.monotonic()
    path = Path(path)
    out = {"ok": False, "path": str(path), "format": kind_of(path), "title": path.stem, "markdown": "",
           "sections": [], "pages": 0, "backend": "", "warnings": [], "error": ""}
    try:
        if not path.is_file():
            raise DocError("no such file: %s" % path.name)
        if path.stat().st_size > MAX_FILE_BYTES:
            raise DocError("the file is larger than %d MB" % (MAX_FILE_BYTES // 1048576))
        reader = READERS.get(path.suffix.lower())
        if reader is None:
            if _has("markitdown"):
                reader = read_markitdown
            else:
                head = path.read_bytes()[:2048]
                if b"\x00" in head:
                    raise DocError("LOKI cannot read %s files yet (install the documents add-on for more formats)"
                                   % (path.suffix or "these"))
                reader = read_plain
        got = reader(path, ocr=ocr, describe=describe, vision=vision, password=password, engine=engine, depth=depth)
        out.update(got)
        out["markdown"] = build_markdown(out["title"], out["sections"])
        out["ok"] = True
    except DocError as exc:
        out["error"] = str(exc)
    except Exception as exc:  # noqa: BLE001 - a broken file never breaks the caller
        out["error"] = "could not read %s: %s: %s" % (path.name, type(exc).__name__, str(exc)[:200])
    out["seconds"] = round(time.monotonic() - started, 2)
    return out


# --------------------------------------------------------------------------- cache + chunks
def cache_key(path: Path, **opts) -> str:
    st = Path(path).stat()
    raw = "%s|%d|%d|%s" % (Path(path).resolve(), st.st_size, st.st_mtime_ns, json.dumps(opts, sort_keys=True))
    return hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()[:20]


def convert_cached(path, cache_dir, **opts) -> dict:
    """convert() with the result kept in cache_dir/<key>.json until the file changes."""
    path = Path(path)
    try:
        key = cache_key(path, **{k: v for k, v in opts.items() if k != "vision"})
    except OSError:
        return convert(path, **opts)
    folder = Path(cache_dir)
    hit = folder / (key + ".json")
    try:
        data = json.loads(hit.read_text(encoding="utf-8"))
        if data.get("ok"):
            data["cached"] = True
            return data
    except (OSError, ValueError):
        pass
    got = convert(path, **opts)
    if got.get("ok"):
        try:
            folder.mkdir(parents=True, exist_ok=True)
            tmp = hit.with_suffix(".tmp")
            tmp.write_text(json.dumps(got, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, hit)
        except OSError:
            pass
    return got


def chunks(doc: dict, size: int = 900) -> list:
    """[(n, text, anchor)] - each section in ~size-character windows (paragraph boundaries), the section title
    leading every window so a passage is understandable alone."""
    out, n = [], 0
    for s in doc.get("sections") or []:
        head = s.get("title") or ""
        paras = [p for p in re.split(r"\n\s*\n", s.get("text") or "") if p.strip()] or ([head] if head else [])
        buf = ""
        for p in paras:
            if buf and len(buf) + len(p) > size:
                n += 1
                out.append((n, (head + "\n" + buf).strip(), s["anchor"]))
                buf = ""
            while len(p) > size * 2:
                n += 1
                out.append((n, (head + "\n" + p[:size * 2]).strip(), s["anchor"]))
                p = p[size * 2:]
            buf = (buf + "\n\n" + p) if buf else p
        if buf.strip():
            n += 1
            out.append((n, (head + "\n" + buf).strip(), s["anchor"]))
    return out


def select(doc: dict, pages: str = "", section: str = "") -> list:
    """The sections a reader asked for: pages "3", "2-5", "1,4-6" (PDF pages / slides / sheets by number) or
    a section anchor / title words."""
    sections = doc.get("sections") or []
    if section:
        want = str(section).strip().lstrip("#").lower()
        hit = [s for s in sections if s["anchor"].lower() == want]
        if not hit:
            hit = [s for s in sections if want in s["title"].lower() or want in s["anchor"].lower()]
        return hit
    if pages:
        nums = set()
        for part in re.split(r"[,\s]+", str(pages)):
            m = re.match(r"^(\d+)(?:-(\d+))?$", part.strip())
            if m:
                a, b = int(m.group(1)), int(m.group(2) or m.group(1))
                nums.update(range(min(a, b), min(max(a, b), a + 500) + 1))
        return [s for i, s in enumerate(sections, 1) if (s.get("page") or i) in nums]
    return sections
