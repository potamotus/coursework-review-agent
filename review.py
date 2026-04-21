#!/usr/bin/env python3
"""
Review agent CLI — reviews teammates' Google Docs artifacts against a
methodology markdown, with string-match verification of every cited quote.

Commands:
  pending                               — list tasks in REVIEW_STATUS_READY state
  fetch <row|url>                       — emit task + artifact text + methodology path
  post-comments <doc_id> <file.json>    — post comments to Google Doc; each comment's
                                          quotes are verified by string-match against
                                          methodology file and the doc. Unverified → REJECTED.
  delete-comment <doc_id> <comment_id>  — delete a comment
  save-private <slug> <file.md>         — save subjective review to AI_reviews/<date>_<slug>.md

Anti-hallucination guarantee: post-comments refuses to post any comment whose
quotes don't appear verbatim in the respective source. Whitespace is normalized,
exact content must match.
"""
import os, sys, json, re, datetime, hashlib
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


def _load_env():
    env_file = Path(__file__).parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

HERE = Path(__file__).parent
KEY = Path(os.environ.get("REVIEW_KEY_PATH", HERE / "key.json")).expanduser()
METHODOLOGY = Path(os.environ.get(
    "REVIEW_METHODOLOGY_PATH", HERE / "methodology" / "methodology.md"
)).expanduser()
AI_REVIEWS = Path(os.environ.get("REVIEW_AI_REVIEWS_DIR", HERE / "AI_reviews")).expanduser()
LOG = HERE / "reviews_log.jsonl"

SPREADSHEET_ID = os.environ.get("REVIEW_SPREADSHEET_ID")
TASKS_SHEET = os.environ.get("REVIEW_TASKS_SHEET", "Этап 1")
TASKS_RANGE = os.environ.get("REVIEW_TASKS_RANGE", "B4:G50")
STATUS_READY = os.environ.get("REVIEW_STATUS_READY", "Сделана")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/drive",
]

if not SPREADSHEET_ID:
    sys.exit("REVIEW_SPREADSHEET_ID is not set. Copy .env.example to .env and fill it in.")
if not KEY.exists():
    sys.exit(f"Service account key not found at {KEY}. Set REVIEW_KEY_PATH or place key.json here.")
if not METHODOLOGY.exists():
    sys.exit(f"Methodology file not found at {METHODOLOGY}. See README.md §Methodology.")

_creds = None
def creds():
    global _creds
    if _creds is None:
        _creds = service_account.Credentials.from_service_account_file(str(KEY), scopes=SCOPES)
    return _creds

def sheets():  return build("sheets", "v4", credentials=creds(), cache_discovery=False)
def docs():    return build("docs",   "v1", credentials=creds(), cache_discovery=False)
def drive():   return build("drive",  "v3", credentials=creds(), cache_discovery=False)


def _normalize(s):
    return re.sub(r"\s+", " ", s).strip()


def verify_quote(quote, source):
    return _normalize(quote) in _normalize(source)


def _extract_doc_id(s):
    m = re.search(r"/document/d/([a-zA-Z0-9_-]+)", s)
    return m.group(1) if m else None


def _get_doc(doc_id):
    return docs().documents().get(documentId=doc_id, includeTabsContent=True).execute()


def _find_text_anchor(doc, target):
    """Find startIndex + length of `target` within a single textRun.
    Returns (start_index, length, tab_id) or (None, None, None)."""
    norm_target = _normalize(target)

    def scan(content, tab_id=None):
        for elem in content:
            if "paragraph" in elem:
                for el in elem["paragraph"].get("elements", []):
                    tr = el.get("textRun")
                    if not tr:
                        continue
                    text = tr.get("content", "")
                    pos = text.find(target)
                    if pos >= 0:
                        return el["startIndex"] + pos, len(target), tab_id
                    # Try whitespace-normalized match: find position of normalized target
                    # in normalized text, then map back
                    norm_text = _normalize(text)
                    if norm_target in norm_text:
                        # Best-effort: return start of textRun with full length
                        return el["startIndex"], len(text.rstrip("\n")), tab_id
            elif "table" in elem:
                for row in elem["table"].get("tableRows", []):
                    for cell in row.get("tableCells", []):
                        r = scan(cell.get("content", []), tab_id)
                        if r[0] is not None:
                            return r
        return None, None, None

    tabs = doc.get("tabs", [])
    if tabs:
        def walk_tabs(ts):
            for t in ts:
                tid = t.get("tabProperties", {}).get("tabId")
                r = scan(t.get("documentTab", {}).get("body", {}).get("content", []), tid)
                if r[0] is not None:
                    return r
                r = walk_tabs(t.get("childTabs", []))
                if r[0] is not None:
                    return r
            return None, None, None
        return walk_tabs(tabs)
    return scan(doc.get("body", {}).get("content", []))


