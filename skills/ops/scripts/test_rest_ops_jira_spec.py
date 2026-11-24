#!/usr/bin/env python3
"""Self-check for rest_ops_jira_spec.py (jira-call) and gen_jira_index.py. No network, no framework:
python3 test_rest_ops_jira_spec.py"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gen_jira_index as gen  # noqa: E402
import rest_ops_jira_spec as spec  # noqa: E402
from acli_rest_common import Fatal, HttpError  # noqa: E402
from rest_write_base import OPERATIONS, canonical  # noqa: E402

FAILS = []


def check(name, cond):
    if not cond:
        FAILS.append(name)
        print(f"FAIL: {name}")


def refuses(name, flags, needle):
    try:
        spec._validate(flags)
    except Fatal as e:
        check(name, needle in str(e))
        return
    check(name + " (should have refused)", False)


# --- the pinned index ------------------------------------------------------------------------------------------
idx = spec.load_index()["ops"]
check("index has 630 operations", len(idx) == 630)
tiers = {t: sum(1 for o in idx.values() if o["tier"] == t) for t in ("read", "write", "destructive")}
check("tiers cover every operation", sum(tiers.values()) == len(idx))
check("every GET is read and nothing else is", all((o["method"] == "GET") == (o["tier"] == "read") for o in idx.values()))
check("every DELETE is destructive", all(o["tier"] == "destructive" for o in idx.values() if o["method"] == "DELETE"))
check("no PATCH in the index (http_request cannot send it)", all(o["method"] != "PATCH" for o in idx.values()))
check("jira-call is registered", "jira-call" in OPERATIONS and OPERATIONS["jira-call"]["product"] == "jira")

# --- generator on a tiny spec ---------------------------------------------------------------------------------
tiny = {"info": {"version": "9"}, "paths": {
    "/rest/api/3/thing/{id}": {
        "parameters": [{"$ref": "#/components/parameters/id"}],
        "get": {"operationId": "getThing", "tags": ["Things"]},
        "put": {"operationId": "putThing", "tags": ["Things"], "requestBody": {"required": True, "content": {
            "application/json": {"schema": {"$ref": "#/components/schemas/T"}}}}},
        "delete": {"operationId": "delThing", "tags": ["Things"], "x-experimental": True}},
    "/rest/api/3/workflow": {"post": {"operationId": "mkWorkflow", "tags": ["Workflows"]}},
    "/rest/api/3/issue/bulk": {"post": {"operationId": "bulkThing", "tags": ["Issues"], "deprecated": True}}},
    "components": {"parameters": {"id": {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}},
                   "schemas": {"T": {"allOf": [{"required": ["a"]}, {"required": ["b"], "type": "object"}]}}}}
built = gen.build(tiny)["ops"]
check("gen: shared $ref param resolved", built["putThing"]["params"][0]["name"] == "id")
check("gen: allOf required fields merged", built["putThing"]["body"]["fields"] == ["a", "b"])
check("gen: tiers", (built["getThing"]["tier"], built["putThing"]["tier"], built["delThing"]["tier"],
                     built["mkWorkflow"]["tier"], built["bulkThing"]["tier"]) ==
      ("read", "write", "destructive", "destructive", "destructive"))
check("gen: flags", built["delThing"].get("experimental") and built["bulkThing"].get("deprecated"))

# --- validate ------------------------------------------------------------------------------------------------
ok = spec._validate({"op": "createComponent", "body": '{"name": "x", "project": "AB"}'})
check("validate: happy path stores a canonical body", ok == {"op": "createComponent",
                                                              "body": '{"name": "x", "project": "AB"}'})
check("validate: stored args re-validate to themselves", spec._validate(dict(ok)) == ok)
refuses("validate: no op", {}, "usage")
refuses("validate: unknown op", {"op": "nope"}, "unknown Jira operation")
refuses("validate: GET refused", {"op": "getComponent", "path": "id=1"}, "is a read")
refuses("validate: hand-written op redirected", {"op": "createVersion", "body": "{}"}, "version-create")
refuses("validate: multipart refused", {"op": "addAttachment", "path": "issueIdOrKey=A-1"}, "multipart")
refuses("validate: missing path param", {"op": "updateComponent", "body": "{}"}, "needs --path id")
refuses("validate: bad path characters", {"op": "updateComponent", "path": "id=1/../2", "body": "{}"}, "allowed characters")
refuses("validate: unknown path param", {"op": "updateComponent", "path": ["id=1", "x=2"], "body": "{}"}, "no path parameter 'x'")
refuses("validate: enum", {"op": "addWorklog", "path": "issueIdOrKey=A-1", "query": "adjustEstimate=bogus",
                           "body": "{}"}, "must be one of")
refuses("validate: body missing", {"op": "createComponent"}, "needs a body")
refuses("validate: body not JSON", {"op": "createComponent", "body": "{x"}, "not valid JSON")
refuses("validate: body scalar", {"op": "createComponent", "body": "5"}, "object or array")
refuses("validate: both body flags", {"op": "createComponent", "body": "{}", "body-file": "x"}, "not both")
refuses("validate: body on a bodyless op", {"op": "deleteComponent", "path": "id=1", "allow-destructive": "yes",
                                            "body": "{}"}, "takes no body")
refuses("validate: destructive gate", {"op": "deleteComponent", "path": "id=1"}, "--allow-destructive yes")
refuses("validate: gate value", {"op": "deleteComponent", "path": "id=1", "allow-destructive": "true"}, "value yes")
refuses("validate: experimental gate", {"op": "addGadget", "path": "dashboardId=1", "body": "{}"}, "--allow-experimental yes")
refuses("validate: deprecated gate", {"op": "setLocale", "body": "{}"}, "--allow-deprecated yes")
refuses("validate: unknown flag", {"op": "createComponent", "body": "{}", "force": "1"}, "unknown flag")
try:
    spec._validate({"op": "createComponent", "body": "{}"}, ["x"])
    check("validate: positional refused", False)
except Fatal as e:
    check("validate: positional refused", "no positional" in str(e))
allowed = spec._validate({"op": "deleteComponent", "path": "id=10", "query": "moveIssuesTo=11", "allow-destructive": "yes"})
check("validate: gated op accepted with its flag", allowed["allow-destructive"] == "yes" and allowed["path"] == ["id=10"])

# --- plan ---------------------------------------------------------------------------------------------------
calls = []


def get_ok(path, params):
    calls.append(path)
    return {"id": "10", "name": "old", "lead": {"x": 1}, "count": 3}


def get_404(path, params):
    raise HttpError(404, "api.atlassian.com", "not found")


base, body = spec._plan(get_ok, spec._validate({"op": "updateComponent", "path": "id=10", "body": '{"name": "new"}'}))
check("plan: GETs the sibling for the current state", calls == ["/rest/api/3/component/10"])
check("plan: base keeps scalar fields only", base["current"] == {"id": "10", "name": "old", "count": 3} and base["exists"])
check("plan: body passes through", body == {"name": "new"} and base["method"] == "PUT")
base404, _ = spec._plan(get_404, spec._validate({"op": "updateComponent", "path": "id=10", "body": "{}"}))
check("plan: a 404 sibling means exists false", base404["exists"] is False)
try:
    spec._plan(lambda p, q: (_ for _ in ()).throw(HttpError(500, "h", "boom")),
               spec._validate({"op": "updateComponent", "path": "id=10", "body": "{}"}))
    check("plan: a 500 propagates", False)
except HttpError:
    check("plan: a 500 propagates", True)
calls.clear()
bcreate, _ = spec._plan(get_ok, spec._validate({"op": "createComponent", "body": "{}"}))
check("plan: no sibling GET for a create", calls == [] and "exists" not in bcreate)
notes = spec._describe({"method": "DELETE", "path": "/p", "tier": "destructive", "exists": True}, None)
check("describe: delete says irreversible", any("IRREVERSIBLE" in n for n in notes))
check("describe: experimental noted", any("experimental" in n for n in
                                          spec._describe({"method": "POST", "path": "/p", "tier": "write",
                                                          "experimental": True}, {})))
check("canonical(None) round-trips for a bodyless request", json.loads(canonical(None)) is None)

# --- send ---------------------------------------------------------------------------------------------------
sent = []


def http(method, path, payload):
    sent.append((method, path, payload))
    return '{"id": "11", "self": "https://x.atlassian.net/rest/api/3/component/11", "name": "x"}'


dargs = spec._validate({"op": "deleteComponent", "path": "id=10", "query": "moveIssuesTo=11", "allow-destructive": "yes"})
dbase, dbody = spec._plan(get_ok, dargs)
spec._send(http, dargs, dbase, canonical(dbody))
check("send: DELETE with a query and no body", sent[-1] == ("DELETE", "/rest/api/3/component/10?moveIssuesTo=11", None))
cargs = spec._validate({"op": "createComponent", "body": '{"name": "x"}'})
cbase, cbody = spec._plan(get_ok, cargs)
spec._send(http, cargs, cbase, canonical(cbody))
check("send: POST body goes as bytes", sent[-1] == ("POST", "/rest/api/3/component", b'{"name": "x"}'))

# --- read-back ----------------------------------------------------------------------------------------------
check("readback: delete confirmed by 404", spec._readback(get_404, dargs, dbase, "null", {}) is True)
check("readback: delete still present", spec._readback(get_ok, dargs, dbase, "null", {}) is False)
uargs = spec._validate({"op": "updateComponent", "path": "id=10", "body": '{"name": "old"}'})
ubase, ubody = spec._plan(get_ok, uargs)
check("readback: PUT matches the sibling", spec._readback(get_ok, uargs, ubase, canonical(ubody), {}) is True)
check("readback: PUT mismatch", spec._readback(get_ok, uargs, ubase, '{"name": "other"}', {}) is False)
check("readback: POST follows self", spec._readback(lambda p, q: {"name": "x"}, cargs, cbase, '{"name": "x"}',
                                                    {"self": "https://x.atlassian.net/rest/api/3/component/11"}) is True)
check("readback: POST self with a different value", spec._readback(lambda p, q: {"name": "y"}, cargs, cbase,
                                                                   '{"name": "x"}', {"self": "/rest/api/3/component/11"}) is False)
for label, res in (("no self", {"id": "1"}), ("foreign self path", {"self": "https://x/other/11"})):
    try:
        spec._readback(get_ok, cargs, cbase, '{"name": "x"}', res)
        check(f"readback: {label} is unverified", False)
    except Fatal:
        check(f"readback: {label} is unverified", True)
check("readback: DELETE on a resource path has a GET sibling to check", spec._sibling_get(idx, idx["deleteComponent"]) is not None)
check("sibling: a POST collection path has none", spec._sibling_get(idx, idx["createComponent"]) is None)

check("compare: all simple fields equal is True", spec._compare({"a": 1}, {"a": 1, "b": 2}) is True)
check("compare: a mismatch is False", spec._compare({"a": 1}, {"a": 2}) is False)
check("compare: nested values skipped is partial", spec._compare({"a": 1, "n": {"x": 1}}, {"a": 1, "n": {"x": 2}}) == "partial")
check("compare: a field Jira does not echo is partial", spec._compare({"a": 1, "hidden": "s"}, {"a": 1}) == "partial")
check("compare: nothing comparable is exists-only", spec._compare({"n": {"x": 1}}, {"id": "1"}) == "exists")
check("compare: no body is exists-only", spec._compare(None, {"id": "1"}) == "exists")
check("readback: a create with a nested-only body is exists-only", spec._readback(
    lambda p, q: {"id": "11"}, cargs, cbase, '{"scheme": {"id": 1}}', {"self": "/rest/api/3/component/11"}) == "exists")

check("index was built by this generator schema", spec.load_index()["schema"] == gen.SCHEMA_VERSION)
for bad in (".", "..", "..."):
    refuses(f"validate: path value {bad!r} walks the URL", {"op": "updateComponent", "path": f"id={bad}", "body": "{}"}, "allowed characters")
check("validate: a dotted id is still fine", spec._validate({"op": "updateComponent", "path": "id=1.2", "body": "{}"})["path"] == ["id=1.2"])
check("tier: creating a screen is a plain write", idx["addScreenTab"]["tier"] == "write" if "addScreenTab" in idx else True)
check("tier: workflow changes stay destructive", all(o["tier"] == "destructive" for o in idx.values() if o["tag"] == "Workflows" and o["method"] != "GET"))
noget = sorted(k for k, o in idx.items() if o["method"] == "DELETE" and spec._sibling_get(idx, o) is None and k not in spec.HANDWRITTEN
                and not (o.get("body") or {}).get("required") and not o.get("experimental") and not o.get("deprecated"))
check("index has DELETE operations without a GET sibling to test with", bool(noget))
if noget:
    nop = idx[noget[0]]
    nflags = {"op": noget[0], "allow-destructive": "yes", "path": [f"{p['name']}={p['enum'][0] if p.get('enum') else 1}" for p in nop["params"] if p["in"] == "path" and p["required"]],
              "query": [f"{p['name']}=1" for p in nop["params"] if p["in"] == "query" and p["required"] and not p.get("enum")]}
    nflags = {k: v for k, v in nflags.items() if v}
    nargs = spec._validate(nflags)
    nbase, _ = spec._plan(get_ok, nargs)
    check("plan: a DELETE with no GET says apply cannot confirm it", nbase.get("no_readback") is True and any(
        "no read-back" in n for n in spec._describe(nbase, None)))

if FAILS:
    print(f"{len(FAILS)} check(s) failed")
    sys.exit(1)
print("ok")
