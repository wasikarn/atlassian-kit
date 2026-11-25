"""Spec-driven write operations of acli-rest-write: jira-call, confluence-call (v2) and confluence-v1-call.

plan <name> --op <operationId> [--path name=value ...] [--query name=value ...] [--body '<JSON>' | --body-file FILE]
            [--allow-destructive yes] [--allow-experimental yes] [--allow-deprecated yes]

Each operation name is bound to one pinned index under skills/ops/data (built by gen_spec_index.py from Atlassian's
OpenAPI spec). The index decides what is valid: unknown operation ids, GET operations (reads go through
acli-rest-get.py), multipart operations, missing or unknown parameters and missing required body fields are refused.
Tiers: write runs on plan + confirm; destructive (every DELETE and the admin tags in gen_spec_index.py) also needs
--allow-destructive yes. Operations that already have a hand-written entry are refused and point to it."""

import functools
import json
import pathlib
import re
import urllib.parse
from types import SimpleNamespace

from acli_rest_common import Fatal, HttpError
from rest_write_base import OPERATIONS, _check_flags, _one

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"

JIRA = SimpleNamespace(
    name="jira-call", product="jira", index="jira-v3-index.json",
    # operationId -> the hand-written operation with richer previews and read-back
    handwritten={"editIssue": "issue-set", "deleteIssue": "issue-delete", "createVersion": "version-create",
                 "updateVersion": "version-edit", "deleteVersion": "version-delete", "createFilter": "filter-create"},
    find="acli-rest-get.py jira-ops <text>", read="acli-rest-get.py api jira {path}",
    self_marker="/rest/api/3/", self_keep=True, extra={})
CONFLUENCE_V2 = SimpleNamespace(
    name="confluence-call", product="confluence", index="confluence-v2-index.json",
    handwritten={"createPage": "page-create", "updatePage": "page-update", "deletePage": "page-delete"},
    find="acli-rest-get.py confluence-ops <text>", read="acli-rest-get.py api confluence /wiki/api/v2{path}",
    self_marker="/wiki/api/v2", self_keep=False, extra={})
CONFLUENCE_V1 = SimpleNamespace(
    name="confluence-v1-call", product="confluence", index="confluence-v1-index.json",
    handwritten={"createAttachment": "attachment-upload"},
    find="acli-rest-get.py confluence-ops <text>", read="acli-rest-get.py api confluence /wiki/rest/api{path}",
    self_marker="/wiki/rest/api", self_keep=False,
    # these reach resolve_target in acli-rest-write.py: the v1 base for reads and sends, one token key (granular or classic scopes)
    extra={"send_api": "/wiki/rest/api", "read_api": "/wiki/rest/api",
           "send_token_key": "ACLI_REST_WRITE_CONFLUENCE_V1_TOKEN",
           "read_token_key": "ACLI_REST_WRITE_CONFLUENCE_V1_TOKEN"})
CONFIGS = (JIRA, CONFLUENCE_V2, CONFLUENCE_V1)
HANDWRITTEN = JIRA.handwritten  # kept for the tests

GATES = (("allow-destructive", "destructive tier", lambda op: op["tier"] == "destructive"),
         ("allow-experimental", "experimental", lambda op: op.get("experimental")),
         ("allow-deprecated", "deprecated", lambda op: op.get("deprecated")))
PARTIAL, EXISTS_ONLY = "partial", "exists"  # read-back results besides True/False; acli-rest-write.py words them
VALUE_RE = re.compile(r"^[^\x00-\x1f]{1,500}$")
PATH_VALUE_RE = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}$")
MAX_BODY = 200_000
SCALARS = (str, int, float, bool, type(None))
_INDEXES = {}


def load_index(cfg=JIRA):
    if cfg.index not in _INDEXES:
        try:
            _INDEXES[cfg.index] = json.loads((DATA_DIR / cfg.index).read_text())
        except (OSError, ValueError) as e:
            raise Fatal(f"cannot read the operation index {cfg.index}: {type(e).__name__}") from None
    return _INDEXES[cfg.index]


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


def _kv(items):
    """name=value strings (already checked by _pairs) back to a dict."""
    return dict(i.split("=", 1) for i in items)


def _validate(flags, pos=(), cfg=JIRA):
    if pos:
        raise Fatal(f"{cfg.name} takes no positional arguments: {pos[0]!r}")
    _check_flags(flags, {"op", "path", "query", "body", "body-file", "allow-destructive", "allow-experimental",
                         "allow-deprecated"}, cfg.name)
    op_id = _one(flags, "op")
    if not op_id:
        raise Fatal(f"usage: {cfg.name} --op <operationId> [--path n=v] [--query n=v] [--body JSON | --body-file F] "
                    f"(find ids with: {cfg.find})")
    index = load_index(cfg)["ops"]
    if op_id not in index:
        raise Fatal(f"unknown operation {op_id!r} for {cfg.name} (find ids with: {cfg.find})")
    op = index[op_id]
    if op_id in cfg.handwritten:
        raise Fatal(f"{op_id} has a hand-written operation with a fuller preview: use {cfg.handwritten[op_id]}")
    if op["method"] == "GET":
        raise Fatal(f"{op_id} is a read: use {cfg.read.format(path=op['path'])}")
    if op.get("body", {}).get("multipart"):
        raise Fatal(f"{op_id} is a multipart upload; {cfg.name} does not send those")
    args = {"op": op_id}
    for flag, why, applies in GATES:
        needed = applies(op)
        if flag in flags:
            if str(_one(flags, flag)) != "yes":
                raise Fatal(f"--{flag} takes the value yes")
            args[flag] = "yes"
        if needed and flag not in args:
            raise Fatal(f"{op_id} is {why}: add --{flag} yes to plan it")
    path_args = _pairs(_list(flags, "path"), "path")
    query_args = _pairs(_list(flags, "query"), "query")
    declared = {(p["in"], p["name"]): p for p in op["params"]}
    for kind, given in (("path", path_args), ("query", query_args)):
        for name, value in given.items():
            p = declared.get((kind, name))
            if p is None:
                raise Fatal(f"{op_id} has no {kind} parameter {name!r} "
                            f"(has: {', '.join(sorted(n for k, n in declared if k == kind)) or 'none'})")
            ok = (PATH_VALUE_RE.match(value) and value.strip(".")) if kind == "path" else VALUE_RE.match(value)  # "." and ".." would walk the URL
            if not ok:
                raise Fatal(f"--{kind} {name} has a value outside the allowed characters")
            if p.get("enum") and value not in [str(e) for e in p["enum"]]:
                raise Fatal(f"--{kind} {name} must be one of {p['enum']}")
    for (kind, name), p in declared.items():
        if p["required"] and name not in (path_args if kind == "path" else query_args):
            raise Fatal(f"{op_id} needs --{kind} {name}=<value>")
    if path_args:
        args["path"] = sorted(f"{k}={v}" for k, v in path_args.items())
    if query_args:
        args["query"] = sorted(f"{k}={v}" for k, v in query_args.items())
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
    path = op["path"]
    for name, v in _kv(args.get("path", [])).items():
        path = path.replace("{" + name + "}", urllib.parse.quote(v, safe=""))
    return path


