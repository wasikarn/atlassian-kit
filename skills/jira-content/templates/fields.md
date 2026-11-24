# Fields beyond summary and description

The one place that says which Jira fields a ticket can carry besides its title and body, how to ask for them, and how to send them. Each guided file's Step 1 points here. Checked live on project APPR on 2026-11-24: the create screen (`createmeta`) for Epic, Story, Task, Sub-task and Bug, and a read-back of a ticket created with these values. Other projects can differ, so run `acli-rest-get.py createmeta <KEY> <ISSUETYPE-ID>` before relying on a field.

## How to ask

Ask for these fields in the same message as the gather questions, as one optional group: "มี field เพิ่มไหม (priority, assignee, due date, start date, components, fix versions, team, sprint)". Done when each field has a value from the user or is left unset.

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
| Team | all | `additionalAttributes.customfield_10001` | the team id as a string, e.g. `"98e4ed27-9428-4bab-8975-41e18f32e17c"` (see Looking up Team and Sprint) |
| Sprint | all | `additionalAttributes.customfield_10020` | the sprint id as a number, e.g. `22452` (see Looking up Team and Sprint) |
| Story Points | Story (verified); Task and others untested | `additionalAttributes.customfield_10028` | a number, e.g. `3` |
| Original estimate, Time tracking | Task (verified); others untested | `additionalAttributes.timetracking` | `{"originalEstimate": "2h 30m", "remainingEstimate": "2h"}`; Jira duration format (`w`, `d`, `h`, `m`) |

`customfield_10015` is this site's Start date; resolve the id from `createmeta` on another site. Send the `additionalAttributes` group with `md2adf.sh ... -a '<JSON object>'`:

```bash
bash "${CLAUDE_SKILL_DIR}/scripts/md2adf.sh" body.md -s "Summary" -p APPR -t Task -l test \
  -a '{"priority": {"name": "Low"}, "duedate": "2026-12-31", "components": [{"name": "4.Payment"}]}' > /tmp/wi.json
```

Read the lists with `python3 "${CLAUDE_SKILL_DIR}/../ops/scripts/acli-rest-get.py" api jira /rest/api/3/project/<KEY>/components`.

`customfield_10001`, `customfield_10020` and `customfield_10028` are this site's Team, Sprint and Story Points ids. The site also has a second field named "Story point estimate" (`customfield_10016`); it stayed empty in the test, so use `customfield_10028`. resolve them from `createmeta` on another site.

Verified end to end: priority, due date, start date, one component, one fix version, a label, a team, a sprint, Story Points (on a Story) and original plus remaining estimate (on a Task) all read back as sent.

## Looking up Team and Sprint

Neither has a name lookup in this plugin. Take the id from a ticket that already uses it, with a read-only search through `acli-rest-get.py api jira`:

- Team: `/rest/api/3/search/jql?jql=project = KEY AND Team is not EMPTY&fields=customfield_10001`; each result holds `{id, name}`.
- Sprint: `/rest/api/3/search/jql?jql=project = KEY AND sprint is not EMPTY&fields=customfield_10020`; each result holds `{id, name, state, boardId}`.

The api reader accepts only `/rest/api/3/` paths, so the agile board endpoints are out of reach. A team or sprint that no ticket in the project uses yet therefore cannot be found; ask the user for its id. Prefer a `future` sprint over an `active` one when the ticket is only a test, and never put a real ticket into a closed sprint. Show the resolved name next to the id in the preview.

## Bug only

Two more fields sit on the Bug screen. Both go through `additionalAttributes` and read back as sent (verified on a live APPR Bug, 2026-11-24).

| Field | Where it goes | Value |
|---|---|---|
| Environment | `additionalAttributes.environment` | an ADF document, not a plain string: `{"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": "staging"}]}]}` |
| Affects versions | `additionalAttributes.versions` | `[{"name": "R2c"}]`; same version list as Fix versions, and the name must exist |

Environment is free text in Jira, so there is no dropdown. Offer `production / uat / sit / staging / dev / local` as suggestions and use whatever the user types, unchanged; if the user gives no value, leave it unset. The description holds no environment or version text; these fields do (see `bug.md`).

## Dependencies

Jira records a dependency as an issue link (blocks, is blocked by, relates to, duplicates, clones), not as description text. The create payload has no link field, so create the ticket first, then link it:

```bash
acli jira workitem link create --out KEY-1 --in KEY-2 --type Blocks --yes
```

`--out` is the ticket that blocks and `--in` is the ticket that is blocked: the example makes KEY-1 block KEY-2. Verified live on APPR (2026-11-24): KEY-1 then lists KEY-2 under `blocks`, and KEY-2 lists KEY-1 as `is blocked by`. Other types (`Relates`, `Duplicate`, `Cloners`) were not tested; read the type names from the site's link types before using one. This is a write: show the pair, the direction and the type, and run it only after the user confirms.

## Not supported yet

A field goes in this table only after a real write on the project failed or was refused, or when Jira owns the field (Status moves by transition, Development comes from linked branches). A field missing from a screen, or from the `createmeta` list, is not proof: Story Points, Original estimate and Time tracking were listed here on that basis and then worked through `additionalAttributes`. Try one create on a throwaway ticket (label `test`), read it back, then decide.

| Field | Why |
|---|---|
| Status | Changes by transition (`atlassian-kit:ops`), not at create. |
| Development | Jira fills it from linked branches and pull requests. |

Convert a spoken estimate ("2 ชม. 30 นาที") to Jira format (`2h 30m`) and show the converted value in the preview. When the user asks for one of these, say which row applies and create the ticket without it, after they confirm.
