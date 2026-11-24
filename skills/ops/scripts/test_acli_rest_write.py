#!/usr/bin/env python3
"""Self-check for acli-rest-write.py (plan / apply plumbing). Fake opener, fake acli, temp env files,
no network, no real operation registered. No framework — run directly: python3 test_acli_rest_write.py"""
import datetime
import hashlib
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import urllib.error
import http.client
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("acli_rest_write", HERE / "acli-rest-write.py")
assert spec and spec.loader
import rest_ops_jira_issues  # noqa: E402  (HERE is on sys.path above)
rw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rw)

HOST = "example-site.atlassian.net"
EMAIL = "op@example.com"
CID = "11111111-2222-3333-4444-555555555555"
WTOKEN = "WRITE-SECRET-TOKEN-QQ"
RTOKEN = "READ-SECRET-TOKEN-ZZ"
JIRA = f"https://api.atlassian.com/ex/jira/{CID}"
ACLI_OK = SimpleNamespace(returncode=0, stdout=f"✓ Authenticated\n  Site: {HOST}\n  Email: {EMAIL}\n")
ENV_OK = (f"ACLI_REST_WRITE_SITE={HOST}\nACLI_REST_WRITE_EMAIL={EMAIL}\n"
          f"ACLI_REST_WRITE_JIRA_TOKEN={WTOKEN}\nACLI_REST_WRITE_CONFLUENCE_TOKEN=CONF-SECRET-QQ\n"
          f"ACLI_REST_READ_TOKEN={RTOKEN}\n")


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
    def __init__(self, routes):
        self.routes, self.calls, self.argvs = routes, [], []

    def open(self, req, timeout=None):
        self.calls.append(req)
        for prefix, fn in self.routes:
            if req.full_url.startswith(prefix):
                res = fn(req)
                if isinstance(res, Exception):
                    raise res
                return _Resp(res)
        raise AssertionError(f"unexpected request to {req.full_url}")


def env_file(text=ENV_OK, mode=0o600):
    path = Path(tempfile.mkdtemp()) / "atlassian.env"
    path.write_text(text)
    os.chmod(path, mode)
    return path


def tenant_route():
    return (f"https://{HOST}/_edge/tenant_info", lambda r: json.dumps({"cloudId": CID}))


# A test-only operation. The real registry is empty in phase 1.
def fake_validate(flags, pos=()):
    if set(flags) != {"key"} or not re.match(r"^[A-Z]+-[0-9]+$", str(flags["key"])):
        raise rw.Fatal("fake-set takes exactly --key ISSUE")
    return flags


def fake_plan(get, args):
    cur = get(f"/rest/api/3/issue/{args['key']}", {})
    return {"summary": cur["summary"]}, {"fields": {"summary": "NEW"}}


def fake_send(http, args, base, body_text):
    return http("PUT", f"/rest/api/3/issue/{args['key']}", body_text.encode())  # returns the response text


def fake_readback(get, args, base, body_text, result):
    return get(f"/rest/api/3/issue/{args['key']}", {})["summary"] == "NEW"


FAKE_OP = {"product": "jira", "validate": fake_validate, "plan": fake_plan,
           "send": fake_send, "readback": fake_readback}


def run(argv, routes, env=None, acli=lambda: ACLI_OK, register=True):
    """Run rw.main with injected fakes. Returns (code, stdout, stderr, opener)."""
    if register:
        rw.OPERATIONS["fake-set"] = FAKE_OP
    op = FakeOpener(routes)

    def runner(cmd):
        op.argvs.append(cmd)
        assert cmd[0] == "acli", f"unexpected subprocess: {cmd}"
        return acli()

    out, err = io.StringIO(), io.StringIO()
    env_path = env if isinstance(env, Path) else env_file(env if env is not None else ENV_OK)
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = rw.main(["acli-rest-write.py", *argv], opener=op, run=runner, env_file=env_path)
    finally:
        rw.OPERATIONS.pop("fake-set", None)
    return code, out.getvalue(), err.getvalue(), op


def plan_for(key="DEMO-1", routes=None, env=None):
    base_routes = [tenant_route(), (f"{JIRA}/rest/api/3/issue/{key}",
                                    lambda r: json.dumps({"summary": "old title"}))]
    code, out, err, op = run(["plan", "fake-set", "--key", key], routes or base_routes, env=env)
    return code, out, err, op


def request_path(out):
    m = re.search(r"^request: (\S+)$", out, re.M)
    assert m, out
    return Path(m.group(1))


def confirm_of(out):
    m = re.search(r"^confirm: ([0-9a-f]{12})$", out, re.M)
    assert m, out
    return m.group(1)


def apply_for(path, confirm, routes=None, env=None, acli=lambda: ACLI_OK):
    base_routes = [tenant_route(),
                   (f"{JIRA}/rest/api/3/issue/DEMO-1", lambda r: json.dumps({"summary": "old title"})),
                   (f"{JIRA}/rest/api/3/issue/DEMO-1", lambda r: json.dumps({"summary": "NEW"}))]
    return run(["apply", str(path), "--confirm", confirm], routes or base_routes, env=env, acli=acli)


# --- plan: reads only, writes a private request file -------------------------

def test_plan_makes_only_get_requests_and_sends_no_body():
    code, out, err, op = plan_for()
    assert code == 0, err
    assert all(r.get_method() == "GET" for r in op.calls)
    assert all(r.data is None for r in op.calls)


def test_plan_request_file_is_private_and_holds_no_secret():
    code, out, err, _ = plan_for()
    path = request_path(out)
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert oct(path.parent.stat().st_mode & 0o777) == "0o700"
    text = path.read_text()
    assert WTOKEN not in text and RTOKEN not in text
    assert WTOKEN not in out + err and RTOKEN not in out + err
    data = json.loads(text)
    assert set(data) == {"schema", "created", "operation", "args", "target", "base", "body_text"}
    assert "method" not in data and "path" not in data and "url" not in data


def test_plan_confirm_is_the_first_12_hex_of_the_file_hash():
    code, out, _, _ = plan_for()
    path = request_path(out)
    assert confirm_of(out) == hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def test_plan_states_the_target_label_and_the_change():
    code, out, _, _ = plan_for()
    assert f"PRODUCTION {HOST}" in out
    assert '"summary": "old title"' in out and '"summary": "NEW"' in out


def test_plan_refuses_an_unknown_operation_without_any_request():
    code, out, err, op = run(["plan", "no-such-op", "--key", "DEMO-1"], [tenant_route()])
    assert code == 1 and "unknown operation" in err
    assert op.calls == []


def test_plan_refuses_bad_arguments_before_any_request():
    code, out, err, op = run(["plan", "fake-set", "--key", "x; rm -rf"], [tenant_route()])
    assert code == 1 and "fake-set takes exactly" in err
    assert op.calls == []


def test_plan_refuses_when_the_write_token_is_missing():
    no_write = "\n".join(l for l in ENV_OK.splitlines() if "JIRA_TOKEN" not in l)
    code, out, err, op = plan_for(env=no_write)
    assert code == 1 and "ACLI_REST_WRITE_JIRA_TOKEN" in err
    assert op.calls == [] or all(r.get_method() == "GET" for r in op.calls)


def test_read_token_is_never_used_for_writes():
    only_read = "\n".join(l for l in ENV_OK.splitlines() if "WRITE" not in l)
    code, out, err, op = plan_for(env=only_read)
    assert code == 1 and "ACLI_REST_WRITE_SITE" in err
    assert not any(RTOKEN in str(r.header_items()) for r in op.calls)


def test_alternate_env_file_with_the_acli_site_is_refused():
    alt = env_file(ENV_OK)
    code, out, err, op = run(["plan", "fake-set", "--key", "DEMO-1", "--env-file", str(alt)],
                             [tenant_route()], env=alt)
    assert code == 1 and "same site as acli" in err
    assert all(r.get_method() == "GET" for r in op.calls)


def test_alternate_env_file_is_labelled_as_alternate_not_production():
    other = ENV_OK.replace(HOST, "scratch-site.atlassian.net")
    routes = [(f"https://scratch-site.atlassian.net/_edge/tenant_info", lambda r: json.dumps({"cloudId": CID})),
              (f"https://api.atlassian.com/ex/jira/{CID}/rest/api/3/issue/DEMO-1",
               lambda r: json.dumps({"summary": "old title"}))]
    alt = env_file(other)
    code, out, err, _ = run(["plan", "fake-set", "--key", "DEMO-1", "--env-file", str(alt)], routes, env=alt)
    assert code == 0, err
    assert "ALTERNATE TARGET scratch-site.atlassian.net" in out
    assert "PRODUCTION" not in out


# --- apply: the file is checked, rebuilt and bound to the confirm hash -------

def test_apply_sends_exactly_the_body_text_from_the_file_and_then_deletes_it():
    code, out, err, _ = plan_for()
    path, conf = request_path(out), confirm_of(out)
    body_text = json.loads(path.read_text())["body_text"]
    sent, state = [], {"summary": "old title"}

    def issue(req):
        if req.get_method() == "GET":
            return json.dumps(state)
        sent.append(req.data)
        state["summary"] = "NEW"  # the server accepted the write
        return json.dumps({"ok": True})

    routes = [tenant_route(), (f"{JIRA}/rest/api/3/issue/DEMO-1", issue)]
    code, out2, err2, _ = run(["apply", str(path), "--confirm", conf], routes)
    assert code == 0, err2
    assert sent == [body_text.encode()]
    assert not path.exists()


def test_apply_refuses_a_wrong_confirm_and_sends_nothing():
    code, out, _, _ = plan_for()
    path = request_path(out)
    code, out2, err, op = apply_for(path, "000000000000")
    assert code == 1 and "confirm" in err
    assert path.exists()
    assert not any(r.get_method() in ("PUT", "POST") for r in op.calls)


def test_apply_refuses_a_file_edited_after_the_plan():
    code, out, _, _ = plan_for()
    path, conf = request_path(out), confirm_of(out)
    data = json.loads(path.read_text())
    data["body_text"] = data["body_text"].replace("NEW", "EVIL")
    path.write_text(json.dumps(data))
    code, _, err, op = apply_for(path, conf)
    assert code == 1 and "confirm" in err
    assert not any(r.get_method() in ("PUT", "POST") for r in op.calls)


def test_apply_refuses_a_forged_file_with_a_method_or_path_key_even_with_a_matching_hash():
    code, out, _, _ = plan_for()
    path = request_path(out)
    for extra in ({"method": "DELETE"}, {"path": "/rest/api/3/issue/DEMO-1"}, {"url": "https://evil"}):
        data = json.loads(path.read_text())
        data.update(extra)
        path.write_text(json.dumps(data))
        conf = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        code, _, err, op = apply_for(path, conf)
        assert code == 1 and "unexpected key" in err, extra
        assert not any(r.get_method() in ("PUT", "POST", "DELETE") for r in op.calls)


def test_apply_refuses_an_operation_the_registry_does_not_know():
    code, out, _, _ = plan_for()
    path = request_path(out)
    data = json.loads(path.read_text())
    data["operation"] = "page-purge"
    path.write_text(json.dumps(data))
    code, _, err, op = apply_for(path, hashlib.sha256(path.read_bytes()).hexdigest()[:12])
    assert code == 1 and "unknown operation" in err
    assert not any(r.get_method() in ("PUT", "POST", "DELETE") for r in op.calls)


def test_apply_refuses_a_request_file_older_than_thirty_minutes():
    code, out, _, _ = plan_for()
    path = request_path(out)
    data = json.loads(path.read_text())
    old = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=31)
    data["created"] = old.strftime("%Y-%m-%dT%H:%M:%SZ")
    path.write_text(json.dumps(data))
    code, _, err, op = apply_for(path, hashlib.sha256(path.read_bytes()).hexdigest()[:12])
    assert code == 1 and "older than 30 minutes" in err
    assert not any(r.get_method() in ("PUT", "POST") for r in op.calls)


