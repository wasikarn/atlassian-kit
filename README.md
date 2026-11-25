# atlassian-kit

An Atlassian toolkit for Claude Code covering Jira and Confluence: acli for search and bulk ops via JQL,
REST plan/apply scripts for what acli cannot do (versions, filters, boards, Confluence pages and
attachments, plus `jira-call`, `confluence-call` and `confluence-v1-call` for any other Jira or Confluence write from pinned indexes of Atlassian's OpenAPI specs), ADF↔markdown conversion, and template-conforming content authoring for Jira issues
and Confluence pages.

Extracted from [kbg-harness](https://github.com/wasikarn/kbg-harness) — it started as
skills inside a general engineering harness and moved out here to stand on its own.

## Skills

- **`acli`** — the mechanical backend for all Jira/Confluence work: search, view, edit,
  transition, comment, link, clone, bulk ops, Confluence space ops (full CRUD) and page
  reads (page *writes* are MCP-only — see `confluence-content`), org admin, ADF↔markdown
  conversion. Owns no content standard — a tool, same role as the Atlassian MCP.
- **`jira-content`** — creates or edits the *content* of a Jira Bug/Story/Task/Epic/
  Sub-task or a templated comment, against the team's canonical templates (Thai
  PO/QA-readable, GWT Acceptance Criteria), with a preview-and-confirm gate before any
  write. Calls into `acli`'s scripts to execute.
- **`confluence-content`** — the Confluence counterpart: creates or edits a Spec/PRD
  page's content against its own template. MCP-only (acli's `confluence page` command
  is view-only).

`jira-content` and `confluence-content` share one Acceptance Criteria rule
(`templates/acceptance-criteria.md`, at the plugin root) so the format can't drift
between the two products. All three skills ship together and are not separable.

## Agents

Two dispatchable subagents (`agents/*.md`) wrap the skills above for non-trivial,
multi-step work you'd rather hand off than drive call-by-call:

- **`jira-expert`** — Jira triage, bulk JQL ops, and template-conforming ticket/comment
  authoring. Backed by `acli` + `jira-content`.
- **`confluence-expert`** — Confluence page reads and Spec/PRD authoring. Backed by
  `acli` + `confluence-content`.

Both are **preview-then-stop**: neither holds MCP tools, and each is instructed never to
fire a mutating acli command itself. Each drafts and renders the payload, then returns the
exact command/call for you to run after review — this plugin's acli and MCP calls hit real
production Jira/Confluence. Both keep `Bash` for read-only acli, so the plugin enforces the
acli rule with a hook: inside a subagent (these two or any other), `hooks/acli-guard.py` denies
a Bash or Monitor acli command unless it is provably a read, any acli mention in a
context-mode execute or batch call, and any Atlassian MCP tool that isn't a read (`createJiraIssue`,
`executeWrite`, ...); a main-thread acli or Atlassian MCP write prompts, which blocks it in an
unattended run. A script the subagent writes and runs is not checked: the hook is a safety net,
not a wall. The hook runs only while the plugin is enabled; to cover
sessions where it isn't, register the same script as a user-level PreToolUse hook (matcher and
settings in `hooks/hooks.json`).

## Tickets from the Jira form

A Bug submitted through the APPR "แจ้งบั๊ก" form reaches Jira as plain text, because a form cannot
prefill a template and no Jira Automation rule is used (the site is near its monthly run limit).
At triage, someone with this plugin runs `python3 skills/ops/scripts/acli-reformat.py KEY` to
preview and `--apply` to write the headings and lists. A line `Env: x` in the description also
sets the Environment field.

## Prerequisites

This plugin is **not self-contained**. It needs, installed separately:

1. **The [`acli` CLI](https://developer.atlassian.com/cloud/acli/)** — installed and
   authenticated (`acli jira auth login` / `acli confluence auth login`). This is the
   primary backend for `acli` and `jira-content`.
2. **The official Atlassian plugin** (provides the `mcp__plugin_atlassian_atlassian__*`
   MCP tools) — used as a fallback for the handful of things `acli` genuinely can't do
   yet (see `skills/ops/SKILL.md` § "When acli can't"), by `jira-content` when `acli`
   is unavailable or can't set a required field, and as the **only** backend for
   `confluence-content` (a REST helper covers the write gaps). Status (2026-11-19): the MCP is unavailable here (blocked token); `skills/ops/scripts/acli-rest-write.py` covers the write gaps (page create/update, priority/parent/fixVersions, version create) in plan-apply form — its first live write currently waits on site permissions, granted by the site admin.

No skill ships its own `.mcp.json` — bundling one for a fallback path would mean
duplicating credentials and rewriting every MCP tool literal for no functional gain.

## Install

```
/plugin marketplace add wasikarn/atlassian-kit
/plugin install atlassian-kit@atlassian-kit
```

Ships `defaultEnabled: false` — add `"atlassian-kit@atlassian-kit": true` to your Claude Code
`settings.json` after install, then restart.

## Versioning

Bump `version` in `.claude-plugin/plugin.json` on every release (the marketplace file `.claude-plugin/marketplace.json` in this repo
carries no version) — same-version edits to a cached plugin are silent no-ops. Add a matching
entry to [`CHANGELOG.md`](CHANGELOG.md) in the same change.

## Changelog

See [`CHANGELOG.md`](CHANGELOG.md) for release notes.