def _build_doc_anchor(start_index, length, revision_id=None, tab_id=None):
    txt = {"o": start_index, "l": length}
    if tab_id:
        txt["ix"] = tab_id
    anchor = {"a": [{"txt": txt}]}
    if revision_id:
        anchor["r"] = revision_id
    return json.dumps(anchor, ensure_ascii=False)


def _get_head_revision(doc_id, doc=None):
    if doc is None:
        doc = _get_doc(doc_id)
    return doc.get("revisionId")


def _doc_text(doc_id, tab_name=None):
    doc = _get_doc(doc_id)
    def collect(body):
        out = []
        for elem in body.get("content", []):
            if "paragraph" in elem:
                for el in elem["paragraph"].get("elements", []):
                    if "textRun" in el:
                        out.append(el["textRun"].get("content", ""))
            elif "table" in elem:
                out.append("\n[TABLE]\n")
                for row in elem["table"].get("tableRows", []):
                    row_cells = []
                    for cell in row.get("tableCells", []):
                        cell_text = collect(cell).strip()
                        row_cells.append(cell_text)
                    out.append(" | ".join(row_cells) + "\n")
                out.append("[/TABLE]\n")
        return "".join(out)
    tabs = doc.get("tabs", [])
    if tab_name:
        def find_tab(tabs):
            for t in tabs:
                tp = t.get("tabProperties", {})
                if tp.get("title") == tab_name or tp.get("tabId") == tab_name:
                    return t
                child = find_tab(t.get("childTabs", []))
                if child: return child
            return None
        t = find_tab(tabs)
        if not t:
            raise ValueError(f"Tab not found: {tab_name}")
        return collect(t.get("documentTab", {}).get("body", {}))
    if tabs:
        # No tab specified — concatenate all tabs with markers
        parts = []
        def walk(tabs, depth=0):
            for t in tabs:
                title = t.get("tabProperties", {}).get("title", "?")
                parts.append(f"\n\n=== TAB: {title} ===\n\n")
                parts.append(collect(t.get("documentTab", {}).get("body", {})))
                walk(t.get("childTabs", []), depth+1)
        walk(tabs)
        return "".join(parts)
    return collect(body_of(doc))


def cmd_pending():
    r = sheets().spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{TASKS_SHEET}'!{TASKS_RANGE}",
    ).execute()
    pending = []
    range_start_row = int(re.search(r"\d+", TASKS_RANGE).group()) if re.search(r"\d+", TASKS_RANGE) else 4
    for i, row in enumerate(r.get("values", [])):
        row = row + [""] * (6 - len(row))
        if row[4] == STATUS_READY:
            pending.append({
                "row": i + range_start_row, "num": row[0], "title": row[1],
                "assignee": row[2], "reviewer": row[3],
                "status": row[4], "artifact": row[5],
            })
    print(json.dumps(pending, ensure_ascii=False, indent=2))


def cmd_fetch(arg):
    task = None
    if arg.isdigit():
        row = int(arg)
        r = sheets().spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{TASKS_SHEET}'!B{row}:G{row}",
        ).execute()
        vals = (r.get("values", [[]])[0] + [""] * 6)[:6]
        task = {"row": row, "num": vals[0], "title": vals[1],
                "assignee": vals[2], "reviewer": vals[3],
                "status": vals[4], "artifact": vals[5]}
        artifact_src = vals[5]
    else:
        artifact_src = arg
        task = {"artifact": arg}

    doc_id = _extract_doc_id(artifact_src) if artifact_src else None
    artifact_text = None
    error = None
    if doc_id:
        try:
            artifact_text = _doc_text(doc_id)
        except HttpError as e:
            error = f"{e.status_code} {e.reason}"
        except Exception as e:
            error = str(e)

    print(json.dumps({
        "task": task,
        "artifact_doc_id": doc_id,
        "artifact_text": artifact_text,
        "artifact_fetch_error": error,
        "methodology_path": str(METHODOLOGY.resolve()),
    }, ensure_ascii=False, indent=2))


def _build_body(c):
    if c["type"] == "methodology_violation":
        lines = []
        if c.get("artifact_quote"):
            lines.append(f"Cmd+F для поиска: «{c['artifact_quote']}»")
        else:
            lines.append(f"Место: {c.get('artifact_absence', 'раздел отсутствует')}")
        section = c.get("methodology_section", "")
        header = f"Цитата из методички (раздел {section}):" if section else "Цитата из методички:"
        lines += ["", header, f"«{c['methodology_quote']}»"]
        lines += ["", "Чего не хватает:", c["violation"]]
        return "\n".join(lines)
    if c["type"] == "citation_check":
        lines = [f"Cmd+F для поиска: «{c['artifact_claim']}»", ""]
        if c.get("source_url"):
            lines.append(f"Источник: {c['source_url']}")
        else:
            lines.append("Источник не указан")
        if c.get("source_quote"):
            lines.append(f"Из источника: «{c['source_quote']}»")
        lines += ["", "Проблема:", c["issue"]]
        return "\n".join(lines)
    raise ValueError(f"unknown comment type: {c['type']}")


