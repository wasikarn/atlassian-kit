#!/usr/bin/env python3
"""acli-reformat: turn a plain-text Bug description (for example one submitted
through a Jira form) into the template's shape: real headings, numbered and
bulleted lists. Previews by default; --apply writes.

Usage:
  python3 acli-reformat.py KEY            # preview
  python3 acli-reformat.py KEY --apply    # write with acli edit --from-json
  python3 acli-reformat.py KEY --file view.json   # offline: read a saved view payload

Only text lines that exactly match a known section name become headings, and
nothing is reordered, added or reworded. With --apply, an "Env: x" line under Environment also sets the Jira Environment field. A description that already has headings
is left alone.
"""
import json, os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from adf2md import render_block

HEADINGS = {
    "environment": "Environment",
    "test data": "Test Data",
    "steps to reproduce": "Steps to Reproduce",
    "expected result": "Expected Result",
    "actual result": "Actual Result",
    "ผลกระทบ": "ผลกระทบ (Impact)",
    "impact": "ผลกระทบ (Impact)",
    "หลักฐาน": "หลักฐานประกอบ (Evidence)",
    "evidence": "หลักฐานประกอบ (Evidence)",
    "วิธีเลี่ยงชั่วคราว": "วิธีเลี่ยงชั่วคราว (Workaround)",
    "workaround": "วิธีเลี่ยงชั่วคราว (Workaround)",
    "regression": "Regression",
    "acceptance criteria": "Acceptance Criteria",
}
TEMPLATE = ["Environment", "Test Data", "Steps to Reproduce", "Expected Result", "Actual Result",
            "ผลกระทบ (Impact)", "Acceptance Criteria"]
NUM = re.compile(r"^\s*\d+[.)]\s+")
BUL = re.compile(r"^\s*[-*" + chr(0x2022) + r"]\s+")
ENV = re.compile(r"^\s*env(ironment)?\s*:\s*(.+)$", re.I)


def _key(line):
    s = line.strip().strip("*").strip().rstrip(":").strip()
    s = re.sub(r"\s*\(.*\)$", "", s)  # "ผลกระทบ (Impact)" -> "ผลกระทบ"
    return s.lower()


def _lines(node):
    """Lines of a paragraph, each a list of text nodes (marks kept), or None when it holds
    anything but text and line breaks."""
    out, cur = [], []
    for c in node.get("content", []):
        if c.get("type") == "text":
            cur.append(c)
        elif c.get("type") == "hardBreak":
            out.append(cur)
            cur = []
        else:
            return None
    out.append(cur)
    return out


def _plain(node):
    """All text under an ADF node."""
    if not isinstance(node, dict):
        return ""
    return node.get("text", "") + "".join(_plain(c) for c in node.get("content", []))


def _para(nodes):
    return {"type": "paragraph", "content": nodes}


def _item(nodes):
    return {"type": "listItem", "content": [_para(nodes)]}


def _after(nodes, rx):
    """The nodes with the list marker removed from the first one, or None if it spans nodes."""
    first = nodes[0]
    m = rx.match(first.get("text", ""))
    if not m:
        return None
    rest = first["text"][m.end():]
    return ([dict(first, text=rest)] if rest else []) + nodes[1:]


def reformat(doc):
    """Return (new_doc, headings_found), or (None, reason) when the text is left alone."""
    nodes = doc.get("content", [])
    if any(n.get("type") == "heading" for n in nodes):
        return None, "already has headings"
    flat = []
    for n in nodes:
        ls = _lines(n) if n.get("type") == "paragraph" else None
        if ls is None:
            flat.append(("raw", n))
        else:
            flat.extend(("t", s) for s in ls)
    out, found = [], []
    state = {"section": None, "list": None}

    def add_item(kind, nodes):
        lst = state["list"]
        if lst is None or lst["type"] != kind:
            lst = {"type": kind, "content": []}
            if kind == "orderedList":
                lst["attrs"] = {"order": 1}
            out.append(lst)
            state["list"] = lst
        lst["content"].append(_item(nodes))

    for kind, val in flat:
        if kind == "raw":
            state["list"] = None
            out.append(val)
            continue
        s = _plain({"content": val}).strip()
        if not s:
            state["list"] = None
        elif _key(s) in HEADINGS and (len(val) == 1 or not any(n.get("marks") for n in val)):
            state["list"] = None
            state["section"] = HEADINGS[_key(s)]
            found.append(state["section"])
            # a single marked node (a linked "Environment") keeps its marks on the canonical name
            node = dict(val[0], text=state["section"]) if len(val) == 1 else {"type": "text", "text": state["section"]}
            out.append({"type": "heading", "attrs": {"level": 2}, "content": [node]})
        elif NUM.match(s) and _after(val, NUM):
            add_item("orderedList", _after(val, NUM))
        elif BUL.match(s) and _after(val, BUL):
            add_item("bulletList", _after(val, BUL))
        elif state["section"] == "Environment" and ":" in s:
            add_item("bulletList", val)
        else:
            state["list"] = None
            out.append(_para(val))
    if len(found) < 2:
        return None, "no known section names found"
    return {"type": "doc", "version": 1, "content": out}, found


