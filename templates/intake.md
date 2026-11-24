# Intake: check before you create or update

The one place that says what to look up and what to ask before a Jira ticket is created or changed. `jira-content/SKILL.md` Step 1b points here. Wording of the ticket text stays in [`writing-rules.md`](writing-rules.md).

## Duplicate check (every create)

Skip it only when the user names an existing ticket key; go to Update flow below. Otherwise, after the gather answers are in and before Step 2:

1. Take 2 or 3 distinctive words from the summary. Drop type words ("เพิ่ม", "แก้", "Bug").
2. Search the project, read-only, newest first, with the table wrapper (verified on APPR: it returns the same tickets as the raw REST search, as key, type, status, assignee and summary):

```bash
bash "${CLAUDE_SKILL_DIR}/../ops/scripts/acli-ls.sh" --jql 'project = KEY AND summary ~ "word" ORDER BY created DESC'
```

   Join several words with `AND summary ~ "word2"`. Use `summary ~`, not `text ~`: on APPR the second returns tickets that do not match the words. The wrapper prints up to 30 rows; read the first 5.
3. Show the first 5 hits as key, status and summary in the preview, Done tickets included, so the user can tell an old ticket from a real duplicate.
4. No hit: go to Step 2 without asking. A hit: stop and ask the user to pick one with `AskUserQuestion` (the four choices below as its options). Never pick for them.

| Choice | What follows |
|---|---|
| Update the existing ticket | Update flow below |
| Comment on the existing ticket | [`comments.md`](../skills/jira-content/templates/comments.md) |
| Create a new ticket and link it | Create, then `acli jira workitem link create --out NEW --in OLD --type Relates --yes` after the user confirms the pair. `Relates` is a link type on APPR; `link create` itself was verified with `Blocks` ([`fields.md`](../skills/jira-content/templates/fields.md) § Dependencies) |
| Create a new ticket, no link | Step 2 |

## Update flow

1. Read the ticket first: `acli jira workitem view KEY --json`, rendered to Markdown with `adf2md.py`.
2. Ask which section changes and whether the new text replaces or is appended.
3. Edit that section only, with `acli-edit.sh`. Never replace the whole body. The commands, `--dry-run` and the node count before a full replace are in [`editing.md`](../skills/jira-content/editing.md).
4. Show what changes before writing.

Fields an update can change: description sections, plus what `acli-rest-write.py issue-set` supports (priority, parent, fix versions, environment, affects versions). Due date, components, team, sprint, story points and estimates cannot be changed on an existing ticket yet. Say so; do not promise them.

## Preview always

Every create and every update shows its preview and waits for the user's go-ahead, a ticket with the label `test` included. The preview carries the duplicate-check result. After the preview, ask for the go-ahead with `AskUserQuestion`: create, or change something first.

## How to ask

A closed choice is an `AskUserQuestion`: the ticket type (Bug, Story, Task, Epic, Sub-task), the duplicate pick above, the preview go-ahead, and replace or append in the update flow. Ticket content (symptom, reason, scope, expected result) is free text; ask it in one message as the guided file says. When `AskUserQuestion` is not available (an unattended or headless run), print the same options as a numbered list, recommended one first, and stop until the user answers; never choose for them.
