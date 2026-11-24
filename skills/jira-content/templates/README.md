# jira-content templates

Every template that defines what a created or edited Jira ticket contains lives here. `atlassian-kit:ops` is the mechanical backend these templates are sent through (ADF conversion, `create --from-json`, MCP fallback); it owns none of this content. Confluence templates live in the sibling `atlassian-kit:confluence-content` skill, since Confluence is a different product.

## Files

| File | Use |
|---|---|
| `bug.md`, `story.md`, `task.md`, `epic.md`, `subtask.md` | Guided creation: gather questions, then the Thai description. Read by `SKILL.md` Steps 1 and 2. |
| `bug.payload.json`, `story.payload.json`, `task.payload.json`, `epic.payload.json`, `subtask.payload.json` | ADF payloads for `acli jira workitem create --from-json`, when the content is already complete. |
| `comments.md` | Four comment shapes for an existing ticket: status update, QA verification, blocker, decision record. |
| `title-conventions.md` | The summary rule shared by all five types. |

The Acceptance Criteria rule sits at the plugin root, [`../../../templates/acceptance-criteria.md`](../../../templates/acceptance-criteria.md), because `confluence-content` shares it. Title rules stay here: a Confluence page title is a different concept from a work-item summary.

## Writing rules

These apply to every sentence a template asks you to write. Each guided file points here instead of repeating them.

1. Use the user's specifics: numbers, screen names, error text, IDs, file paths. The ticket should say what fails and when ("ขึ้น 'สำเร็จ' แต่ยอดยัง 500 บาท"), not that something "ทำงานผิดพลาด".
2. When the user has not given a fact, write `ไม่ทราบ` or ask. A guessed value, date or cause goes in no section.
3. One idea per line. Use plain verbs (คือ, เป็น, มี). Leave out importance claims ("สำคัญอย่างยิ่ง", "ครอบคลุม", "ยกระดับ"), reassurance, and a closing line that restates the section.
4. Delete a section that has nothing real in it. A required section is never deleted; write `ไม่ทราบ` instead.
5. Keep technical terms in English (repo, branch, deploy). Write quantities as Arabic numerals ("2 ตัว") and put a space between Thai and English words.
6. When `siang:humanize` is installed, run it over the prose fields (summary, reason, impact, context). It never touches AC blocks, code, IDs or quoted error text.

## Two paths, same sections

Each of the five types has a guided file and a payload. They serve two situations and must stay in step:

- Guided file: the user has not yet given the content, so ask the gather questions, then write.
- Payload: the content is already complete, so fill the placeholders directly.

Every field that `SKILL.md`'s Input Contract marks required must appear as its own section on both paths, never folded into another section's placeholder where it is easy to drop. Add or remove a required section on one path and mirror it on the other. Recommended and optional sections may differ in depth.

