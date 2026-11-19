#!/usr/bin/env python3
"""Self-check for acli-rest-get.py: fake opener, fake acli, temp env file, no network.
No framework — run directly: python3 test_acli_rest_get.py"""
import http.client
import importlib.util
import io
import json
import os
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
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


ENV_OK = f"# read-only token\nACLI_REST_READ_SITE={HOST}\nACLI_REST_READ_EMAIL={EMAIL}\nACLI_REST_READ_TOKEN={TOKEN}\n"


def write_env(text, mode=0o600):
    path = Path(tempfile.mkdtemp()) / "atlassian.env"
    path.write_text(text)
    os.chmod(path, mode)
    return path


def run_main(argv, routes, env=ENV_OK, acli=lambda: ACLI_OK, mode=0o600):
    env_file = write_env(env, mode) if env is not None else Path(tempfile.mkdtemp()) / "missing.env"
    op = FakeOpener(routes)
    op.argvs = []

    def run(cmd):
        op.argvs.append(cmd)
        assert cmd[0] == "acli", f"unexpected subprocess: {cmd}"
        return acli()

    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = rg.main(["acli-rest-get.py", *argv], opener=op, run=run, env_file=env_file)
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
        rg.http_get(op, "https://evil.example.com/x", (EMAIL, TOKEN))
    except rg.Fatal as e:
        assert "refusing" in str(e)
    else:
        raise AssertionError("credential was allowed to a foreign host")
    assert op.calls == [], "no request may be made"


def test_default_opener_refuses_to_build_a_follow_up_request_for_a_3xx():
    handlers = [h for h in rg.default_opener().handlers if isinstance(h, urllib.request.HTTPRedirectHandler)]
    assert len(handlers) == 1, "exactly one redirect handler, ours"
    req = urllib.request.Request("https://api.atlassian.com/x")
    for status in (301, 302, 303, 307, 308):
        assert handlers[0].redirect_request(req, None, status, "", {}, "https://evil.example.com/") is None


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


def test_missing_env_file_is_fatal_names_the_path_and_makes_no_request():
    code, _, err, op = run_main(["find-user", "x"], standard_routes(), env=None)
    assert code == 1 and "missing.env" in err and "not found" in err
    assert op.calls == []


def test_env_file_for_another_site_is_refused_before_any_request():
    other = ENV_OK.replace(HOST, "other-site.atlassian.net")
    code, _, err, op = run_main(["find-user", "x"], standard_routes(), env=other)
    assert code == 1 and "ACLI_REST_READ_SITE" in err
    assert op.calls == []


def test_env_file_for_another_account_is_refused_before_any_request():
    code, _, err, op = run_main(["find-user", "x"], standard_routes(), env=ENV_OK.replace(EMAIL, "b@example.com"))
    assert code == 1 and "ACLI_REST_READ_EMAIL" in err
    assert op.calls == []


def test_env_file_without_a_token_is_fatal():
    no_token = "\n".join(l for l in ENV_OK.splitlines() if "TOKEN" not in l)
    code, _, err, op = run_main(["find-user", "x"], standard_routes(), env=no_token)
    assert code == 1 and "ACLI_REST_READ_TOKEN" in err and op.calls == []


def test_env_file_readable_by_group_or_others_is_refused():
    for mode in (0o644, 0o640, 0o604):
        code, _, err, op = run_main(["find-user", "x"], standard_routes(), mode=mode)
        assert code == 1 and "chmod 600" in err, oct(mode)
        assert op.calls == []


def test_env_values_may_be_quoted_and_exported():
    quoted = f'export ACLI_REST_READ_SITE="{HOST}"\nACLI_REST_READ_EMAIL=\'{EMAIL}\'\nACLI_REST_READ_TOKEN="{TOKEN}"\n'
    seen = []

    def route(req):
        seen.append(req)
        return "[]"

    code, _, err, _ = run_main(["find-user", "x"], standard_routes(
        [(f"{JIRA}/rest/api/3/user/search", route)]), env=quoted)
    assert code == 0, err
    import base64
    assert base64.b64decode(seen[0].get_header("Authorization").split(" ", 1)[1]).decode() == f"{EMAIL}:{TOKEN}"


def test_no_site_override_flag_exists():
    code, _, err, op = run_main(["find-user", "x", "--site", "other.atlassian.net"], standard_routes(
        [(f"{JIRA}/rest/api/3/user/search", lambda r: json.dumps([{"accountId": "a1"}]))]))
    assert code == 1 and "usage" in err
    assert op.calls == [] and op.argvs == []
    src = (Path(__file__).parent / "acli-rest-get.py").read_text()
    assert "argparse" not in src and '"--' not in src, "the script must take no flags"


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

def test_createmeta_follows_pages_until_total_is_reached():
    def route(req):
        start = int(urllib.parse.parse_qs(urllib.parse.urlsplit(req.full_url).query)["startAt"][0])
        if start == 0:
            return json.dumps({"startAt": 0, "maxResults": 2, "total": 3, "issueTypes": [{"id": "1"}, {"id": "2"}]})
        assert start == 2, start
        return json.dumps({"startAt": 2, "maxResults": 2, "total": 3, "issueTypes": [{"id": "3"}]})

    code, out, err, _ = run_main(["createmeta", "DEMO"], standard_routes(
        [(f"{JIRA}/rest/api/3/issue/createmeta/DEMO/issuetypes", route)]))
    assert code == 0, err
    assert [v["id"] for v in json.loads(out)] == ["1", "2", "3"]


