# coursework-review-agent

A command-line review agent that reads teammates' Google Docs artifacts, compares them against a methodology document, fact-checks every cited source, and posts verbatim-quoted comments back to the Doc — with a **mechanical anti-hallucination barrier** that physically prevents the agent from posting any claim it can't back with a literal quote.

> **Built for**: a team lead who has to review teammates' work against a rubric (university methodology, corporate style guide, technical spec) and wants an agent to do it without fabricating criticism.

## Why

AI review of prose has one catastrophic failure mode: the agent **manufactures findings**. It claims "the methodology requires X" where X isn't in the methodology, or "the source says Y" where Y isn't at the URL. Readers — especially the reviewed teammate — can't tell if the comment is legitimate until they manually check each citation. At scale this destroys trust.

This tool eliminates that failure mode at the CLI level: every comment body is built from JSON slots the agent fills, and before any comment is posted, the CLI runs a byte-exact substring check of the agent's quote against the source file. If the quote isn't present, the comment is **rejected, not posted**. Whitespace is normalized; content isn't. The agent can't invent a source quote because invention doesn't survive `str.__contains__`.

## Two-flow architecture

| Flow | Trigger | Output | Trust tier |
|---|---|---|---|
| **A. Methodology compliance + citation check** | "review task N for methodology" | Comments posted to Google Doc via Drive API | **Objective** — every finding backed by a verbatim methodology quote and/or verbatim source quote |
| **B. Quality / subjective review** | "quality review task N" | Markdown file in `AI_reviews/` (local, gitignored) | **Subjective** — free-form but still requires verbatim blockquotes from the artifact |

The two flows are **deliberately independent**. Flow A is public and defensible; Flow B is private and opinionated. Mixing them ships subjective opinions under an objective-looking interface.

## Features

- **Two Google APIs**: Sheets (task table), Docs (artifact content + tables), Drive (post comments).
- **Whitespace-normalized string-match verification** on every quote before posting.
- **Flexible CLI surface**: `pending`, `fetch`, `post-comments`, `delete-comment`, `save-private`.
- **Task-table layout**: standard B-G columns for #, title, assignee, reviewer, status, artifact URL.
- **Service-account auth** — no OAuth flow, works unattended.

## Setup

### 1. Google Cloud project

1. Create (or reuse) a Google Cloud project at https://console.cloud.google.com/
2. Enable three APIs:
   - **Google Sheets API** (`sheets.googleapis.com`)
   - **Google Docs API** (`docs.googleapis.com`)
   - **Google Drive API** (`drive.googleapis.com`)
3. Create a **service account** (IAM & Admin → Service Accounts → Create)
4. Add a **JSON key** for that service account; download it; save as `key.json` in this directory

### 2. Share your artifacts with the service account

The service account has an email like `my-sa@project.iam.gserviceaccount.com`. For the agent to read/comment on:
- The **tasks spreadsheet**: share with **Viewer** (Editor also works)
- Each **Google Doc artifact**: share with **Commenter** (or Editor)

The easiest scaling pattern: create a single Google Drive folder for all artifacts, share the folder with the service account once, have teammates drop artifacts into that folder.

### 3. Configure

```bash
cp .env.example .env
# edit .env and set REVIEW_SPREADSHEET_ID, REVIEW_TASKS_SHEET, status value
```

### 4. Methodology

Place your methodology as `methodology/methodology.md` — see [methodology/README.md](methodology/README.md) for conversion guidance.

The file is **gitignored** — each user keeps their own local copy.

### 5. Install

```bash
python -m venv venv
./venv/bin/pip install -r requirements.txt
```

### 6. Sanity check

```bash
./venv/bin/python review.py pending
```

Should print tasks matching your `REVIEW_STATUS_READY` value.

## Task table layout

The tool expects this exact column layout (configurable column letters via `REVIEW_TASKS_RANGE`, but positional semantics are fixed):

