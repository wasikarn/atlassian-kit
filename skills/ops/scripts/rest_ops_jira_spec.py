"""jira-call: any Jira Cloud v3 write, driven by the pinned OpenAPI index (skills/ops/data/jira-v3-index.json).

plan jira-call --op <operationId> [--path name=value ...] [--query name=value ...] [--body '<JSON>' | --body-file FILE]
               [--allow-destructive yes] [--allow-experimental yes] [--allow-deprecated yes]

The index decides what is valid: unknown operation ids, GET operations (reads go through acli-rest-get.py), multipart
operations, missing or unknown parameters and missing required body fields are refused. Tiers: write runs on plan +
confirm; destructive (every DELETE and the admin tags in gen_jira_index.py) also needs --allow-destructive yes.
Operations that already have a hand-written entry are refused and point to it."""

import json
import pathlib
import re
import urllib.parse

from acli_rest_common import Fatal, HttpError
from rest_write_base import OPERATIONS, _check_flags, _one

INDEX_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "jira-v3-index.json"
_INDEX = None

# operationId -> the hand-written operation with richer previews and read-back
HANDWRITTEN = {"editIssue": "issue-set", "deleteIssue": "issue-delete", "createVersion": "version-create",
               "updateVersion": "version-edit", "deleteVersion": "version-delete", "createFilter": "filter-create"}
GATES = (("allow-destructive", "destructive tier"), ("allow-experimental", "experimental"),
         ("allow-deprecated", "deprecated"))
VALUE_RE = re.compile(r"^[^\x00-\x1f]{1,500}$")
PATH_VALUE_RE = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}$")
MAX_BODY = 200_000
SCALARS = (str, int, float, bool, type(None))


def load_index(path=None):
    global _INDEX
    if path is not None:
        return json.loads(pathlib.Path(path).read_text())
    if _INDEX is None:
        try:
            _INDEX = json.loads(INDEX_PATH.read_text())
        except (OSError, ValueError) as e:
            raise Fatal(f"cannot read the Jira operation index {INDEX_PATH}: {type(e).__name__}") from None
    return _INDEX


def _list(flags, name):
    v = flags.get(name, [])
    return [v] if isinstance(v, str) else list(v)


def _pairs(items, what):
    out = {}
    for item in items:
        if "=" not in item:
            raise Fatal(f"--{what} needs name=value, not {item!r}")
        k, v = item.split("=", 1)
        if k in out:
            raise Fatal(f"--{what} {k} is given twice")
        out[k] = v
    return out


def _validate(flags, pos=()):
    if pos:
        raise Fatal(f"jira-call takes no positional arguments: {pos[0]!r}")
    _check_flags(flags, {"op", "path", "query", "body", "body-file", "allow-destructive", "allow-experimental",
                         "allow-deprecated"}, "jira-call")
    op_id = _one(flags, "op")
    if not op_id:
        raise Fatal("usage: jira-call --op <operationId> [--path n=v] [--query n=v] [--body JSON | --body-file F] "
                    "(find ids with: acli-rest-get.py jira-ops <text>)")
    index = load_index()["ops"]
    if op_id not in index:
        raise Fatal(f"unknown Jira operation {op_id!r} (find ids with: acli-rest-get.py jira-ops <text>)")
    op = index[op_id]
    if op_id in HANDWRITTEN:
        raise Fatal(f"{op_id} has a hand-written operation with a fuller preview: use {HANDWRITTEN[op_id]}")
    if op["method"] == "GET":
        raise Fatal(f"{op_id} is a read: use acli-rest-get.py api jira {op['path']}")
    if op.get("body", {}).get("multipart"):
        raise Fatal(f"{op_id} is a multipart upload; jira-call does not send those")
    args = {"op": op_id}
    for flag, why in GATES:
        needed = {"allow-destructive": op["tier"] == "destructive", "allow-experimental": op.get("experimental"),
                  "allow-deprecated": op.get("deprecated")}[flag]
        if flag in flags:
            if str(_one(flags, flag)) != "yes":
                raise Fatal(f"--{flag} takes the value yes")
            args[flag] = "yes"
        if needed and flag not in args:
            raise Fatal(f"{op_id} is {why}: add --{flag} yes to plan it")
    pp = _pairs(_list(flags, "path"), "path")
    qq = _pairs(_list(flags, "query"), "query")
    declared = {(p["in"], p["name"]): p for p in op["params"]}
    for kind, given in (("path", pp), ("query", qq)):
        for name, value in given.items():
            p = declared.get((kind, name))
            if p is None:
                raise Fatal(f"{op_id} has no {kind} parameter {name!r} "
                            f"(has: {', '.join(sorted(n for k, n in declared if k == kind)) or 'none'})")
            ok = PATH_VALUE_RE.match(value) if kind == "path" else VALUE_RE.match(value)
            if not ok:
                raise Fatal(f"--{kind} {name} has a value outside the allowed characters")
            if p.get("enum") and value not in [str(e) for e in p["enum"]]:
                raise Fatal(f"--{kind} {name} must be one of {p['enum']}")
    for (kind, name), p in declared.items():
        if p["required"] and name not in (pp if kind == "path" else qq):
            raise Fatal(f"{op_id} needs --{kind} {name}=<value>")
    if pp:
        args["path"] = sorted(f"{k}={v}" for k, v in pp.items())
    if qq:
        args["query"] = sorted(f"{k}={v}" for k, v in qq.items())
    spec_body = op.get("body")
    text = None
    if "body" in flags and "body-file" in flags:
        raise Fatal("give --body or --body-file, not both")
    if "body-file" in flags:
        try:
            text = pathlib.Path(str(_one(flags, "body-file"))).read_text()
        except OSError as e:
            raise Fatal(f"cannot read --body-file: {type(e).__name__}") from None
    elif "body" in flags:
        text = str(_one(flags, "body"))
    if text is None:
        if spec_body and spec_body["required"]:
            raise Fatal(f"{op_id} needs a body (--body JSON or --body-file F)")
    else:
        if not spec_body:
            raise Fatal(f"{op_id} takes no body")
        if len(text) > MAX_BODY:
            raise Fatal(f"the body is over {MAX_BODY} bytes")
        try:
            doc = json.loads(text)
        except ValueError:
            raise Fatal("the body is not valid JSON") from None
        if not isinstance(doc, (dict, list)):
            raise Fatal("the body must be a JSON object or array")
        if isinstance(doc, dict):
            missing = [f for f in spec_body["fields"] if f not in doc]
            if missing:
                raise Fatal(f"the body lacks required field(s): {', '.join(missing)}")
        args["body"] = json.dumps(doc, sort_keys=True, ensure_ascii=False)
    return args