def env_value(doc):
    """The value of an "Env: ..." bullet inside the Environment section, or None."""
    section = None
    for n in doc.get("content", []):
        if n.get("type") == "heading":
            section = _key(_plain(n))
        elif n.get("type") == "bulletList" and section == "environment":
            for it in n.get("content", []):
                m = ENV.match(_plain(it).strip())
                if m:
                    return m.group(2).strip()
    return None


def _env_text(v):
    """Plain text of the Environment field, which view returns as a string or ADF."""
    return (v if isinstance(v, str) else _plain(v)).strip() if v else ""


def set_env(key, env):
    """Set the Environment field; returns the exit code."""
    adf = {"type": "doc", "version": 1, "content": [_para([{"type": "text", "text": env}])]}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(adf, f)
    batch = os.path.join(os.path.dirname(os.path.abspath(__file__)), "acli-issue-set-batch.py")
    r = subprocess.run([sys.executable, batch, "--yes", key, "--", "--environment-adf", f.name],
                       capture_output=True, text=True)
    os.unlink(f.name)
    print(r.stdout[-600:] + r.stderr[-600:])
    if r.returncode:
        print("Environment was not set; rerun with --apply to retry it (the description is already done)")
    return r.returncode


def _load(text):
    try:
        return json.loads(text[text.index("{"):])
    except (ValueError, json.JSONDecodeError) as e:
        sys.exit("FATAL: invalid JSON: " + str(e))


def _view(key, path):
    if path:
        return _load(open(path, encoding="utf-8").read())
    r = subprocess.run(["acli", "jira", "workitem", "view", key, "--json"], capture_output=True, text=True)
    if r.returncode:
        sys.exit("FATAL: acli view failed: " + r.stdout[-300:] + r.stderr[-300:])
    return _load(r.stdout)


def main(argv):
    path = argv[argv.index("--file") + 1] if "--file" in argv else None
    args = [a for a in argv if not a.startswith("--") and a != path]
    if not args:
        sys.exit("usage: acli-reformat.py KEY [--apply] [--file view.json]")
    key = args[0]
    data = _view(key, path)
    desc = (data.get("fields") or {}).get("description")
    if not desc:
        sys.exit("FATAL: no description on " + key)
    new, info = reformat(desc)
    current = _env_text((data.get("fields") or {}).get("environment"))
    if new is None:
        print(key + ": left as is (" + info + ")")
        env = env_value(desc) if info == "already has headings" else None
        if not env or env == current:
            return 0
        print("--- Environment field " + ("will be" if "--apply" in argv else "would be") + " set to: " + env + " ---")
        return set_env(key, env) if "--apply" in argv else 0
    print("--- " + key + " new description (headings: " + ", ".join(info) + ") ---")
    for n in new["content"]:
        print(render_block(n))
    env = env_value(new)
    if env:
        print("--- Environment field will be set to: " + env + " ---")
    missing = [h for h in TEMPLATE if h not in info]
    if missing:
        print("--- not in the ticket (needs a person to write): " + ", ".join(missing) + " ---")
    if "--apply" not in argv:
        print("--- preview only; add --apply to write ---")
        return 0
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"issues": [key], "description": new}, f)
    r = subprocess.run(["acli", "jira", "workitem", "edit", "--from-json", f.name, "--yes"],
                       capture_output=True, text=True)
    os.unlink(f.name)
    print(r.stdout + r.stderr)
    if r.returncode or not env:
        return r.returncode
    return set_env(key, env)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
