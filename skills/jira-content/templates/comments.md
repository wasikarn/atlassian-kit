# Comment templates

Four shapes for commenting on an existing ticket: status update, QA verification, blocker or question, decision record. They are a starting proposal, not mined from real tickets and not confirmed as a team standard (the [AC format](../../../templates/acceptance-criteria.md) was). Revise them once they have been used in practice.

A trivial one-line comment needs no template; call `acli jira workitem comment create --key KEY-1 --body "..."` directly (see `atlassian-kit:ops`). Use these four when the comment has real structure. Wording rules are in [`README.md`](README.md) § Writing rules: Thai, plain, one idea per line, specific. Run its two passes (item 6) on a structured comment before sending; a one-line comment needs none.

## Ground rules

1. A comment is a log entry, not the source of truth. When a decision record changes scope, AC or the description's facts, edit the description too (`acli-edit.sh` or `acli-set-desc.sh`; see `SKILL.md` § Editing an existing Jira issue's description). A comment that redefines the ticket while the description stays stale is the drift these templates exist to prevent.
2. Every comment ends with what happens next. A status update without "ขั้นตอนถัดไป" gives nobody an action.
3. Dates: write one when it is known and leave the field blank when it is not. A guessed date is never filled in (the `atlassian-kit:ops` rule: fail loud, never invent a value).

## Sending

Comments go through the comment ADF pipeline. `comment create` and `comment update` take ADF differently (see `atlassian-kit:ops` § Description format).

```bash
bash "${CLAUDE_SKILL_DIR}/scripts/md2adf.sh" note.md > /tmp/note.json   # bare doc mode, no -s/-p/-t
acli jira workitem comment create --key KEY-1 --body-file /tmp/note.json
```

Pick the shape from what the user wants to say, then ask only for that shape's fields. Done when no `[ ]` placeholder is left.

## สถานะความคืบหน้า (status update)

Say what happened in the work, not the team's internal steps.

```
## 📌 ความคืบหน้า

[สิ่งที่ทำเสร็จแล้ว ระบุสิ่งที่เปลี่ยนจริง]

**ขั้นตอนถัดไป:** [สิ่งที่จะทำต่อ]
**คาดว่าจะเสร็จ:** [วันที่ ถ้าทราบ ไม่ทราบให้เว้นว่าง]
```

## ผลตรวจ QA (QA verification)

Use the same `AC#` numbering as the ticket's own [Acceptance Criteria](../../../templates/acceptance-criteria.md), so each result traces to the AC it checks. Write one line per AC.

```
## 🧪 ผลตรวจ QA

* AC1 [ชื่อ AC]: ✅ ผ่าน / ❌ ไม่ผ่าน [สิ่งที่เห็นจริง ถ้าไม่ผ่าน]
* AC2 [ชื่อ AC]: ✅ ผ่าน / ❌ ไม่ผ่าน [สิ่งที่เห็นจริง ถ้าไม่ผ่าน]

**สรุป:** [ผ่านทั้งหมด พร้อมปิดงาน / ไม่ผ่าน ต้องแก้เพิ่ม]
```

## คำถาม/ติดขัด (blocker or question)

Name who has to answer.

```
## ⚠️ คำถาม/ติดขัด

[สิ่งที่ติดขัด หรือคำถามที่ต้องการคำตอบ พร้อมชื่อคนที่ต้องตอบ]

**ผลกระทบถ้าไม่ได้คำตอบ:** [เช่น งานหยุด, เดดไลน์เลื่อน ระบุวันถ้าทราบ]
```

## บันทึกการตัดสินใจ (decision record)

```
## 📋 บันทึกการตัดสินใจ

**ประเด็น:** [สิ่งที่ต้องตัดสินใจ]
**ตัดสินใจ:** [ผลการตัดสินใจ]
**เหตุผล:** [เหตุผลที่เจาะจง]
**ผู้ตัดสินใจ:** [ชื่อหรือบทบาท ถ้าทราบ]
```

If the decision changes scope or AC, apply ground rule 1.
