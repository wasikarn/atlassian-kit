---
name: jira-content
description: "Create or edit template-shaped Jira content — Bug/Story/Task/Epic/Sub-task descriptions and templated comments (status update/QA verification/blocker/decision record) — against the team's REQUIRED formats (GWT Acceptance Criteria, Thai PO/QA structure), whether acli or the Atlassian MCP does the write. Use BEFORE calling `acli jira workitem create/edit` or any Jira-create MCP tool — never hand-build template-shaped content."
when_to_use: "Trigger on ANY intent to create/file/open/log/report/raise a bug, defect, issue, story, task, epic, or sub-task, or to write/format/fix a Jira issue's description or a structured comment — Thai or English, e.g. 'สร้างบั๊ก', 'แตก sub-task ให้หน่อย', 'file a bug for X', 'open a ticket about Y', 'add a status update to PROJ-123', 'คอมเมนต์อัปเดตความคืบหน้า PROJ-123'. Also trigger when ANOTHER skill's instructions say 'publish this to the tracker/backlog' or 'file this PRD as an issue' — a foreign content shape (PRD, code-review finding, to-do) is never the Jira template; convert to this skill's shape first, don't pass it straight to acli/MCP. Don't use for Confluence pages/specs/PRDs (atlassian-kit:confluence-content), or for search, view, transition, link, clone, bulk ops, JQL export, Confluence blog/space/admin, or a trivial one-line comment (atlassian-kit:ops)."
---

# Jira Content

Create or edit the **content** of a Jira Bug/Story/Task/Epic/Sub-task, or a templated comment — against the team's canonical templates. Defaults to the **PROJ board** when the user doesn't name a project; works on any project / Atlassian site. Jira only — Confluence pages/specs are `atlassian-kit:confluence-content`'s job.

**Backend: acli-first with Atlassian MCP fallback** — `atlassian-kit:ops` is the mechanical tool this skill drives. This skill owns *what goes in the body*. Templates in `${CLAUDE_SKILL_DIR}/templates/` — see [`templates/README.md`](templates/README.md) for the index.

## When to use this skill vs acli vs confluence-content

- **This skill** — create/edit Jira Bug/Story/Task/Epic/Sub-task content or a templated comment.
- **`atlassian-kit:confluence-content`** — Confluence Spec/PRD page.
- **`atlassian-kit:ops`** — search, view, transition, link, clone, bulk ops, JQL export, Confluence blog/space/admin, trivial one-line comments.

## Step 1 — Pick the type and gather

| What | Template | Gather |
|---|---|---|
| Bug | `templates/bug.md` | Guided: ask its gather questions |
| Story | `templates/story.md` | Guided: ask its gather questions |
| Task | `templates/task.md` | Guided: ask its gather questions |
| Epic | `templates/epic.md` | Guided: ask its gather questions |
| Sub-task | `templates/subtask.md` | Guided: ask its gather questions; needs a parent key |
| Templated comment | `templates/comments.md` | Ask which of the 4 (status/QA/blocker/decision), then its fields |

```bash
cat "${CLAUDE_SKILL_DIR}/templates/bug.md"   # or story.md, task.md, epic.md, subtask.md, comments.md
```

Ask the type with `AskUserQuestion` when it is not clear, and all gather questions **at once, not one by one**, as free text. If the user already provided enough, skip to Step 2. Ask the optional fields in [`templates/fields.md`](templates/fields.md) in the same message; a field the user leaves out stays unset.

## Step 1b — Check for existing tickets

Before Step 2 on every create, run the duplicate check in [`../../templates/intake.md`](../../templates/intake.md) and let the user choose when it finds a likely match. Closed choices (type, duplicate pick, preview go-ahead) go through `AskUserQuestion`; see its § How to ask. When the user names an existing ticket key, skip Step 1 and use the update flow in the same file. The preview in Step 4 is shown for every create and update, the label `test` included.

## Step 2 — Format the content

Write the body in **Thai** using the matching template. Wording rules for the ticket text are in [`../../templates/writing-rules.md`](../../templates/writing-rules.md). Run its passes on the draft before the preview. **AC format/register/coverage rules are canonical in [`../../templates/acceptance-criteria.md`](../../templates/acceptance-criteria.md) — never restate them, just apply them.**

## Step 3 — Resolve issue metadata

*(Skip for comments.)* Resolve at runtime; never hardcode IDs except the default project key `PROJ`.

