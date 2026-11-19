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
def fake_validate(args):
    if set(args) != {"key"} or not re.match(r"^[A-Z]+-[0-9]+$", str(args["key"])):
        raise rw.Fatal("fake-set takes exactly --key ISSUE")
    return args


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
    data["operation"] = "page-delete"
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


def test_only_page_create_is_registered():
    assert sorted(rw.OPERATIONS) == ["page-create"], sorted(rw.OPERATIONS)
    for name, op in rw.OPERATIONS.items():
        assert set(op) >= {"product", "validate", "plan", "send", "readback"}, (name, sorted(op))


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
    assert code == 1 and "spaces named DEMO" in err and "not proof" in err or "DEMO" in err
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
