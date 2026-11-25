#!/usr/bin/env python3
"""Behaviour checks for doctor.py (plain asserts, stub acli and stub runner)."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import doctor  # noqa: E402

GOOD = "ACLI_SITE=s.atlassian.net\nACLI_EMAIL=u@e.com\nACLI_JIRA_TOKEN=j\nACLI_CONFLUENCE_TOKEN=c\n"


class Proc:
    def __init__(self, code):
        self.returncode = code


def home_with(text, mode=0o600):
    d = tempfile.mkdtemp()
    (Path(d) / ".claude").mkdir()
    p = Path(d) / ".claude" / "atlassian.env"
    p.write_text(text)
    if os.name != "nt":
        os.chmod(p, mode)
    return d


def status_of(results, name):
    return next(s for n, s, _ in results if n == name)


def test_missing_acli_fails_with_install_hint():
    res = doctor.check_acli(lambda _c: None)
    assert res[1] == "FAIL" and "install acli" in res[2]


def test_missing_key_is_named_but_its_value_is_never_shown():
    res = doctor.check_env_file(home_with(GOOD.replace("ACLI_EMAIL=u@e.com\n", "")))
    keys = res[0]
    assert keys[1] == "FAIL" and "ACLI_EMAIL" in keys[2]
    assert "u@e.com" not in str(res) and "=j" not in str(res)


def test_missing_file_fails_and_names_the_setup_script():
    res = doctor.check_env_file(tempfile.mkdtemp())
    assert res[0][1] == "FAIL" and "setup_credentials.py" in res[0][2]


def test_loose_permissions_fail_on_posix():
    if os.name == "nt":
        return
    res = doctor.check_env_file(home_with(GOOD, mode=0o644))
    assert status_of(res, "credentials permissions") == "FAIL"


def test_smoke_runs_both_products_and_a_failure_is_reported():
    calls = []

    def runner(cmd):
        calls.append(cmd[-2:])
        return Proc(0 if "jira" in cmd else 3)
    res = doctor.check_smoke(runner)
    assert calls == [["jira", "/rest/api/3/myself"], ["confluence", "/wiki/api/v2/spaces?limit=1"]]
    assert [s for _, s, _ in res] == ["PASS", "FAIL"]


def test_smoke_is_skipped_when_credentials_are_not_ready():
    ran = []
    res = doctor.run_checks(home=tempfile.mkdtemp(), which=lambda _c: "/x/acli",
                            runner=lambda cmd: ran.append(cmd) or Proc(0))
    assert ran == [] and all(s in ("PASS", "FAIL", "SKIP") for _, s, _ in res)
    assert [s for n, s, _ in res if "smoke" in n] == ["SKIP", "SKIP"]


def test_all_green_path_passes_end_to_end():
    res = doctor.run_checks(home=home_with(GOOD), which=lambda _c: "/x/acli", runner=lambda cmd: Proc(0))
    assert all(s != "FAIL" for _, s, _ in res)
    assert [s for n, s, _ in res if "smoke" in n] == ["PASS", "PASS"]


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", name)
            except Exception as exc:
                failed += 1
                print("FAIL", name, repr(exc))
    print("fails=%d" % failed)
    sys.exit(1 if failed else 0)