- **Site** — `acli jira auth status`. For MCP, `mcp__plugin_atlassian_atlassian__getAccessibleAtlassianResources`. Ask if several.
- **Project key** — User request; default `PROJ` only when the content is plausibly work for that project. If the ticket is clearly about something else (a different product, a personal project, generic content with no signal for that project), ask for the real project key instead of silently filing it under `PROJ` — the default is a convenience for the common case, not a license to guess the project. Validate via `acli jira project view --key <KEY>` before create. Fall back to `mcp__plugin_atlassian_atlassian__listJiraProjects` (v1: `getVisibleJiraProjects`) (deferred on v2: `executeRead(name="listJiraProjects", cloudId=…, inputs={"action": "create"})` lists projects you can create in, see `ops/SKILL.md` § "When acli can't") only if acli is unavailable/unauthed.
- **Issue type** — Matches Step 1's pick. acli has no issue-type-metadata command; confirm via `mcp__plugin_atlassian_atlassian__listJiraProjectIssueTypesMetadata` (v1: `getJiraProjectIssueTypesMetadata`) (deferred on v2: reach it via `executeRead`, see `ops/SKILL.md` § "When acli can't") if create rejects. If the project key is still unresolved among multiple plausible candidates, check issue-type support on those candidates proactively (same MCP call) before asking the user to pick — narrowing "which of these projects" down to only the ones that actually support the requested type is a more useful question than a blind pick-one-of-N.
- **Other fields** (priority beyond the default, assignee, due date, start date, components, fix versions) — [`templates/fields.md`](templates/fields.md) lists what each type supports, the value format and what is not supported yet.
- **Priority** — **Bug:** money/data-loss/blocked-workflow → `High`; functional w/ workaround → `Medium`; cosmetic → `Low`. **Others:** `Medium` unless user says otherwise.
- **Labels** — `bug` + 1-2 domain tags (Bug); 1-2 domain tags (others). Do NOT auto-add PO/QA labels.
- **Environment** *(Bug only)* — Native Jira field. prod/staging/local. Wrap in ADF for MCP fallback.
- **Affects versions** *(Bug only)* — Only if user gives a valid version; validate or omit.
- **Parent** *(Sub-task only)* — Required. Sub-tasks can't be created without one.
- **Assignee** — Don't set one by default (Jira then applies the project's default assignee, which can be the project lead, not unassigned). Only set if user names one. acli's `--assignee` only resolves `@me`/`default`/email; a raw accountId for anyone *other than yourself* silently unassigns instead (see `atlassian-kit:ops`'s `REFERENCE.md`). When email is privacy-hidden, resolve via `mcp__plugin_atlassian_atlassian__lookupJiraAccountId` (deferred on v2: `executeRead(name="lookupJiraAccountId", cloudId=…, inputs={"query": "<name|email>"})`, see `ops/SKILL.md` § "When acli can't"; v1 took `searchString`), then set `assignee` on v2 (v1: `assignee_account_id`).

## Step 4 — Preview and confirm

Show resolved metadata + Thai title + rendered content + chosen backend as a review surface. If the type has an AC section, confirm it covers error + boundary + regression paths (see [`../../templates/acceptance-criteria.md`](../../templates/acceptance-criteria.md)). Create/send **only on the user's explicit go-ahead** — this gate is the safeguard against unwanted writes.

`md2adf.sh`/`adf2md.py` (the acli-path preview mechanism in 5a) only carry summary/project/type/labels/parent. Every field passed with `-a` (`additionalAttributes`: priority, environment, affects-version and the rest) and `--assignee` (email or account ID) never appear in that rendered card even when resolved. State them in prose alongside the rendered card rather than assuming the script surfaces them. Priority, due date, start date, components and fix versions are set at create time with `md2adf.sh -a` (see [`templates/fields.md`](templates/fields.md)); environment and affects-version go the same way (ADF document and `[{"name": ...}]`; see the Bug only section of `fields.md`).

Before showing the preview, re-read the metadata table you're about to display against the actual flag/payload values you're about to send — rendering only proves a value is syntactically valid, not that it matches what you stated as resolved. Confirmed failure mode: a Bug's metadata table stated Labels as `bug`, `billing`, `csv-export`, but the actual `-l` flag and MCP `additional_fields.labels` carried only `billing,csv-export` — `bug` silently dropped between what was claimed resolved and what was typed into the command, and rendering caught nothing because `billing,csv-export` is a perfectly valid label list on its own. A field the render mechanism does carry (like labels) is not automatically safe just because it isn't on the priority/environment/affects-version blind-spot list above.

