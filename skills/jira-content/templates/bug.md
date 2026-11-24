# Bug: gather questions and Thai description

Loaded by `atlassian-kit:jira-content` Steps 1 and 2. The shared metadata table, preview gate and create commands live in `SKILL.md`. Other rules are defined once, elsewhere:

- AC format, register and coverage: [`acceptance-criteria.md`](../../../templates/acceptance-criteria.md)
- Title: [`title-conventions.md`](title-conventions.md)
- Wording of the ticket text: [`README.md`](README.md) § Writing rules

This file holds only the Bug questions and the Thai description.

## Step 1: gather

Ask all seven at once. Done when items 1 to 6 each have an answer from the user. If the user cannot answer one, write `ไม่ทราบ` in that section; a guess is never an answer. Item 7 may be empty.

1. **Bug summary**: a short Thai title naming the symptom, e.g. "ยอดคงเหลือไม่ถูกหักหลังลูกค้ายืนยันการสั่งซื้อ"
2. **What happened**: the wrong result as the user saw it (message text, wrong value, status code)
3. **What should have happened**: the correct result
4. **How to reproduce**: exact numbered steps
5. **Where and how often**: environment (prod / staging / local), screen or channel, every time or sometimes (and the condition)
6. **Impact**: who is affected and how badly (money, data loss, blocked workflow, cosmetic)
7. **Evidence**: screenshot, log line, error code, trace ID, affected record ID

If the user's first message already answers items 1 to 6, go straight to Step 2.

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

1. [ขั้นตอน]
2. [ขั้นตอน]
3. [ขั้นตอน]

> 📌 ผลลัพธ์ที่ได้: [ค่าหรือข้อความที่เห็นจริง]
> 📌 ผลลัพธ์ที่คาดหวัง: [ค่าหรือข้อความที่ควรเห็น]

---

## 🌐 ความถี่และเงื่อนไข

* **ความถี่:** [เกิดทุกครั้ง / เกิดบางครั้ง พร้อมเงื่อนไข]
* **ช่องทาง/หน้าจอที่เกี่ยวข้อง:** [เช่น แอป Player, หน้า Admin, เว็บไซต์]

> ℹ️ สภาพแวดล้อม (prod/staging/local) และเวอร์ชัน/Build จะบันทึกใน **field ของ Jira โดยตรง** (Environment + Affects versions) ไม่ใส่ในคำอธิบายนี้

---

## 💥 ผลกระทบ (Impact)

[ใครได้รับผลกระทบ รุนแรงแค่ไหน ใส่จำนวนหรือยอดเงินถ้ามี]

---

## 📎 หลักฐานประกอบ (Evidence)

[screenshot, log, error code, trace ID ลบทั้ง section ถ้าไม่มี]

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
