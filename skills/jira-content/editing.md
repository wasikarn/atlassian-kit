# Editing an existing ticket or comment

Moved out of `SKILL.md` so the main file stays small; `SKILL.md` links here. Paths below are relative to this folder.

## Editing an existing Jira issue's description

Template-conforming edits — fixing a description that doesn't match team format, adding a missing AC, appending a status update — use acli's read-modify-write scripts. **Never** blind-replace with `acli jira workitem edit --description` (wraps plain text into one literal ADF paragraph — see `atlassian-kit:ops` § Description format).

```bash
bash "${CLAUDE_SKILL_DIR}/scripts/acli-edit.sh" KEY notes.md
bash "${CLAUDE_SKILL_DIR}/scripts/acli-edit.sh" KEY --replace-section "🧪 เกณฑ์การยอมรับ" new-ac.md
bash "${CLAUDE_SKILL_DIR}/scripts/acli-set-desc.sh" KEY desc.md   # full replace only
```

Same preview-and-confirm gate as create: render the new body (both scripts support `--dry-run`), show it, edit only on the user's explicit go-ahead. Note `--dry-run` still contacts production — both scripts fetch the live description first, then skip only the final write; there's no fully offline way to preview an edit against a real ticket.

To sanity-check the merge logic itself with zero production contact (e.g. while developing this skill, or validating a tricky `--replace-section` heading match before risking it on a real ticket), call the underlying merge script directly against local files instead of going through `acli-edit.sh`: `python3 "${CLAUDE_SKILL_DIR}/../ops/scripts/acli-edit.py" MODE KEY CUR.json OUT.json [NEW.json] [HEADING]` (`MODE` is `append`/`remove`/`replace`; `CUR.json` is a local bare ADF doc used as the current description, or a saved `view --json` payload for the same `KEY`; it doesn't need to come from a live ticket). This is a testing aid, not part of the normal user-facing edit flow — the two commands above stay the documented way to actually edit a ticket.

Before any full-body replace (`acli-set-desc.sh`, or `--replace-section` on a section that might carry one) on an existing ticket, count structural nodes first — `acli jira workitem view KEY --json | python3 "${CLAUDE_SKILL_DIR}/../ops/scripts/adf-node-diff.py" -`. If `table`/`expand`/`panel`/`extension` count > 0, a Markdown round-trip silently drops them (see `atlassian-kit:ops` § Description format) — edit around the affected section instead of a full-body replace.

## Editing an existing templated comment

Fixing/updating a comment that already follows one of the 4 `templates/comments.md` shapes — e.g. "แก้ comment สถานะล่าสุดให้หน่อย". **Never** hand this to acli's raw `comment update --body-adf` without going through the template first.

```bash
# 1. Read existing comment (find its id first if not given):
acli jira workitem view KEY --fields comment --json
# 2. Edit the Markdown per templates/comments.md (keep AC# numbering if it references the ticket's own AC). Preview before sending.
# 3. Re-convert and update (comment update needs --body-adf, not --body-file):
bash "${CLAUDE_SKILL_DIR}/scripts/md2adf.sh" note.md > /tmp/note.json
acli jira workitem comment update --key KEY --id <commentId> --body-adf /tmp/note.json
```

## Reformat a ticket that arrived as plain text

A ticket created from a Jira form (or typed without headings) has its sections as plain lines, so it does not look like the template. Preview the fix, then apply:

```bash
python3 "${CLAUDE_SKILL_DIR}/../ops/scripts/acli-reformat.py" KEY            # preview, writes nothing
python3 "${CLAUDE_SKILL_DIR}/../ops/scripts/acli-reformat.py" KEY --apply    # write
```

It turns a line that exactly matches a section name (Environment, Test Data, Steps to Reproduce, Expected Result, Actual Result, ผลกระทบ, Evidence, Workaround, Regression, Acceptance Criteria) into a heading, `1.` lines into a numbered list, and the lines under Environment into bullets. It never reorders, rewords or adds a section; the preview lists the template sections the ticket lacks, which a person has to write. A description that already has headings is left alone.