This check isn't limited to fields the metadata table displays — a payload-only value like `cloudId` (needed for any MCP call, including one offered as a non-default option) is just as capable of being silently wrong, and the table has no row for it to be cross-checked against. Resolve `cloudId` via `mcp__plugin_atlassian_atlassian__getAccessibleAtlassianResources` before writing it into any MCP payload — the site's hostname (e.g. `<site>.atlassian.net`, the value shown in the table's own "Site" row) is not a `cloudId` and will fail the call; confirmed failure mode: a drafted MCP option used the hostname string in the `cloudId` field instead of the resolved GUID.

## Step 5 — Create

Default to `acli`. Fall back to Atlassian MCP only when acli is unavailable, unauthenticated, or cannot set a required field. "Required" means the *user* explicitly stated a value for a field acli's create schema can't carry (e.g. an explicit environment) — that's what forces the whole create over to MCP. A value *you* inferred rather than the user stating it (e.g. assuming Environment=prod from context) doesn't force the switch by itself: keep acli as the default and state the inferred value in prose per Step 4, since the user hasn't confirmed it yet either. Two drafts can correctly land on different defaults for this reason — check which case actually applies before reading that as an inconsistency.

### 5a — Jira issue via acli (default)

```bash
acli jira auth status
# Bug/Story — guided Markdown → ADF
bash "${CLAUDE_SKILL_DIR}/scripts/md2adf.sh" /tmp/ticket.md \
  -s "<Thai summary>" -p <projectKey> -t <Bug|Story> -l "<labels>" > /tmp/wi.json
# Task/Epic/Sub-task — fill templates/*.payload.json placeholders directly, or convert Markdown:
bash "${CLAUDE_SKILL_DIR}/scripts/md2adf.sh" /tmp/ticket.md \
  -s "<summary>" -p <projectKey> -t <Task|Epic|Sub-task> -l "<labels>" > /tmp/wi.json
# Sub-task additionally needs -P <parentKey> — omitting it produces an invalid create payload (Step 3: parent is required)

acli jira workitem create --from-json /tmp/wi.json --json
```

Reply: `✅ Created [PROJ-XXX](https://<site>.atlassian.net/browse/PROJ-XXX)`. Priority, due date, start date, components and fix versions go in at create time through `md2adf.sh -a` (see [`templates/fields.md`](templates/fields.md)). Bug's `environment` and `versions` go the same way; use `issue-set` only on an existing issue.

### 5b — Jira issue MCP fallback

Use it only for what acli cannot do (see `ops/SKILL.md` § "When acli can't"). Load [`mcp-fallback.md`](mcp-fallback.md) before calling any MCP tool; it holds the tool shapes, the v1 and v2 differences and the field list.

### 5c — Templated comment (on an existing ticket)

```bash
bash "${CLAUDE_SKILL_DIR}/scripts/md2adf.sh" note.md > /tmp/note.json   # bare doc mode — no -s/-p/-t
acli jira workitem comment create --key KEY-1 --body-file /tmp/note.json
```

## Editing an existing ticket or comment

Load [`editing.md`](editing.md): description edits (the read-modify-write scripts, never a blind replace) and edits to a templated comment. Both keep the preview-and-confirm gate of Step 4.

## Input Contract

- **Required (Bug):** Thai summary, actual behavior, expected behavior, impact.
- **Required (Story):** Thai summary, business reason, desired behavior, in/out scope, AC.
- **Required (Task/Epic/Sub-task):** the sections `templates/README.md` § Sections by type marks `always`; Sub-task also needs a parent.
- **Required (templated comment):** which of the 4 templates, and its fields.
- **Optional:** evidence (Bug), affected version (Bug), PO decision points (Story), explicit project key (defaults `PROJ`), explicit assignee.
- **Tooling:** prefers `acli` when installed + authed; falls back to Atlassian MCP. If neither, ask the user to run `acli jira auth login` or enable the Atlassian MCP.

## Output Format

- **Preview:** site, project, issue type, priority, labels, assignee (if any), Thai title, rendered content, chosen backend.
- **Result:** issue key + URL, or comment confirmation.

## Failure Modes

- `acli` not installed or not authed → prompt to auth or fall back to MCP.
- Project key or issue type does not exist on the resolved site.
- `environment` rejected as plain string (Bug) → retry with ADF wrapper.
- `versions` value not found (Bug) → stop; don't retry without it, since the user confirmed a preview that had it (the **Fail loud** rule). Put the exact error in the reply and ask for the right version name, or for an OK to create without it.
- Sub-task create rejected for missing/invalid parent → stop and ask for the right parent key; don't retry with a parent the user didn't confirm at the preview.
- Assignee email cannot be resolved → ask the user for another email or name. If they'd rather go without, say in the preview that Jira will apply the project's default assignee, which may be a person (assignee is not on the rendered card).
- User does not confirm at preview gate → creation/edit is skipped.

## Related

- `atlassian-kit:ops` — search, view, edit, transition, bulk ops, Confluence blog/space/admin, ADF↔markdown. The backend tool this skill invokes.
- `atlassian-kit:confluence-content` — Confluence Spec/PRD page content. The Confluence-side counterpart.
- `atlassian:triage-issue` — de-duping/triaging before filing (needs the official Atlassian plugin).
