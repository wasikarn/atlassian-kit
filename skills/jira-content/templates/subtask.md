# Sub-task: gather questions and Thai description

Loaded by `atlassian-kit:jira-content` Steps 1 and 2. The shared metadata table, preview gate and create commands live in `SKILL.md`. Other rules are defined once, elsewhere:

- AC format, register and coverage: [`acceptance-criteria.md`](../../../templates/acceptance-criteria.md)
- Title: [`title-conventions.md`](title-conventions.md)
- Wording of the ticket text: [`README.md`](README.md) § Writing rules

The section names below match `subtask.payload.json`, so a ticket written from this file and one filled straight into the payload carry the same sections. Use this file when the user has not yet given the content; use the payload directly when the content is already complete.

## Step 1: gather

Ask all five at once. Done when items 1 to 4 each have an answer from the user, and the parent key in item 1 exists. Item 5 may be "none". A sub-task cannot be created without a parent; if the user names none, stop and ask.

1. **Parent key**: the issue this slice belongs to, e.g. `PROJ-479`
2. **Sub-task title**: `[PARENT-KEY]` plus a Thai imperative verb and one slice, narrow enough to tell apart from its siblings, e.g. "[PROJ-809] เขียน migration เพิ่มคอลัมน์ display_time_id"
3. **Scope**: the one action this sub-task completes, and the files it touches
4. **Done check**: what the person verifying the work will see once it is finished (feeds the ACs)
5. **Out of scope**: what sibling sub-tasks handle, so the work does not overlap

If the user's first message already answers these, go straight to Step 2.

Ask the optional fields in [`fields.md`](fields.md) in the same message (priority, assignee, due date, start date, components, fix versions). A field the user leaves out stays unset.

## Step 2: write the description

Write in Thai with this structure. Fill each section from the Step 1 answers only. Done when no `< >` placeholder is left, every AC has all three bullets, and there is at least 1 AC.

```
# Scope

[การกระทำเดียวที่ทำจบในตัว แคบกว่า task พร้อมไฟล์ที่เกี่ยวข้อง]

# Out of scope

* <ส่วนที่ sibling sub-task อื่นทำ ลบทั้ง section ถ้าไม่มี>

# Acceptance Criteria

**AC1 — <ชื่อสั้น>**

* กำหนดให้: <สถานะก่อนทำ>
* เมื่อ: <การกระทำ>
* ผลลัพธ์: <ผลที่เห็น ตอบ yes/no ได้ ใช้คำที่เข้าใจง่าย ไม่ใช้ชื่อ field, enum, API>

**AC2 — <ชื่อสั้น>**

* กำหนดให้: <สถานะก่อนทำ>
* เมื่อ: <การกระทำ>
* ผลลัพธ์: <กรณี error หรือ boundary ลบ AC นี้ถ้าไม่เกี่ยวข้อง>

# Files affected

* <path>: <สิ่งที่เปลี่ยน ลบทั้ง section ถ้ายังไม่ทราบ>
```

Next: `SKILL.md` Step 3 (metadata: issue type `Sub-task`, parent required; set `parentIssueId` to the key in the payload or pass `--parent <KEY>`), then Step 4 (preview) and Step 5 (create).
