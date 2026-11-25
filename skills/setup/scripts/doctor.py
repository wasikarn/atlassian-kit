#!/usr/bin/env python3
"""Re-runnable health check for the atlassian-kit setup. Prints PASS/FAIL/SKIP per check; never prints a secret.

Checks: token expiry from the dates typed at setup (WARN within 30 days, FAIL when past), acli on PATH, credentials file present with the four keys, POSIX mode 600, and a read smoke
against Jira and Confluence through acli-rest-get.py. Windows ACL is not checked here: SKIP with a reason.
Exit 0 only when no check FAILs.
"""
import json
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

META_NAME = "atlassian-kit-meta.json"  # written by setup_credentials.py
WARN_DAYS = 30
KEYS = ("ACLI_SITE", "ACLI_EMAIL", "ACLI_JIRA_TOKEN", "ACLI_CONFLUENCE_TOKEN")
SCRIPTS = Path(__file__).resolve().parents[2] / "ops" / "scripts"
SMOKE = (
    ("Jira read smoke", ["api", "jira", "/rest/api/3/myself"]),
    ("Confluence read smoke", ["api", "confluence", "/wiki/api/v2/spaces?limit=1"]),
)


def check_acli(which):
    if which("acli") is None:
        return ("acli on PATH", "FAIL", "not found; install acli from the official Atlassian download, then reopen the terminal")
    return ("acli on PATH", "PASS", "found")


def check_env_file(home):
    path = Path(home) / ".claude" / "atlassian.env"
    if not path.exists():
        return [("credentials file", "FAIL", f"{path} missing; run skills/setup/scripts/setup_credentials.py")]
    found = {line.split("=", 1)[0] for line in path.read_text(encoding="utf-8").splitlines() if "=" in line}
    missing = [k for k in KEYS if k not in found]
    results = [("credentials keys", "FAIL" if missing else "PASS",
                "missing: " + ", ".join(missing) if missing else "all four keys present (values not shown)")]
    if os.name == "nt":
        results.append(("credentials permissions", "SKIP", "Windows ACL not checked by doctor; confirm with icacls"))
    else:
        mode = path.stat().st_mode & 0o777
        results.append(("credentials permissions", "PASS" if mode == 0o600 else "FAIL",
                        f"mode {oct(mode)}" + ("" if mode == 0o600 else "; run chmod 600 on the file")))
    return results


def check_expiry(home, today=None):
    path = Path(home) / ".claude" / META_NAME
    if not path.exists():
        return [("token expiry", "SKIP", "no dates recorded; rerun setup_credentials.py to record them")]
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
        days = {p: (date.fromisoformat(meta[f"{p}_expires"]) - (today or date.today())).days for p in ("jira", "confluence")}
    except (ValueError, KeyError, TypeError):
        return [("token expiry", "FAIL", f"{path} is unreadable; rerun setup_credentials.py")]
    results = []
    for product, left in days.items():
        if left < 0:
            results.append((f"{product} token expiry", "FAIL", f"expired {-left} days ago; create a new token and rerun setup"))
        elif left <= WARN_DAYS:
            results.append((f"{product} token expiry", "WARN", f"{left} days left; create a new token soon"))
        else:
            results.append((f"{product} token expiry", "PASS", f"{left} days left (date typed at setup, not read from Atlassian)"))
    return results


def check_login(runner):
    ok = runner(["acli", "jira", "auth", "status"]).returncode == 0
    return ("acli login", "PASS" if ok else "FAIL",
            "logged in" if ok else "not logged in; run `acli jira auth login` with the same site, email and Jira token")


def _reason(proc):
    lines = [l.strip() for l in ((proc.stderr or "") + (proc.stdout or "")).splitlines() if l.strip()]
    return lines[-1][:200] if lines else "no message"


def check_smoke(runner):
    results = []
    for name, args in SMOKE:
        proc = runner([sys.executable, str(SCRIPTS / "acli-rest-get.py"), *args])
        ok = proc.returncode == 0
        results.append((name, "PASS" if ok else "FAIL",
                        "read ok" if ok else f"exit {proc.returncode}: {_reason(proc)}"))
    return results


def run_checks(home=Path.home(), which=shutil.which, runner=None):
    runner = runner or (lambda cmd: subprocess.run(cmd, capture_output=True, text=True))
    results = [check_acli(which)]
    results += check_env_file(home)
    results += check_expiry(home)
    if not any(status == "FAIL" for _, status, _ in results):
        results.append(check_login(runner))
    if any(status == "FAIL" for _, status, _ in results):
        results += [(name, "SKIP", "credentials not ready") for name, _ in SMOKE]
    else:
        results += check_smoke(runner)
    return results


def main():
    results = run_checks()
    for name, status, detail in results:
        print(f"{status:4}  {name}: {detail}")
    return 1 if any(status == "FAIL" for _, status, _ in results) else 0


if __name__ == "__main__":
    sys.exit(main())
