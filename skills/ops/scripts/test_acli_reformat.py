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

print("ok: acli-reformat")
