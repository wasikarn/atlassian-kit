# Intake: check before you create or update

The one place that says what to look up and what to ask before a Jira ticket is created or changed. `jira-content/SKILL.md` Step 1b points here. Wording of the ticket text stays in [`writing-rules.md`](writing-rules.md).

## Duplicate check (every create)

Skip it only when the user names an existing ticket key; go to Update flow below. Otherwise, after the gather answers are in and before Step 2:

1. Take 2 or 3 distinctive words from the summary. Drop type words ("เพิ่ม", "แก้", "Bug"). A word holds letters and digits only; the read tool rejects other characters.
2. Search the project, read-only, newest first. Percent-encode the JQL, with `~` as `%7E` and a quote as `%22`:

```bash
python3 "${CLAUDE_SKILL_DIR}/../ops/scripts/acli-rest-get.py" api jira \
  "/rest/api/3/search/jql?jql=project%20%3D%20KEY%20AND%20summary%20%7E%20%22word%22%20ORDER%20BY%20created%20DESC&fields=summary,status&maxResults=5"
```

   Join several words with `%20AND%20summary%20%7E%20%22word2%22`. Use `summary ~`, not `text ~`: on APPR the second returns tickets that do not match the words.
3. Show up to 5 hits as key, status and summary in the preview, Done tickets included, so the user can tell an old ticket from a real duplicate.
4. No hit: go to Step 2 without asking. A hit: stop and let the user pick one. Never pick for them.

| Choice | What follows |
|---|---|
| Update the existing ticket | Update flow below |
| Comment on the existing ticket | [`comments.md`](../skills/jira-content/templates/comments.md) |
| Create a new ticket and link it | Create, then `acli jira workitem link create --out NEW --in OLD --type Relates --yes` after the user confirms the pair. `Relates` is a link type on APPR; `link create` itself was verified with `Blocks` ([`fields.md`](../skills/jira-content/templates/fields.md) § Dependencies) |
| Create a new ticket, no link | Step 2 |

## Update flow

1. Read the ticket first: `acli jira workitem view KEY --json`, rendered to Markdown with `adf2md.py`.
2. Ask which section changes and whether the new text replaces or is appended.
3. Edit that section only, with `acli-edit.sh`. Never replace the whole body. The commands, `--dry-run` and the node count before a full replace are in `jira-content/SKILL.md` § Editing an existing Jira issue's description.
4. Show what changes before writing.

Fields an update can change: description sections, plus what `acli-rest-write.py issue-set` supports (priority, parent, fix versions, environment, affects versions). Due date, components, team, sprint, story points and estimates cannot be changed on an existing ticket yet. Say so; do not promise them.

## Preview always

Every create and every update shows its preview and waits for the user's go-ahead, a ticket with the label `test` included. The preview carries the duplicate-check result.
