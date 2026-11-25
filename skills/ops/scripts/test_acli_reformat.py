#!/usr/bin/env python3
"""Tests for acli-reformat.py (framework-free)."""
import importlib.util, os

here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("reformat", os.path.join(here, "acli-reformat.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def para(*lines):
    c = []
    for i, ln in enumerate(lines):
        if i:
            c.append({"type": "hardBreak"})
        if ln:
            c.append({"type": "text", "text": ln})
    return {"type": "paragraph", "content": c}


def doc(*nodes):
    return {"type": "doc", "version": 1, "content": list(nodes)}


def kinds(d):
    return [n["type"] for n in d["content"]]


def texts(n):
    return [i["content"][0]["content"][0]["text"] for i in n["content"]]


# 1. one paragraph with line breaks, the shape a plain submit produces
d, found = m.reformat(doc(para(
    "Environment", "Device: Desktop (Chrome)", "Env: sit", "",
    "Steps to Reproduce", "1. open", "2. submit", "",
    "Expected Result", "1. a ticket", "",
    "ผลกระทบ", "none")))
assert found == ["Environment", "Steps to Reproduce", "Expected Result", "ผลกระทบ (Impact)"], found
assert kinds(d) == ["heading", "bulletList", "heading", "orderedList", "heading", "orderedList",
                    "heading", "paragraph"], kinds(d)
assert texts(d["content"][1]) == ["Device: Desktop (Chrome)", "Env: sit"]
assert texts(d["content"][3]) == ["open", "submit"]

# 2. one paragraph per line, bold label and trailing colon still match
d, found = m.reformat(doc(para("Test Data:"), para("account 1"), para("**Actual Result**"), para("- wrong value")))
assert found == ["Test Data", "Actual Result"] and kinds(d) == ["heading", "paragraph", "heading", "bulletList"]

# 3. left alone: already formatted, or too few section names
assert m.reformat(doc({"type": "heading", "attrs": {"level": 2}, "content": [], }, para("x")))[0] is None
assert m.reformat(doc(para("just a sentence", "Environment")))[1] == "no known section names found"

# 4. a paragraph with a mention or link is kept as is; other blocks pass through
rich = {"type": "paragraph", "content": [{"type": "mention", "attrs": {"id": "1"}}]}
rule = {"type": "rule"}
d, _ = m.reformat(doc(para("Environment", "Env: sit"), rich, rule, para("Actual Result", "1. x")))
assert rich in d["content"] and rule in d["content"]

# 5. headings are matched exactly, not by prefix
assert m.reformat(doc(para("Environment details", "Test Data notes")))[0] is None

# 6. the Env bullet feeds the Environment field; no Env line means None
d, _ = m.reformat(doc(para("Environment", "Device: x", "Env : sit", "Actual Result", "1. y")))
assert m.env_value(d) == "sit"
d, _ = m.reformat(doc(para("Environment", "Device: x", "Actual Result", "1. y")))
assert m.env_value(d) is None

# 7. marks (bold, link) survive in paragraphs, list items and Environment bullets
BOLD, LINK = [{"type": "strong"}], [{"type": "link", "attrs": {"href": "http://x"}}]


def line(*nodes):
    return list(nodes)


def rich_para(*lines):
    c = []
    for i, ln in enumerate(lines):
        if i:
            c.append({"type": "hardBreak"})
        c.extend(ln)
    return {"type": "paragraph", "content": c}


def T(s, marks=None):
    n = {"type": "text", "text": s}
    if marks:
        n["marks"] = marks
    return n


d, _ = m.reformat(doc(rich_para(
    [T("Environment")], [T("Env: "), T("sit", BOLD)], [T("Steps to Reproduce")],
    [T("1. press "), T("Save", BOLD)], [T("see "), T("docs", LINK)], [T("Actual Result")], [T("- bad")])))
env_item = d["content"][1]["content"][0]["content"][0]["content"]
assert env_item[1] == T("sit", BOLD), env_item
step = d["content"][3]["content"][0]["content"][0]["content"]
assert step == [T("press "), T("Save", BOLD)], step
para_nodes = d["content"][4]["content"]
assert para_nodes == [T("see "), T("docs", LINK)], para_nodes

# 8. env_value reads only the Environment section
d = doc({"type": "heading", "attrs": {"level": 2}, "content": [T("Test Data")]},
        {"type": "bulletList", "content": [m._item([T("Env: prod")])]},
        {"type": "heading", "attrs": {"level": 2}, "content": [T("Environment")]},
        {"type": "bulletList", "content": [m._item([T("Device: x")])]})
assert m.env_value(d) is None
d["content"].append({"type": "heading", "attrs": {"level": 2}, "content": [T("Actual Result")]})
d["content"].append({"type": "bulletList", "content": [m._item([T("Env: stage")])]})
assert m.env_value(d) is None
d["content"][3]["content"].append(m._item([T("Env: sit")]))
assert m.env_value(d) == "sit"

# 9. main(): description written, Environment failed; a retry sets only the Environment
import json, tempfile
calls = []


class Done:
    def __init__(self, rc=0):
        self.returncode, self.stdout, self.stderr = rc, "", ""


def run_main(view_fields, argv_extra, env_rc=0):
    del calls[:]
    p = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump({"fields": view_fields}, p)
    p.close()

    def fake(cmd, **kw):
        calls.append(cmd)
        return Done(env_rc if any("set-batch" in str(c) for c in cmd) else 0)
    real, m.subprocess.run = m.subprocess.run, fake
    try:
        rc = m.main(["APPR-1", "--file", p.name] + argv_extra)
    finally:
        m.subprocess.run = real
        os.unlink(p.name)
    return rc


headed = doc({"type": "heading", "attrs": {"level": 2}, "content": [T("Environment")]},
             {"type": "bulletList", "content": [m._item([T("Env: sit")])]})
rc = run_main({"description": headed}, ["--apply"])
assert rc == 0 and len(calls) == 1 and "set-batch" in " ".join(calls[0]), calls
rc = run_main({"description": headed, "environment": {"type": "doc", "version": 1, "content": [
    {"type": "paragraph", "content": [T("sit")]}]}}, ["--apply"])
assert rc == 0 and calls == [], calls  # already set, nothing to do
rc = run_main({"description": headed}, [])
assert rc == 0 and calls == [], calls  # preview never writes
rc = run_main({"description": headed}, ["--apply"], env_rc=3)
assert rc == 3

# 10. a marked heading line keeps its marks; a mixed-marks line is not turned into a heading
d, found = m.reformat(doc(rich_para([T("Environment", LINK)], [T("Env: sit")], [T("Test Data")], [T("a")])))
assert found == ["Environment", "Test Data"] and d["content"][0]["content"] == [T("Environment", LINK)], d["content"][0]
d, found = m.reformat(doc(rich_para([T("Environment")], [T("Env: sit")], [T("Test "), T("Data", BOLD)], [T("a")],
                                    [T("Actual Result")], [T("- x")])))
assert found == ["Environment", "Test Data", "Actual Result"], found
assert d["content"][2] == {"type": "heading", "attrs": {"level": 2}, "content": [T("Test Data")]}, d["content"][2]

# 11. an Env bullet under a mixed-marks Test Data heading is not the Environment value
d, _ = m.reformat(doc(rich_para([T("Environment")], [T("Device: phone")], [T("Test "), T("Data", BOLD)],
                                [T("Env: prod")], [T("Actual Result")], [T("- failure")])))
assert m.env_value(d) is None

print("ok: acli-reformat")
