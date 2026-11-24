# Epic: gather questions and Thai description

Loaded by `atlassian-kit:jira-content` Steps 1 and 2. The shared metadata table, preview gate and create commands live in `SKILL.md`. Other rules are defined once, elsewhere:

- Title: [`title-conventions.md`](title-conventions.md)
- Wording of the ticket text: [`README.md`](README.md) § Writing rules

The section names below match `epic.payload.json`, so a ticket written from this file and one filled straight into the payload carry the same sections. Use this file when the user has not yet given the content; use the payload directly when the content is already complete.

## Step 1: gather

Ask all six at once. Done when items 1 to 4 each have an answer from the user. Items 5 and 6 may be "none yet". If the user cannot answer one, write `ไม่ทราบ` in that section; a guess is never an answer.

1. **Epic title**: a Thai noun phrase naming the initiative, e.g. "ระบบคิดค่าบริการแบบ Traffic-based สำหรับ Campaign"
2. **Goal**: the business outcome this epic exists to reach, and the goal, OKR or initiative it rolls up to
3. **Scope and out of scope**: what the epic covers and what it leaves alone, at the level of features, not files
4. **Success criteria**: outcomes the PO can answer yes or no to once the epic ends
5. **Deliverables**: the shippable pieces or milestones
6. **Dependencies, risks and known child items**: what blocks it, what could slip, which tasks or stories are already planned

An epic is work estimated in weeks or more. If the user describes work of hours or days, say a Story or Task fits better and ask before going on.

If the user's first message already answers these, go straight to Step 2.

Ask the optional fields in [`fields.md`](fields.md) in the same message (priority, assignee, due date, start date, components, fix versions, team, sprint). A field the user leaves out stays unset.

## Step 2: write the description

Write in Thai with this structure. Fill each section from the Step 1 answers only, then run the passes in [`writing-rules.md`](../../../templates/writing-rules.md). Done when no `< >` placeholder is left and every Success Criteria line can be answered yes or no.

```
# Goal

[ผลลัพธ์ทางธุรกิจที่ต้องการ 1-2 ประโยค พร้อม goal, OKR หรือ initiative ที่ผูกอยู่]

# Scope

* <สิ่งที่ epic ครอบคลุม ระดับ feature ไม่ใช่ไฟล์หรือบรรทัด>

# Out of scope

* <สิ่งที่ epic ไม่แตะ ลบทั้ง section ถ้าไม่มี>

# Success Criteria

* <ผลลัพธ์ระดับ epic ที่วัดได้ ตอบ yes/no ได้>
* <ผลลัพธ์ถัดไป>

# Key Deliverables

* <ชิ้นงานหรือ milestone ที่ส่งมอบได้ ไม่ใช่รายการ task>

# Dependencies & Risks

* <สิ่งที่ต้องรอ หรือความเสี่ยงที่ทำให้แผนเลื่อน ลบทั้ง section ถ้าไม่มี>

# Child Work Items

* <Task, Story หรือ Sub-task ที่จะสร้างภายใต้ epic นี้ ลบทั้ง section ถ้ายังไม่ได้ breakdown>

# References

* <plan, PRD, Figma, link ลบทั้ง section ถ้าไม่มี>
```

An Epic has Success Criteria, not Acceptance Criteria. Epic-level outcomes are not per-scenario, so do not force them into the กำหนดให้/เมื่อ/ผลลัพธ์ shape.

Next: `SKILL.md` Step 3 (metadata: issue type `Epic`, priority `Medium` by default), then Step 4 (preview) and Step 5 (create).
