# Jira issue through MCP (fallback)

Moved out of `SKILL.md` so the main file stays small; `SKILL.md` links here. Paths below are relative to this folder.

> **Status:** no Atlassian MCP tools are available here. For the fields acli cannot set, `acli-rest-write.py issue-set` (priority/parent/environment/fixVersions/affects-versions) and `version-create` exist — same plan-then-apply flow (see `ops/SKILL.md` § "When acli can't"). `issue-set` is verified live on production (2026-11-24): preview, then apply with the printed `--confirm`.

Call `mcp__plugin_atlassian_atlassian__createJiraIssue` (v2 shape per Atlassian's v2 skills, see `ops/SKILL.md` § "When acli can't"; v1 differences in the comments):

```
cloudId:       <resolved>
projectKey:    <resolved>
issueType:     "Bug" | "Story" | "Task" | "Epic" | "Sub-task"   # v1: issueTypeName
summary:       <Thai title>
description:   <formatted Thai content, Markdown>   # v1 also took contentFormat: "markdown"; v2 format param not shown, check the live schema
parent:        <parentKey>   # Sub-task only — top-level param, plain issue key string, NOT nested in additional_fields
priority:      <derived>     # v2: top-level string. v1: additional_fields "priority": { "name": <derived> }
additional_fields: {
  // v2 reserves additional_fields for custom fields; whether labels/environment/versions are
  // top-level on v2 is not shown — check the live schema. On v1 they go here:
  "labels": [<domain tags>],
  // Bug only:
  "environment": { "version": 1, "type": "doc", "content": [
    { "type": "paragraph", "content": [{ "type": "text", "text": "prod" }] }
  ]},
  "versions": [{ "name": <version> }]   # Affects Version/s, NOT fixVersions — omit if unvalidated
}
# assignee: OMIT by default. Include ONLY if user named an assignee (accountId). v1: assignee_account_id.
```

**Read the ticket back before replying (required for every MCP create).** On v2 a wrong parameter
name can be dropped with no error (`ops/SKILL.md` § "When acli can't"), so the create succeeds
on production with fields left empty or at the project default. The v2 names for `environment` and
`versions` are not confirmed yet. Read it with `getJiraIssue(cloudId, issueIdOrKey="<KEY>")`: a
Primary tool on v2, so it works in every case that sends a create here, including acli being down
or logged out. Check each field the user stated or you sent: `priority`, `labels`, `environment`,
`versions`, `assignee`, `parent`. Skip a field the user agreed to leave out, at the preview or when asked after a rejected create. For `description`, only check that it is present and not empty:
its stored form can differ from the Markdown you sent, and v2's format parameter is unverified, so
ask the user to open the ticket page once and confirm headings and lists rendered (not literal
`##`). A clean create needs every other field **Set** (or confirmed by the cross-check below):
- **Set:** present with the value you sent, compared by meaning: the response may wrap it (e.g.
  `{"name": "High"}` for `priority`) or return `environment` as rich text in another form.
- **Empty or different:** present but empty, null, or another value. A dropped `priority` or
  `assignee` comes back as the project default, not null. Name each such field in the reply and
  stop; don't retry with guessed parameter names (the **Fail loud** rule in `ops/SKILL.md`).
- **Absent from the response:** not verified; the v2 response shape is not in Atlassian's examples.
  If acli is logged in to the same site you created on (`acli jira auth status`), cross-check with
  `acli jira workitem view <KEY> --fields '*all' --json` (read-only). For `labels`, don't trust a
  null there: `ops/ISSUES.md` Issue 3 saw `view --json` show null labels that were set (seen
  without `--fields`; not re-checked with `*all`). If neither read confirms a field, ask the user
  to open the ticket and check it.

Reply: `✅ Created [PROJ-XXX](https://<site>.atlassian.net/browse/PROJ-XXX)`, plus any field the read-back found empty, different, or couldn't confirm.

