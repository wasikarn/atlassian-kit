# Title conventions

The summary rule for all five types. Every guided template's gather questions and every `*.payload.json`'s `summary` field point here; edit the rule here, not per template. (Scattered copies drifted before, which is why [`acceptance-criteria.md`](../../../templates/acceptance-criteria.md) is also single-source.)

Grounded in Atlassian's [bug-report template](https://www.atlassian.com/software/jira/templates/bug-report) ("as short as a few words as long as it makes it easy for team members to identify the bug") and common issue-title practice: imperative verb for work items, behavior-focused wording for user-facing issues, readable in a backlog list without opening the ticket.

## Rules for every type

- Thai, one line, no trailing period, same register as the description.
- A reader scanning the backlog knows what the ticket is about from the title alone.
- The title states what, not how it was noticed or how it will be fixed. Root cause and fix go in the description (Evidence, Technical Notes); a title that leads with a diagnosis needs a rename when the real cause turns out different.
- No `[Area]` bracket by default. `labels` already carries the domain tag (`SKILL.md` Step 3), so a bracket duplicates it. Add one only when the team cannot filter or group by label in their list view, or already writes tags in its titles (for example the Bug `[RePI][Desktop][F7_E2E]` in APPR-8455: system, platform, test suite); then follow the team. Sub-task is the exception: its bracket holds the parent key, which no other field carries.
- One ticket, one title. A title that needs "และ" or "กับ" describes two tickets.

Done when the title passes each line above.

## Pattern by type

| Type | Pattern | Example |
|---|---|---|
| Bug | Observable symptom, present tense | "ยอดคงเหลือไม่ถูกหักหลังลูกค้ายืนยันการสั่งซื้อ" |
| Story | The outcome the user gets once shipped | "หักยอดคงเหลือตอนลูกค้ายืนยันการสั่งซื้อ" |
| Task | Imperative verb plus concrete object; describes the work, not the user value | "เพิ่ม index ตาราง orders ให้ query ยืนยันคำสั่งซื้อ" |
| Epic | Noun phrase naming the initiative, broader than one fix | "ระบบคิดค่าบริการแบบ Traffic-based สำหรับ Campaign" |
| Sub-task | `[PARENT-KEY] ` plus imperative plus a slice that differs from its siblings | "[PROJ-809] เขียน migration เพิ่มคอลัมน์ display_time_id" |

## Anti-patterns

- Vague: "บั๊กหน้า login". Which bug, on which step?
- Diagnosis in the title: "เพราะ null pointer ตอน settle". That is the cause, so it belongs in Evidence.
- Several issues: "แก้ settlement + เพิ่ม logging + refactor retry". Split into 3 tickets.
- Empty: "Bug in payment". A scanner learns nothing they can act on.
