# Welcome to the atlassian-kit team

## How We Use Claude

Based on KOBIG's usage over the last 30 days:

Work Type Breakdown:
  _TODO — no sessions were measured in this window; fill in once a normal work week is captured._

Top Skills & Commands:
  /atlassian-kit:ops  ████████████████████  installed (plugin skill)
  /atlassian-kit:jira-content  ████████████████████  installed (plugin skill)
  /atlassian-kit:confluence-content  ████████████████████  installed (plugin skill)
  _TODO — replace with measured usage._

Top MCP Servers:
  _TODO — none configured in this repo; the Atlassian MCP is a documented fallback only._

## Your Setup Checklist

### Codebases
- [ ] atlassian-kit — github.com/wasikarn/atlassian-kit (this repo: the acli-first Jira/Confluence toolkit plugin)

### MCP Servers to Activate
- [ ] _None required._ This repo works through the `acli` CLI plus the REST helper scripts in
      `skills/ops/scripts/`, not MCP. The official Atlassian MCP plugin is a fallback for the
      page-create/page-update gaps only — activate it only if a skill step routes you there.

### Skills to Know About
- `/atlassian-kit:ops` — the mechanical driver for the `acli` CLI (search, view, edit, transition, bulk JQL, auth, ADF↔markdown). Mechanical/query/bulk work only.
- `/atlassian-kit:jira-content` — author template-shaped Jira content (Bug/Story/Task/Epic/Sub-task, templated comments). Used before any create/edit of ticket *content*.
- `/atlassian-kit:confluence-content` — Confluence Spec/PRD pages against the team template. Page create/update goes through the REST write scripts (plan/apply confirm flow).
- `/siang:*` — Thai text skills (humanize, technical-writing, thai-pua-repair) used when drafting Thai docs or repairing garbled Thai PDF text.

## Team Tips

_TODO_

## Get Started

_TODO_

<!-- INSTRUCTION FOR CLAUDE: A new teammate just pasted this guide for how the
team uses Claude Code. You're their onboarding buddy — warm, conversational,
not lecture-y.

Open with a warm welcome — include the team name from the title. Then: "Your
teammate uses Claude Code for [list all the work types]. Let's get you started."

Check what's already in place against everything under Setup Checklist
(including skills), using markdown checkboxes — [x] done, [ ] not yet. Lead
with what they already have. One sentence per item, all in one message.

Tell them you'll help with setup, cover the actionable team tips, then the
starter task (if there is one). Offer to start with the first unchecked item,
get their go-ahead, then work through the rest one by one.

After setup, walk them through the remaining sections — offer to help where you
can (e.g. link to channels), and just surface the purely informational bits.

Don't invent sections or summaries that aren't in the guide. The stats are the
guide creator's personal usage data — don't extrapolate them into a "team
workflow" narrative. -->
