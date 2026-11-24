# Writing rules for ticket and page text

The one place that says how to word text a content template asks you to write (Jira tickets and comments, Confluence pages). Each template links here instead of repeating it. These rules distil `siang:technical-writing` and `siang:humanize`, so they work on a machine without that plugin. When siang is installed, run it as an extra pass; this file is still the baseline.

## Pass 1: say it so the reader can act

Run it on every prose field (summary, reason, scope, impact, context, notes). Done when each line passes all six checks.

1. Name the reader and the job. A ticket reader is a PO, QA or developer who must finish or verify the work without asking you.
2. Use the user's specifics: numbers, screen names, error text, IDs, file paths. Write what fails and when ("ขึ้น 'สำเร็จ' แต่ยอดยัง 500 บาท"), not that something "ทำงานผิดพลาด".
3. Use only facts the user gave. When a fact is missing, write `ไม่ทราบ` or ask. A guessed value, date or cause goes in no section.
4. Lead each section with its outcome. One idea per line; one action per step.
5. Delete a section that has nothing real in it. A required section is never deleted; write `ไม่ทราบ` instead.
6. Read the draft once as a reader with nothing else open. A term you cannot place, or a step you cannot perform from the page, gets fixed or named as `ไม่ทราบ`.

## Pass 2: remove what reads as AI-written

Run it after Pass 1, on the same fields. Done when none of these is left.

- **Em dash (`—`).** Use a comma, a colon or a new sentence.
- **Importance and filler words:** "สำคัญอย่างยิ่ง", "ครอบคลุม", "ยกระดับ", "อย่างมีประสิทธิภาพ", and reassurance such as "ไม่ต้องกังวล".
- **A closing line that restates the section,** and a first line that announces what comes next.
- **Forced triads:** three items listed to sound complete when the user gave two.
- **"Not X but Y"** framing, and bold labels on every bullet.
- **Thai order:** put a condition clause (`ถ้า`, `หาก`, `เมื่อ`, `หลัง`, `ตอน`) at the front of the sentence, not the end.
- **Plain verbs:** คือ, เป็น, มี instead of a stacked noun phrase.
- **Terms and numbers:** keep technical terms in English (repo, branch, deploy), write quantities as Arabic numerals ("2 ตัว"), and put a space between Thai and English words.

## What neither pass touches

AC blocks (the กำหนดให้, เมื่อ, ผลลัพธ์ bullets), section headings, code, IDs and quoted error text. Neither pass adds a fact the user did not give.

## Final check, on any machine

Before the preview, count the em dashes in the file you are about to send. It must print 0:

```bash
grep -o "—" body.md | wc -l
```

A dash inside quoted error text or code is the only allowed hit; write it out as the words "em dash" when a ticket needs to mention the mark. When `siang:humanize` is installed, also run its `scan.py` on the file and read every hit.

Source of the full rules: the `siang` plugin (`siang:technical-writing`, `siang:humanize`). This file keeps only what ticket and page text needs, so it can lag behind siang.