def test_apply_refuses_when_the_live_state_no_longer_matches_the_base():
    code, out, _, _ = plan_for()
    path, conf = request_path(out), confirm_of(out)
    routes = [tenant_route(),
              (f"{JIRA}/rest/api/3/issue/DEMO-1", lambda r: json.dumps({"summary": "someone changed it"}))]
    code, _, err, op = run(["apply", str(path), "--confirm", conf], routes)
    assert code == 1 and "changed since the plan" in err
    assert not any(r.get_method() in ("PUT", "POST") for r in op.calls)


def test_apply_refuses_when_the_target_host_changed_since_the_plan():
    code, out, _, _ = plan_for()
    path, conf = request_path(out), confirm_of(out)
    moved = ENV_OK.replace(HOST, "other-site.atlassian.net")
    code, _, err, op = apply_for(path, conf, env=moved)
    assert code == 1 and "target" in err
    assert not any(r.get_method() in ("PUT", "POST") for r in op.calls)


def test_apply_refuses_when_the_rebuilt_body_differs_from_the_file():
    code, out, _, _ = plan_for()
    path = request_path(out)
    data = json.loads(path.read_text())
    data["body_text"] = json.dumps({"fields": {"summary": "OTHER"}}, sort_keys=True, separators=(",", ":"))
    path.write_text(json.dumps(data))
    code, _, err, op = apply_for(path, hashlib.sha256(path.read_bytes()).hexdigest()[:12])
    assert code == 1 and "does not match" in err
    assert not any(r.get_method() in ("PUT", "POST") for r in op.calls)


# --- exit codes: 1 refused, 2 rejected by server, 3 sent but unverified ------

def _apply_with_put(status_or_exc, readback_summary="NEW"):
    code, out, _, _ = plan_for()
    path, conf = request_path(out), confirm_of(out)

    def put(req):
        if isinstance(status_or_exc, Exception):
            raise status_or_exc
        return urllib.error.HTTPError(req.full_url, status_or_exc, "x", http.client.HTTPMessage(), io.BytesIO(b"nope"))

    routes = [tenant_route(),
              (f"{JIRA}/rest/api/3/issue/DEMO-1",
               lambda r: json.dumps({"summary": "old title"}) if r.get_method() == "GET" else put(r))]
    return run(["apply", str(path), "--confirm", conf], routes)


def test_a_4xx_on_the_write_is_exit_2_and_says_the_request_was_sent():
    code, out, err, _ = _apply_with_put(409)
    assert code == 2 and "HTTP 409" in err and "sent" in err


def test_a_5xx_on_the_write_is_exit_3_and_says_do_not_re_run():
    code, out, err, _ = _apply_with_put(503)
    assert code == 3 and "do not re-run" in err


def test_a_timeout_after_the_write_started_is_exit_3():
    code, out, err, _ = _apply_with_put(TimeoutError("slow"))
    assert code == 3 and "do not re-run" in err


def test_a_read_back_that_differs_is_exit_3_with_the_restore_hint():
    code, out, err, _ = plan_for()
    path, conf = request_path(out), confirm_of(out)
    routes = [tenant_route(),
              (f"{JIRA}/rest/api/3/issue/DEMO-1",
               lambda r: json.dumps({"summary": "old title"}) if r.get_method() == "GET"
               else json.dumps({"ok": True}))]
    code, out, err, _ = run(["apply", str(path), "--confirm", conf], routes)
    assert code == 3 and "read-back" in err


def test_tokens_never_reach_stdout_or_stderr_on_error_paths():
    code, out, err, _ = _apply_with_put(409)
    assert WTOKEN not in out + err and RTOKEN not in out + err


def test_registered_operations_match_the_plan_phases_so_far():
    assert sorted(rw.OPERATIONS) == ["attachment-upload", "board-columns-set", "board-delete", "board-property-set", "confluence-call", "confluence-v1-call", "filter-create", "issue-delete", "issue-set", "jira-call", "page-create", "page-delete", "page-fetch", "page-update",
                                     "version-create", "version-delete", "version-edit"], sorted(rw.OPERATIONS)
    for name, op in rw.OPERATIONS.items():
        expected = {"product", "validate", "plan", "send", "readback"} if name != "page-fetch" else {"planOnly", "product", "validate", "plan"}
        assert set(op) >= expected, (name, sorted(op))
    for name, op in rw.OPERATIONS.items():
        expected = {"product", "validate", "plan", "send", "readback"} if name != "page-fetch" else {"planOnly", "product", "validate", "plan"}
        assert set(op) >= expected, (name, sorted(op))


def test_the_write_script_source_has_one_request_builder_and_no_flags_for_tokens():
    src = (HERE / "acli-rest-write.py").read_text()
    assert "--token" not in src and "--site" not in src
    assert "os.environ" not in src, "tokens come from the env file, never the environment"


# --- page-create (phase 2) ---------------------------------------------------

