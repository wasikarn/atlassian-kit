# Fields beyond summary and description

The one place that says which Jira fields a ticket can carry besides its title and body, how to ask for them, and how to send them. Each guided file's Step 1 points here. Checked live on project APPR on 2026-11-24: the create screen (`createmeta`) for Epic, Story, Task, Sub-task and Bug, and a read-back of a ticket created with these values. Other projects can differ, so run `acli-rest-get.py createmeta <KEY> <ISSUETYPE-ID>` before relying on a field.

## How to ask

Ask for these fields in the same message as the gather questions, as one optional group: "มี field เพิ่มไหม (priority, assignee, due date, start date, components, fix versions)". Done when each field has a value from the user or is left unset.

- A field the user did not mention stays unset. Priority is the one exception: it defaults to `Medium` (Bug: from severity, see `SKILL.md` Step 3).
- A value that must already exist in the project (component, version) is checked against the list below before the preview. If it is missing, stop and ask; never create a new component or version to make the ticket go through.

## Supported at create

| Field | Types | Where it goes in the create payload | Value |
|---|---|---|---|
| Labels | all | `labels` (`-l` on `md2adf.sh`) | array of strings |
| Assignee | all | `assignee` (`--assignee`) | email or accountId; only when the user names one |
| Reporter | all | leave unset | Jira uses the logged-in user |
| Parent | Sub-task (required), Story and Task (optional) | `parentIssueId` (`-P`) | issue key, e.g. `PROJ-479` |
| Priority | all | `additionalAttributes.priority` | `{"name": "Low"}`; names are Highest, High, Medium, Low, Lowest |
| Due date | all | `additionalAttributes.duedate` | `"2026-12-31"` (YYYY-MM-DD) |
| Start date | all | `additionalAttributes.customfield_10015` | `"2026-12-01"` (YYYY-MM-DD) |
| Components | all | `additionalAttributes.components` | `[{"name": "4.Payment"}]`; list: `GET /rest/api/3/project/<KEY>/components` |
| Fix versions | all | `additionalAttributes.fixVersions` | `[{"name": "R2c"}]`; list: `GET /rest/api/3/project/<KEY>/versions` |

`customfield_10015` is this site's Start date; resolve the id from `createmeta` on another site. Send the `additionalAttributes` group with `md2adf.sh ... -a '<JSON object>'`:

```bash
bash "${CLAUDE_SKILL_DIR}/scripts/md2adf.sh" body.md -s "Summary" -p APPR -t Task -l test \
  -a '{"priority": {"name": "Low"}, "duedate": "2026-12-31", "components": [{"name": "4.Payment"}]}' > /tmp/wi.json
```

Read the lists with `python3 "${CLAUDE_SKILL_DIR}/../ops/scripts/acli-rest-get.py" api jira /rest/api/3/project/<KEY>/components`.

Verified end to end: priority, due date, start date, one component, one fix version and a label all read back as sent.

## Bug only

Environment (`environment`, rich text) and Affects versions (`versions`) sit on the Bug screen. They are not covered by the check above; `SKILL.md` Step 3 keeps its current handling of both until they are verified.

## Not supported yet

| Field | Why |
|---|---|
| Story Points, Original estimate, Time tracking | On this project they are on no create or edit screen, so Jira would reject a value. A Jira admin has to add them to the screen first. |
| Team | The value is a team id; no lookup is wired in yet. |
| Sprint | The value is a sprint id from the board's sprint list; the lookup is not wired in yet. |
| Status | Changes by transition (`atlassian-kit:ops`), not at create. |
| Development | Jira fills it from linked branches and pull requests. |

When the user asks for one of these, say which row applies and create the ticket without it, after they confirm.
