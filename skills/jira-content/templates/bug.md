# Bug: gather questions and Thai description

Loaded by `atlassian-kit:jira-content` Steps 1 and 2. The shared metadata table, preview gate and create commands live in `SKILL.md`. Other rules are defined once, elsewhere:

- AC format, register and coverage: [`acceptance-criteria.md`](../../../templates/acceptance-criteria.md)
- Title: [`title-conventions.md`](title-conventions.md)
- Wording of the ticket text: [`README.md`](README.md) § Writing rules

This file holds only the Bug questions and the Thai description.

## Step 1: gather

Ask all eleven at once. Done when items 1 to 3, 5 and 6 each have an answer from the user. If the user cannot answer one, write `ไม่ทราบ` in that section; a guess is never an answer. Items 4 and 7 to 11 may be empty; a section with no answer is deleted.

1. **Bug summary**: a short Thai title naming the symptom, e.g. "ยอดคงเหลือไม่ถูกหักหลังลูกค้ายืนยันการสั่งซื้อ"
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

Ask the optional fields in [`fields.md`](fields.md) in the same message (priority, assignee, due date, start date, components, fix versions, team, sprint). A field the user leaves out stays unset.

## Step 2: write the description

Write in Thai with this structure. Fill each section from the Step 1 answers only. Done when no `[ ]` placeholder is left, every AC has all three bullets, and there are at least 2 ACs (fix verified, regression).

```
## 🐞 อาการที่พบ (สิ่งที่เกิดขึ้นจริง)

[2-3 ประโยค: หน้าจอหรือ API ตอบอะไร ค่าที่ผิดคืออะไร]

---

## ✅ สิ่งที่ควรเป็น (ผลลัพธ์ที่ถูกต้อง)

[ระบบควรทำอะไรแทน]

---

## 🔁 ขั้นตอนการเกิดปัญหา (Steps to Reproduce)

[ลบทั้ง section ถ้าไม่มีขั้นตอน]

1. [ขั้นตอน]
2. [ขั้นตอน]
3. [ขั้นตอน]

> 📌 ผลลัพธ์ที่ได้: [ค่าหรือข้อความที่เห็นจริง]
> 📌 ผลลัพธ์ที่คาดหวัง: [ค่าหรือข้อความที่ควรเห็น]

---

## 🌐 ความถี่และเงื่อนไข

* **ความถี่:** [เกิดทุกครั้ง / เกิดบางครั้ง พร้อมเงื่อนไข]
* **ช่องทาง/หน้าจอที่เกี่ยวข้อง:** [เช่น แอป Player, หน้า Admin, เว็บไซต์]
* **เครื่อง/Client:** [browser, OS, อุปกรณ์, app version, URL ลบบรรทัดนี้ถ้าไม่มี]

> ℹ️ สภาพแวดล้อม (production/uat/sit/staging/dev/local) และเวอร์ชัน/Build จะบันทึกใน **field ของ Jira โดยตรง** (Environment + Affects versions) ไม่ใส่ในคำอธิบายนี้

---

## 💥 ผลกระทบ (Impact)

[ใครได้รับผลกระทบ รุนแรงแค่ไหน ใส่จำนวนหรือยอดเงินถ้ามี]

---

## 📎 หลักฐานประกอบ (Evidence)

[screenshot, log, error code, trace ID ลบทั้ง section ถ้าไม่มี]

---

## 🧾 ข้อมูลที่ใช้ทดสอบ (Test data)

[account, record ID หรือข้อมูลที่ใช้ทำให้เกิดบั๊ก ลบทั้ง section ถ้าไม่มี]

---

## 🩹 วิธีเลี่ยงชั่วคราว (Workaround)

[วิธีเลี่ยงและขั้นตอน หรือ "ไม่มี" ลบทั้ง section ถ้าไม่ทราบ]

---

## ⏪ Regression

[เคยทำงานปกติใน version หรือวันที่เท่าไร และอะไรเปลี่ยนหลังจากนั้น ลบทั้ง section ถ้าไม่ทราบ]

---

## 🧪 เกณฑ์การยอมรับการแก้ไข (Acceptance Criteria) สำหรับ QA

**AC1 — ยืนยันว่าแก้แล้ว (Fix verified)**

* กำหนดให้: [สถานะที่เคยทำให้เกิดบั๊ก]
* เมื่อ: [การกระทำที่เคยทำให้เกิดบั๊ก]
* ผลลัพธ์: [ผลที่ถูกต้องตอนนี้ ระบุให้เจาะจง]

**AC2 — ตรวจ Regression**

* กำหนดให้: [สถานะหรือ flow ที่ไม่เกี่ยวกับบั๊ก]
* เมื่อ: [การกระทำปกติ]
* ผลลัพธ์: ทำงานเหมือนเดิม ไม่ได้รับผลกระทบจากการแก้รอบนี้
```

The Thai section headings and their emoji are the team's required shape; keep them as written.

Weak and strong versions of the first section:

- Weak: "ระบบทำงานผิดพลาดตอนสั่งซื้อ ทำให้ผู้ใช้ได้รับผลกระทบ"
- Strong: "หลังลูกค้ากดยืนยันสั่งซื้อ 200 บาท หน้าจอขึ้น 'สำเร็จ' แต่ยอดคงเหลือยังเป็น 500 บาท"

Next: `SKILL.md` Step 3 (metadata: issue type `Bug`, priority from severity, plus the Bug-only Environment and Affects versions), then Step 4 (preview) and Step 5 (create).
