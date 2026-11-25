#!/usr/bin/env python3
"""Behaviour checks for setup_credentials.py (plain asserts, no framework)."""
import os
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import setup_credentials as sc  # noqa: E402


def test_site_accepts_host_or_url_and_rejects_other_hosts():
    assert sc.normalize_site("https://Mimo-Tech.atlassian.net/") == "mimo-tech.atlassian.net"
    assert sc.normalize_site("  your-site.atlassian.net ") == "your-site.atlassian.net"
    for bad in ("example.com", "https://a.atlassian.net.evil.io", "", "a b.atlassian.net"):
        try:
            sc.normalize_site(bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad!r}")


def test_email_and_token_are_checked():
    assert sc.check_email(" you@example.com ") == "you@example.com"
    for bad in ("not-an-email", "a@b"):
        try:
            sc.check_email(bad)
        except ValueError:
            continue
        raise AssertionError(bad)
    assert sc.check_token(" abc123 ") == "abc123"
    for bad in ("", "ab cd", "x=y", "q'q", "h#h"):
        try:
            sc.check_token(bad)
        except ValueError:
            continue
        raise AssertionError(repr(bad))


def test_write_creates_four_keys_and_mode_600_on_posix():
    with tempfile.TemporaryDirectory() as home:
        target = Path(home) / ".claude" / "atlassian.env"
        values = {"ACLI_SITE": "s.atlassian.net", "ACLI_EMAIL": "u@e.com",
                  "ACLI_JIRA_TOKEN": "JTOK", "ACLI_CONFLUENCE_TOKEN": "CTOK"}
        sc.write_env(target, values)
        assert target.read_text() == (
            "ACLI_SITE=s.atlassian.net\nACLI_EMAIL=u@e.com\nACLI_JIRA_TOKEN=JTOK\nACLI_CONFLUENCE_TOKEN=CTOK\n")
        if os.name != "nt":
            assert stat.S_IMODE(target.stat().st_mode) == 0o600
        assert [p.name for p in target.parent.iterdir()] == ["atlassian.env"], "temp file left behind"


def test_write_replaces_existing_file_and_failure_leaves_it_intact():
    with tempfile.TemporaryDirectory() as home:
        target = Path(home) / "atlassian.env"
        target.write_text("ACLI_SITE=old\n")
        sc.write_env(target, {"ACLI_SITE": "new.atlassian.net", "ACLI_EMAIL": "a@b.co",
                              "ACLI_JIRA_TOKEN": "j", "ACLI_CONFLUENCE_TOKEN": "c"})
        assert target.read_text().startswith("ACLI_SITE=new.atlassian.net\n")
        real = sc.render

        def boom(values):
            raise OSError("disk full")
        sc.render = boom
        try:
            sc.write_env(target, {})
        except OSError:
            pass
        finally:
            sc.render = real
        assert target.read_text().startswith("ACLI_SITE=new.atlassian.net\n"), "old file damaged"
        assert [p.name for p in target.parent.iterdir()] == ["atlassian.env"], "temp file left behind"


def test_ask_values_reads_tokens_only_through_the_secret_prompt():
    answers = iter(["https://s.atlassian.net", "u@e.com"])
    secrets = iter(["JTOK", "CTOK"])
    got = sc.ask_values(input_fn=lambda _p: next(answers), secret_fn=lambda _p: next(secrets))
    assert got == {"ACLI_SITE": "s.atlassian.net", "ACLI_EMAIL": "u@e.com",
                   "ACLI_JIRA_TOKEN": "JTOK", "ACLI_CONFLUENCE_TOKEN": "CTOK"}


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", name)
            except Exception as exc:  # report every failure, then exit non-zero
                failed += 1
                print("FAIL", name, repr(exc))
    print("fails=%d" % failed)
    sys.exit(1 if failed else 0)