| Column | Meaning |
|---|---|
| B | Task number / ID |
| C | Task title |
| D | Assignee name |
| E | Reviewer name |
| F | Status (match against `REVIEW_STATUS_READY` for `pending` to pick up) |
| G | Artifact URL (Google Docs link; bare text is also tolerated but won't be fetchable) |

Header row(s) are skipped by starting `REVIEW_TASKS_RANGE` after them (default `B4:G50`).

## Commands

```bash
./venv/bin/python review.py pending
./venv/bin/python review.py fetch <row_number|url>
./venv/bin/python review.py post-comments <doc_id> <candidates.json>
./venv/bin/python review.py delete-comment <doc_id> <comment_id>
./venv/bin/python review.py save-private <slug> <path_to_md>
```

### Candidate JSON schema

For `post-comments`, input is an array of candidate comments:

```json
[
  {
    "type": "methodology_violation",
    "methodology_quote": "verbatim quote from methodology.md",
    "methodology_section": "2.3 Section name (optional)",
    "artifact_quote": "verbatim quote from artifact (optional if absence)",
    "artifact_absence": "short description (optional if artifact_quote set)",
    "violation": "- bullet one\n- bullet two"
  },
  {
    "type": "citation_check",
    "verdict": "source_contradicts | source_absent_of_claim | source_unreachable | missing_citation",
    "artifact_claim": "verbatim quote of the factual claim from the artifact",
    "source_url": "https://... (or null if missing_citation)",
    "source_quote": "verbatim quote from source page (or null if unreachable/missing)",
    "issue": "- bullet one\n- bullet two"
  }
]
```

**Every `*_quote` field is verified via normalized substring match** before posting. Failing checks → comment is tagged `REJECTED` and never posted.

## Posted comment format

Strict template, no decorative characters:

```
Cmd+F для поиска: «<artifact_quote>»

Цитата из методички (раздел 2.3):
«<methodology_quote>»

Чего не хватает:
- <gap 1>
- <gap 2>
```

## Design notes

**Three-tier trust surface.** Drive API for comments; Docs API for artifact read; Sheets API for tasks. Each has its own failure mode; the CLI isolates them.

**Mechanical anti-hallucination.** The CLI doesn't trust the LLM. It verifies every quote via substring match before posting. Whitespace normalization handles line breaks from the PDF-derived methodology file without allowing content substitution.

**No side-anchoring in Docs.** Drive API `anchor` and `quotedFileContent` are saved but ignored by the Google Docs UI for Workspace files (documented Google-side limitation: Issue Tracker 292610078, 357985444; googleworkspace/cli#169). Comments appear in the comments panel, not as bubbles on the margin. We put the quoted text inside the body with a `Cmd+F` hint instead. No public API works around this.

**What the barrier catches:** fabricated methodology requirements, fabricated artifact content, fabricated source quotes.
**What it does not catch:** misinterpretation of a real quote, selective reading, context-loss. Those require human review — which is why the workflow shows candidates for approval before posting.

## Integration with Claude Code (optional)

If you use [Claude Code](https://claude.com/claude-code), drop this skill template into `~/.claude/skills/review/SKILL.md`, adapt the paths at the top, and the agent will auto-invoke it when you say "review task N":

See [SKILL-TEMPLATE.md](SKILL-TEMPLATE.md).

## Project structure

```
.
├── review.py                   # the CLI (~250 lines)
├── .env.example                # config template
├── requirements.txt
├── LICENSE                     # MIT
├── methodology/
│   ├── README.md               # how to populate
│   └── methodology.md          # gitignored — your own
├── AI_reviews/                 # gitignored — Flow B output
├── key.json                    # gitignored — service account
└── SKILL-TEMPLATE.md           # optional Claude Code skill template
```

## License

MIT — see [LICENSE](LICENSE).

## Related

- [gantt-sheets-cli](https://github.com/potamotus/gantt-sheets-cli) — companion tool for managing Gantt charts in Google Sheets from the terminal.
