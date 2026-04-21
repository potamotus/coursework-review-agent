# Claude Code skill template

Drop this into `~/.claude/skills/review/SKILL.md` (create the directory if needed). Replace `<ABSOLUTE_PATH_TO_REVIEW_AGENT>` and `<YOUR_SA_EMAIL>` with your own values.

---

```markdown
---
name: review
description: Review a teammate's Google Docs artifact against the user's methodology file, with mechanical string-match verification of every cited quote. Triggers on "review", "check", "проверить", "дать ревью", and variants.
user-invokable: true
---

# Review agent

Tasks live in a Google Sheets tab; each task has an artifact URL (Google Doc).

| Flow | Trigger | Output |
|---|---|---|
| **A — Methodology + citation compliance** | "review", "check against methodology" | Comments posted to Google Doc |
| **B — Quality / subjective** | "quality review", "style check" | `review_agent/AI_reviews/<YYYYMMDD>_<slug>.md` |

**Flows are independent. Never mix B into A.**

## Location

`<ABSOLUTE_PATH_TO_REVIEW_AGENT>/`

## CLI

```bash
cd "<ABSOLUTE_PATH_TO_REVIEW_AGENT>"
./venv/bin/python review.py <command>
```

| Command | Purpose |
|---|---|
| `pending` | List tasks with ready-status (config-driven) |
| `fetch <row\|url>` | Task meta + full artifact text (tables included) + methodology path |
| `post-comments <doc_id> <file.json>` | Post batch; CLI verifies every quote via string-match before posting |
| `delete-comment <doc_id> <comment_id>` | Remove a comment |
| `save-private <slug> <file.md>` | Flow B output |

---

## Core rule: **quote or drop**

**Every public finding must be backed by verbatim quotes** — from methodology, artifact, or fetched source. The CLI mechanically verifies each quote (normalized-whitespace substring match) before posting. Unverified → `REJECTED`, not posted.

- **Methodology is always cited word-for-word.** No paraphrase, no summary, no approximation.
- If you can't produce the exact text — **drop the finding**. Never edit a quote to force it through.
- Barrier catches fabrication, not misinterpretation.

---

## Flow A pipeline

**1. Load everything.**
- `fetch <row|url>` → task + full artifact text (tables marked `[TABLE]..[/TABLE]`).
- `Read` the methodology file **in full**. No skimming, no partial reads.

**2. Systematic comparison, section by section.**
- Walk the methodology in order. For every prescriptive element — check the artifact.
- Use only text present in the files. Don't project expected requirements.

**3. Fact-check every citation.**
- For each citation in the artifact, fetch the source URL via `WebFetch` or `firecrawl-scrape`.
- Locate verbatim text that supports or contradicts the specific claim.
- Reachable, claim present: no finding.
- Reachable, claim not there: verdict `source_absent_of_claim`, `source_quote` = verbatim closest content.
- Reachable, claim contradicted: verdict `source_contradicts`, `source_quote` = verbatim contradicting text.
- Unreachable (paywall / 404 / bot block): verdict `source_unreachable`, `source_url` set, `source_quote: null`. Never fabricate.
- Factual claim with no citation that clearly needs one: verdict `missing_citation`, both `source_url` and `source_quote` = null.

**4. Build candidates JSON** (schema below).

**5. Show list to user for approval.** For each finding emit one line: `type` + `methodology_section`/`verdict` + a ≤10-word restatement of `violation`/`issue`. Not the full JSON. Wait for explicit yes.

**6. Post.** `post-comments <doc_id> <file>`. On `REJECTED` — fix the quote or drop the finding. Never paraphrase to get past the check.

**7. Remind user to audit.** Open the comments panel, skim the posted comments before relying.

## Flow B pipeline

Free-form markdown. Every concern that references specific artifact text **must include a verbatim blockquote** of that text. `save-private <slug> <path>`.

---

## JSON schema

```json
[
  {
    "type": "methodology_violation",
    "methodology_quote": "verbatim from methodology file",
    "methodology_section": "section label",
    "artifact_quote": "verbatim from artifact (present-and-wrong case)",
    "artifact_absence": "short description of what's missing (absence case)",
    "violation": "- bullet\n- bullet"
  },
  {
    "type": "citation_check",
    "verdict": "source_contradicts | source_absent_of_claim | source_unreachable | missing_citation",
    "artifact_claim": "verbatim claim from artifact",
    "source_url": "https://... or null",
    "source_quote": "verbatim from source or null",
    "issue": "- bullet"
  }
]
```

**Quote rules:**
- Copy exactly. Don't fix typos, normalize quotes, or clean OCR glitches — match the file as-is.
- Whitespace normalized by verifier; **content must match byte-for-byte**.
- Shortest self-contained anchor.
- `citation_check` with verdict `source_contradicts` or `source_absent_of_claim` **requires** `source_quote` (verbatim from fetched page). `source_unreachable` and `missing_citation` → `source_quote: null`.

---

## Posted comment — hard rules

- **No emojis. Anywhere.** Not in JSON fields, not in body, not in `violation` / `issue`. No exceptions.
- **`violation` / `issue` = bullet list.** Each line starts with `- `, joined by `\n`. Concise; many short bullets beat one long sentence.
- **Body is assembled by CLI.** You fill slots — it emits these fixed structures:

Headers wrapped in `*…*` (Google Docs Slack-style bold in comments). Each header on its own line; value on the next line.

`methodology_violation`:
```
*Cmd+F для поиска:*
«<artifact_quote>»

*Цитата из методички (раздел <section>):*
«<methodology_quote>»

*Чего не хватает:*
<violation bullets, as written>
```

`citation_check`:
```
*Cmd+F для поиска:*
«<artifact_claim>»

*Источник:*
<source_url>
(or standalone line "*Источник не указан*" if null)

*Из источника:*
«<source_quote>»
(block omitted if null)

*Проблема:*
<issue bullets, as written>
```

Don't restructure. Only the labels are bold — values and bullet text stay plain.

---

## Operational

- **Do not add `anchor` or `quotedFileContent` fields.** CLI ignores them; reader uses the Cmd+F hint in the body.
- **SA identity.** Comments sign as `<YOUR_SA_EMAIL>`. Mention once per session if relevant.
- **Access errors.** `fetch` returns 403 → user needs to share the artifact with SA as Commenter.

## Paths

- Methodology: `review_agent/methodology/methodology.md`
- Private reviews: `review_agent/AI_reviews/`
- Log: `review_agent/reviews_log.jsonl`
```
