# Claude Code skill template

Drop this into `~/.claude/skills/review/SKILL.md` (create the directory if needed). Adapt the path at the top to your local checkout.

---

```markdown
---
name: review
description: Review a teammate's work on a coursework/project artifact against a methodology document. Produces compliance comments posted to Google Docs (objective, with verbatim methodology citations and source fact-checks) and/or a private subjective quality review saved to AI_reviews/. Use when the user asks to "review", "check", or "give feedback" on a task or when they ask what's ready for review.
user-invokable: true
---

# Review agent

The user is a team lead reviewing teammates' work. Tasks are listed in a Google Sheets tab; each task has an artifact URL (Google Doc). This skill produces two kinds of review output:

| Flow | Trigger | Output | Nature |
|---|---|---|---|
| **A. Methodology compliance + fact-check** | "review task N for methodology" | Comments posted to Google Doc | Objective, every finding backed by verbatim quote |
| **B. Quality / subjective** | "quality review task N" | `AI_reviews/<date>_<slug>.md` | Free-form but artifact-quoted |

## Location
<adapt path>/review_agent/

## CLI
Always via venv:
```bash
cd <path>/review_agent
./venv/bin/python review.py <command>
```

| Command | Purpose |
|---|---|
| `pending` | List tasks with ready status |
| `fetch <row>\|<url>` | JSON: task meta + artifact text + methodology path |
| `post-comments <doc_id> <file.json>` | Post, with mechanical quote verification |
| `delete-comment <doc_id> <comment_id>` | Remove a comment |
| `save-private <slug> <file.md>` | Save subjective review |

## Anti-hallucination protocol (CRITICAL)

The system has a string-match barrier. **Every comment's quotes are verified verbatim** against methodology and doc content before posting. Unverified → REJECTED.

Your job: **only produce findings that can be backed by verbatim quotes**. If you can't find the exact text in the methodology to support your claim — don't make the claim.

## Flow A

1. Run `pending` or `fetch <row>` — get task, artifact text, methodology path
2. Read the WHOLE methodology via `Read` tool (full coverage required)
3. For each potential issue, classify:
   - **`methodology_violation`**: artifact misses/violates a methodology requirement
   - **`citation_check`**: with verdict `source_contradicts | source_absent_of_claim | source_unreachable | missing_citation`
4. For `citation_check` verifying a source: **actually fetch it** via WebFetch or firecrawl and quote verbatim. If fetch fails → `source_unreachable`, don't fabricate.
5. Write candidates JSON to `/tmp/review_candidates_<task>.json`:

```json
[
  {
    "type": "methodology_violation",
    "methodology_quote": "verbatim from methodology, exactly",
    "methodology_section": "2.4 (optional)",
    "artifact_quote": "verbatim from artifact (or null if absence)",
    "artifact_absence": "short description (or null if quote present)",
    "violation": "- bullet 1\n- bullet 2"
  }
]
```

6. **Show candidates to user, get approval.** Never post without confirmation.
7. On approval: `post-comments <doc_id> <file.json>`. If any REJECTED, show the reason (quote not found verbatim) and iterate.

## Flow B

Free-form subjective analysis in markdown. Structure: concerns with verbatim blockquotes from artifact. Save via `save-private`.

## Strict comment formatting rules

- **NO emojis.** Ever. In comment body, in violation text, in issue text.
- **`violation` / `issue` fields: bullet points** (each line starts with `- `).
- Comment body built automatically as: `Cmd+F...` → methodology quote → bulleted gaps.

## Known limitation: Google Docs comment anchoring

Drive API `anchor` and `quotedFileContent` are saved but ignored by Google Docs UI (documented Google-side limitation). Comments show in the panel, not as side-bubbles. We don't send them — the Cmd+F hint in the body is the reader's jump-to mechanism.
```