def _query(args):
    pairs = list(_kv(args.get("query", [])).items())
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


def _item_get(index, op):
    """The GET that reads one item of the collection a POST creates into: <path>/{one param}, no required query."""
    for o in index.values():
        head, _, last = o["path"].rpartition("/")
        if (o["method"] == "GET" and head == op["path"] and re.fullmatch(r"\{[^{}/]+\}", last)
                and not any(p["required"] and p["in"] == "query" for p in o["params"])):
            return o
    return None


def _plan(get, args, cfg=JIRA):
    index = load_index(cfg)["ops"]
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
    elif op["method"] == "DELETE":
        base["no_readback"] = True
    return base, (json.loads(args["body"]) if "body" in args else None)


def _describe(base, body, cfg=JIRA):
    notes = [f"{base['method']} {base['path']} ({base['tier']})"]
    if base.get("experimental"):
        notes.append("experimental: Atlassian may change or remove this operation without notice")
    if base.get("deprecated"):
        notes.append("deprecated: Atlassian plans to remove this operation")
    if base.get("no_readback"):
        notes.append("no read-back: the index has no GET on this path, so apply cannot confirm the delete; check the product after it")
    if base["method"] == "DELETE":
        notes.append("IRREVERSIBLE: no undo for this delete" + (
            "" if base.get("exists", True) else "; the target was not found just now"))
    elif base["tier"] == "destructive":
        notes.append("destructive tier: an admin or bulk change; check the body before you confirm")
    if "exists" in base and base["method"] != "DELETE":
        notes.append("target exists now" if base["exists"] else "target does not exist now")
    return notes


def _send(http, args, base, body_text, cfg=JIRA):
    url = base["path"] + (f"?{_query(args)}" if args.get("query") else "")
    payload = body_text.encode() if body_text and body_text != "null" else None
    return http(base["method"], url, payload)


def _comparable(sent, cur):
    return isinstance(cur, dict) and any(isinstance(v, SCALARS) and k in cur for k, v in sent.items())


def _compare(sent, cur):
    """False on a mismatch; True when every sent field was compared; PARTIAL when nested values were skipped;
    EXISTS_ONLY when nothing could be compared (the resource was found and that is all that is known)."""
    if not isinstance(sent, dict) or not _comparable(sent, cur):
        return EXISTS_ONLY
    for k, v in sent.items():
        if isinstance(v, SCALARS) and k in cur and cur[k] != v:
            return False
    skipped = any(not (isinstance(v, SCALARS) and k in cur) for k, v in sent.items())
    return PARTIAL if skipped else True


def _self_path(result, cfg):
    """The resource path inside the response's self link (Jira `self`, Confluence v1 `_links.self`), or ''."""
    links = result.get("_links") if isinstance(result, dict) else None
    url = (result.get("self") if isinstance(result, dict) else None) or (
        links.get("self") if isinstance(links, dict) else None)
    if not isinstance(url, str):
        return ""
    full = urllib.parse.urlsplit(url).path
    at = full.find(cfg.self_marker)  # the gateway prefixes /ex/<product>/<cloud id>; the site URL has no prefix
    if at < 0:
        return ""
    got = full[at:] if cfg.self_keep else full[at + len(cfg.self_marker):]
    return "" if ".." in got else got


def _readback(get, args, base, body_text, result, cfg=JIRA):
    index = load_index(cfg)["ops"]
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
    got = _self_path(result, cfg)
    if got:
        return _compare(sent, get(got, {}))
    new_id = str(result.get("id", "")) if isinstance(result, dict) else ""
    if op["method"] == "POST" and PATH_VALUE_RE.match(new_id) and new_id.strip(".") and _item_get(index, op):
        return _compare(sent, get(f"{path}/{new_id}", {}))
    raise Fatal("this operation has no read-back the index can derive; check the result in the product")


def register(cfg):
    OPERATIONS[cfg.name] = {
        "product": cfg.product,
        "validate": functools.partial(_validate, cfg=cfg), "plan": functools.partial(_plan, cfg=cfg),
        "send": functools.partial(_send, cfg=cfg), "readback": functools.partial(_readback, cfg=cfg),
        "describe": functools.partial(_describe, cfg=cfg), **cfg.extra}


for _cfg in CONFIGS:
    register(_cfg)
