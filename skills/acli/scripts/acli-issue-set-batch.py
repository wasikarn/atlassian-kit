#!/usr/bin/env python3
"""Batch `acli-rest-write.py issue-set`: plan every key, then (with --yes) apply each.

  acli-issue-set-batch.py [--yes] [--writer PATH] KEY [KEY...] -- <issue-set flags, no --key>

Without --yes it stops after the previews (preview before mutate). Any plan failure aborts
before the first apply; the first failing apply stops the run and names the keys left over.
"""
import os, re, subprocess, sys
from typing import NoReturn

HERE = os.path.dirname(os.path.abspath(__file__))


def fatal(msg) -> NoReturn:
    print(f"FATAL: {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(p.stdout)
    sys.stderr.write(p.stderr)
    return p


def main(argv):
    yes, writer = False, os.path.join(HERE, "acli-rest-write.py")
    while argv and argv[0] in ("--yes", "--writer"):
        flag = argv.pop(0)
        if flag == "--yes":
            yes = True
        elif argv:
            writer = argv.pop(0)
        else:
            fatal("--writer needs a path")
    if "--" not in argv:
        fatal("usage: acli-issue-set-batch.py [--yes] KEY [KEY...] -- <issue-set flags>")
    cut = argv.index("--")
    keys, flags = argv[:cut], argv[cut + 1:]
    if not keys or not flags:
        fatal("need at least one KEY and one issue-set flag")
    if "--key" in flags:
        fatal("do not pass --key; the keys come before --")
    plans = []
    for k in keys:
        p = run([sys.executable, writer, "plan", "issue-set", "--key", k, *flags])
        req, conf = (re.search(rf"^{n}: (\S+)$", p.stdout, re.M) for n in ("request", "confirm"))
        if p.returncode or not req or not conf:
            fatal(f"plan failed for {k}; nothing applied")
        plans.append((k, req.group(1), conf.group(1)))
    if not yes:
        print(f"previewed {len(plans)} key(s); rerun with --yes to apply")
        return 0
    for i, (k, req, conf) in enumerate(plans):
        if run([sys.executable, writer, "apply", req, "--confirm", conf]).returncode:
            left = [x[0] for x in plans[i + 1:]]
            fatal(f"apply failed for {k}; applied {i}, not attempted: {' '.join(left) or 'none'}")
    print(f"applied {len(plans)} key(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
