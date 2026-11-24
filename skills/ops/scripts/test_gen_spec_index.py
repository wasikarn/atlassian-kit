#!/usr/bin/env python3
"""Self-check for gen_spec_index.py: index building from tiny specs and every command-line path.
No network, no framework: python3 test_gen_spec_index.py"""
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gen_spec_index as gen  # noqa: E402

FAILS = []


def check(name, cond):
    if not cond:
        FAILS.append(name)
        print(f"FAIL: {name}")


JIRA, V2, V1 = gen.SPECS["jira"], gen.SPECS["confluence-v2"], gen.SPECS["confluence-v1"]
TINY = {"info": {"version": "7"}, "paths": {
    "/a/{id}": {
        "parameters": [{"$ref": "#/components/parameters/id"}],
        "get": {"operationId": "getA", "tags": ["T"]},
        "put": {"operationId": "putA", "tags": ["T"], "parameters": [
            {"name": "mode", "in": "query", "schema": {"type": "string", "enum": ["a", "b"]}},
            {"name": "X-Hdr", "in": "header", "schema": {"type": "string"}},
            {"name": "bare", "in": "query"}],
            "requestBody": {"$ref": "#/components/requestBodies/RB"}},
        "delete": {"tags": ["T"]}},
    "/wf": {"post": {"operationId": "mkWf", "tags": ["Workflows"]}},
    "/x/bulk": {"post": {"operationId": "bulkX", "tags": ["T"], "deprecated": True, "x-experimental": True}},
    "/up": {"post": {"operationId": "upload", "requestBody": {"content": {"multipart/form-data": {}}}}},
    "/odd": {"post": {"operationId": "odd", "tags": ["T"], "requestBody": {"content": {
        "application/json": {"schema": {"$ref": "#/components/schemas/Loop"}}}}}},
    "/deep": {"post": {"operationId": "deep", "tags": ["T"], "requestBody": {"content": {
        "application/json": {"schema": {"$ref": "#/components/schemas/D0"}}}}}}},
    "components": {
        "parameters": {"id": {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}},
        "requestBodies": {"RB": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/T"}}}}},
        "schemas": {"T": {"allOf": [{"required": ["a"]}, {"required": ["b"]}]},
                    "Loop": {"$ref": "#/components/schemas/Loop"},
                    **{f"D{i}": {"allOf": [{"$ref": f"#/components/schemas/D{i + 1}"}], "required": [f"f{i}"]} for i in range(8)},
                    "D8": {"required": ["f8"]}}}}

built = gen.build(TINY)["ops"]
check("build: ids, methods and relative paths", built["getA"]["method"] == "GET" and built["putA"]["path"] == "/a/{id}")
check("build: shared $ref parameter resolved", built["getA"]["params"] == [{"name": "id", "in": "path", "required": True, "type": "string"}])
check("build: query enum kept, header parameter dropped, schema-less parameter typed string",
      [(p["name"], p.get("enum"), p["type"]) for p in built["putA"]["params"] if p["name"] != "id"] == [("mode", ["a", "b"], "string"), ("bare", None, "string")])
check("build: $ref request body with allOf required fields merged", built["putA"]["body"] == {"required": True, "multipart": False, "fields": ["a", "b"]})
check("build: missing operationId falls back to method:path", "delete:/a/{id}" in built)
check("build: tiers", (built["getA"]["tier"], built["putA"]["tier"], built["delete:/a/{id}"]["tier"], built["mkWf"]["tier"], built["bulkX"]["tier"])
      == ("read", "write", "destructive", "destructive", "destructive"))
check("build: experimental and deprecated flags", built["bulkX"].get("experimental") and built["bulkX"].get("deprecated"))
check("build: multipart detected and no json fields", built["upload"]["body"] == {"required": False, "multipart": True, "fields": []})
check("build: a $ref cycle ends instead of hanging, with no fields", built["odd"]["body"]["fields"] == [])
check("build: required-field recursion stops after 5 levels", built["deep"]["body"]["fields"] == ["f0", "f1", "f2", "f3", "f4", "f5"])
check("build: version is copied", gen.build(TINY)["version"] == "7")
check("build: a spec without info has an empty version", gen.build({"paths": {}})["version"] == "")

spec_v1 = {"paths": {"/wiki/rest/api/content": {"post": {"operationId": "c", "tags": ["Group"]}},
                     "/wiki/rest/atlassian-connect/x": {"get": {"operationId": "skipme"}}}}
b1 = gen.build(spec_v1, V1)["ops"]
check("v1: prefix stripped, other API families skipped", list(b1) == ["c"] and b1["c"]["path"] == "/content")
check("v1: admin tag is destructive", b1["c"]["tier"] == "destructive")
check("v2: no admin tag means write", gen.build({"paths": {"/p": {"post": {"operationId": "p", "tags": ["Page"]}}}}, V2)["ops"]["p"]["tier"] == "write")
check("v2: admin tag is destructive", gen.build({"paths": {"/p": {"post": {"operationId": "p", "tags": ["Redactions"]}}}}, V2)["ops"]["p"]["tier"] == "destructive")
check("tier: path part marks jira bulk as destructive", gen.tier_of("post", "/rest/api/3/issue/bulk", "Issues", JIRA) == "destructive")
try:
    gen.build({"paths": {"/a": {"get": {"operationId": "same"}}, "/b": {"get": {"operationId": "same"}}}})
    check("build: a duplicate operation id is refused", False)
except ValueError as e:
    check("build: a duplicate operation id is refused", "same" in str(e))
check("dump: stable, compact, newline-terminated", gen.dump({"b": 1, "a": [1]}) == '{"a":[1],"b":1}\n')

# --- command line -----------------------------------------------------------------------------------------------


def cli(argv, fetch=None):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = gen.main(argv, fetch=fetch)
    return code, out.getvalue(), err.getvalue()


SEEN = []


def fake_fetch(spec):
    @contextlib.contextmanager
    def fetch(url, timeout):
        SEEN.append((url, timeout))
        yield io.BytesIO(json.dumps(spec).encode())
    return fetch


with tempfile.TemporaryDirectory() as d:
    sp, out = Path(d, "spec.json"), Path(d, "idx.json")
    sp.write_text(json.dumps(TINY))
    code, so, _ = cli(["jira", "--file", str(sp), "--out", str(out)])
    check("main: writes a new index and reports the counts", code == 0 and "8 operations" in so and "8 added" in so and out.exists())
    code, so, _ = cli(["jira", "--file", str(sp), "--out", str(out)])
    check("main: a second run reports nothing changed", code == 0 and "0 added, 0 removed, 0 changed" in so)
    changed = json.loads(sp.read_text())
    del changed["paths"]["/wf"]
    changed["paths"]["/a/{id}"]["get"]["tags"] = ["Other"]
    sp.write_text(json.dumps(changed))
    code, so, _ = cli(["jira", "--file", str(sp), "--out", str(out)])
    check("main: removed and changed operations are counted", code == 0 and "1 removed" in so and "1 changed" in so)
    code, so, _ = cli(["jira", "--file", str(sp), "--out", str(out), "--check"])
    check("main: --check on a current index passes", code == 0 and "index is current" in so)
    sp.write_text(json.dumps(TINY))
    code, _, se = cli(["jira", "--file", str(sp), "--out", str(out), "--check"])
    check("main: --check on a stale index fails and names the file", code == 1 and "differs from the spec" in se and "idx.json" in se)
    code, _, se = cli(["jira", "--file", str(sp), "--out", str(Path(d, "missing.json")), "--check"])
    check("main: --check with no file fails", code == 1)
    fetched = Path(d, "fetched.json")
    code, so, _ = cli(["confluence-v1", "--out", str(fetched)], fetch=fake_fetch(spec_v1))
    check("main: no --file fetches the spec from its published URL", code == 0 and SEEN == [(V1.url, 120)] and fetched.exists())
    nested = Path(d, "deep", "dir", "idx.json")
    code, _, _ = cli(["confluence-v2", "--file", str(sp), "--out", str(nested)])
    check("main: the output directory is created", code == 0 and nested.exists())

for label, argv in (("no arguments", []), ("unknown flag", ["jira", "--bogus"]), ("unknown spec", ["nope"]),
                    ("flag without a value", ["jira", "--out"]), ("two spec names", ["jira", "confluence-v2"]),
                    ("flags only", ["--check"])):
    code, _, se = cli(argv)
    check(f"main: {label} prints usage and exits 2", code == 2 and "usage:" in se)

if FAILS:
    print(f"{len(FAILS)} check(s) failed")
    sys.exit(1)
print("ok")