def _build_path(op, args):
    values = dict(i.split("=", 1) for i in args.get("path", []))
    path = op["path"]
    for name, v in values.items():
        path = path.replace("{" + name + "}", urllib.parse.quote(v, safe=""))
    return path


def _query(args):
    pairs = [tuple(i.split("=", 1)) for i in args.get("query", [])]
    return urllib.parse.urlencode(pairs) if pairs else ""


def _sibling_get(index, op):
    """The GET operation on the same path with no required query parameter, if the index has one. Only PUT and
    DELETE address one resource; a POST on a collection path would match its list GET, which says nothing about the target."""
    if op["method"] not in ("PUT", "DELETE"):
        return None
    for o in index.values():
        if o["path"] == op["path"] and o["method"] == "GET" and not any(
                p["required"] and p["in"] == "query" for p in o["params"]):
            return o
    return None


def _plan(get, args):
    index = load_index()["ops"]
    op = index[args["op"]]
    path = _build_path(op, args)
    base = {"op": args["op"], "method": op["method"], "path": path, "tier": op["tier"]}
    if args.get("query"):
        base["query"] = args["query"]
    for flag in ("experimental", "deprecated"):
        if op.get(flag):
            base[flag] = True
    if _sibling_get(index, op) is not None:
        try:
            cur = get(path, {})
            base["exists"] = True
            if isinstance(cur, dict):
                base["current"] = {k: v for k, v in cur.items() if isinstance(v, SCALARS)}
        except HttpError as e:
            if e.code != 404:
                raise
            base["exists"] = False
    return base, (json.loads(args["body"]) if "body" in args else None)


def _describe(base, body):
    notes = [f"{base['method']} {base['path']} ({base['tier']})"]
    if base.get("experimental"):
        notes.append("experimental: Atlassian may change or remove this operation without notice")
    if base.get("deprecated"):
        notes.append("deprecated: Atlassian plans to remove this operation")
    if base["method"] == "DELETE":
        notes.append("IRREVERSIBLE: Jira has no undo for this delete" + (
            "" if base.get("exists", True) else "; the target was not found just now"))
    elif base["tier"] == "destructive":
        notes.append("destructive tier: an admin or bulk change; check the body before you confirm")
    if "exists" in base and base["method"] != "DELETE":
        notes.append("target exists now" if base["exists"] else "target does not exist now")
    return notes


def _send(http, args, base, body_text):
    url = base["path"] + (f"?{_query(args)}" if args.get("query") else "")
    payload = body_text.encode() if body_text and body_text != "null" else None
    return http(base["method"], url, payload)


def _comparable(sent, cur):
    return isinstance(cur, dict) and any(isinstance(v, SCALARS) and k in cur for k, v in sent.items())


def _compare(sent, cur):
    """False on a mismatch; True when every sent field was compared; "partial" when nested values were skipped;
    "exists" when nothing could be compared (the resource was found and that is all that is known)."""
    if not isinstance(sent, dict) or not _comparable(sent, cur):
        return "exists"
    for k, v in sent.items():
        if isinstance(v, SCALARS) and k in cur and cur[k] != v:
            return False
    skipped = any(not (isinstance(v, SCALARS) and k in cur) for k, v in sent.items())
    return "partial" if skipped else True


def _readback(get, args, base, body_text, result):
    index = load_index()["ops"]
    op = index[args["op"]]
    path = base["path"]
    sibling = _sibling_get(index, op)
    if base["method"] == "DELETE":
        if sibling is None:
            raise Fatal("no GET on this path to confirm the delete")
        try:
            get(path, {})
        except HttpError as e:
            if e.code == 404:
                return True
            raise
        return False
    sent = json.loads(body_text) if body_text and body_text != "null" else None
    if sibling is not None and isinstance(sent, dict):
        cur = get(path, {})
        if _comparable(sent, cur):
            return _compare(sent, cur)
    if isinstance(result, dict) and isinstance(result.get("self"), str):
        full = urllib.parse.urlsplit(result["self"]).path
        at = full.find("/rest/api/3/")  # the gateway prefixes /ex/jira/<cloud id>; the site URL has no prefix
        got = full[at:] if at >= 0 else ""
        if got and ".." not in got:
            cur = get(got, {})
            return _compare(sent, cur)
    raise Fatal("this operation has no read-back the index can derive; check the result in Jira")


OPERATIONS["jira-call"] = {"product": "jira", "validate": _validate, "plan": _plan, "send": _send,
                           "readback": _readback, "describe": _describe}
