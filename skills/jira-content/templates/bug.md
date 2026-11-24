# Bug: gather questions and Thai description

Loaded by `atlassian-kit:jira-content` Steps 1 and 2. The shared metadata table, preview gate and create commands live in `SKILL.md`. Other rules are defined once, elsewhere:

- AC format, register and coverage: [`acceptance-criteria.md`](../../../templates/acceptance-criteria.md)
- Title: [`title-conventions.md`](title-conventions.md)
- Wording of the ticket text: [`writing-rules.md`](../../../templates/writing-rules.md)

This file holds only the Bug questions and the Thai description.

## Step 1: gather

Ask all eleven at once. Done when items 1 to 3, 5 and 6 each have an answer from the user. If the user cannot answer one, write `ไม่ทราบ` in that section; a guess is never an answer. Items 4 and 7 to 11 may be empty; a section with no answer is deleted.

1. **Bug summary**: a short Thai title naming the symptom, e.g. "ยอดคงเหลือไม่ถูกหักหลังลูกค้ายืนยันการสั่งซื้อ". Ask whether the team uses title tags such as `[RePI][Desktop][F7_E2E]` (system, platform, test suite); if so, put them first
2. **What happened**: the wrong result as the user saw it (message text, wrong value, status code)
3. **What should have happened**: the correct result
4. **How to reproduce** (optional): exact numbered steps
5. **Where and how often**: environment (offer production / uat / sit / staging / dev / local, or any value the user types; the user may skip it), screen or channel, every time or sometimes (and the condition)
6. **Impact**: who is affected and how badly (money, data loss, blocked workflow, cosmetic)
7. **Evidence**: screenshot, log line, error code, trace ID, affected record ID
8. **Test data**: account, record ID, or the data used to trigger it
9. **Workaround**: is there a way around it, and what is it (or "none")
10. **Regression**: the last version or date it worked, and what changed since
11. **Client details**: browser, OS, device, app version, URL

If the user's first message already answers items 1 to 6, go straight to Step 2.

## Step 2: write the description

Write in Thai with this structure. Fill each section from the Step 1 answers only. Done when no `[ ]` placeholder is left, every AC has all three bullets, and there are at least 2 ACs (fix verified, regression).

```
## Environment

* Device: [อุปกรณ์หรือ browser เช่น Desktop (Chrome)]
* Version: [เวอร์ชัน/Build ของ Web หรือ App]
* Env: [production / uat / sit / staging / dev / local]
* ความถี่: [เกิดทุกครั้ง / เกิดบางครั้ง พร้อมเงื่อนไข]
* ช่องทาง/หน้าจอ: [เช่น แอป Player, หน้า Admin, เว็บไซต์]
* Client อื่นๆ: [OS, URL ลบบรรทัดนี้ถ้าไม่มี]

## Test Data

[account, record ID หรือข้อมูลที่ใช้ทำให้เกิดบั๊ก ลบทั้ง section ถ้าไม่มี]

## Steps to Reproduce

[ลบทั้ง section ถ้าไม่มีขั้นตอน]

1. [ขั้นตอน]
2. [ขั้นตอน]
3. [ขั้นตอน]

## Expected Result

1. [ผลที่ควรเห็น เจาะจง]

## Actual Result

1. [ผลที่เห็นจริง ข้อเดียวกับ Expected ข้อ 1]

## ผลกระทบ (Impact)

[ใครได้รับผลกระทบ รุนแรงแค่ไหน ใส่จำนวนหรือยอดเงินถ้ามี]

## หลักฐานประกอบ (Evidence)

[screenshot, log, error code, trace ID ลบทั้ง section ถ้าไม่มี]

## วิธีเลี่ยงชั่วคราว (Workaround)

[วิธีเลี่ยงและขั้นตอน หรือ "ไม่มี" ลบทั้ง section ถ้าไม่ทราบ]

## Regression

[เคยทำงานปกติใน version หรือวันที่เท่าไร และอะไรเปลี่ยนหลังจากนั้น ลบทั้ง section ถ้าไม่ทราบ]

## Acceptance Criteria

**AC1: ยืนยันว่าแก้แล้ว (Fix verified)**

* กำหนดให้: [สถานะที่เคยทำให้เกิดบั๊ก]
* เมื่อ: [การกระทำที่เคยทำให้เกิดบั๊ก]
* ผลลัพธ์: [ผลที่ถูกต้องตอนนี้ ระบุให้เจาะจง]

**AC2: ตรวจ Regression**

* กำหนดให้: [สถานะหรือ flow ที่ไม่เกี่ยวกับบั๊ก]
* เมื่อ: [การกระทำปกติ]
* ผลลัพธ์: ทำงานเหมือนเดิม ไม่ได้รับผลกระทบจากการแก้รอบนี้
```

The section order and the English headings Environment, Test Data, Steps to Reproduce, Expected Result and Actual Result follow the team's real Bug tickets (APPR-8455); the sections after them are this kit's additions. Write the same Environment and Version values into the Jira fields too (Environment, Affects versions; [`fields.md`](fields.md)). When there are several wrong results, number them and keep each Actual item paired with the Expected item of the same number.

Weak and strong versions of an Actual Result item:

- Weak: "ระบบทำงานผิดพลาดตอนสั่งซื้อ ทำให้ผู้ใช้ได้รับผลกระทบ"
- Strong: "หลังลูกค้ากดยืนยันสั่งซื้อ 200 บาท หน้าจอขึ้น 'สำเร็จ' แต่ยอดคงเหลือยังเป็น 500 บาท"

Next: `SKILL.md` Step 3 (metadata: issue type `Bug`, priority from severity, plus the Bug-only Environment and Affects versions), then Step 4 (preview) and Step 5 (create).
