---
name: setup
description: Set up atlassian-kit on a new machine: check acli, create the credentials file with a hidden prompt, then run doctor. Use when a teammate installs the plugin for the first time or a credential check fails.
---

# Setup

Run the steps in order. Stop at the first FAIL and fix it before the next step.

## 1. Prerequisites

- Install acli from the official Atlassian download (macOS: Homebrew is optional; use the official installer if it is missing).
- Install Python 3 (`python3` on macOS; `py` or `python` on Windows; use that launcher wherever a command below says `python3`).
- Install the official Atlassian plugin from the Claude marketplace. The Atlassian MCP fallback and the `confluence-content` page create/update need it.
- Enable this plugin. The hook that blocks unsafe acli writes runs only while the plugin is enabled.

## 2. Create an API token (done by you, in the browser)

Create three tokens at id.atlassian.com, API tokens. The first two are scoped ("Create API token with scopes", one per product); the third is an unscoped token ("Create API token") that acli itself uses to log in.

- Jira token: read:jira-work, write:jira-work, read:jira-user, manage:jira-project, read:project:jira, read:issue-details:jira, read:board-scope:jira-software, write:board-scope:jira-software, read:board-scope.admin:jira-software, write:board-scope.admin:jira-software
- Confluence token: read:space, read:page, read:attachment, read:content-details, write:page, write:attachment, delete:page (all :confluence)
- acli login token: no scopes to pick. Name it so you can tell it apart.
- Choose an expiry date. Put a calendar reminder 30 days before it.

Do not paste tokens into the chat. Press Create, copy the token, and keep it for step 3.

## 3. Write the credentials file

Run this in your own terminal (not through the agent). The path is absolute, so the current folder does not matter:

```
python3 "${CLAUDE_SKILL_DIR}/scripts/setup_credentials.py"
```

It asks for the site (for example `your-site.atlassian.net`), your Atlassian email, the three tokens through a hidden prompt (Jira, Confluence, acli login), then the expiry date of each token (YYYY-MM-DD). It writes `~/.claude/atlassian.env` with five keys and restricts the file to your user. Replacing an existing file rewrites all five keys and drops any optional override lines you added by hand. The expiry dates go to `~/.claude/atlassian-kit-meta.json` (not secret) so doctor can warn.

To preview without changing anything, run `python3 "${CLAUDE_SKILL_DIR}/scripts/setup_credentials.py" --dry-run`. It lists the prerequisites, the file it would create or replace and the permissions it would set, checks only local facts (acli, Python), asks for nothing and sends nothing. Exit code 1 means a prerequisite is missing.

## 4. Verify

Log acli in first, because the read checks go through it: run `acli jira auth login` and enter your site, your email and the unscoped acli login token (the third token from step 2, also stored as ACLI_LOGIN_TOKEN).

```
python3 "${CLAUDE_SKILL_DIR}/scripts/doctor.py"
```

Every line should read PASS. WARN means a token expires within 30 days; FAIL means it already has. Doctor reads the dates you typed at setup, not Atlassian, so a wrong date gives a wrong warning. Re-run it after any change. A SKIP on Windows permissions means doctor did not check the ACL; confirm it with `icacls`.

## Common failures

| Output | Fix |
|---|---|
| acli not found | Install acli, then reopen the terminal |
| credentials file missing | Run step 3 |
| missing key | Run step 3 again and answer y to replace |
| acli login FAIL | Run `acli jira auth login` with your site, email and the unscoped login token, then rerun doctor |
| permissions FAIL | `chmod 600 ~/.claude/atlassian.env` (macOS) |
| Jira or Confluence smoke FAIL | Doctor prints the last message line of the failed call. The token is wrong or missing a scope; create a new token with the scopes above and rerun step 3 |

## Notes

- The agent never reads or prints the credentials file.
- Write checks (creating issues or pages) are not part of setup; the write scripts plan first and need a confirm value.
