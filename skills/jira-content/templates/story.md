# Story: gather questions and Thai description

Loaded by `atlassian-kit:jira-content` Steps 1 and 2. The shared metadata table, preview gate and create commands live in `SKILL.md`. Other rules are defined once, elsewhere:

- AC format, register and coverage, including the Story-only additions: [`acceptance-criteria.md`](../../../templates/acceptance-criteria.md)
- Title: [`title-conventions.md`](title-conventions.md)
- Wording of the ticket text: [`writing-rules.md`](../../../templates/writing-rules.md)

This file holds only the Story questions and the Thai description.

## Step 1: gather

Ask all eight at once. Done when items 1 to 4 and 6 each have an answer from the user. Items 5, 7 and 8 may be "none". If the user cannot answer one, write `ไม่ทราบ` in that section; a guess is never an answer.

1. **Feature name**: a short Thai title naming the outcome, e.g. "หักยอดคงเหลือตอนลูกค้ายืนยันการสั่งซื้อ"
2. **Why now**: the business reason or the problem being solved
3. **Behavior**: what the system should do, in plain language
4. **Out of scope**: what this round does not cover (QA relies on this list)
5. **PO decisions**: trade-offs or edge cases the PO must sign off on
6. **Acceptance criteria**: rough testable behaviors; you format them
7. **Sub-tasks**: the planned steps and who owns each
8. **Dependencies**: tickets this story blocks or waits on, as keys

If the behavior looks too big for one sprint, say so and offer to split it into stories, or to raise an Epic, before Step 2.

Sub-tasks and dependencies do not go in the description. After the story exists, create each sub-task with [`subtask.md`](subtask.md) and each dependency as an issue link (see [`fields.md`](fields.md) § Dependencies).

If the user's first message already answers these, go straight to Step 2.

## Step 2: write the description

Write in Thai with this structure. Fill each section from the Step 1 answers only. Done when no `[ ]` placeholder is left, every AC has all three bullets, and there are at least 3 ACs (happy path, error or edge, regression or permission).

```
## 🎯 เหตุผลทางธุรกิจ (ทำไมต้องทำ)

[ปัญหาปัจจุบัน 2-3 ประโยค จบด้วยสิ่งที่ต้องการให้เกิด]

---

## ✅ พฤติกรรมที่ต้องการ

1. [ระบบทำอะไร]
2. [ระบบทำอะไร]

> ⚠️ [สิ่งที่ไม่เกิดขึ้น ถ้ามีข้อควรระวัง]

---

## 📋 ขอบเขต (Scope)

**อยู่ในขอบเขตรอบนี้**
* [รายการ]

**ไม่อยู่ในขอบเขตรอบนี้ (แจ้ง QA ให้ทราบ)**
* [รายการ]

---

## ⚠️ จุดที่ PO ต้องรับทราบและตัดสินใจร่วม

[ใส่เฉพาะเมื่อมีจุดตัดสินใจจริง ไม่มีให้ลบทั้ง section]

---

## 🧪 เกณฑ์การยอมรับ (Acceptance Criteria) สำหรับ QA

**AC1: [ชื่อสั้น] (happy path)**

* กำหนดให้: [สถานะก่อนทำ]
* เมื่อ: [การกระทำ]
* ผลลัพธ์: [ผลที่เห็น ระบุให้เจาะจง ใช้ภาษาธุรกิจ]

**AC2: [ชื่อสั้น] (error หรือ edge case)**

* กำหนดให้: [สถานะก่อนทำ]
* เมื่อ: [การกระทำ]
* ผลลัพธ์: [ผลที่เห็น]

**AC3: [ชื่อสั้น] (regression หรือ permission)**

* กำหนดให้: [สถานะก่อนทำ]
* เมื่อ: [การกระทำ]
* ผลลัพธ์: [ผลที่เห็น]

---

📎 อ้างอิงการตัดสินใจเชิงเทคนิค: [spec หรือ ADR ลบบรรทัดนี้ถ้าไม่มี]
```

The Thai section headings and their emoji are the team's required shape; keep them as written. When the change shows on several screens, or touches existing data that lacks the new value, add one AC per screen and one fallback AC for that data (see the Story additions in `acceptance-criteria.md`).

Weak and strong versions of the business reason:

- Weak: "เพื่อยกระดับประสบการณ์ผู้ใช้และเพิ่มความถูกต้องของระบบ"
- Strong: "ตอนนี้ยอดคงเหลือถูกหักตอนสิ้นวัน ลูกค้าที่สั่งซ้ำก่อนสิ้นวันจึงสั่งเกินยอดได้ ต้องหักทันทีที่ยืนยัน"

Next: `SKILL.md` Step 3 (metadata: issue type `Story`, priority `Medium` by default, no environment or versions rows), then Step 4 (preview) and Step 5 (create).
