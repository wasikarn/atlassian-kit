#!/usr/bin/env python3
"""Build a pinned operation index under skills/ops/data from one of Atlassian's OpenAPI specs.

usage: gen_spec_index.py (jira | confluence-v2 | confluence-v1) [--file SPEC.json] [--out FILE] [--check]

Without --file the spec is fetched from Atlassian. The index is the only thing the spec-driven operations
(rest_ops_spec.py) trust: operation id, method, path template, params, the top-level required body fields, flags and a
safety tier. --check rebuilds in memory and exits 1 when the file on disk differs (a refresh is a reviewable diff).
Descriptions and examples are dropped on purpose so the files stay small."""

import json
import pathlib
import sys
import urllib.request
from types import SimpleNamespace

DATA = pathlib.Path(__file__).resolve().parent.parent / "data"
SCHEMA_VERSION = 1
METHODS = ("get", "post", "put", "patch", "delete")
CONFLUENCE = "https://dac-static.atlassian.com/cloud/confluence/"

# Tiers: read = GET; write = other methods; destructive = needs --allow-destructive on top of plan + confirm.
# prefix: v1 paths start with /wiki/rest/api; the index keeps them relative to that base (the engine adds it back).
SPECS = {
    "jira": SimpleNamespace(
        url="https://dac-static.atlassian.com/cloud/jira/platform/swagger-v3.v3.json", out="jira-v3-index.json", prefix="",
        tags=frozenset({
            "Workflows", "Workflow schemes", "Workflow scheme drafts", "Issue security schemes", "Permission schemes",
            "Issue type schemes", "Issue type screen schemes", "Field schemes", "Issue field configurations",
            "Issue notification schemes", "Priority schemes", "Project role actors", "Groups", "Issue bulk operations",
            "Issue custom field contexts"}),
        path_parts=("/bulk", "/permissionscheme")),
    "confluence-v2": SimpleNamespace(
        url=CONFLUENCE + "openapi-v2.v3.json", out="confluence-v2-index.json", prefix="",
        tags=frozenset({"Content Permissions", "Classification Level", "Space Roles", "Space Permission Transition",
                        "Admin Key", "Redactions", "App Properties"}),
        path_parts=()),
    "confluence-v1": SimpleNamespace(
        url=CONFLUENCE + "swagger.v3.json", out="confluence-v1-index.json", prefix="/wiki/rest/api",
        tags=frozenset({"Content restrictions", "Space permissions", "Group", "Settings", "Themes", "Audit",
                        "Dynamic modules", "Space settings", "User properties"}),
        path_parts=()),
}


def tier_of(method, path, tag, cfg):
    if method == "get":
        return "read"
    if method == "delete" or tag in cfg.tags or any(p in path for p in cfg.path_parts):
        return "destructive"
    return "write"


def _resolve(spec, node):
    seen = 0
    while isinstance(node, dict) and "$ref" in node and seen < 20:
        cur = spec
        for part in node["$ref"].lstrip("#/").split("/"):
            cur = cur[part]
        node, seen = cur, seen + 1
    return node


def _required(spec, schema, depth=0):
    """Top-level required property names of a body schema, following $ref and allOf."""
    schema = _resolve(spec, schema)
    if not isinstance(schema, dict) or depth > 5:
        return []
    req = list(schema.get("required", []))
    for sub in schema.get("allOf", []):
        req += _required(spec, sub, depth + 1)
    return sorted(set(req))


def build(spec, cfg=SPECS["jira"]):
    ops = {}
    for path, item in spec["paths"].items():
        if cfg.prefix and not path.startswith(cfg.prefix + "/"):
            continue  # v1 also lists a few /wiki/rest/atlassian-connect paths; they are not this API
        rel = path[len(cfg.prefix):]
        shared = item.get("parameters", [])
        for method in METHODS:
            op = item.get(method)
            if not op:
                continue
            tag = (op.get("tags") or ["Other"])[0]
            params = []
            for p in shared + op.get("parameters", []):
                p = _resolve(spec, p)
                if p.get("in") not in ("path", "query"):
                    continue
                sch = _resolve(spec, p.get("schema", {}))
                entry = {"name": p["name"], "in": p["in"], "required": bool(p.get("required")),
                         "type": sch.get("type", "string") if isinstance(sch, dict) else "string"}
                if isinstance(sch, dict) and sch.get("enum"):
                    entry["enum"] = sch["enum"]
                params.append(entry)
            body = None
            rb = _resolve(spec, op["requestBody"]) if op.get("requestBody") else None
            if rb:
                content = rb.get("content", {})
                json_c = content.get("application/json")
                body = {"required": bool(rb.get("required")),
                        "multipart": any(k.startswith("multipart/") for k in content),
                        "fields": _required(spec, json_c.get("schema", {})) if json_c else []}
            oid = op.get("operationId") or f"{method}:{rel}"
            if oid in ops:
                raise ValueError(f"duplicate operation id {oid!r} ({method.upper()} {rel})")
            ops[oid] = {"method": method.upper(), "path": rel, "tag": tag, "tier": tier_of(method, rel, tag, cfg),
                        "params": params, **({"body": body} if body else {}),
                        **({"experimental": True} if op.get("x-experimental") else {}),
                        **({"deprecated": True} if op.get("deprecated") else {})}
    return {"schema": SCHEMA_VERSION, "source": cfg.url, "version": spec.get("info", {}).get("version", ""),
            "ops": dict(sorted(ops.items()))}


def dump(index):
    return json.dumps(index, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"


def main(argv, fetch=None):
    args, opts, name = list(argv), {}, None
    while args:
        a = args.pop(0)
        if a == "--check":
            opts[a] = True
        elif a in ("--file", "--out") and args:
            opts[a] = args.pop(0)
        elif a in SPECS and name is None:
            name = a
        else:
            print(__doc__, file=sys.stderr)
            return 2
    if name is None:
        print(__doc__, file=sys.stderr)
        return 2
    cfg = SPECS[name]
    if "--file" in opts:
        spec = json.loads(pathlib.Path(opts["--file"]).read_text())
    else:
        with (fetch or urllib.request.urlopen)(cfg.url, timeout=120) as r:  # fixed https URL from SPECS
            spec = json.load(r)
    index = build(spec, cfg)
    out = pathlib.Path(opts.get("--out", DATA / cfg.out))
    text = dump(index)
    if "--check" in opts:
        if out.exists() and out.read_text() == text:
            print("index is current")
            return 0
        print(f"FATAL: {out} differs from the spec", file=sys.stderr)
        return 1
    old = json.loads(out.read_text())["ops"] if out.exists() else {}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    new = index["ops"]
    changed = sum(1 for k in new if k in old and new[k] != old[k])
    print(f"{out}: {len(new)} operations ({len(set(new) - set(old))} added, {len(set(old) - set(new))} removed, "
          f"{changed} changed), {len(text)} bytes")
    return 0


if __name__ == "__main__":  # pragma: no cover  (the process entry point)
    sys.exit(main(sys.argv[1:]))
