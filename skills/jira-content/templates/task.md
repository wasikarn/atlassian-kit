# Task: gather questions and Thai description

Loaded by `atlassian-kit:jira-content` Steps 1 and 2. The shared metadata table, preview gate and create commands live in `SKILL.md`. Other rules are defined once, elsewhere:

- AC format, register and coverage: [`acceptance-criteria.md`](../../../templates/acceptance-criteria.md)
- Title: [`title-conventions.md`](title-conventions.md)
- Wording of the ticket text: [`README.md`](README.md) § Writing rules

The section names below match `task.payload.json`, so a ticket written from this file and one filled straight into the payload carry the same sections. Use this file when the user has not yet given the content; use the payload directly when the content is already complete.

## Step 1: gather

Ask all six at once. Done when items 1 to 4 each have an answer from the user. Items 5 and 6 may be "none". If the user cannot answer one, write `ไม่ทราบ` in that section; a guess is never an answer.

1. **Task title**: a Thai imperative verb plus the concrete object, e.g. "เพิ่ม index ตาราง orders ให้ query ยืนยันคำสั่งซื้อ"
2. **Why**: the goal, with a link to the plan or spec if there is one
3. **Scope**: files or modules and what changes in each (line references help)
4. **Done check**: what the person verifying the work will see once it is finished (feeds the ACs)
5. **Out of scope**: what this task will not touch
6. **Tests**: which assertions or test cases must pass

If the user's first message already answers these, go straight to Step 2.

Ask the optional fields in [`fields.md`](fields.md) in the same message (priority, assignee, due date, start date, components, fix versions, team, sprint). A field the user leaves out stays unset.

## Step 2: write the description

Write in Thai with this structure. Fill each section from the Step 1 answers only. Done when no `< >` placeholder is left, each AC has all three bullets, and there are at least 2 ACs (done-state, error or permission).

```
# Context

[ทำไมต้องทำ 1-2 ประโยค พร้อม link plan/spec ถ้ามี]

# Scope

* <ไฟล์หรือโมดูล>: <สิ่งที่เปลี่ยน>
* <ไฟล์หรือโมดูล>: <สิ่งที่เปลี่ยน>

# Out of scope

* <สิ่งที่ task นี้ไม่แตะ ลบทั้ง section ถ้าไม่มี>

# Acceptance Criteria

**AC1 — <ชื่อสั้น>**

* กำหนดให้: <สถานะก่อนทำ>
* เมื่อ: <การกระทำ>
* ผลลัพธ์: <ผลที่เห็น ตอบ yes/no ได้ ใช้คำที่ PO/QA เข้าใจ ไม่ใช้ชื่อ field, enum, API>

**AC2 — <ชื่อสั้น>**

* กำหนดให้: <สถานะก่อนทำ>
* เมื่อ: <การกระทำ>
* ผลลัพธ์: <กรณี error, edge หรือ permission>

# Tests

* <assert อะไร หรือ test case ไหนต้องผ่าน>

# References

* <plan, Figma, PR, link ลบทั้ง section ถ้าไม่มี>
```

Section names stay in English because the payload template uses them; the body text is Thai. A Task's ACs describe what a reviewer observes, so they follow the same plain-language rule as a Story's.

Next: `SKILL.md` Step 3 (metadata: issue type `Task`, priority `Medium` by default), then Step 4 (preview) and Step 5 (create).