def test_createmeta_without_a_total_is_fatal_not_silently_short():
    code, out, err, _ = run_main(["createmeta", "DEMO"], standard_routes(
        [(f"{JIRA}/rest/api/3/issue/createmeta/DEMO/issuetypes",
          lambda r: json.dumps({"issueTypes": [{"id": "1"}]}))]))
    assert code == 1 and "total" in err and out == ""


def test_createmeta_empty_page_before_total_is_fatal_not_an_endless_loop():
    code, out, err, op = run_main(["createmeta", "DEMO"], standard_routes(
        [(f"{JIRA}/rest/api/3/issue/createmeta/DEMO/issuetypes",
          lambda r: json.dumps({"total": 5, "issueTypes": []}))]))
    assert code == 1 and "empty page" in err and out == ""
    assert len([c for c in op.calls if "/createmeta/" in c.full_url]) == 1


def test_createmeta_with_issue_type_hits_the_fields_path():
    code, out, err, op = run_main(["createmeta", "DEMO", "10004"], standard_routes(
        [(f"{JIRA}/rest/api/3/issue/createmeta/DEMO/issuetypes/10004",
          lambda r: json.dumps({"startAt": 0, "maxResults": 50, "total": 1, "fields": [{"fieldId": "priority"}]}))]))
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


# --- review fixes (0.1.59) ---------------------------------------------------

def _http_error(status, body=b""):
    return lambda r: urllib.error.HTTPError(r.full_url, status, "x", http.client.HTTPMessage(), io.BytesIO(body))


def test_unauthorized_and_forbidden_are_fatal_with_their_status():
    for status in (401, 403):
        code, out, err, _ = run_main(["find-user", "x"], standard_routes(
            [(f"{JIRA}/rest/api/3/user/search", _http_error(status))]))
        assert code == 1 and f"HTTP {status}" in err and out == "", (status, err)


def test_token_never_reaches_output_on_an_error_path():
    code, out, err, _ = run_main(["find-user", "x"], standard_routes(
        [(f"{JIRA}/rest/api/3/user/search", _http_error(401, b"bad credentials"))]))
    assert code == 1
    assert TOKEN not in out and TOKEN not in err


def test_only_acli_is_spawned_and_never_the_keychain_tool():
    _, _, _, op = run_main(["find-user", "x"], standard_routes(
        [(f"{JIRA}/rest/api/3/user/search", lambda r: "[]")]))
    assert op.argvs == [["acli", "jira", "auth", "status"]], op.argvs


def test_token_is_never_passed_in_any_subprocess_argv():
    _, _, _, op = run_main(["find-user", "x"], standard_routes(
        [(f"{JIRA}/rest/api/3/user/search", lambda r: "[]")]))
    assert not any(TOKEN in part for argv in op.argvs for part in argv)


def test_source_sends_only_get_and_never_a_request_body():
    here = Path(__file__).parent
    src = (here / "acli-rest-get.py").read_text()
    common = (here / "acli_rest_common.py").read_text()
    assert "http_get(" in src and "http_request(" not in src, "the read script uses only the GET helper"
    assert common.count("urllib.request.Request(") == 1, "one place in the shared module builds a request"
    assert rg.METHOD == "GET"
    for word in ("data=", '"POST"', '"PUT"', '"DELETE"', '"PATCH"', "urlopen("):
        assert word not in src, word


def test_issue_type_id_that_is_not_digits_is_rejected_before_any_request():
    for bad in ("../../x?y", "10004/..", "abc", ""):
        code, _, err, op = run_main(["createmeta", "DEMO", bad], standard_routes())
        assert code == 1 and "not an issue type id" in err, (bad, err)
        assert op.calls == [], bad


def test_bad_arguments_do_no_acli_env_file_or_network_work():
    for argv in (["set-parent", "DEMO-1"], ["transitions"], ["transitions", "bad key"], ["createmeta", "demo"]):
        code, _, err, op = run_main(argv, standard_routes())
        assert code == 1 and "FATAL" in err, argv
        assert op.calls == [] and op.argvs == [], argv


def test_non_json_success_body_is_fatal_without_a_traceback():
    code, out, err, _ = run_main(["find-user", "x"], standard_routes(
        [(f"{JIRA}/rest/api/3/user/search", lambda r: "<html>login</html>")]))
    assert code == 1 and "FATAL" in err and "not JSON" in err and out == ""


def test_non_json_tenant_info_is_fatal():
    code, _, err, _ = run_main(["find-user", "x"], [(f"https://{HOST}/_edge/tenant_info", lambda r: "nope")])
    assert code == 1 and "not JSON" in err


def test_missing_acli_binary_is_fatal_without_a_traceback():
    def boom(cmd, **_):
        raise FileNotFoundError(cmd[0])

    op = FakeOpener([])
    err = io.StringIO()
    with redirect_stdout(io.StringIO()), redirect_stderr(err):
        code = rg.main(["acli-rest-get.py", "find-user", "x"], opener=op, run=lambda cmd: rg.run_command(cmd, spawn=boom),
                       env_file=write_env(ENV_OK))
    assert code == 1 and "FATAL" in err.getvalue() and "not found" in err.getvalue()


def test_transition_without_a_target_status_reports_null():
    tr = {"transitions": [{"id": "5", "name": "Comment", "to": None}]}
    code, out, err, _ = run_main(["transitions", "DEMO-7"], standard_routes(
        [(f"{JIRA}/rest/api/3/issue/DEMO-7/transitions", lambda r: json.dumps(tr))]))
    assert code == 0, err
    assert json.loads(out) == [{"id": "5", "name": "Comment", "to": None}]


def test_docstring_states_both_find_user_limits():
    doc = rg.__doc__
    assert "1,000" in doc and "empty" in doc and "50" in doc


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
