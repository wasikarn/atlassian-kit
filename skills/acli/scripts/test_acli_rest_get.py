#!/usr/bin/env python3
"""Self-check for acli-rest-get.py: fake opener, fake acli and Keychain, no network.
No framework — run directly: python3 test_acli_rest_get.py"""
import http.client
import importlib.util
import io
import json
import sys
import urllib.error
import urllib.parse
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location("acli_rest_get", Path(__file__).parent / "acli-rest-get.py")
assert spec and spec.loader
rg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rg)

HOST = "example-site.atlassian.net"
EMAIL = "op@example.com"
CID = "11111111-2222-3333-4444-555555555555"
TOKEN = "SECRET-TOKEN-XYZ"
JIRA = f"https://api.atlassian.com/ex/jira/{CID}"
ACLI_OK = SimpleNamespace(returncode=0, stdout=f"✓ Authenticated\n  Site: {HOST}\n  Email: {EMAIL}\n")


class _Resp:
    def __init__(self, body):
        self._b = body.encode()

    def read(self, n=-1):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    """routes: list of (url_prefix, fn(req) -> body str | Exception). Records every URL it is asked for."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def open(self, req, timeout=None):
        self.calls.append(req)
        for prefix, fn in self.routes:
            if req.full_url.startswith(prefix):
                res = fn(req)
                if isinstance(res, Exception):
                    raise res
                return _Resp(res)
        raise AssertionError(f"unexpected request to {req.full_url}")


def standard_routes(extra=()):
    return [
        (f"https://{HOST}/_edge/tenant_info", lambda r: json.dumps({"cloudId": CID})),
        *extra,
    ]


def keychain_ok(*_):
    return SimpleNamespace(returncode=0, stdout=TOKEN + "\n")


def keychain_missing(*_):
    return SimpleNamespace(returncode=44, stdout="")


def run_main(argv, routes, keychain=keychain_ok, acli=lambda: ACLI_OK):
    op = FakeOpener(routes)
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = rg.main(["acli-rest-get.py", *argv], opener=op, run_acli=acli, run_keychain=keychain)
    return code, out.getvalue(), err.getvalue(), op


# --- GET only, token scope ---------------------------------------------------

def test_transitions_builds_the_scoped_url_and_parses_the_list():
    tr = {"transitions": [{"id": "31", "name": "Start", "to": {"name": "In Progress"}},
                          {"id": "41", "name": "Done", "to": {"name": "Done"}}]}
    code, out, err, op = run_main(["transitions", "DEMO-7"], standard_routes(
        [(f"{JIRA}/rest/api/3/issue/DEMO-7/transitions", lambda r: json.dumps(tr))]))
    assert code == 0, err
    assert json.loads(out) == [{"id": "31", "name": "Start", "to": "In Progress"},
                               {"id": "41", "name": "Done", "to": "Done"}]
    assert all(r.get_method() == "GET" for r in op.calls)


def test_every_api_request_is_get_with_basic_auth_for_the_email():
    seen = []

    def route(req):
        seen.append(req)
        return json.dumps({"transitions": []})

    run_main(["transitions", "DEMO-7"], standard_routes(
        [(f"{JIRA}/rest/api/3/issue/DEMO-7/transitions", route)]))
    assert len(seen) == 1
    import base64
    got = base64.b64decode(seen[0].get_header("Authorization").split(" ", 1)[1]).decode()
    assert got == f"{EMAIL}:{TOKEN}", got


def test_token_never_reaches_stdout_or_stderr():
    code, out, err, _ = run_main(["find-user", "somchai"], standard_routes(
        [(f"{JIRA}/rest/api/3/user/search", lambda r: json.dumps([{"accountId": "a1"}]))]))
    assert code == 0
    assert TOKEN not in out and TOKEN not in err


def test_credential_is_refused_for_any_host_but_api_atlassian_com():
    op = FakeOpener([])
    try:
        rg.call(op, "https://evil.example.com/x", (EMAIL, TOKEN))
    except rg.Fatal as e:
        assert "refusing" in str(e)
    else:
        raise AssertionError("credential was allowed to a foreign host")
    assert op.calls == [], "no request may be made"


def test_default_opener_does_not_follow_redirects():
    op = rg.default_opener()
    assert any(isinstance(h, rg._NoRedirect) for h in op.handlers), "redirect handler missing"


def test_a_redirect_is_fatal_not_followed():
    code, out, err, _ = run_main(["find-user", "x"], standard_routes(
        [(f"{JIRA}/rest/api/3/user/search",
          lambda r: urllib.error.HTTPError(r.full_url, 302, "Found", http.client.HTTPMessage(), io.BytesIO(b"")))]))
    assert code == 1 and "FATAL" in err and "302" in err


# --- identity and target -----------------------------------------------------

def test_host_that_is_not_atlassian_net_is_fatal_before_any_request():
    bad = lambda: SimpleNamespace(returncode=0, stdout=f"  Site: evil.example.com\n  Email: {EMAIL}\n")
    code, out, err, op = run_main(["find-user", "x"], [], acli=bad)
    assert code == 1 and "not a *.atlassian.net" in err
    assert op.calls == []


def test_missing_site_is_fatal():
    no_site = lambda: SimpleNamespace(returncode=0, stdout=f"  Email: {EMAIL}\n")
    code, _, err, op = run_main(["find-user", "x"], [], acli=no_site)
    assert code == 1 and "exactly one Site" in err and op.calls == []


def test_non_uuid_cloud_id_is_fatal_and_no_credential_is_sent():
    routes = [(f"https://{HOST}/_edge/tenant_info", lambda r: json.dumps({"cloudId": "not-a-uuid"}))]
    code, _, err, op = run_main(["find-user", "x"], routes)
    assert code == 1 and "did not return a UUID" in err
    assert all(r.get_header("Authorization") is None for r in op.calls)


def test_target_line_names_host_cloud_id_and_email():
    code, _, err, _ = run_main(["find-user", "x"], standard_routes(
        [(f"{JIRA}/rest/api/3/user/search", lambda r: json.dumps([{"accountId": "a1"}]))]))
    assert code == 0
    assert f"target: {HOST} ({CID}) as {EMAIL}" in err


def test_missing_keychain_item_names_service_and_account():
    code, _, err, op = run_main(["find-user", "x"], standard_routes(), keychain=keychain_missing)
    assert code == 1
    assert f"acli-rest-read:{HOST}" in err and EMAIL in err
    assert not any(r.get_header("Authorization") for r in op.calls)


def test_no_site_override_flag_exists():
    code, _, err, op = run_main(["find-user", "x", "--site", "other.atlassian.net"], standard_routes(
        [(f"{JIRA}/rest/api/3/user/search", lambda r: json.dumps([{"accountId": "a1"}]))]))
    assert code == 1 and "usage" in err
    assert not any("other.atlassian.net" in r.full_url for r in op.calls)


# --- find-user: best effort, says so -----------------------------------------

def _users(n):
    return json.dumps([{"accountId": f"a{i}", "displayName": f"U{i}", "active": True} for i in range(n)])


def test_find_user_empty_result_warns_it_is_not_proof():
    code, out, err, _ = run_main(["find-user", "nobody"], standard_routes(
        [(f"{JIRA}/rest/api/3/user/search", lambda r: "[]")]))
    assert code == 0 and json.loads(out) == []
    assert "not proof" in err


def test_find_user_full_page_warns_to_narrow_and_does_not_paginate():
    calls = []

    def route(req):
        calls.append(req.full_url)
        return _users(50)

    code, out, err, _ = run_main(["find-user", "a"], standard_routes(
        [(f"{JIRA}/rest/api/3/user/search", route)]))
    assert code == 0 and len(json.loads(out)) == 50
    assert "narrow the query" in err
    assert len(calls) == 1, "find-user must not page"


def test_find_user_returns_only_account_fields_not_email():
    row = [{"accountId": "a1", "displayName": "Somchai", "active": True, "emailAddress": "s@x.com"}]
    code, out, _, _ = run_main(["find-user", "Somchai"], standard_routes(
        [(f"{JIRA}/rest/api/3/user/search", lambda r: json.dumps(row))]))
    assert code == 0
    assert json.loads(out) == [{"accountId": "a1", "displayName": "Somchai", "active": True}]
    assert "emailAddress" not in out


# --- createmeta: pagination --------------------------------------------------

def test_createmeta_follows_pages_until_is_last():
    def route(req):
        start = int(urllib.parse.parse_qs(urllib.parse.urlsplit(req.full_url).query)["startAt"][0])
        if start == 0:
            return json.dumps({"values": [{"id": "1"}, {"id": "2"}], "isLast": False})
        return json.dumps({"values": [{"id": "3"}], "isLast": True})

    code, out, err, _ = run_main(["createmeta", "DEMO"], standard_routes(
        [(f"{JIRA}/rest/api/3/issue/createmeta/DEMO/issuetypes", route)]))
    assert code == 0, err
    assert [v["id"] for v in json.loads(out)] == ["1", "2", "3"]


def test_createmeta_missing_is_last_is_fatal_not_silently_short():
    code, out, err, _ = run_main(["createmeta", "DEMO"], standard_routes(
        [(f"{JIRA}/rest/api/3/issue/createmeta/DEMO/issuetypes",
          lambda r: json.dumps({"values": [{"id": "1"}]}))]))
    assert code == 1 and "isLast" in err and out == ""


def test_createmeta_with_issue_type_hits_the_fields_path():
    code, out, err, op = run_main(["createmeta", "DEMO", "10004"], standard_routes(
        [(f"{JIRA}/rest/api/3/issue/createmeta/DEMO/issuetypes/10004",
          lambda r: json.dumps({"values": [{"fieldId": "priority"}], "isLast": True}))]))
    assert code == 0, err
    assert json.loads(out) == [{"fieldId": "priority"}]


# --- input validation --------------------------------------------------------

def test_bad_issue_key_is_rejected_before_any_request():
    code, _, err, op = run_main(["transitions", "x; rm -rf"], standard_routes())
    assert code == 1 and "not an issue key" in err
    assert all("/rest/" not in r.full_url for r in op.calls)


def test_bad_project_key_is_rejected_before_any_request():
    code, _, err, op = run_main(["createmeta", "appr-1"], standard_routes())
    assert code == 1 and "not a project key" in err
    assert all("/rest/" not in r.full_url for r in op.calls)


def test_unknown_subcommand_prints_usage():
    code, _, err, op = run_main(["set-parent", "DEMO-1"], standard_routes())
    assert code == 1 and "usage" in err


# --- error reporting ---------------------------------------------------------

def test_http_error_is_fatal_with_status_and_no_traceback():
    code, out, err, _ = run_main(["transitions", "DEMO-7"], standard_routes(
        [(f"{JIRA}/rest/api/3/issue/DEMO-7/transitions",
          lambda r: urllib.error.HTTPError(r.full_url, 404, "Not Found", http.client.HTTPMessage(), io.BytesIO(b"no issue")))]))
    assert code == 1 and "HTTP 404" in err and "Traceback" not in err and out == ""


def test_rate_limit_is_reported_not_retried():
    calls = []

    def route(req):
        calls.append(req)
        return urllib.error.HTTPError(req.full_url, 429, "Too Many", http.client.HTTPMessage(), io.BytesIO(b""))

    code, _, err, _ = run_main(["find-user", "x"], standard_routes(
        [(f"{JIRA}/rest/api/3/user/search", route)]))
    assert code == 1 and "HTTP 429" in err
    assert len(calls) == 1, "429 must not be retried"


def test_timeout_is_fatal():
    code, _, err, _ = run_main(["find-user", "x"], standard_routes(
        [(f"{JIRA}/rest/api/3/user/search", lambda r: TimeoutError("slow"))]))
    assert code == 1 and "failed" in err


if __name__ == "__main__":
    failed = 0
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        try:
            fn()
        except Exception as e:  # report every failure, then exit non-zero
            failed += 1
            print(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