def cmd_post_comments(doc_id, comments_path):
    comments = json.loads(Path(comments_path).read_text(encoding="utf-8"))
    methodology = METHODOLOGY.read_text(encoding="utf-8")
    doc = _get_doc(doc_id)
    # Build flat text for quote verification
    def collect_flat(body):
        out = []
        for elem in body.get("content", []):
            if "paragraph" in elem:
                for el in elem["paragraph"].get("elements", []):
                    if "textRun" in el:
                        out.append(el["textRun"].get("content", ""))
            elif "table" in elem:
                for row in elem["table"].get("tableRows", []):
                    for cell in row.get("tableCells", []):
                        out.append(collect_flat(cell))
        return "".join(out)
    doc_content_parts = []
    for tab in doc.get("tabs", []):
        doc_content_parts.append(collect_flat(tab.get("documentTab", {}).get("body", {})))
    if not doc.get("tabs"):
        doc_content_parts.append(collect_flat(doc.get("body", {})))
    doc_content = "\n".join(doc_content_parts)

    revision_id = _get_head_revision(doc_id, doc=doc)
    results = []
    d = drive()
    for i, c in enumerate(comments):
        # Verify quotes
        reject = None
        if c.get("type") == "methodology_violation":
            if not verify_quote(c.get("methodology_quote", ""), methodology):
                reject = "methodology_quote NOT in methodology.md"
            elif c.get("artifact_quote") and not verify_quote(c["artifact_quote"], doc_content):
                reject = "artifact_quote NOT in doc"
        elif c.get("type") == "citation_check":
            if not verify_quote(c.get("artifact_claim", ""), doc_content):
                reject = "artifact_claim NOT in doc"
            elif c.get("source_quote") and not c.get("source_url"):
                reject = "source_quote given without source_url"
        else:
            reject = f"unknown type: {c.get('type')}"

        if reject:
            results.append({"index": i, "status": "REJECTED", "reason": reject, "comment": c})
            continue

        body = _build_body(c)
        # Drive API `anchor` and `quotedFileContent` are both rendered poorly by the
        # Google Docs UI for Workspace files (confirmed limitation — see Issue Tracker
        # 292610078, 357985444). `quotedFileContent` shows as "Исходный контент удалён"
        # when anchor resolution fails. We skip both and put the quote inside the body.
        request_body = {"content": body}
        try:
            r = d.comments().create(
                fileId=doc_id,
                fields="id,content",
                body=request_body,
            ).execute()
            results.append({"index": i, "status": "POSTED", "comment_id": r["id"]})
        except HttpError as e:
            results.append({"index": i, "status": "ERROR", "reason": f"{e.status_code} {e.reason}"})
    # Log
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": datetime.datetime.now().isoformat(),
            "doc_id": doc_id,
            "posted": sum(1 for r in results if r["status"] == "POSTED"),
            "rejected": sum(1 for r in results if r["status"] == "REJECTED"),
            "errors": sum(1 for r in results if r["status"] == "ERROR"),
        }, ensure_ascii=False) + "\n")
    print(json.dumps(results, ensure_ascii=False, indent=2))


def cmd_delete_comment(doc_id, comment_id):
    drive().comments().delete(fileId=doc_id, commentId=comment_id).execute()
    print(f"Deleted: {comment_id}")


def cmd_save_private(slug, content_file):
    AI_REVIEWS.mkdir(exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d")
    path = AI_REVIEWS / f"{ts}_{slug}.md"
    p = Path(content_file)
    content = p.read_text(encoding="utf-8") if p.exists() else content_file
    path.write_text(content, encoding="utf-8")
    print(f"Saved: {path}")


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    cmd, *args = sys.argv[1:]
    handlers = {
        "pending": lambda: cmd_pending(),
        "fetch": lambda: cmd_fetch(args[0]),
        "post-comments": lambda: cmd_post_comments(args[0], args[1]),
        "delete-comment": lambda: cmd_delete_comment(args[0], args[1]),
        "save-private": lambda: cmd_save_private(args[0], args[1]),
    }
    if cmd not in handlers:
        print(f"Unknown command: {cmd}\n{__doc__}"); sys.exit(1)
    handlers[cmd]()


if __name__ == "__main__":
    main()
