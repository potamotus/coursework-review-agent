# Methodology

Place your methodology document here as `methodology.md` (plain text, markdown-friendly).

This file is **gitignored** — methodology content is typically copyrighted and user-specific.

## If you have a PDF methodology

Convert it to markdown once:

```bash
# via poppler's pdftotext
pdftotext "your-methodology.pdf" methodology.md
```

Then optionally clean up the top/bottom if the PDF has title-page and table-of-contents boilerplate. The tool uses the text verbatim for string-match citation — do NOT paraphrase or "fix" OCR glitches. If your PDF extracted `e clusive` instead of `exclusive`, that's what the tool will match against.

## What matters for this file

- **Verbatim content** — every methodology requirement the agent cites must appear here exactly. The agent's output passes through a mechanical substring check against this file before any comment gets posted.
- **Full content** — the agent reads the whole file per review to avoid missing cross-cutting requirements.
- **Section headings** (optional but useful) — makes it easier for the agent to reference sections in comments.
