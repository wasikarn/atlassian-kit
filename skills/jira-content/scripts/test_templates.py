#!/usr/bin/env python3
"""Checks on the ticket and page templates: no em dash in ticket-visible text, payload shape,
guided/payload section parity, relative links, and md2adf flags documented in ops/SKILL.md."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DASH = chr(0x2014)
DASH_EXEMPT = {"writing-rules.md"}  # the rule file names the mark on purpose
PARITY = ("task", "epic", "subtask")  # guided headings equal payload headings for these three


def dash_hits(path):
    return [f"{path.name}:{n}" for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1) if DASH in line]


def payload_problems(doc):
    """A heading holds text only; a listItem sits inside a list."""
    bad = []

    def walk(node, parent):
        if isinstance(node, dict):
            kind = node.get("type")
            if kind == "heading" and any(c.get("type") != "text" for c in node.get("content", [])):
                bad.append("heading with a non-text child")
            if kind == "listItem" and parent not in ("bulletList", "orderedList"):
                bad.append(f"listItem inside {parent}")
            for value in node.values():
                walk(value, kind)
        elif isinstance(node, list):
            for value in node:
                walk(value, parent)

    walk(doc, None)
    return bad


def payload_headings(doc):
    out = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "heading":
                out.append("".join(c.get("text", "") for c in node["content"]))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(doc)
    return out


def guided_headings(md):
    blocks = re.findall(r"```\n(.*?)```", md, re.S)
    return [line[2:] for block in blocks for line in block.split("\n") if line.startswith("# ")]


def broken_links(path):
    bad = []
    for target in re.findall(r"\]\(([^)\s]+)\)", path.read_text(encoding="utf-8")):
        if target == "url" or re.match(r"(https?:|mailto:|#)", target) or re.search(r"[<>$\{]", target):  # "url" is the placeholder in Markdown-syntax docs
            continue
        if not (path.parent / target.split("#")[0]).exists():
            bad.append(f"{path.name}: {target}")
    return bad


def undocumented_flags(py_text, md_text):
    """Each add_argument option must show up on a line of the doc that mentions md2adf."""
    doc = "\n".join(line for line in md_text.splitlines() if "md2adf" in line)
    missing = []
    for call in re.findall(r"add_argument\(([^)]*?)(?:,\s*help|\))", py_text):
        opts = re.findall(r'"(--?[\w-]+)"', call)
        if opts and not any(re.search(rf"(?<![\w-]){re.escape(o)}(?![\w-])", doc) for o in opts):
            missing.append("/".join(opts))
    return missing


# --- the checks themselves, on synthetic input ------------------------------------------------
def test_checks_catch_what_they_claim():
    tmp = Path(__file__).resolve().parent / "_tmp_templates_check"
    tmp.mkdir(exist_ok=True)
    try:
        f = tmp / "a.md"
        f.write_text("ok\nAC1 " + DASH + " x\n", encoding="utf-8")
        assert dash_hits(f) == ["a.md:2"]
        f.write_text("[a](missing.md) [b](a.md) [c](https://x.y) [d](#top)\n", encoding="utf-8")
        assert broken_links(f) == ["a.md: missing.md"]
    finally:
        for p in tmp.iterdir():
            p.unlink()
        tmp.rmdir()
    text = {"type": "text", "text": "t"}
    good = {"type": "doc", "content": [{"type": "heading", "content": [text]},
                                      {"type": "bulletList", "content": [{"type": "listItem", "content": []}]}]}
    assert payload_problems(good) == []
    misplaced = {"type": "doc", "content": [{"type": "heading", "content": [text, {"type": "listItem", "content": []}]}]}
    assert payload_problems(misplaced) == ["heading with a non-text child", "listItem inside heading"]
    assert guided_headings("x\n```\n# A\n* b\n# C\n```\n") == ["A", "C"]
    assert payload_headings({"type": "heading", "content": [{"type": "text", "text": "A"}]}) == ["A"]
    py = 'ap.add_argument("-a", "--attrs", help="x")\nap.add_argument("--new", help="y")\n'
    assert undocumented_flags(py, "md2adf.py x -a '{}'") == ["--new"]


# --- the repo ---------------------------------------------------------------------------------
def ticket_text_files():
    dirs = [ROOT / "skills/jira-content/templates", ROOT / "skills/confluence-content/templates", ROOT / "templates"]
    return [p for d in dirs for p in sorted(d.iterdir()) if p.suffix in (".md", ".json") and p.name not in DASH_EXEMPT]


def test_no_em_dash_in_ticket_visible_text():
    hits = [h for p in ticket_text_files() for h in dash_hits(p)]
    assert not hits, f"em dash in {hits}"


def test_payloads_are_well_formed():
    for p in sorted((ROOT / "skills/jira-content/templates").glob("*.payload.json")):
        problems = payload_problems(json.loads(p.read_text(encoding="utf-8")))
        assert not problems, f"{p.name}: {problems}"


def test_guided_and_payload_sections_match():
    t = ROOT / "skills/jira-content/templates"
    for name in PARITY:
        guided = guided_headings((t / f"{name}.md").read_text(encoding="utf-8"))
        payload = payload_headings(json.loads((t / f"{name}.payload.json").read_text(encoding="utf-8")))
        assert guided == payload, f"{name}: guided {guided} != payload {payload}"


def test_relative_links_resolve():
    files = list((ROOT / "skills").rglob("*.md")) + list((ROOT / "templates").glob("*.md")) + [ROOT / "README.md"]
    bad = [b for p in files for b in broken_links(p)]
    assert not bad, f"broken links {bad}"


def test_md2adf_flags_are_documented_in_ops_skill():
    py = (ROOT / "skills/ops/scripts/md2adf.py").read_text(encoding="utf-8")
    md = (ROOT / "skills/ops/SKILL.md").read_text(encoding="utf-8")
    assert not undocumented_flags(py, md), f"not in ops/SKILL.md: {undocumented_flags(py, md)}"


if __name__ == "__main__":
    failed = 0
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        try:
            fn()
        except AssertionError as e:
            failed += 1
            print(f"FAIL {name}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
