#!/usr/bin/env python3
import os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BATCH = os.path.join(HERE, "acli-issue-set-batch.py")
FAKE = """import sys
a = sys.argv[1:]
if a[0] == "plan":
    k = a[a.index("--key") + 1]
    if k == "BAD-1": sys.exit(1)
    print("request: /tmp/" + k); print("confirm: abcdef012345")
elif a[1].endswith("APPR-2"): sys.exit(1)
"""
tmp = tempfile.mkdtemp()
w = os.path.join(tmp, "w.py")
open(w, "w").write(FAKE)


def batch(*a):
    p = subprocess.run([sys.executable, BATCH, "--writer", w, *a], capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


rc, out = batch("APPR-1", "--", "--priority", "High")
assert rc == 0 and "rerun with --yes" in out and "applied" not in out.replace("applied?", ""), out
rc, out = batch("--yes", "APPR-1", "BAD-1", "--", "--priority", "High")
assert rc == 1 and "plan failed for BAD-1; nothing applied" in out, out
rc, out = batch("--yes", "APPR-1", "APPR-2", "APPR-3", "--", "--priority", "High")
assert rc == 1 and "apply failed for APPR-2; applied 1, not attempted: APPR-3" in out, out
rc, out = batch("--yes", "APPR-1", "--", "--priority", "High")
assert rc == 0 and "applied 1 key(s)" in out, out
rc, out = batch("APPR-1", "--", "--key", "X")
assert rc == 1, out
print("PASS")