CONF = f"https://api.atlassian.com/ex/confluence/{CID}/wiki/api/v2"
ADF = {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": "hello"}]}]}
SPACE_ID = "123"
PARENT = "999"


def adf_file(doc=ADF):
    path = Path(tempfile.mkdtemp()) / "body.adf.json"
    path.write_text(json.dumps(doc))
    return path


def conf_routes(space_results=None, title_results=None, parent_space=None, created=None, readback_adf=None, state=None):
    state = state if state is not None else {}
    """Dispatch by (method, path, query). Returns a route list for the confluence calls."""

    state.update(title_results=title_results, created=created)
    space_pages = [dict(p) for p in space_results if p["key"] == "DEMO"]

    def routes_for(req):
        method, url = req.get_method(), req.full_url
        split, query = urllib.parse.urlsplit(url.split("#")[0]), urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        u = split.path
        if method == "GET" and u.endswith("/spaces"):
            cur = query.get("cursor", [""])[0]
            if cur == "c2" or space_pages:
                page = space_pages
                next_ = {}
            else:
                page, next_ = [], {"next": "/wiki/api/v2/spaces?cursor=c2"}  # first page empty, wanted on the second
            return json.dumps({"results": page, "_links": next_})
        if method == "POST" and u.endswith("/pages"):
            state["created"] = json.loads(req.data.decode())
            return json.dumps({"id": "555", "status": "current", "title": state["created"]["title"], "spaceId": SPACE_ID})
        if method == "GET" and "/pages/" in u:
            pid = u.rsplit("/", 1)[1].split("?")[0]
            if pid == PARENT:
                return json.dumps({"id": PARENT, "spaceId": parent_space or SPACE_ID, "title": "Parent"})
            if pid == "555":
                if state["created"] is None:
                    raise AssertionError("read-back for a page that was never created")
                val = json.dumps(readback_adf if readback_adf is not None else ADF)
                return json.dumps({"id": "555", "title": state["created"]["title"],
                                   "body": {"atlas_doc_format": {"representation": "atlas_doc_format", "value": val}}})
            raise AssertionError(f"unexpected page id {pid}")
        if method == "GET" and u.endswith("/pages"):
            return json.dumps({"results": state["title_results"] if state["title_results"] is not None else [], "_links": {}})
        raise AssertionError(f"unexpected confluence call {method} {u}")

    return [(CONF, routes_for)]


def env_conf():
    return env_file(ENV_OK)


def plan_page(routes):
    return run(["plan", "page-create", "--space", "DEMO", "--title", "T", "--body-adf", str(adf_file())],
               routes + [tenant_route()])


def test_page_create_plan_finds_the_space_on_the_second_page_and_builds_the_wire():
    routes = conf_routes(space_results=[{"id": SPACE_ID, "key": "DEMO"}])
    code, out, err, op = plan_page(routes)
    assert code == 0, err
    assert '"spaceId"' not in out.splitlines()[0]
    assert "ALTERNATE" not in out and f"PRODUCTION {HOST}" in out
    data = json.loads(request_path(out).read_text())
    assert json.loads(data["body_text"]) == ADF
    assert data["target"]["host"] == HOST
    assert all(r.get_method() == "GET" for r in op.calls)


def test_page_create_plan_refuses_a_space_key_with_zero_or_two_matches():
    code, out, err, op = plan_page(conf_routes(space_results=[{"id": "9", "key": "OTHER"}]))
    assert code == 1 and "expected exactly one space named DEMO" in err and "what this account can see" in err
    assert not any(r.get_method() == "POST" for r in op.calls)


def test_page_create_plan_refuses_a_duplicate_title():
    routes = conf_routes(space_results=[{"id": SPACE_ID, "key": "DEMO"}], title_results=[{"id": "42", "title": "T"}])
    code, out, err, op = plan_page(routes)
    assert code == 1 and "already" in err
    assert not any(r.get_method() == "POST" for r in op.calls)


def test_page_create_plan_refuses_a_parent_outside_the_space():
    routes = conf_routes(space_results=[{"id": SPACE_ID, "key": "DEMO"}], parent_space="888")
    code, out, err, op = run(["plan", "page-create", "--space", "DEMO", "--title", "T",
                              "--body-adf", str(adf_file()), "--parent", PARENT],
                             routes + [tenant_route()])
    assert code == 1 and "parent" in err
    assert not any(r.get_method() == "POST" for r in op.calls)


def test_page_create_plan_refuses_a_body_file_that_is_not_an_adf_doc():
    notadf = adf_file({"type": "paragraph"})
    code, out, err, op = run(["plan", "page-create", "--space", "DEMO", "--title", "T", "--body-adf", str(notadf)],
                             [tenant_route()])
    assert code == 1 and "not an ADF doc" in err
    assert op.calls == [] or not any(r.get_method() == "POST" for r in op.calls)


def test_page_create_plan_refuses_a_missing_body_file_before_any_request():
    code, out, err, op = run(["plan", "page-create", "--space", "DEMO", "--title", "T",
                              "--body-adf", "/nonexistent/x.json"], [tenant_route()])
    assert code == 1 and "not found" in err
    assert op.calls == [] or all(r.get_method() == "GET" and "rest/api" not in r.full_url for r in op.calls)


def test_page_create_apply_sends_the_wire_body_with_the_adf_embedded_and_verifies():
    routes = conf_routes(space_results=[{"id": SPACE_ID, "key": "DEMO"}])
    code, out, err, op = plan_page(routes)
    assert code == 0, err
    path, conf = request_path(out), confirm_of(out)
    state = {}
    routes2 = conf_routes(space_results=[{"id": SPACE_ID, "key": "DEMO"}], state=state) + [tenant_route()]
    code, out2, err2, op2 = run(["apply", str(path), "--confirm", conf], routes2, env=env_conf())
    assert code == 0, err2
    wire = state["created"]
    assert wire["spaceId"] == SPACE_ID and wire["status"] == "current" and wire["title"] == "T"
    assert json.loads(wire["body"]["value"]) == ADF
    assert wire["body"]["representation"] == "atlas_doc_format"
    assert not path.exists()


def test_page_create_apply_refuses_when_the_title_was_taken_between_plan_and_apply():
    routes = conf_routes(space_results=[{"id": SPACE_ID, "key": "DEMO"}])
    code, out, err, op = plan_page(routes)
    path, conf = request_path(out), confirm_of(out)
    routes2 = conf_routes(space_results=[{"id": SPACE_ID, "key": "DEMO"}], title_results=[{"id": "42", "title": "T"}]) + [tenant_route()]
    code, out2, err2, op2 = run(["apply", str(path), "--confirm", conf], routes2, env=env_conf())
    assert code == 1 and "changed since the plan" in err2
    assert not any(r.get_method() == "POST" for r in op2.calls)


def test_page_create_read_back_that_differs_is_exit_3():
    routes = conf_routes(space_results=[{"id": SPACE_ID, "key": "DEMO"}])
    code, out, err, op = plan_page(routes)
    path, conf = request_path(out), confirm_of(out)
    changed = {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": "DIFFERENT"}]}]}
    routes2 = conf_routes(space_results=[{"id": SPACE_ID, "key": "DEMO"}], readback_adf=changed) + [tenant_route()]
    code, out2, err2, op2 = run(["apply", str(path), "--confirm", conf], routes2, env=env_conf())
    assert code == 3 and "read-back" in err2


def test_page_create_space_lookup_pagination_follows_next():
    routes = conf_routes(space_results=[{"id": SPACE_ID, "key": "DEMO"}])
    code, out, err, _ = plan_page(routes)
    assert code == 0, err


# --- issue-set and version-create (phase 3) ---------------------------------

ISSUE = {"id": "10001", "key": "DEMO-1", "fields": {
    "priority": {"name": "Medium"}, "parent": None, "environment": None,
    "fixVersions": [], "versions": []}}
PRIORITIES = [{"id": "3", "name": "Low"}, {"id": "2", "name": "Medium"}, {"id": "1", "name": "High"}]
VERSIONS = [{"id": "11", "name": "1.0"}, {"id": "12", "name": "2.0"}]
EDITMETA = {"fields": {"priority": {"required": False, "name": "Priority"},
                       "fixVersions": {"name": "Fix Version"},
                       "versions": {"name": "Affects versions"},
                       "environment": {"name": "Environment"}}}
NEW_ISSUE = dict(ISSUE, fields=dict(ISSUE["fields"], priority={"name": "High"},
                                    fixVersions=[{"name": "1.0"}]))


def jira_routes(state=None):
    state = state if state is not None else {"issue": ISSUE}

    def route(req):
        method, u = req.get_method(), urllib.parse.urlsplit(req.full_url).path
        if method == "GET" and u.endswith("/search/jql"):
            return json.dumps({"issues": [], "names": {}})
        if method == "GET" and "/editmeta" in u:
            return json.dumps(EDITMETA)
        if method == "GET" and u.endswith("/priority"):
            return json.dumps(PRIORITIES)
        if method == "GET" and "/versions" in u:
            return json.dumps(VERSIONS)
        if method == "GET" and u.endswith("/project/DEMO"):
            return json.dumps({"id": "10001", "key": "DEMO", "name": "Demo"})
        if method == "GET" and "/issue/DEMO-1" in u:
            return json.dumps(state["issue"])
        if method == "GET" and "/issue/DEMO-2" in u:
            return json.dumps({"id": "10002", "key": "DEMO-2", "fields": {}})
        if method == "PUT" and "/issue/" in u:
            state["put"] = json.loads(req.data.decode())
            return ""  # 204 body is empty
        if method == "POST" and u.endswith("/version"):
            state["posted_version"] = json.loads(req.data.decode())
            return json.dumps({"id": "13", "name": "3.0", "projectId": "10001"})
        if method == "GET" and "/version/13" in u:
            return json.dumps({"id": "13", "name": "3.0", "projectId": "10001"})
        raise AssertionError(f"unexpected jira call {method} {u}")

    return [(JIRA, route)]


def run_issue_set(argv_extra, routes, env=None, register=True):
    argv = ["plan", "issue-set", "--key", "DEMO-1"] + argv_extra
    return run(argv, routes + [tenant_route()], env=env)


def test_issue_set_builds_update_verbs_and_priority_from_plan_reads():
    code, out, err, op = run_issue_set(["--priority", "High", "--add-fix-version", "1.0"], jira_routes())
    assert code == 0, err
    data = json.loads(request_path(out).read_text())
    sent, body = data["base"], json.loads(data["body_text"])
    assert sent["priority"] == "Medium" and sent["fixVersions"] == []
    assert body["update"]["fixVersions"] == [{"add": {"name": "1.0"}}]
    assert body["fields"]["priority"] == {"name": "High"}


def test_issue_set_without_any_change_is_a_usage_error():
    code, out, err, op = run_issue_set([], jira_routes())
    assert code == 1 and "usage" in err.lower()


def test_issue_set_rejects_an_unknown_priority_before_writing_the_request():
    code, out, err, op = run_issue_set(["--priority", "Urgent"], jira_routes())
    assert code == 1 and "Urgent" in err and "priority" in err
    assert not any(r.get_method() == "PUT" for r in op.calls)


def test_issue_set_rejects_an_unknown_version_name_from_the_project_list():
    code, out, err, op = run_issue_set(["--add-fix-version", "9.9"], jira_routes())
    assert code == 1 and "9.9" in err
    assert not any(r.get_method() == "PUT" for r in op.calls)


def test_issue_set_rejects_removing_a_version_that_is_not_on_the_issue():
    code, out, err, op = run_issue_set(["--remove-fix-version", "1.0"], jira_routes())
    assert code == 1 and "not on" in err
    assert not any(r.get_method() == "PUT" for r in op.calls)


def test_issue_set_apply_sends_the_file_body_and_verifies_the_readback():
    code, out, err, _ = run_issue_set(["--priority", "High", "--add-fix-version", "1.0"],
                                      jira_routes(state={"issue": ISSUE}))
    path, conf = request_path(out), confirm_of(out)
    puts, issue_state = [], {"issue": ISSUE}
    routes = jira_routes(issue_state)
    orig = routes[0][1]

    def route2(req):  # stateful like a server: the read-back happens after the PUT
        if req.get_method() == "PUT":
            puts.append(json.loads(req.data.decode()))
            issue_state["issue"] = NEW_ISSUE
        return orig(req)

    routes[0] = (JIRA, route2)
    code, out2, err2, op2 = run(["apply", str(path), "--confirm", conf], routes + [tenant_route()], env=env_conf())
    assert code == 0, err2
    assert puts[0]["fields"]["priority"] == {"name": "High"}, puts
    assert puts[0]["update"]["fixVersions"] == [{"add": {"name": "1.0"}}]
    assert not path.exists()


def test_issue_set_apply_refuses_when_the_issue_changed_since_the_plan():
    code, out, err, _ = run_issue_set(["--priority", "High"], jira_routes(state={"issue": ISSUE}))
    path, conf = request_path(out), confirm_of(out)
    moved = dict(ISSUE, fields=dict(ISSUE["fields"], priority={"name": "Low"}))
    code, out2, err2, op2 = run(["apply", str(path), "--confirm", conf],
                                jira_routes(state={"issue": moved}) + [tenant_route()], env=env_conf())
    assert code == 1 and "changed since the plan" in err2
    assert not any(r.get_method() == "PUT" for r in op2.calls)


def test_issue_set_parent_and_environment_flags_are_carryable():
    env_tmp = env_file()
    body_file = adf_file({"type": "doc", "version": 1, "content": [{"type": "paragraph",
                          "content": [{"type": "text", "text": "prod"}]}]})
    code, out, err, op = run_issue_set(["--parent", "DEMO-2", "--environment-adf", str(body_file)], jira_routes())
    assert code == 0, err
    data = json.loads(request_path(out).read_text())
    body = json.loads(data["body_text"])
    assert body["fields"]["parent"] == {"key": "DEMO-2"}
    assert body["fields"]["environment"]["content"][0]["content"][0]["text"] == "prod"


def test_version_create_builds_project_id_and_posts_the_version():
    code, out, err, op = run(["plan", "version-create", "--project", "DEMO", "--name", "3.0"], jira_routes() + [tenant_route()], env=env_conf())
    assert code == 0, err
    data = json.loads(request_path(out).read_text())
    body = json.loads(data["body_text"])
    assert body == {"projectId": "10001", "name": "3.0"}
    assert "already exists" not in err


def test_version_create_refuses_aduplicate_name():
    code, out, err, op = run(["plan", "version-create", "--project", "DEMO", "--name", "1.0"], jira_routes() + [tenant_route()], env=env_conf())
    assert code == 1 and "already exists" in err
    assert not any(r.get_method() == "POST" for r in op.calls)


def test_version_create_apply_posts_and_verifies_by_id():
    code, out, err, _ = run(["plan", "version-create", "--project", "DEMO", "--name", "3.0"], jira_routes() + [tenant_route()], env=env_conf())
    path, conf = request_path(out), confirm_of(out)
    state = {}
    routes = jira_routes(state) + [tenant_route()]
    code, out2, err2, op2 = run(["apply", str(path), "--confirm", conf], routes, env=env_conf())
    assert code == 0, err2
    assert state["posted_version"] == {"projectId": "10001", "name": "3.0"}
    assert not path.exists()


# --- page-fetch and page-update (phase 4) -----------------------------------

V2_PAGE = {"id": "555", "status": "current", "title": "Demo page", "version": {"number": 7},
           "spaceId": "123",
           "body": {"atlas_doc_format": {"representation": "atlas_doc_format", "value": json.dumps(ADF)}}}
MACRO_ADF = {"type": "doc", "version": 1, "content": [
    {"type": "paragraph", "content": [{"type": "text", "text": "hello"}]},
    {"type": "extension", "content": [], "attrs": {"id": "m1", "name": "Mermaid diagram"}}]}
LIVE_PAGE = dict(V2_PAGE, body={"atlas_doc_format": {"representation": "atlas_doc_format", "value": json.dumps(MACRO_ADF)}})
EDITED_DROP_MACRO = {"type": "doc", "version": 1,
                     "content": [{"type": "paragraph", "content": [{"type": "text", "text": "hello"}]}]}
EDITED_ADD_LINE = {"type": "doc", "version": 1, "content": [
    {"type": "paragraph", "content": [{"type": "text", "text": "hello"}]},
    {"type": "extension", "content": [], "attrs": {"id": "m1", "name": "Mermaid diagram"}},
    {"type": "paragraph", "content": [{"type": "text", "text": "new line"}]}]}


def _chdir_tmp():
    d = Path(tempfile.mkdtemp())
    old = os.getcwd()
    os.chdir(d)
    return d, old


def test_page_fetch_writes_adf_and_base_files_and_the_base_holds_the_hash():
    import hashlib as h
    d, old = _chdir_tmp()
    try:
        code, out, err, op = run(["page-fetch", "555"], [(CONF, lambda req: json.dumps(LIVE_PAGE))] + [tenant_route()],
                                 env=env_conf())
    finally:
        os.chdir(old)
    assert code == 0, err
    base = json.loads((d / "page-555-v7.base.json").read_text())
    adf = json.loads((d / "page-555-v7.adf.json").read_text())
    assert base["pageId"] == "555" and base["version"] == 7 and base["title"] == "Demo page"
    assert base["adfSha"] == h.sha256(json.dumps(adf, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _planned_update(live, edited):
    d, old = _chdir_tmp()
    os.chdir(old)  # page-fetch files land in tmp; paths stay absolute for --base/--body-adf
    d2, old2 = _chdir_tmp()
    try:
        run(["page-fetch", "555"], [(CONF, lambda req: json.dumps(live))] + [tenant_route()], env=env_conf())
        base_abs = d2 / "page-555-v7.base.json"
        edited_path = adf_file(edited)
        os.chdir(old2)
        return d2, base_abs, edited_path, old2
    finally:
        pass


def test_page_update_plan_shows_the_diff_and_a_confirm_when_the_base_matches():
    d2, base_abs, edited_path, old2 = _planned_update(LIVE_PAGE, EDITED_ADD_LINE)
    try:
        code, out, err, op = run(["plan", "page-update", "--base", str(base_abs), "--body-adf", str(edited_path)],
                                 [(CONF, lambda req: json.dumps(LIVE_PAGE))] + [tenant_route()], env=env_conf())
        assert code == 0, err
        assert "confirm:" in out and "draft" in out.lower()
        assert "new line" in out
        data = json.loads(request_path(out).read_text())
        wire = json.loads(data["body_text"])
        assert wire["version"]["number"] == 8
        assert json.loads(wire["body"]["value"]) == EDITED_ADD_LINE
    finally:
        os.chdir(old2)


def test_page_update_refuses_a_stale_base_version():
    d2, base_abs, edited_path, old2 = _planned_update(LIVE_PAGE, EDITED_ADD_LINE)
    stale = dict(V2_PAGE, version={"number": 8})
    try:
        code, out, err, op = run(["plan", "page-update", "--base", str(base_abs), "--body-adf", str(edited_path)],
                                 [(CONF, lambda req: json.dumps(stale))] + [tenant_route()], env=env_conf())
        assert code == 1 and "no longer matches" in err
        assert not any(r.get_method() == "PUT" for r in op.calls)
    finally:
        os.chdir(old2)


def test_page_update_refuses_a_changed_adf_at_the_same_version():
    d2, base_abs, edited_path, old2 = _planned_update(LIVE_PAGE, EDITED_ADD_LINE)
    changed = json.loads(json.dumps(LIVE_PAGE))
    changed["body"]["atlas_doc_format"]["value"] = json.dumps(ADF)  # different ADF, same version
    try:
        code, out, err, op = run(["plan", "page-update", "--base", str(base_abs), "--body-adf", str(edited_path)],
                                 [(CONF, lambda req: json.dumps(changed))] + [tenant_route()], env=env_conf())
        assert code == 1 and "no longer matches" in err
    finally:
        os.chdir(old2)


def test_page_update_refuses_node_loss_and_allows_it_per_type():
    d2, base_abs, edited_path, old2 = _planned_update(LIVE_PAGE, EDITED_DROP_MACRO)
    try:
        code, out, err, op = run(["plan", "page-update", "--base", str(base_abs), "--body-adf", str(edited_path)],
                                 [(CONF, lambda req: json.dumps(LIVE_PAGE))] + [tenant_route()], env=env_conf())
        assert code == 1 and "extension" in err and "allow-node-loss" in err
        code, out, err, op = run(["plan", "page-update", "--base", str(base_abs), "--body-adf", str(edited_path),
                                  "--allow-node-loss", "extension"],
                                 [(CONF, lambda req: json.dumps(LIVE_PAGE))] + [tenant_route()], env=env_conf())
        assert code == 0, err
        assert "extension" in out and "allow-node-loss" in out
    finally:
        os.chdir(old2)


def test_page_update_apply_sends_version_plus_one_and_verifies_by_read_back():
    d2, base_abs, edited_path, old2 = _planned_update(LIVE_PAGE, EDITED_ADD_LINE)
    try:
        code, out, err, _ = run(["plan", "page-update", "--base", str(base_abs), "--body-adf", str(edited_path)],
                                [(CONF, lambda req: json.dumps(LIVE_PAGE))] + [tenant_route()], env=env_conf())
        path, conf = request_path(out), confirm_of(out)
        state = {"page": LIVE_PAGE}

        def route(req):
            if req.get_method() == "GET":
                return json.dumps(state["page"])
            assert req.get_method() == "PUT"
            state["put"] = json.loads(req.data.decode())
            state["page"] = dict(LIVE_PAGE, version={"number": 8},
                                 body={"atlas_doc_format": {"representation": "atlas_doc_format",
                                                            "value": json.dumps(EDITED_ADD_LINE)}})
            return json.dumps(state["page"])

        code, out2, err2, op2 = run(["apply", str(path), "--confirm", conf],
                                    [(CONF, route)] + [tenant_route()], env=env_conf())
        assert code == 0, err2
        assert state["put"]["version"]["number"] == 8
        assert json.loads(state["put"]["body"]["value"]) == EDITED_ADD_LINE
        assert not path.exists()
    finally:
        os.chdir(old2)


def test_page_update_read_back_that_differs_is_exit_3():
    d2, base_abs, edited_path, old2 = _planned_update(LIVE_PAGE, EDITED_ADD_LINE)
    try:
        code, out, err, _ = run(["plan", "page-update", "--base", str(base_abs), "--body-adf", str(edited_path)],
                                [(CONF, lambda req: json.dumps(LIVE_PAGE))] + [tenant_route()], env=env_conf())
        path, conf = request_path(out), confirm_of(out)

        def route(req):
            if(req.get_method() == "PUT"):
                return json.dumps(dict(LIVE_PAGE, version={"number": 8}))
            return json.dumps(LIVE_PAGE)  # read-back still the old body

        code, out2, err2, op2 = run(["apply", str(path), "--confirm", conf],
                                    [(CONF, route)] + [tenant_route()], env=env_conf())
        assert code == 3 and "read-back" in err2
        assert path.exists()
    finally:
        os.chdir(old2)


def test_page_fetch_never_applies():
    req = json.dumps({"schema": 1, "created": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "operation": "page-fetch", "args": {"page": "555"},
                      "target": {"host": HOST, "cloudId": CID, "email": EMAIL}, "base": {}, "body_text": "{}\n"})
    path = Path(tempfile.mkdtemp()) / "request.json"
    path.write_text(req)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    code, out, err, op = run(["apply", str(path), "--confirm", digest],
                             [(CONF, lambda r: json.dumps(LIVE_PAGE))] + [tenant_route()], env=env_conf())
    assert code == 1 and "read-only" in err


# --- audit fixes (0.1.67): exit-3 on read-back failure, allow-node-loss through
# --- apply, repeated flags collect, unknown/typo flags are fatal ---------------

def test_apply_exit_3_when_the_read_back_get_fails_after_the_send():
    code, out, err, _ = plan_for()
    path, conf = request_path(out), confirm_of(out)
    gets, sent = {"n": 0}, []

    def issue(req):
        if req.get_method() == "PUT":
            sent.append(req.data)
            return json.dumps({"ok": True})
        gets["n"] += 1
        if gets["n"] == 1:
            return json.dumps({"summary": "old title"})
        raise urllib.error.HTTPError(req.full_url, 502, "Bad Gateway",
                                     http.client.HTTPMessage(), io.BytesIO(b""))

    code, out2, err2, op = run(["apply", str(path), "--confirm", conf],
                               [tenant_route(), (f"{JIRA}/rest/api/3/issue/DEMO-1", issue)])
    assert code == 3, err2
    assert len(sent) == 1, "the write fired; the exit must still be 3, never 1"
    assert "SENT BUT UNVERIFIED" in err2 and "do not re-run `apply`" in err2
    assert path.exists()


def test_apply_exit_3_when_the_read_back_times_out_after_the_send():
    code, out, err, _ = plan_for()
    path, conf = request_path(out), confirm_of(out)
    gets, sent = {"n": 0}, []

    def issue(req):
        if req.get_method() == "PUT":
            sent.append(req.data)
            return json.dumps({"ok": True})
        gets["n"] += 1
        if gets["n"] == 1:
            return json.dumps({"summary": "old title"})
        raise TimeoutError("slow read-back")

    code, out2, err2, op = run(["apply", str(path), "--confirm", conf],
                               [tenant_route(), (f"{JIRA}/rest/api/3/issue/DEMO-1", issue)])
    assert code == 3, err2
    assert len(sent) == 1
    assert "SENT BUT UNVERIFIED" in err2


def test_apply_exit_2_includes_the_server_rejection_body():
    code, out, err, op = plan_page(conf_routes(space_results=[{"id": SPACE_ID, "key": "DEMO"}]))
    path, conf = request_path(out), confirm_of(out)

    def route(req):
        u, m = urllib.parse.urlsplit(req.full_url).path, req.get_method()
        if m == "GET" and u.endswith("/spaces"):
            return json.dumps({"results": [{"id": SPACE_ID, "key": "DEMO"}], "_links": {}})
        if m == "GET" and u.endswith("/pages"):
            return json.dumps({"results": [], "_links": {}})
        raise urllib.error.HTTPError(req.full_url, 409, "Conflict", http.client.HTTPMessage(),
                                     io.BytesIO(b'{"errors":[{"title":"A page with this title already exists"}]}'))

    code, out2, err2, op2 = run(["apply", str(path), "--confirm", conf],
                                [(CONF, route)] + [tenant_route()], env=env_conf())
    assert code == 2, err2
    assert "already exists" in err2, "the server's 4xx body must reach the operator"
    assert path.exists()


def test_page_update_apply_carries_allow_node_loss_through_the_file():
    d2, base_abs, edited_path, old2 = _planned_update(LIVE_PAGE, EDITED_DROP_MACRO)
    try:
        code, out, err, _ = run(["plan", "page-update", "--base", str(base_abs), "--body-adf", str(edited_path),
                                 "--allow-node-loss", "extension"],
                                [(CONF, lambda req: json.dumps(LIVE_PAGE))] + [tenant_route()], env=env_conf())
        assert code == 0, err
        path, conf = request_path(out), confirm_of(out)
        state = {"page": LIVE_PAGE}

        def route(req):
            if req.get_method() == "PUT":
                state["put"] = json.loads(req.data.decode())
                state["page"] = dict(LIVE_PAGE, version={"number": 8},
                                     body={"atlas_doc_format": {"representation": "atlas_doc_format",
                                                                "value": state["put"]["body"]["value"]}})
                return json.dumps(state["page"])
            return json.dumps(state["page"])

        code, out2, err2, op2 = run(["apply", str(path), "--confirm", conf],
                                    [(CONF, route)] + [tenant_route()], env=env_conf())
        assert code == 0, err2
        assert json.loads(state["put"]["body"]["value"]) == EDITED_DROP_MACRO
        assert not path.exists()
    finally:
        os.chdir(old2)


def test_parse_flags_collects_repeated_flags_in_order():
    flags, pos = rw.parse_flags(["--key", "DEMO-1", "--remove-fix-version", "1.0",
                                 "--remove-fix-version", "2.0", "positional"])
    assert flags == {"key": "DEMO-1", "remove-fix-version": ["1.0", "2.0"]}
    assert pos == ["positional"]


def test_repeated_remove_flag_collects_all_values_into_the_write():
    both = jira_routes({"issue": dict(ISSUE, fields=dict(ISSUE["fields"],
                                                         fixVersions=[{"name": "1.0"}, {"name": "2.0"}]))})
    code, out, err, op = run_issue_set(["--remove-fix-version", "1.0", "--remove-fix-version", "2.0"], both)
    assert code == 0, err
    body = json.loads(json.loads(request_path(out).read_text())["body_text"])
    assert body["update"]["fixVersions"] == [{"remove": {"name": "1.0"}}, {"remove": {"name": "2.0"}}]


def test_a_typo_second_change_is_fatal_not_silently_dropped():
    both = jira_routes({"issue": dict(ISSUE, fields=dict(ISSUE["fields"],
                                                         fixVersions=[{"name": "1.0"}, {"name": "2.0"}]))})
    code, out, err, op = run_issue_set(["--remove-fix-version", "1.0", "--remove-fix-versions", "2.0"], both)
    assert code == 1 and "unknown flag" in err
    assert op.calls == []


def test_a_single_value_flag_given_twice_is_fatal():
    flags, _ = rw.parse_flags(["--key", "DEMO-1", "--key", "DEMO-2"])
    assert flags["key"] == ["DEMO-1", "DEMO-2"]
    try:
        rest_ops_jira_issues._validate_issue_set(flags, ())
    except rw.Fatal as e:
        assert "--key" in str(e) and "once" in str(e)
    else:
        raise AssertionError("a repeated --key passed validation")


def test_page_update_refuses_unknown_flags():
    d2, base_abs, edited_path, old2 = _planned_update(LIVE_PAGE, EDITED_ADD_LINE)
    try:
        code, out, err, op = run(["plan", "page-update", "--base", str(base_abs), "--body-adf", str(edited_path),
                                  "--bogus", "1"],
                                 [(CONF, lambda req: json.dumps(LIVE_PAGE))] + [tenant_route()], env=env_conf())
        assert code == 1 and "unknown flag" in err
        assert op.calls == []
    finally:
        os.chdir(old2)


def test_page_fetch_takes_no_flags():
    code, out, err, op = run(["page-fetch", "555", "--bogus", "1"],
                             [(CONF, lambda req: json.dumps(LIVE_PAGE))] + [tenant_route()], env=env_conf())
    assert code == 1 and "no flags" in err
    assert op.calls == []


# --- step-6 whole-picture fixes (0.1.68) ----------------------------------------

def test_env_file_flag_reads_its_own_file_for_the_alternate_target():
    prod = env_file(ENV_OK)
    other = env_file(ENV_OK.replace(HOST, "scratch-site.atlassian.net"))
    routes = [("https://scratch-site.atlassian.net/_edge/tenant_info", lambda r: json.dumps({"cloudId": CID})),
              (f"{JIRA}/rest/api/3/issue/DEMO-1", lambda r: json.dumps({"summary": "old title"}))]
    code, out, err, op = run(["plan", "fake-set", "--key", "DEMO-1", "--env-file", str(other)], routes, env=prod)
    assert code == 0, err
    assert "ALTERNATE TARGET scratch-site.atlassian.net" in out


def test_apply_exit_3_when_the_read_back_returns_a_non_dict_body():
    code, out, err, _ = plan_for()
    path, conf = request_path(out), confirm_of(out)
    gets, sent = {"n": 0}, []

    def issue(req):
        if req.get_method() == "PUT":
            sent.append(req.data)
            return json.dumps({"ok": True})
        gets["n"] += 1
        if gets["n"] == 1:
            return json.dumps({"summary": "old title"})
        return "[]"  # a JSON list where the read-back expects an object

    code, out2, err2, op = run(["apply", str(path), "--confirm", conf],
                               [tenant_route(), (f"{JIRA}/rest/api/3/issue/DEMO-1", issue)])
    assert code == 3, err2
    assert len(sent) == 1
    assert "SENT BUT UNVERIFIED" in err2
    assert "Traceback" not in err2, "an unguarded shape error must not leak a traceback"


def test_apply_refuses_unknown_flags_on_the_apply_line():
    code, out, err, _ = plan_for()
    path, conf = request_path(out), confirm_of(out)
    code, out2, err2, op = run(["apply", str(path), "--confirm", conf, "--bogus", "1"],
                               [tenant_route(), (f"{JIRA}/rest/api/3/issue/DEMO-1",
                                                 lambda r: json.dumps({"summary": "old title"}))])
    assert code == 1 and "unknown flag" in err2
    assert not any(r.get_method() in ("PUT", "POST") for r in op.calls)


def test_stray_positionals_are_fatal_for_the_flagged_operations():
    code, out, err, op = run_issue_set(["--priority", "High", "APPR-1"], jira_routes())
    assert code == 1 and "positional" in err
    assert op.calls == []


def test_allow_node_loss_rejects_the_camel_case_synonym():
    d2, base_abs, edited_path, old2 = _planned_update(LIVE_PAGE, EDITED_ADD_LINE)
    try:
        code, out, err, op = run(["plan", "page-update", "--base", str(base_abs), "--body-adf", str(edited_path),
                                  "--allowNodeLoss", "extension"],
                                 [(CONF, lambda req: json.dumps(LIVE_PAGE))] + [tenant_route()], env=env_conf())
        assert code == 1 and "unknown flag" in err
        assert op.calls == []
    finally:
        os.chdir(old2)


# --- version-edit / version-delete (0.1.70): the raw Jira version lifecycle ----

def _version_routes(state):
    def route(req):
        u, m = urllib.parse.urlsplit(req.full_url).path, req.get_method()
        if m == "PUT" and u.endswith("/rest/api/3/version/18329"):
            state["v"] = dict(state["v"], **json.loads(req.data.decode()))
            return json.dumps(state["v"])
        if m == "DELETE" and u.endswith("/rest/api/3/version/18329"):
            state["deleted"] = req.full_url
            return ""
        if m == "GET" and u.endswith("/rest/api/3/version/18329"):
            if state.get("deleted"):
                return urllib.error.HTTPError(req.full_url, 404, "nf", http.client.HTTPMessage(),
                                              io.BytesIO(b'{"errorMessages":["Could not find version"]}'))
            return json.dumps(state["v"])
        raise AssertionError(f"unexpected {m} {u}")
    return [(JIRA, route)]


def test_version_edit_refuses_unknown_flags_and_zero_changes():
    code, _, err, op = run(["plan", "version-edit", "--id", "18329"], jira_routes() + [tenant_route()])
    assert code == 1 and "usage" in err and op.calls == []
    code, _, err, op = run(["plan", "version-edit", "--id", "18329", "--named", "x"], jira_routes() + [tenant_route()])
    assert code == 1 and "unknown flag" in err and op.calls == []
    code, _, err, op = run(["plan", "version-edit", "--id", "18329", "--released", "TRUE!"], jira_routes() + [tenant_route()])
    assert code == 1 and "true or false" in err and op.calls == []


def test_version_edit_applies_and_read_backs():
    state = {"v": {"id": "18329", "name": "1.0", "description": "old", "projectId": "17951",
                   "archived": False, "released": False}}
    code, out, err, op = run(["plan", "version-edit", "--id", "18329", "--description", "live edit"],
                             _version_routes(state) + [tenant_route()])
    assert code == 0, err
    path, conf = request_path(out), confirm_of(out)
    code, out2, err2, op2 = run(["apply", str(path), "--confirm", conf],
                                _version_routes(state) + [tenant_route()])
    assert code == 0, err2
    assert state["v"]["description"] == "live edit"
    assert not path.exists()


def test_version_edit_accepts_a_description_file_and_boolean_flags():
    state = {"v": {"id": "18329", "name": "1.0", "description": "", "projectId": "17951",
                   "archived": False, "released": False}}
    adf_path = adf_file()
    adf_path.write_text("desc from file")
    code, out, err, op = run(["plan", "version-edit", "--id", "18329", "--description-file", str(adf_path),
                              "--archived", "true"],
                             _version_routes(state) + [tenant_route()])
    assert code == 0, err
    data = json.loads(request_path(out).read_text())
    wire = json.loads(data["body_text"])
    assert wire == {"description": "desc from file", "archived": True}


def test_version_delete_applies_and_verifies_by_a_404_readback():
    state = {"v": {"id": "18329", "name": "1.0", "projectId": "17951"}}
    code, out, err, op = run(["plan", "version-delete", "--id", "18329"],
                             _version_routes(state) + [tenant_route()])
    assert code == 0, err
    path, conf = request_path(out), confirm_of(out)
    code, out2, err2, op2 = run(["apply", str(path), "--confirm", conf],
                                _version_routes(state) + [tenant_route()])
    assert code == 0, err2
    assert state.get("deleted")
    assert not path.exists()


def test_version_delete_passes_the_escalation_toggles_as_query_params():
    state = {"v": {"id": "18329", "name": "1.0", "projectId": "17951"}}
    code, out, err, op = run(["plan", "version-delete", "--id", "18329", "--delete-fixed-issues", "true",
                              "--move-affected-to", "18400"],
                             _version_routes(state) + [tenant_route()])
    assert code == 0, err
    path, conf = request_path(out), confirm_of(out)
    code, out2, err2, op2 = run(["apply", str(path), "--confirm", conf],
                                _version_routes(state) + [tenant_route()])
    assert code == 0, err2
    import urllib.parse as up
    q = up.parse_qs(up.urlsplit(state["deleted"]).query)
    assert q == {"deleteFixedIssues": ["true"], "moveAffectedIssuesTo": ["18400"]}


def test_version_edit_round_trips_a_release_date_edit():
    # regression: release-date was stored under releaseDate and apply's re-validation refused it
    state = {"v": {"id": "18329", "name": "1.0", "description": "", "projectId": "17951",
                   "archived": False, "released": False, "releaseDate": None}}
    code, out, err, op = run(["plan", "version-edit", "--id", "18329", "--release-date", "2027-01-31"],
                             _version_routes(state) + [tenant_route()])
    assert code == 0, err
    path, conf = request_path(out), confirm_of(out)
    code, out2, err2, op2 = run(["apply", str(path), "--confirm", conf],
                                _version_routes(state) + [tenant_route()])
    assert code == 0, err2
    assert state["v"]["releaseDate"] == "2027-01-31"


# --- page-delete (0.1.74): Confluence page to trash, with homepage/children/status refusals ----

def _page_delete_routes(state):
    def route(req):
        u, m = urllib.parse.urlsplit(req.full_url).path, req.get_method()
        if m == "DELETE" and u.endswith("/pages/555"):
            state["deleted"] = req.full_url
            state["page"] = dict(state["page"], status="trashed") if state.get("trash_visible") else None
            return ""
        if m == "GET" and u.endswith("/pages/555"):
            if state["page"] is None:
                return urllib.error.HTTPError(req.full_url, 404, "nf", http.client.HTTPMessage(), io.BytesIO(b"{}"))
            return json.dumps(state["page"])
        if m == "GET" and u.endswith("/pages/555/children"):
            return json.dumps({"results": state.get("children", [])})
        if m == "GET" and u.endswith("/spaces/123"):
            return json.dumps({"id": "123", "key": "ARAC", "homepageId": state.get("homepage", "999")})
        raise AssertionError(f"unexpected {m} {u}")
    return [(CONF, route), tenant_route()]


def _live_state(**extra):
    return dict({"page": {"id": "555", "status": "current", "title": "Demo page", "spaceId": "123",
                          "version": {"number": 7}}}, **extra)


def test_page_delete_refuses_bad_arguments_before_any_request():
    for argv in (["plan", "page-delete"], ["plan", "page-delete", "--page", "abc"],
                 ["plan", "page-delete", "--page", "555", "--purge", "true"],
                 ["plan", "page-delete", "555"]):
        code, _, err, op = run(argv, _page_delete_routes(_live_state()), env=env_conf())
        assert code == 1 and op.calls == [], (argv, err)


def test_page_delete_plan_names_the_page_and_sends_no_write():
    code, out, err, op = run(["plan", "page-delete", "--page", "555"],
                             _page_delete_routes(_live_state()), env=env_conf())
    assert code == 0, err
    assert "Demo page" in out and "confirm:" in out
    assert {c.get_method() for c in op.calls} == {"GET"}


def test_page_delete_refuses_a_space_homepage():
    code, _, err, _ = run(["plan", "page-delete", "--page", "555"],
                          _page_delete_routes(_live_state(homepage="555")), env=env_conf())
    assert code == 1 and "homepage" in err


def test_page_delete_refuses_a_page_that_has_children():
    code, _, err, _ = run(["plan", "page-delete", "--page", "555"],
                          _page_delete_routes(_live_state(children=[{"id": "556"}])), env=env_conf())
    assert code == 1 and "child" in err


def test_page_delete_refuses_a_page_that_is_not_current():
    state = _live_state()
    state["page"]["status"] = "trashed"
    code, _, err, _ = run(["plan", "page-delete", "--page", "555"], _page_delete_routes(state), env=env_conf())
    assert code == 1 and "current" in err


def test_page_delete_apply_trashes_without_purge_and_verifies_by_a_404_readback():
    state = _live_state()
    code, out, err, _ = run(["plan", "page-delete", "--page", "555"], _page_delete_routes(state), env=env_conf())
    assert code == 0, err
    path, conf = request_path(out), confirm_of(out)
    code, out2, err2, _ = run(["apply", str(path), "--confirm", conf], _page_delete_routes(state), env=env_conf())
    assert code == 0, err2
    assert urllib.parse.urlsplit(state["deleted"]).query == ""  # no purge=true: the page stays in the trash
    assert not path.exists()


def test_page_delete_accepts_a_trashed_status_readback():
    state = _live_state(trash_visible=True)
    code, out, err, _ = run(["plan", "page-delete", "--page", "555"], _page_delete_routes(state), env=env_conf())
    assert code == 0, err
    path, conf = request_path(out), confirm_of(out)
    code, _, err2, _ = run(["apply", str(path), "--confirm", conf], _page_delete_routes(state), env=env_conf())
    assert code == 0, err2


def test_page_delete_apply_refuses_when_the_page_gained_a_child_after_the_plan():
    state = _live_state()
    code, out, err, _ = run(["plan", "page-delete", "--page", "555"], _page_delete_routes(state), env=env_conf())
    path, conf = request_path(out), confirm_of(out)
    state["children"] = [{"id": "556"}]
    code, _, err2, op = run(["apply", str(path), "--confirm", conf], _page_delete_routes(state), env=env_conf())
    assert code == 1 and "deleted" not in state
    assert "DELETE" not in {c.get_method() for c in op.calls}


# --- attachment-upload (0.1.75): one image to a page, via Confluence v1 multipart ---------

V1 = f"https://api.atlassian.com/ex/confluence/{CID}/wiki/rest/api"
PNG = b"\x89PNG\r\n\x1a\n" + b"fake-image-bytes"


def _img(name="diagram.png", data=PNG):
    p = Path(tempfile.mkdtemp()) / name
    p.write_bytes(data)
    return p


def _attach_routes(state):
    def v2(req):
        u, m = urllib.parse.urlsplit(req.full_url).path, req.get_method()
        if m == "GET" and u.endswith("/pages/555"):
            return json.dumps({"id": "555", "status": "current", "title": "Demo page", "spaceId": "123"})
        if m == "GET" and u.endswith("/pages/555/attachments"):
            want = urllib.parse.parse_qs(urllib.parse.urlsplit(req.full_url).query).get("filename", [None])[0]
            rows = [a for a in state["atts"] if want in (None, a["title"])]
            return json.dumps({"results": rows})
        raise AssertionError(f"unexpected {m} {u}")

    def v1(req):
        assert req.get_method() == "POST" and req.full_url.endswith("/content/555/child/attachment"), req.full_url
        state["post"] = req
        m = re.search(rb'filename="([^"]+)"', req.data)
        name = m.group(1).decode()
        if state.get("drop"):
            return json.dumps({"results": [{"id": "att1", "title": name}]})
        state["atts"].append({"id": "att1", "title": name, "fileSize": len(PNG)})
        return json.dumps({"results": [{"id": "att1", "title": name}]})
    return [(V1, v1), (CONF, v2), tenant_route()]


def env_att():
    return env_file(ENV_OK + "ACLI_REST_WRITE_CONFLUENCE_FILE_TOKEN=filetoken-xyz\n")


def test_attachment_upload_plan_refuses_when_the_file_token_is_missing_and_sends_nothing():
    code, _, err, op = run(["plan", "attachment-upload", "--page", "555", "--file", str(_img())],
                           _attach_routes({"atts": []}), env=env_conf())
    assert code == 1 and "ACLI_REST_WRITE_CONFLUENCE_FILE_TOKEN" in err and op.calls == []


def test_attachment_upload_sends_the_post_with_the_file_token_and_reads_with_the_granular_one():
    import base64
    state = {"atts": []}
    code, out, err, _ = run(["plan", "attachment-upload", "--page", "555", "--file", str(_img())],
                            _attach_routes(state), env=env_att())
    assert code == 0, err
    path, conf = request_path(out), confirm_of(out)
    code, _, err2, op = run(["apply", str(path), "--confirm", conf], _attach_routes(state), env=env_att())
    assert code == 0, err2
    want_file = "Basic " + base64.b64encode(f"{EMAIL}:filetoken-xyz".encode()).decode()
    auth = {c.get_method(): set() for c in op.calls}
    for c in op.calls:
        auth[c.get_method()].add(c.get_header("Authorization"))
    assert auth["POST"] == {want_file}
    assert want_file not in auth["GET"]


def test_attachment_upload_refuses_bad_arguments_before_any_request():
    good = _img()
    for argv in (["plan", "attachment-upload"],
                 ["plan", "attachment-upload", "--page", "555"],
                 ["plan", "attachment-upload", "--file", str(good)],
                 ["plan", "attachment-upload", "--page", "abc", "--file", str(good)],
                 ["plan", "attachment-upload", "--page", "555", "--file", str(_img("notes.txt"))],
                 ["plan", "attachment-upload", "--page", "555", "--file", str(_img(".env.png"))],
                 ["plan", "attachment-upload", "--page", "555", "--file", str(good), "--name", "../x.png"],
                 ["plan", "attachment-upload", "--page", "555", "--file", str(good), "--purge", "true"]):
        code, _, err, op = run(argv, _attach_routes({"atts": []}), env=env_att())
        assert code == 1 and op.calls == [], (argv, err)


def test_attachment_upload_plan_refuses_a_missing_file_an_empty_file_and_a_huge_file():
    for path, why in ((Path("/nonexistent/x.png"), "not found"), (_img("e.png", b""), "empty")):
        code, _, err, _ = run(["plan", "attachment-upload", "--page", "555", "--file", str(path)],
                              _attach_routes({"atts": []}), env=env_att())
        assert code == 1 and why in err, (path, err)
    big = _img("big.png", b"x" * (10 * 1024 * 1024 + 1))
    code, _, err, _ = run(["plan", "attachment-upload", "--page", "555", "--file", str(big)],
                          _attach_routes({"atts": []}), env=env_att())
    assert code == 1 and "10 MB" in err


def test_attachment_upload_plan_previews_name_size_and_hash_and_sends_no_write():
    img = _img()
    code, out, err, op = run(["plan", "attachment-upload", "--page", "555", "--file", str(img)],
                             _attach_routes({"atts": []}), env=env_att())
    assert code == 0, err
    assert "diagram.png" in out and str(len(PNG)) in out and "confirm:" in out
    assert {c.get_method() for c in op.calls} == {"GET"}
    assert PNG.decode("latin-1") not in out  # the file content never lands in the preview


def test_attachment_upload_plan_refuses_a_name_the_page_already_has():
    state = {"atts": [{"id": "a0", "title": "diagram.png", "fileSize": 3}]}
    code, _, err, _ = run(["plan", "attachment-upload", "--page", "555", "--file", str(_img())],
                          _attach_routes(state), env=env_att())
    assert code == 1 and "already has" in err


def test_attachment_upload_plan_refuses_a_page_that_is_not_current():
    def v2(req):
        return json.dumps({"id": "555", "status": "trashed", "title": "x", "spaceId": "123"})
    code, _, err, _ = run(["plan", "attachment-upload", "--page", "555", "--file", str(_img())],
                          [(CONF, v2), tenant_route()], env=env_att())
    assert code == 1 and "current" in err


def test_attachment_upload_apply_posts_multipart_with_the_xsrf_header_and_verifies():
    state = {"atts": []}
    img = _img()
    code, out, err, _ = run(["plan", "attachment-upload", "--page", "555", "--file", str(img)],
                            _attach_routes(state), env=env_att())
    assert code == 0, err
    path, conf = request_path(out), confirm_of(out)
    code, _, err2, _ = run(["apply", str(path), "--confirm", conf], _attach_routes(state), env=env_att())
    assert code == 0, err2
    req = state["post"]
    assert req.get_header("X-atlassian-token") == "no-check"
    assert req.get_header("Content-type").startswith("multipart/form-data; boundary=")
    assert PNG in req.data and b'filename="diagram.png"' in req.data
    assert not path.exists()


def test_attachment_upload_apply_refuses_when_the_file_changed_after_the_plan():
    state = {"atts": []}
    img = _img()
    code, out, err, _ = run(["plan", "attachment-upload", "--page", "555", "--file", str(img)],
                            _attach_routes(state), env=env_att())
    path, conf = request_path(out), confirm_of(out)
    img.write_bytes(PNG + b"tampered")
    code, _, err2, op = run(["apply", str(path), "--confirm", conf], _attach_routes(state), env=env_att())
    assert code == 1 and "changed" in err2 and "post" not in state
    assert "POST" not in {c.get_method() for c in op.calls}


def test_attachment_upload_apply_exits_3_when_the_readback_does_not_find_the_file():
    state = {"atts": [], "drop": True}
    img = _img()
    code, out, err, _ = run(["plan", "attachment-upload", "--page", "555", "--file", str(img)],
                            _attach_routes(state), env=env_att())
    path, conf = request_path(out), confirm_of(out)
    code, _, err2, _ = run(["apply", str(path), "--confirm", conf], _attach_routes(state), env=env_att())
    assert code == 3 and "UNVERIFIED" in err2


# --- the re-validation invariant: apply re-runs each validator on stored args --

def _stored_args_for_every_operation():
    # one minimal, valid call per writable operation; page-fetch is planOnly and never applies
    seeds = {
        "page-create": ({"space": "APPR", "title": "seed", "body-adf": "seed.adf"}, ()),
        "issue-set": ({"key": "APPR-1", "priority": "High"}, ()),
        "issue-delete": ({"key": "APPR-1"}, ()),
        "filter-create": ({"name": "seed", "jql": "project = APPR"}, ()),
        "board-columns-set": ({"board": "1", "columns": "[{\"name\": \"a\", \"statuses\": []}]"}, ()),
        "board-delete": ({"board": "1"}, ()),
        "confluence-call": ({"op": "createFolder", "body": "{\"spaceId\": \"1\"}"}, ()),
        "confluence-v1-call": ({"op": "createSpace", "body": "{\"key\": \"X\", \"name\": \"n\"}"}, ()),
        "jira-call": ({"op": "createComponent", "body": "{\"name\": \"seed\"}"}, ()),
        "board-property-set": ({"board": "1", "key": "k", "value": "1"}, ()),
        "version-create": ({"project": "APPR", "name": "seed"}, ()),
        "version-edit": ({"id": "18329", "released": "true", "archived": "false",
                          "release-date": "2030-01-01"}, ()),
        "version-delete": ({"id": "18329"}, ()),
        "page-update": ({"base": "seed.base.json", "body-adf": "seed.adf.json"}, ()),
        "page-delete": ({"page": "555"}, ()),
        "attachment-upload": ({"page": "555", "file": "seed.png"}, ()),
    }
    assert set(seeds) == set(rw.OPERATIONS) - {"page-fetch"}, \
        "every writable operation needs a seed here (add one with the operation)"
    return [(name, flags, pos) for name, (flags, pos) in sorted(seeds.items())]


def test_every_operation_validates_its_own_stored_args():
    # the stored-key-vs-CLI-key class (0.1.67 --allow-node-loss, 0.1.71 --release-date): a validator
    # stored an arg under its REST wire name and apply's re-validation refused it. Invariant:
    # whatever validate() returns must pass unchanged through validate() again — the exact shape
    # apply runs. A future operation that breaks this fails here, not in review.
    for op_name, flags, pos in _stored_args_for_every_operation():
        op = rw.OPERATIONS[op_name]
        stored = op["validate"](flags, pos)
        assert isinstance(stored, dict), op_name
        assert op["validate"](stored, ()) == stored, op_name


def test_applys_re_validation_refuses_a_key_no_validator_knows():
    # proves the trap actually fires: an unknown key in stored args must be refused, so a
    # wire-name slip cannot pass apply's re-validation silently
    for op_name, flags, pos in _stored_args_for_every_operation():
        op = rw.OPERATIONS[op_name]
        tampered = dict(op["validate"](flags, pos))
        tampered["wireNameTrap"] = "x"
        try:
            op["validate"](tampered, ())
        except rw.Fatal:
            continue
        raise AssertionError(f"{op_name} re-validated a key no validator knows")


# --- issue-delete: irreversible, so plan names what goes and apply verifies by a 404 -----

def _issue_routes(state):
    def route(req):
        u, m = urllib.parse.urlsplit(req.full_url).path, req.get_method()
        if u.endswith("/rest/api/3/issue/DEMO-9"):
            if m == "DELETE":
                state["deleted"] = req.full_url
                return ""
            if state.get("deleted"):
                return urllib.error.HTTPError(req.full_url, 404, "nf", http.client.HTTPMessage(),
                                              io.BytesIO(b'{"errorMessages":["Issue does not exist"]}'))
            return json.dumps({"fields": state["fields"]})
        raise AssertionError(f"unexpected {m} {u}")
    return [(JIRA, route)]


def _issue_fields(subtasks=()):
    return {"summary": "Old", "issuetype": {"name": "Task"}, "status": {"name": "To Do"},
            "subtasks": [{"key": k} for k in subtasks], "issuelinks": [{}, {}]}


def test_issue_delete_refuses_bad_arguments_before_any_request():
    for argv in (["--key", "nope"], [], ["--key", "DEMO-9", "--jql", "x"]):
        code, _, err, op = run(["plan", "issue-delete", *argv], [tenant_route()])
        assert code == 1 and op.calls == [], argv


def test_issue_delete_plan_lists_what_goes_warns_and_sends_no_write():
    state = {"fields": _issue_fields()}
    code, out, err, op = run(["plan", "issue-delete", "--key", "DEMO-9"], _issue_routes(state) + [tenant_route()])
    assert code == 0, err
    assert "IRREVERSIBLE" in out and "Old" in out and '"links": 2' in out
    assert not state.get("deleted") and all(c.get_method() == "GET" for c in op.calls if "/issue/" in c.full_url)


def test_issue_delete_refuses_sub_tasks_unless_asked_and_then_passes_deleteSubtasks():
    state = {"fields": _issue_fields(["DEMO-10"])}
    code, _, err, _ = run(["plan", "issue-delete", "--key", "DEMO-9"], _issue_routes(state) + [tenant_route()])
    assert code == 1 and "DEMO-10" in err and "--delete-subtasks" in err
    code, out, err, _ = run(["plan", "issue-delete", "--key", "DEMO-9", "--delete-subtasks", "true"],
                            _issue_routes(state) + [tenant_route()])
    assert code == 0, err
    code, _, err2, _ = run(["apply", str(request_path(out)), "--confirm", confirm_of(out)],
                           _issue_routes(state) + [tenant_route()])
    assert code == 0, err2
    assert state["deleted"].endswith("?deleteSubtasks=true")


def test_issue_delete_apply_refuses_a_wrong_confirm_and_deletes_nothing():
    state = {"fields": _issue_fields()}
    code, out, err, _ = run(["plan", "issue-delete", "--key", "DEMO-9"], _issue_routes(state) + [tenant_route()])
    code, _, err2, _ = run(["apply", str(request_path(out)), "--confirm", "000000000000"],
                           _issue_routes(state) + [tenant_route()])
    assert code != 0 and not state.get("deleted")


def test_issue_delete_applies_and_verifies_by_a_404_readback():
    state = {"fields": _issue_fields()}
    code, out, err, _ = run(["plan", "issue-delete", "--key", "DEMO-9"], _issue_routes(state) + [tenant_route()])
    assert code == 0, err
    path = request_path(out)
    code, _, err2, _ = run(["apply", str(path), "--confirm", confirm_of(out)], _issue_routes(state) + [tenant_route()])
    assert code == 0, err2
    assert state["deleted"].endswith("/rest/api/3/issue/DEMO-9") and not path.exists()


# --- filter-create: one saved filter, optionally shared with a project ---------

def _filter_routes(state):
    def route(req):
        u, m = urllib.parse.urlsplit(req.full_url).path, req.get_method()
        if m == "GET" and u.endswith("/rest/api/3/filter/search"):
            return json.dumps({"values": state.get("existing", [])})
        if m == "GET" and u.endswith("/rest/api/3/project/APPR"):
            return json.dumps({"id": "17951"})
        if m == "POST" and u.endswith("/rest/api/3/filter"):
            state["created"] = json.loads(req.data.decode())
            return json.dumps({"id": "321", "name": state["created"]["name"]})
        if m == "GET" and u.endswith("/rest/api/3/filter/321"):
            c = state["created"]
            return json.dumps({"id": "321", "name": c["name"], "jql": c["jql"],
                               "sharePermissions": state.get("shares", c.get("sharePermissions", []))})
        raise AssertionError(f"unexpected {m} {u}")
    return [(JIRA, route)]


def test_filter_create_refuses_bad_arguments_before_any_request():
    for argv in (["--name", "n"], ["--jql", "j"], ["--name", "n", "--jql", "j", "--share-project", "lower"],
                 ["--name", "n", "--jql", "j", "--board", "1"]):
        code, _, err, op = run(["plan", "filter-create", *argv], [tenant_route()])
        assert code == 1 and op.calls == [], argv


def test_filter_create_refuses_a_name_that_already_exists():
    state = {"existing": [{"name": "CML board"}]}
    code, _, err, _ = run(["plan", "filter-create", "--name", "CML board", "--jql", "project = APPR"],
                          _filter_routes(state) + [tenant_route()])
    assert code == 1 and "already exists" in err and "created" not in state


def test_filter_create_posts_the_project_share_and_verifies_by_read_back():
    state = {}
    argv = ["plan", "filter-create", "--name", "CML board", "--jql", "project = APPR", "--description", "d",
            "--share-project", "APPR"]
    code, out, err, op = run(argv, _filter_routes(state) + [tenant_route()])
    assert code == 0, err
    assert "created" not in state
    code, out2, err2, _ = run(["apply", str(request_path(out)), "--confirm", confirm_of(out)],
                           _filter_routes(state) + [tenant_route()])
    assert code == 0, err2
    assert "filter id: 321" in out2
    assert state["created"] == {"name": "CML board", "jql": "project = APPR", "description": "d",
                                "sharePermissions": [{"type": "project", "project": {"id": "17951"}}]}


def test_filter_create_fails_when_the_share_did_not_stick():
    state = {"shares": []}
    code, out, err, _ = run(["plan", "filter-create", "--name", "n", "--jql", "project = APPR", "--share-project", "APPR"],
                            _filter_routes(state) + [tenant_route()])
    assert code == 0, err
    code, _, err2, _ = run(["apply", str(request_path(out)), "--confirm", confirm_of(out)],
                           _filter_routes(state) + [tenant_route()])
    assert code != 0


def test_issue_delete_refuses_a_delete_subtasks_value_other_than_true():
    for value in ("false", "yes", "1"):
        code, _, err, op = run(["plan", "issue-delete", "--key", "APPR-1", "--delete-subtasks", value], [tenant_route()])
        assert code == 1 and op.calls == [], (value, err)


# --- board operations: columns (internal greenhopper API), delete, property ---------------

def _board_model(extra_unmapped=(), dup_open=False):
    todo = [{"id": "10", "name": "Open"}, {"id": "11", "name": "To Do"}]
    if dup_open:
        todo.append({"id": "12", "name": "open"})
    return {"rapidListConfig": {
        "mappedColumns": [
            {"id": 1, "name": "Backlog", "isKanPlanColumn": True, "mappedStatuses": []},
            {"id": 2, "name": "To Do", "isKanPlanColumn": False, "mappedStatuses": todo},
            {"id": 3, "name": "Done", "isKanPlanColumn": False,
             "mappedStatuses": [{"id": "20", "name": "Done"}, {"id": "21", "name": "Resolved"}]}],
        "unmappedStatuses": [{"id": "30", "name": "HOLD"}, *extra_unmapped]}}


def _columns_routes(state):
    def route(req):
        u, m = urllib.parse.urlsplit(req.full_url).path, req.get_method()
        if m == "GET" and u.endswith("/rest/greenhopper/1.0/rapidviewconfig/editmodel"):
            return json.dumps(state.get("model") or _board_model())
        if m == "PUT" and u.endswith("/rest/greenhopper/1.0/rapidviewconfig/columns"):
            state["put"] = json.loads(req.data.decode())
            state["headers"] = {k.lower(): v for k, v in req.header_items()}
            return "{}"
        if m == "GET" and u.endswith("/rest/agile/1.0/board/10103/configuration"):
            cols = state["cfg"] if "cfg" in state else [
                {"name": c["name"], "statuses": [{"id": s["id"]} for s in c["mappedStatuses"]]}
                for c in state["put"]["mappedColumns"]]
            return json.dumps({"columnConfig": {"columns": cols}})
        raise AssertionError(f"unexpected {m} {u}")
    return [(JIRA, route)]


WANTED = [{"name": "Backlog", "statuses": []}, {"name": "To Do", "statuses": ["To Do", "HOLD"]},
          {"name": "Done", "statuses": ["done", "Resolved"]}, {"name": "Review", "statuses": []}]


def _columns_plan(state, wanted=WANTED):
    return run(["plan", "board-columns-set", "--board", "10103", "--columns", json.dumps(wanted)],
               _columns_routes(state) + [tenant_route()])


def test_board_columns_set_refuses_bad_arguments_before_any_request():
    good = json.dumps(WANTED)
    for argv in (["--columns", good], ["--board", "abc", "--columns", good], ["--board", "1"],
                 ["--board", "1", "--columns", "not json"], ["--board", "1", "--columns", "[]"],
                 ["--board", "1", "--columns", json.dumps([{"name": "a", "statuses": []}, {"name": "A", "statuses": []}])],
                 ["--board", "1", "--columns", json.dumps([{"name": "a", "statuses": ["x"]}, {"name": "b", "statuses": ["X"]}])],
                 ["--board", "1", "--columns", json.dumps([{"name": "a", "statuses": [], "id": 3}])],
                 ["--board", "1", "--columns", good, "--force", "true"]):
        code, _, err, op = run(["plan", "board-columns-set", *argv], [tenant_route()])
        assert code == 1 and op.calls == [], argv


def test_board_columns_set_refuses_an_unknown_or_ambiguous_status_name():
    state = {}
    code, _, err, _ = _columns_plan(state, [{"name": "a", "statuses": ["Nope"]}])
    assert code == 1 and "Nope" in err and "put" not in state
    state = {"model": _board_model(dup_open=True)}
    code, _, err, _ = _columns_plan(state, [{"name": "a", "statuses": ["Open"]}])
    assert code == 1 and "cannot choose" in err


def test_board_columns_set_plan_shows_current_new_and_leaving_statuses_and_sends_nothing():
    state = {}
    code, out, err, _ = _columns_plan(state)
    assert code == 0, err
    assert "put" not in state
    assert "OVERWRITES the whole column set of board 10103 (3 columns now, 4 after)" in out
    assert "current: Backlog[]; To Do[Open, To Do]; Done[Done, Resolved]" in out
    assert "new: Backlog[]; To Do[To Do, HOLD]; Done[done, Resolved]; Review[]" in out
    assert "statuses leaving the board: Open" in out
    assert "UNVERIFIED" in out


def test_board_columns_set_apply_puts_the_mapped_columns_and_verifies_by_read_back():
    state = {}
    code, out, err, _ = _columns_plan(state)
    assert code == 0, err
    code, out2, err2, _ = run(["apply", str(request_path(out)), "--confirm", confirm_of(out)],
                              _columns_routes(state) + [tenant_route()])
    assert code == 0, err2
    assert state["put"] == {"rapidViewId": 10103, "mappedColumns": [
        {"name": "Backlog", "isKanPlanColumn": True, "mappedStatuses": [], "id": 1},
        {"name": "To Do", "isKanPlanColumn": False, "mappedStatuses": [{"id": "11"}, {"id": "30"}], "id": 2},
        {"name": "Done", "isKanPlanColumn": False, "mappedStatuses": [{"id": "20"}, {"id": "21"}], "id": 3},
        {"name": "Review", "isKanPlanColumn": False, "mappedStatuses": []}]}
    assert state["headers"]["x-atlassian-token"] == "no-check"


def test_board_columns_set_fails_when_the_read_back_does_not_match():
    state = {"cfg": []}
    code, out, err, _ = _columns_plan(state)
    assert code == 0, err
    code, _, _, _ = run(["apply", str(request_path(out)), "--confirm", confirm_of(out)],
                        _columns_routes(state) + [tenant_route()])
    assert code != 0


def test_board_columns_set_apply_refuses_when_the_board_changed_after_the_plan():
    state = {}
    code, out, err, _ = _columns_plan(state)
    assert code == 0, err
    model = _board_model()
    model["rapidListConfig"]["mappedColumns"][1]["mappedStatuses"].append({"id": "31", "name": "NEW"})
    state["model"] = model
    code, _, err2, _ = run(["apply", str(request_path(out)), "--confirm", confirm_of(out)],
                           _columns_routes(state) + [tenant_route()])
    assert code != 0 and "put" not in state, err2


def _board_routes(state):
    def route(req):
        u, m = urllib.parse.urlsplit(req.full_url).path, req.get_method()
        if m == "GET" and u.endswith("/rest/agile/1.0/board/55"):
            if state.get("deleted") and state.get("rb500"):
                return urllib.error.HTTPError(req.full_url, 500, "boom", http.client.HTTPMessage(), io.BytesIO(b"{}"))
            if state.get("deleted"):
                return urllib.error.HTTPError(req.full_url, 404, "nf", http.client.HTTPMessage(), io.BytesIO(b"{}"))
            return json.dumps({"id": 55, "name": "Old board", "type": "kanban", "location": {"projectKey": "APPR"}})
        if m == "DELETE" and u.endswith("/rest/agile/1.0/board/55"):
            state["deleted"] = True
            return ""
        if u.endswith("/rest/agile/1.0/board/55/properties/cml"):
            if m == "GET":
                if "prop" not in state:
                    return urllib.error.HTTPError(req.full_url, 404, "nf", http.client.HTTPMessage(), io.BytesIO(b"{}"))
                return json.dumps({"key": "cml", "value": state["prop"]})
            if m == "PUT":
                state["prop"] = json.loads(req.data.decode())
                return ""
        raise AssertionError(f"unexpected {m} {u}")
    return [(JIRA, route)]


def test_board_delete_plan_names_the_board_and_apply_verifies_by_a_404():
    state = {}
    code, out, err, _ = run(["plan", "board-delete", "--board", "55"], _board_routes(state) + [tenant_route()])
    assert code == 0, err
    assert "IRREVERSIBLE" in out and "'Old board'" in out and "deleted" not in state
    code, _, err2, _ = run(["apply", str(request_path(out)), "--confirm", confirm_of(out)],
                           _board_routes(state) + [tenant_route()])
    assert code == 0, err2
    assert state["deleted"] is True


def test_board_delete_refuses_a_non_numeric_board_before_any_request():
    code, _, _, op = run(["plan", "board-delete", "--board", "x"], [tenant_route()])
    assert code == 1 and op.calls == []


def test_board_property_set_shows_old_and_new_and_verifies_by_read_back():
    state = {}
    argv = ["plan", "board-property-set", "--board", "55", "--key", "cml", "--value", '{"a": 1}']
    code, out, err, _ = run(argv, _board_routes(state) + [tenant_route()])
    assert code == 0, err
    assert "not set yet" in out and "prop" not in state
    code, _, err2, _ = run(["apply", str(request_path(out)), "--confirm", confirm_of(out)],
                           _board_routes(state) + [tenant_route()])
    assert code == 0, err2
    assert state["prop"] == {"a": 1}


def test_board_property_set_refuses_a_bad_key_or_value_before_any_request():
    for argv in (["--board", "55", "--key", "..", "--value", "1"], ["--board", "55", "--key", "a/b", "--value", "1"], ["--board", "55", "--key", "k", "--value", "{bad"],
                 ["--board", "55", "--value", "1"]):
        code, _, _, op = run(["plan", "board-property-set", *argv], [tenant_route()])
        assert code == 1 and op.calls == [], argv


def test_board_delete_reports_sent_but_unverified_when_the_read_back_errors():
    state = {"rb500": True}
    code, out, err, _ = run(["plan", "board-delete", "--board", "55"], _board_routes(state) + [tenant_route()])
    assert code == 0, err
    code, _, err2, _ = run(["apply", str(request_path(out)), "--confirm", confirm_of(out)],
                           _board_routes(state) + [tenant_route()])
    assert code == 3 and "read-back" in err2 and state["deleted"] is True, err2


# --- jira-call (0.3.0): spec-driven writes through the same plan/apply gate -------

def _component_routes(state):
    def route(req):
        u, m = urllib.parse.urlsplit(req.full_url).path, req.get_method()
        if m == "POST" and u.endswith("/rest/api/3/component"):
            state["c"] = dict(json.loads(req.data.decode()), id="11", self=f"{JIRA}/rest/api/3/component/11")
            return json.dumps(state["c"])
        if m == "DELETE" and u.endswith("/rest/api/3/component/11"):
            state["deleted"] = req.full_url
            return ""
        if m == "GET" and u.endswith("/rest/api/3/component/11"):
            if state.get("deleted") or "c" not in state:
                return urllib.error.HTTPError(req.full_url, 404, "nf", http.client.HTTPMessage(), io.BytesIO(b"{}"))
            return json.dumps(state["c"])
        raise AssertionError(f"unexpected {m} {u}")
    return [(JIRA, route)]


def test_jira_call_create_applies_once_and_verifies_through_the_self_link():
    state = {}
    code, out, err, op = run(["plan", "jira-call", "--op", "createComponent", "--body", '{"name": "api", "project": "APPR"}'],
                             _component_routes(state) + [tenant_route()])
    assert code == 0, err
    assert "c" not in state, "plan must not write"
    path, conf = request_path(out), confirm_of(out)
    code, out2, err2, _ = run(["apply", str(path), "--confirm", conf], _component_routes(state) + [tenant_route()])
    assert code == 0 and "verified by read-back" in out2, err2
    assert state["c"]["name"] == "api" and not path.exists()


def test_jira_call_says_so_when_the_read_back_only_proved_existence():
    state = {}
    body = '{"name": "api", "project": "APPR", "assignee": {"accountId": "x"}}'
    code, out, err, _ = run(["plan", "jira-call", "--op", "createComponent", "--body", body], _component_routes(state) + [tenant_route()])
    assert code == 0, err
    code, out2, err2, _ = run(["apply", str(request_path(out)), "--confirm", confirm_of(out)], _component_routes(state) + [tenant_route()])
    assert code == 0, err2
    assert "compared the simple fields only" in out2 and "verified by read-back" not in out2
    assert "check them in Jira" in out2


def test_confluence_call_names_confluence_not_jira_when_the_read_back_is_partial():
    state = {}

    def route(req):
        u, m = urllib.parse.urlsplit(req.full_url).path, req.get_method()
        if m == "POST" and u.endswith("/wiki/api/v2/folders"):
            state["f"] = dict(json.loads(req.data.decode()), id="77")
            return json.dumps(state["f"])
        if m == "GET" and u.endswith("/wiki/api/v2/folders/77"):
            return json.dumps(state["f"])
        raise AssertionError(f"unexpected {m} {u}")
    body = '{"spaceId": "1", "title": "t", "extra": {"nested": true}}'
    code, out, err, _ = run(["plan", "confluence-call", "--op", "createFolder", "--body", body], [(CONF, route), tenant_route()])
    assert code == 0, err
    code, out2, err2, _ = run(["apply", str(request_path(out)), "--confirm", confirm_of(out)], [(CONF, route), tenant_route()])
    assert code == 0, err2
    assert "check them in Confluence" in out2 and "Jira" not in out2


def test_confluence_call_names_confluence_not_jira_when_the_read_back_only_finds_the_item():
    def route(req):
        u, m = urllib.parse.urlsplit(req.full_url).path, req.get_method()
        if m == "POST" and u.endswith("/wiki/api/v2/folders"):
            return json.dumps({"id": "77"})
        if m == "GET" and u.endswith("/wiki/api/v2/folders/77"):
            return json.dumps({"id": "77"})
        raise AssertionError(f"unexpected {m} {u}")
    code, out, err, _ = run(["plan", "confluence-call", "--op", "createFolder", "--body", '{"spaceId": "1", "title": "t"}'], [(CONF, route), tenant_route()])
    assert code == 0, err
    code, out2, err2, _ = run(["apply", str(request_path(out)), "--confirm", confirm_of(out)], [(CONF, route), tenant_route()])
    assert code == 0, err2
    assert "only confirmed the item exists" in out2 and "check them in Confluence" in out2 and "Jira" not in out2


def test_jira_call_delete_needs_the_gate_flag_then_deletes_and_verifies_by_404():
    state = {"c": {"id": "11", "name": "api"}}
    code, _, err, op = run(["plan", "jira-call", "--op", "deleteComponent", "--path", "id=11"],
                           _component_routes(state) + [tenant_route()])
    assert code == 1 and "--allow-destructive yes" in err
    code, out, err, _ = run(["plan", "jira-call", "--op", "deleteComponent", "--path", "id=11", "--allow-destructive", "yes"],
                            _component_routes(state) + [tenant_route()])
    assert code == 0 and "IRREVERSIBLE" in out, err
    assert "deleted" not in state, "plan must not delete"
    path, conf = request_path(out), confirm_of(out)
    code, _, err2, _ = run(["apply", str(path), "--confirm", conf], _component_routes(state) + [tenant_route()])
    assert code == 0, err2
    assert state["deleted"].endswith("/rest/api/3/component/11")


def test_jira_call_apply_refuses_when_the_target_changed_after_the_plan():
    state = {"c": {"id": "11", "name": "api"}}
    code, out, err, _ = run(["plan", "jira-call", "--op", "deleteComponent", "--path", "id=11", "--allow-destructive", "yes"],
                            _component_routes(state) + [tenant_route()])
    assert code == 0, err
    state["c"]["name"] = "renamed"
    code, _, err2, _ = run(["apply", str(request_path(out)), "--confirm", confirm_of(out)],
                           _component_routes(state) + [tenant_route()])
    assert code != 0 and "live state changed" in err2
    assert "deleted" not in state


# --- confluence-call / confluence-v1-call (0.4.0): Confluence v2 and v1 through the same gate -----

import base64  # noqa: E402

CONFV1 = f"https://api.atlassian.com/ex/confluence/{CID}/wiki/rest/api"
V1TOKEN = "V1-SECRET-QQ"
ENV_V1 = ENV_OK + f"ACLI_REST_WRITE_CONFLUENCE_V1_TOKEN={V1TOKEN}\n"


def _basic_token(req):
    return base64.b64decode(req.get_header("Authorization").split(" ", 1)[1]).decode().split(":", 1)[1]


def test_confluence_call_v2_create_goes_to_the_v2_base_with_the_v2_token_and_verifies_by_id():
    state = {}

    def route(req):
        u, m = urllib.parse.urlsplit(req.full_url).path, req.get_method()
        if m == "POST" and u.endswith("/wiki/api/v2/folders"):
            state["f"] = dict(json.loads(req.data.decode()), id="77")
            return json.dumps(state["f"])
        if m == "GET" and u.endswith("/wiki/api/v2/folders/77"):
            return json.dumps(state["f"])
        raise AssertionError(f"unexpected {m} {u}")
    body = '{"spaceId": "1", "title": "t"}'
    code, out, err, _ = run(["plan", "confluence-call", "--op", "createFolder", "--body", body], [(CONF, route), tenant_route()])
    assert code == 0, err
    assert "f" not in state, "plan must not write"
    code, out2, err2, op = run(["apply", str(request_path(out)), "--confirm", confirm_of(out)], [(CONF, route), tenant_route()])
    assert code == 0 and "verified by read-back" in out2, err2
    assert state["f"]["title"] == "t"
    assert {_basic_token(r) for r in op.calls if "/wiki/" in r.full_url} == {"CONF-SECRET-QQ"}


def test_confluence_v1_call_uses_the_v1_base_and_the_v1_token_for_reads_and_sends():
    state = {}

    def route(req):
        u, m = urllib.parse.urlsplit(req.full_url).path, req.get_method()
        if m == "POST" and u.endswith("/wiki/rest/api/space"):
            state["s"] = dict(json.loads(req.data.decode()), _links={"self": f"https://{HOST}/wiki/rest/api/space/X"})
            return json.dumps(state["s"])
        if m == "GET" and u.endswith("/wiki/rest/api/space/X"):
            return json.dumps(state["s"])
        raise AssertionError(f"unexpected {m} {u}")
    body = '{"key": "X", "name": "n"}'
    code, out, err, _ = run(["plan", "confluence-v1-call", "--op", "createSpace", "--body", body], [(CONFV1, route), tenant_route()], env=ENV_V1)
    assert code == 0, err
    code, out2, err2, op = run(["apply", str(request_path(out)), "--confirm", confirm_of(out)], [(CONFV1, route), tenant_route()], env=ENV_V1)
    assert code == 0 and "verified by read-back" in out2, err2
    wiki = [r for r in op.calls if "/wiki/" in r.full_url]
    assert wiki and {_basic_token(r) for r in wiki} == {V1TOKEN}, "every v1 call must carry the v1 token only"
    assert all("/wiki/rest/api/" in r.full_url for r in wiki)


def test_confluence_v1_call_without_its_token_refuses_before_any_confluence_request():
    code, _, err, op = run(["plan", "confluence-v1-call", "--op", "createSpace", "--body", '{"key": "X", "name": "n"}'],
                           [tenant_route()])
    assert code == 1 and "ACLI_REST_WRITE_CONFLUENCE_V1_TOKEN" in err
    assert all("/wiki/" not in r.full_url for r in op.calls)


def test_confluence_v1_call_that_cannot_be_read_back_ends_sent_but_unverified():
    state = {}

    def route(req):
        u, m = urllib.parse.urlsplit(req.full_url).path, req.get_method()
        if m == "POST" and u.endswith("/wiki/rest/api/content/5/label"):
            state["sent"] = True
            return json.dumps([{"name": "x"}])
        raise AssertionError(f"unexpected {m} {u}")
    code, out, err, _ = run(["plan", "confluence-v1-call", "--op", "addLabelsToContent", "--path", "id=5", "--body", '[{"prefix": "global", "name": "x"}]'],
                            [(CONFV1, route), tenant_route()], env=ENV_V1)
    assert code == 0, err
    code, out2, err2, _ = run(["apply", str(request_path(out)), "--confirm", confirm_of(out)], [(CONFV1, route), tenant_route()], env=ENV_V1)
    assert state["sent"] and code == 3 and "UNVERIFIED" in err2.upper(), (code, err2)


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
