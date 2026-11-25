#!/usr/bin/env python3
"""Write the atlassian-kit credentials file. Run it yourself in a terminal; tokens are typed through a hidden prompt.

Writes ~/.claude/atlassian.env with four keys: ACLI_SITE, ACLI_EMAIL, ACLI_JIRA_TOKEN, ACLI_CONFLUENCE_TOKEN.
Tokens never go in argv, never get printed, and the file is created 0600 (POSIX) or limited to the current user (Windows, icacls).
"""
import getpass
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

KEYS = ("ACLI_SITE", "ACLI_EMAIL", "ACLI_JIRA_TOKEN", "ACLI_CONFLUENCE_TOKEN")
SITE_RE = re.compile(r"^[a-z0-9-]+\.atlassian\.net$")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def normalize_site(raw):
    """Accept https://x.atlassian.net/ and return x.atlassian.net; raise ValueError otherwise."""
    host = raw.strip()
    for prefix in ("https://", "http://"):
        if host.lower().startswith(prefix):
            host = host[len(prefix):]
    host = host.rstrip("/").lower()
    if not SITE_RE.match(host):
        raise ValueError(f"site must look like your-site.atlassian.net, got {raw.strip()!r}")
    return host


def check_email(raw):
    email = raw.strip()
    if not EMAIL_RE.match(email):
        raise ValueError("email must look like you@company.com")
    return email


def check_token(raw):
    token = raw.strip()
    if not token or any(c.isspace() or c in "'\"=#" for c in token):
        raise ValueError("token is empty or contains spaces, quotes, '=' or '#'; paste it again")
    return token


def render(values):
    return "".join(f"{key}={values[key]}\n" for key in KEYS)


def restrict_to_user(path):
    if os.name == "nt":
        user = os.environ.get("USERNAME") or getpass.getuser()
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
                       check=True, capture_output=True)
    else:
        os.chmod(path, 0o600)


def write_env(path, values):
    """Atomic write: a temp file in the same folder, permissions set before any secret lands, then rename."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".atlassian.env.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            restrict_to_user(tmp)
            fh.write(render(values))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path


def ask_values(input_fn=input, secret_fn=getpass.getpass):
    site = normalize_site(input_fn("Atlassian site (e.g. your-site.atlassian.net): "))
    email = check_email(input_fn("Atlassian account email: "))
    jira = check_token(secret_fn("Jira API token (hidden): "))
    confluence = check_token(secret_fn("Confluence API token (hidden): "))
    return {"ACLI_SITE": site, "ACLI_EMAIL": email,
            "ACLI_JIRA_TOKEN": jira, "ACLI_CONFLUENCE_TOKEN": confluence}


def main():
    target = Path.home() / ".claude" / "atlassian.env"
    try:
        values = ask_values()
    except ValueError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1
    if target.exists():
        if input(f"{target} exists. Replace it? [y/N] ").strip().lower() != "y":
            print("Kept the existing file.")
            return 0
    write_env(target, values)
    print(f"Wrote {target} with {len(KEYS)} keys (values not shown).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