Bug and Story use Thai section headings with emoji (the team's required shape). Task, Epic and Sub-task use the English headings their payloads already carry, with Thai body text.

## Sections by type

### Bug (`bug.payload.json`)

Derived from PROJ-418, 447, 455, 457, 460, 461.

| Section | When | Content |
|---|---|---|
| Title (`summary`) | always | Symptom first, no `[Area]` bracket; see [title-conventions.md](title-conventions.md) |
| สรุปปัญหา | always | 1-2 sentences: what broke, where, who it hurts |
| ขั้นตอน Reproduce | always | Numbered actions, one per line |
| ผลที่คาดหวัง | always | What should happen |
| ผลที่เกิดจริง | always | What happens, including the error or wrong state |
| ความรุนแรง | recommended | High, Medium or Low, with one line of why |
| ผลกระทบ | always | Who is affected and how badly; its own section, not a clause inside ความรุนแรง |
| หลักฐาน | if available | Account, order or ID; screenshot or log. Environment and version go in the native Environment and Affects versions fields, not here |
| Acceptance Criteria | always | See [acceptance-criteria.md](../../../templates/acceptance-criteria.md) |
| Technical Notes | if known | Root cause, fix, files |

### Story (`story.payload.json`)

Derived from Atlassian's [user stories guidance](https://www.atlassian.com/agile/project-management/user-stories): a non-technical, end-user view.

| Section | When | Content |
|---|---|---|
| Title (`summary`) | always | The outcome, not the full "As a..." sentence |
| User Story | always | "As a <role>, I want <goal> so that <benefit>" |
| Context | always | Why, in 1-2 non-technical sentences |
| Scope | always | In-scope and out-of-scope bullets; required, so keep it on the direct-payload path too |
| Acceptance Criteria | always | At least 3; see [acceptance-criteria.md](../../../templates/acceptance-criteria.md) |
| Technical Notes | if known | Approach, constraints |
| Dependencies | if known | Blockers, things to wait on |
| References | if any | Plan, Figma, PR, link |

### Task (`task.payload.json`)

Implementation work. Derived from PROJ-466, 467, 473, 479.

| Section | When | Content |
|---|---|---|
| Title (`summary`) | always | Imperative verb plus object |
| Context | always | Why, 1-2 sentences, plus a plan link |
| Scope | always | Files and what changes in each |
| Out of scope | recommended | What this task will not touch |
| Acceptance Criteria | always | See [acceptance-criteria.md](../../../templates/acceptance-criteria.md) |
| Tests | recommended | What to assert |
| References | if any | Plan, Figma, PR links |

### Epic (`epic.payload.json`)

A multi-sprint initiative. Derived from Atlassian's [epics guidance](https://www.atlassian.com/agile/project-management/epics).

| Section | When | Content |
|---|---|---|
| Title (`summary`) | always | Noun phrase naming the initiative |
| Goal | always | The business outcome, 1-2 sentences |
| Scope | always | What the epic covers, feature level |
| Out of scope | recommended | What it leaves alone; prevents scope creep |
| Success Criteria | always | Yes/no outcomes at epic level, one per line |
| Key Deliverables | always | Milestones or shippable pieces, not a task list |
| Dependencies & Risks | if known | Blockers and what could slip |
| Child Work Items | if known | Planned tasks, stories, sub-tasks |
| References | if any | Plan, PRD, Figma, link |

Success Criteria is a different concept from Acceptance Criteria: epic-level outcomes are not per-scenario, so do not force them into the กำหนดให้/เมื่อ/ผลลัพธ์ shape.

### Sub-task (`subtask.payload.json`)

A slice of a parent. Derived from PROJ-436, 437, 489.

| Section | When | Content |
|---|---|---|
| Title (`summary`) | always | `[PARENT-KEY]` plus imperative plus slice, distinct from its siblings |
| Scope | always | One clear action, plus files |
| Out of scope | recommended | What sibling sub-tasks handle |
| Acceptance Criteria | always | See [acceptance-criteria.md](../../../templates/acceptance-criteria.md) |
| Files affected | if known | Paths touched |

A sub-task needs a parent. Set `parentIssueId` in the JSON to the issue key (for example `PROJ-479`; a numeric ID is not needed), or pass `--parent <KEY>` on the CLI.

## Creating from a template

Every payload marks its placeholder text italic (`em`) so it stands out as "replace me". Strip the mark (drop the `marks` key) when you fill in real content, and keep it only on a line that is still optional and unfilled.

```bash
acli jira workitem create --from-json "${CLAUDE_SKILL_DIR}/templates/task.payload.json"
```

Or write the body in Markdown and convert it first; this is easier than editing ADF JSON:

```bash
bash "${CLAUDE_SKILL_DIR}/scripts/md2adf.sh" mytask.md -s "Summary" -p PROJ -t Task > /tmp/wi.json
acli jira workitem create --from-json /tmp/wi.json
```

Grounded in real PROJ work items and Atlassian's [bug-report template](https://www.atlassian.com/software/jira/templates/bug-report), [user stories](https://www.atlassian.com/agile/project-management/user-stories), [acceptance criteria](https://www.atlassian.com/work-management/project-management/acceptance-criteria) and [epics](https://www.atlassian.com/agile/project-management/epics) guidance.
