#!/usr/bin/env python3
"""Build skills/ops/data/jira-v3-index.json from Atlassian's Jira Cloud v3 OpenAPI spec.

usage: gen_jira_index.py (--fetch | --spec FILE) [--out FILE] [--check]

The index is the only thing the jira-call engine trusts: operation id, method, path template, params, the top-level
required body fields, flags and a safety tier. --check rebuilds in memory and exits 1 when it differs from the file on
disk (a refresh is a reviewable diff). Descriptions and examples are dropped on purpose so the file stays small."""

import json
import pathlib
import sys
import urllib.request

SPEC_URL = "https://dac-static.atlassian.com/cloud/jira/platform/swagger-v3.v3.json"
DEFAULT_OUT = pathlib.Path(__file__).resolve().parent.parent / "data" / "jira-v3-index.json"
SCHEMA_VERSION = 1
METHODS = ("get", "post", "put", "patch", "delete")

# Tiers: read = GET; write = other methods; destructive = needs --allow-destructive on top of plan+confirm.
DESTRUCTIVE_TAGS = frozenset({
    "Workflows", "Workflow schemes", "Workflow scheme drafts", "Issue security schemes", "Permission schemes",
    "Issue type schemes", "Issue type screen schemes", "Field schemes", "Issue field configurations",
    "Issue notification schemes", "Priority schemes", "Project role actors", "Groups", "Issue bulk operations",
    "Issue custom field contexts",
})
DESTRUCTIVE_PATH_PARTS = ("/bulk", "/permissionscheme")


def tier_of(method, path, tag):
    if method == "get":
        return "read"
    if method == "delete" or tag in DESTRUCTIVE_TAGS or any(p in path for p in DESTRUCTIVE_PATH_PARTS):
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


def build(spec):
    ops = {}
    for path, item in spec["paths"].items():
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
            rb = _resolve(spec, op.get("requestBody", {})) if op.get("requestBody") else None
            if rb:
                content = rb.get("content", {})
                kinds = sorted(content)
                json_c = content.get("application/json")
                body = {"required": bool(rb.get("required")),
                        "multipart": any(k.startswith("multipart/") for k in kinds),
                        "fields": _required(spec, json_c.get("schema", {})) if json_c else []}
            oid = op.get("operationId") or f"{method}:{path}"
            ops[oid] = {"method": method.upper(), "path": path, "tag": tag, "tier": tier_of(method, path, tag),
                        "params": params, **({"body": body} if body else {}),
                        **({"experimental": True} if op.get("x-experimental") else {}),
                        **({"deprecated": True} if op.get("deprecated") else {})}
    return {"schema": SCHEMA_VERSION, "source": SPEC_URL, "version": spec.get("info", {}).get("version", ""),
            "ops": dict(sorted(ops.items()))}


def dump(index):
    return json.dumps(index, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"


def main(argv):
    args, i, opts = list(argv), 0, {}
    while i < len(args):
        a = args[i]
        if a in ("--fetch", "--check"):
            opts[a] = True
            i += 1
        elif a in ("--spec", "--out") and i + 1 < len(args):
            opts[a] = args[i + 1]
            i += 2
        else:
            print(__doc__, file=sys.stderr)
            return 2
    if bool(opts.get("--fetch")) == bool(opts.get("--spec")):
        print("FATAL: give exactly one of --fetch or --spec FILE", file=sys.stderr)
        return 2
    if opts.get("--fetch"):
        with urllib.request.urlopen(SPEC_URL, timeout=120) as r:  # nosec: fixed https URL
            spec = json.load(r)
    else:
        spec = json.loads(pathlib.Path(opts["--spec"]).read_text())
    index = build(spec)
    out = pathlib.Path(opts.get("--out", DEFAULT_OUT))
    text = dump(index)
    if opts.get("--check"):
        same = out.exists() and out.read_text() == text
        print("index is current" if same else f"FATAL: {out} differs from the spec", file=sys.stderr if not same else sys.stdout)
        return 0 if same else 1
    old = json.loads(out.read_text())["ops"] if out.exists() else {}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    new = index["ops"]
    changed = sum(1 for k in new if k in old and new[k] != old[k])
    print(f"{out}: {len(new)} operations ({len(set(new) - set(old))} added, {len(set(old) - set(new))} removed, "
          f"{changed} changed), {len(text)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
