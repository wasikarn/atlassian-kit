#!/usr/bin/env python3
"""acli-rest-write — Jira/Confluence REST writes as plan (reads only), then apply (sends once).

  acli-rest-write.py plan <operation> [--flag VALUE ...] [--env-file FILE]
  acli-rest-write.py apply <request-file> --confirm <12hex> [--env-file FILE]

plan validates the arguments, resolves the target, fetches the state the operation needs and writes a
request file holding {schema, created, operation, args, target, base, body_text}. No method, path or URL
is stored: apply picks them from code. plan prints a label, the old and new state, `request: <path>` and
`confirm: <first 12 hex of sha256 of the file>`.

apply recomputes the hash, enforces a strict schema (unknown key, unknown operation, older than 30 min),
re-resolves the target, rebuilds the request from the live state with the operation's own planner and
refuses unless base and body match the file, then sends and reads back. The confirm hash proves the file
did not change after the plan was shown; the operator reading the preview is the approval.

Exit codes: 0 sent and verified; 1 refused locally, no write request left the machine; 2 sent and
rejected by the server (4xx — the server's error body is printed); 3 sent but unverified — timeout
or connection error once the write started, a 5xx, or a read-back that fails or does not match.
Do not re-run `apply` at 3 before checking.

Credentials come from a mode-600 env file: ACLI_REST_WRITE_SITE, ACLI_REST_WRITE_EMAIL,
ACLI_REST_WRITE_JIRA_TOKEN, ACLI_REST_WRITE_CONFLUENCE_TOKEN. The default file is ~/.claude/atlassian.env
and must agree with `acli jira auth status`. --env-file names an alternate target (a test site); it must
be a different site than acli's, and the preview labels it ALTERNATE TARGET. The acli-guard hook
denies every subagent call of this script; approving a preview covers calls made through it and
nothing else.
Operations: Confluence page-create / page-fetch (read-only; writes the base+adf files) / page-update;
Jira issue-set / version-create.
"""
import datetime
import hashlib
import json
import os
import pathlib
import re
import sys
import tempfile
import urllib.parse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from acli_rest_common import (  # noqa: E402
    ENV_FILE, HOST_RE, Fatal, HttpError, NetError, acli_identity, cloud_id, default_opener,
    http_request, parse_json, read_env_file, run_command,
)

PRODUCT_BASE = {"jira": f"https://api.atlassian.com/ex/jira",
                "confluence": f"https://api.atlassian.com/ex/confluence"}
MAX_AGE = 30 * 60
FILE_KEYS = {"schema", "created", "operation", "args", "target", "base", "body_text"}
USAGE = ("usage: acli-rest-write.py plan <operation> [--... VALUE] [--env-file FILE] | "
         "apply <request-file> --confirm <12hex> [--env-file FILE]")

OPERATIONS = {}  # name -> {product, validate(flags)->args, plan(get,args)->(base,body), send(http,args,base,body_text)->text, readback(get,args,base,body_text,result)->bool}
KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]+-[0-9]+$")
SPACE_KEY_RE = re.compile(r"^[A-Z][A-Z0-9]*$")
PAGE_ID_RE = re.compile(r"^[0-9]+$")


# --- operation: page-create (Confluence v2) ---------------------------------

def _read_adf(path_str):
    p = pathlib.Path(path_str)
    try:
        raw = p.read_text()
    except FileNotFoundError:
        raise Fatal(f"body file {path_str} not found") from None
    except OSError as e:
        raise Fatal(f"cannot read the body file {path_str}: {type(e).__name__}") from None
    doc = parse_json(raw, str(p))
    if not isinstance(doc, dict) or doc.get("type") != "doc":
        raise Fatal(f"the body file {p} is not an ADF doc (need a {{'type': 'doc', ...}} object)")
    return doc


def _conf_paged(get, path, params):
    out, cursor = [], None
    while True:
        qs = dict(params)
        if cursor:
            qs["cursor"] = cursor
        page = get(path, qs)
        results = page.get("results") if isinstance(page, dict) else None
        if not isinstance(results, list):
            raise Fatal(f"unexpected shape from {path} (need results[])")
        out.extend(results)
        nxt = page.get("_links", {}).get("next") if isinstance(page.get("_links"), dict) else None
        if not nxt:
            return out
        cursor = (urllib.parse.parse_qs(urllib.parse.urlsplit(nxt).query).get("cursor") or [""])[0]
        if not cursor:
            raise Fatal(f"the next link of {path} has no cursor")


def _validate_page_create(flags, pos=()):
    if pos:
        raise Fatal(f"page-create takes no positional arguments: {pos[0]!r}")
    _check_flags(flags, {"space", "title", "parent", "body-adf"}, "page-create")
    for f in ("space", "title", "parent", "body-adf"):
        _one(flags, f)
    if not SPACE_KEY_RE.match(str(flags.get("space", ""))):
        raise Fatal("--space must be an uppercase space key")
    if not str(flags.get("title", "")):
        raise Fatal("--title is required")
    if "parent" in flags and not PAGE_ID_RE.match(str(flags["parent"])):
        raise Fatal("--parent must be a page id (digits)")
    if "body-adf" not in flags:
        raise Fatal("--body-adf FILE is required")
    return dict(flags)


def _plan_page_create(get, args):
    doc = _read_adf(args["body-adf"])
    spaces = _conf_paged(get, "/spaces", {"keys": args["space"]})
    matching = [sp for sp in spaces if str(sp.get("key", "")) == args["space"]]
    if len(matching) != 1:
        raise Fatal(f"expected exactly one space named {args['space']}, found {len(matching)} "
                    f"(the listing only shows what this account can see)")
    space_id = str(matching[0]["id"])
    dup = _conf_paged(get, "/pages", {"space-id": space_id, "title": args["title"]})
    if dup:
        raise Fatal(f"a page titled {args['title']!r} already exists in that space (the listing only "
                    f"shows what this account can see, so an empty result is not proof)")
    parent_id = None
    if "parent" in args:
        parent = get(f"/pages/{args['parent']}", {})
        if str(parent.get("spaceId")) != space_id:
            raise Fatal(f"parent page {args['parent']} lives in space {parent.get('spaceId')}, not {space_id}")
        parent_id = str(args["parent"])
    return {"spaceId": space_id, "parentId": parent_id}, doc


def _send_page_create(http, args, base, body_text):
    wire = {"spaceId": base["spaceId"], "status": "current", "title": args["title"],
            "body": {"representation": "atlas_doc_format", "value": body_text}}
    if base.get("parentId"):
        wire["parentId"] = base["parentId"]
    return http("POST", "/pages", json.dumps(wire).encode())


def _readback_page_create(get, args, base, body_text, result):
    pid = str(result.get("id", "")) if isinstance(result, dict) else ""
    if not PAGE_ID_RE.match(pid):
        return False
    page = get(f"/pages/{pid}", {"body-format": "atlas_doc_format"})
    sent_adf = json.loads(body_text)
    val = (page.get("body", {}).get("atlas_doc_format", {}) or {}).get("value", "")
    try:
        back = json.loads(val)
    except (ValueError, AttributeError):
        return False
    return canonical(back) == canonical(sent_adf) and page.get("title") == args["title"]


OPERATIONS["page-create"] = {"product": "confluence", "validate": _validate_page_create,
                             "plan": _plan_page_create, "send": _send_page_create,
                             "readback": _readback_page_create}
SPACE_KEY_RE = re.compile(r"^[A-Z][A-Z0-9]*$")
PAGE_ID_RE = re.compile(r"^[0-9]+$")


def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)


def parse_flags(rest):
    flags, pos, i = {}, [], 0
    while i < len(rest):
        if rest[i].startswith("--") and len(rest[i]) > 2:
            if i + 1 >= len(rest):
                raise Fatal(f"flag {rest[i]} needs a value")
            key = rest[i][2:]
            if key in flags:  # a repeated flag collects its values, in order
                if isinstance(flags[key], list):
                    flags[key].append(rest[i + 1])
                else:
                    flags[key] = [flags[key], rest[i + 1]]
            else:
                flags[key] = rest[i + 1]
            i += 2
        else:
            pos.append(rest[i])
            i += 1
    return flags, pos


def _one(flags, name):
    """The single value of --name, refusing a repeated flag."""
    value = flags.get(name)
    if isinstance(value, list):
        raise Fatal(f"--{name} was given more than once; it takes a single value")
    return value


def _check_flags(flags, known, op):
    extra = sorted(set(flags) - set(known))
    if extra:
        raise Fatal(f"unknown flag(s) for {op}: " + ", ".join(f"--{f}" for f in extra))


def resolve_target(opener, run, flags, env_file, product):
    """Validate the target before any token is used. Return (label, host, email, cid, token, get)."""
    host, email = acli_identity(run)
    alternate = pathlib.Path(_one(flags, "env-file")) if "env-file" in flags else None
    used = alternate or env_file
    env = read_env_file(used)
    if alternate is not None:
        thost = env.get("ACLI_REST_WRITE_SITE", "")
        if not HOST_RE.match(thost):
            raise Fatal(f"ACLI_REST_WRITE_SITE in {alternate} is not a *.atlassian.net host")
        if thost == host:
            raise Fatal(f"the alternate target in {alternate} is the same site as acli's; refusing "
                        f"to treat it as an alternate target")
        temail, label = env.get("ACLI_REST_WRITE_EMAIL", ""), f"ALTERNATE TARGET {thost}"
    else:
        if env.get("ACLI_REST_WRITE_SITE") != host or env.get("ACLI_REST_WRITE_EMAIL") != email:
            raise Fatal(f"ACLI_REST_WRITE_SITE/EMAIL in {env_file} do not match the acli identity; the target may have changed")
        thost, temail, label = host, email, f"PRODUCTION {host}"
    for key, want in (("ACLI_REST_WRITE_SITE", thost), ("ACLI_REST_WRITE_EMAIL", temail)):
        if env.get(key) != want:
            raise Fatal(f"{key} in {used} does not name the target")
    token_key = f"ACLI_REST_WRITE_{product.upper()}_TOKEN"
    if not env.get(token_key):
        raise Fatal(f"{token_key} is missing in {used}")
    cid = cloud_id(thost, opener)
    target = {"host": thost, "cloudId": cid, "email": temail}
    api_suffix = {"jira": "", "confluence": "/wiki/api/v2"}[product]
    base_url = f"{PRODUCT_BASE[product]}/{cid}{api_suffix}"

    def get(path, params=None):
        url = base_url + path + ("?" + urllib.parse.urlencode(params) if params else "")
        return json.loads(http_request(opener, "GET", url, (temail, env[token_key])))

    return label, target, env[token_key], get, base_url


def _notes(args, flags):
    return []


def write_request(payload):
    d = tempfile.mkdtemp(prefix="acli-rest-write-")  # mode 0o700 per mkdtemp(3)
    p = pathlib.Path(d) / "request.json"
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    return p, text


def do_plan(opener, run, env_file, flags, pos):
    if not pos:
        raise Fatal(USAGE)
    op = OPERATIONS.get(pos[0])
    if op is None:
        raise Fatal(f"unknown operation: {pos[0]!r} (registered: {', '.join(sorted(OPERATIONS))})")
    args = op["validate"]({k: v for k, v in flags.items() if k != "env-file"}, pos[1:])
    label, target, token, get, _ = resolve_target(opener, run, flags, env_file, op["product"])
    base, body = op["plan"](get, args)
    if op.get("planOnly"):
        print(json.dumps({"base": base, "body": body}, ensure_ascii=False))
        return 0
    for note in (op.get("notes") or _notes)(args, flags):
        print(f"note: {note}")
    body_text = canonical(body)
    payload = {"schema": 1, "created": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "operation": pos[0], "args": args, "target": target, "base": base, "body_text": body_text}
    p, text = write_request(payload)
    digest = hashlib.sha256(text.encode()).hexdigest()[:12]
    print(f"{label} ({target['cloudId']}) as {target['email']}")
    print(f"base: {json.dumps(base, ensure_ascii=False)}")
    print(f"body: {json.dumps(body, ensure_ascii=False)}")
    print(f"request: {p}")
    print(f"confirm: {digest}")
    return 0


def _exit2(code, detail):
    print(f"the request was sent and the server rejected it: {detail}", file=sys.stderr)
    return 2


def _exit3(reason, result=None):
    tail = f" server answer: {result}" if result else ""
    print(f"SENT BUT UNVERIFIED ({reason}). do not re-run `apply` before checking; read back first.{tail}",
          file=sys.stderr)
    return 3


def do_apply(opener, run, env_file, flags, pos):
    _check_flags(flags, {"confirm", "env-file"}, "apply")
    if len(pos) != 1 or "confirm" not in flags:
        raise Fatal(USAGE)
    path, want = pathlib.Path(pos[0]), _one(flags, "confirm")
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raise Fatal(f"request file not found: {path}") from None
    if hashlib.sha256(raw).hexdigest()[:12] != want:
        raise Fatal(f"confirm hash does not match: the file changed after the plan was shown (wanted {want})")
    try:
        data = json.loads(raw.decode())
    except ValueError:
        raise Fatal("the request file is not JSON") from None
    if not isinstance(data, dict) or set(data) != FILE_KEYS:
        extra = sorted(set(data) - FILE_KEYS) if isinstance(data, dict) else []
        raise Fatal(f"unexpected key in the request file: {extra}" if extra else "the request file has the wrong keys")
    op = OPERATIONS.get(data["operation"])
    if op is None:
        raise Fatal(f"unknown operation: {data['operation']!r}")
    try:
        age = datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.strptime(
            str(data["created"]), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        raise Fatal("the request file has an unreadable created timestamp") from None
    if age.total_seconds() > MAX_AGE:
        raise Fatal(f"the request file is older than 30 minutes (created {data['created']}); plan again")
    if not isinstance(data["args"], dict) or not isinstance(data["target"], dict):
        raise Fatal("the request file has the wrong shapes in args/target")
    if op.get("planOnly"):
        raise Fatal(f"{data['operation']} is read-only; there is nothing to apply")
    args = op["validate"](data["args"], ())
    label, target, token, get, send_base = resolve_target(opener, run, flags, env_file, op["product"])
    if data["target"].get("host") != target["host"] or data["target"].get("email") != target["email"]:
        raise Fatal("the target changed since the plan; plan again")
    try:
        base, body = op["plan"](get, args)
    except Fatal as e:
        raise Fatal(f"the live state changed since the plan: {e}") from None
    if canonical(base) != canonical(data["base"]):
        raise Fatal("the live state changed since the plan; plan again")
    body_text = canonical(json.loads(data["body_text"]))
    if body_text != canonical(body):
        raise Fatal("the rebuilt request body does not match the previewed one; plan again")
    auth = (target["email"], token)
    http = lambda method, path, payload: http_request(opener, method, send_base + path, auth, payload)
    try:
        result_text = op["send"](http, args, base, data["body_text"])
    except HttpError as e:
        if e.code < 500:
            return _exit2(e.code, str(e))
        return _exit3(str(e))
    except NetError as e:
        return _exit3(f"no answer from the server ({e})")
    try:
        result = json.loads(result_text)
    except ValueError:
        result = result_text[:200]
    try:
        ok = op["readback"](get, args, base, data["body_text"], result)
    except (Fatal, ValueError, TypeError, KeyError, AttributeError) as e:
        return _exit3(f"the read-back failed ({e})")
    if not ok:
        return _exit3("the read-back does not match what was sent", str(result)[:200])
    print(f"applied to {target['host']} and verified by read-back")
    path.unlink()
    return 0


# --- operation: issue-set (Jira) --------------------------------------------

CHANGE_FLAGS = {"priority", "parent", "environment-adf", "add-fix-version", "remove-fix-version",
                "add-affects-version", "remove-affects-version"}


def _jira_get_list(get, path, source):
    rows = get(path, {})
    if not isinstance(rows, list):
        raise Fatal(f"unexpected shape from {source} (need a list)")
    return rows


def _names(rows):
    return {str(r.get("name")) for r in rows if isinstance(r, dict)}


def _validate_issue_set(flags, pos=()):
    if pos:
        raise Fatal(f"issue-set takes no positional arguments: {pos[0]!r}")
    _check_flags(flags, {"key", *CHANGE_FLAGS}, "issue-set")
    for f in ("key", "parent", "priority", "environment-adf"):
        _one(flags, f)
    args = dict(flags)
    if "key" not in args or not KEY_RE.match(str(args["key"])):
        raise Fatal("--key must be a Jira issue key")
    if not [k for k in CHANGE_FLAGS if k in args]:
        raise Fatal(f"usage: issue-set needs at least one change flag: {', '.join('--' + f for f in sorted(CHANGE_FLAGS))}")
    for flag in ("add-fix-version", "remove-fix-version", "add-affects-version", "remove-affects-version"):
        if flag in args:
            items = args[flag] if isinstance(args[flag], list) else [args[flag]]
            if not all(items):
                raise Fatal(f"--{flag} needs a value")
            args[flag] = items
    if "parent" in args and not KEY_RE.match(str(args["parent"])):
        raise Fatal("--parent must be a Jira issue key")
    return args


def _plan_issue_set(get, args):
    key = str(args["key"])
    current = (get(f"/rest/api/3/issue/{key}", {}).get("fields", {}) or {})
    def cur_names(field):
        rows = current.get(field) or []
        return sorted({str(r.get("name")) for r in rows if isinstance(r, dict)})
    base = {"priority": (current.get("priority") or {}).get("name"),
            "fixVersions": cur_names("fixVersions"), "versions": cur_names("versions"),
            "parentKey": (current.get("parent") or {}).get("key"),
            "environmentSet": bool(current.get("environment"))}
    project = key.split("-", 1)[0]
    fields, updates = {}, {}
    if "priority" in args:
        names = _names(_jira_get_list(get, "/rest/api/3/priority", "/rest/api/3/priority"))
        if args["priority"] not in names:
            raise Fatal(f"priority {args['priority']!r} is not one of {sorted(names)}")
        fields["priority"] = {"name": args["priority"]}
    if "parent" in args:
        parent = get(f"/rest/api/3/issue/{args['parent']}", {})
        if str(parent.get("key")) == key:
            raise Fatal("an issue cannot be its own parent")
        fields["parent"] = {"key": str(args["parent"])}
    if "environment-adf" in args:
        fields["environment"] = _read_adf(args["environment-adf"])
    for add_flag, remove_flag, field in (("add-fix-version", "remove-fix-version", "fixVersions"),
                                         ("add-affects-version", "remove-affects-version", "versions")):
        verbs = []
        if add_flag in args or remove_flag in args:
            versions = _names(_jira_get_list(get, f"/rest/api/3/project/{project}/versions",
                                             f"/rest/api/3/project/{project}/versions"))
            for name in args.get(add_flag, []):
                if name not in versions:
                    raise Fatal(f"version {name!r} does not exist in {project} "
                                f"(the list is what this account can see)")
                verbs.append({"add": {"name": name}})
            for name in args.get(remove_flag, []):
                if name not in base[field and ("fixVersions" if field == "fixVersions" else "versions") or field]:
                    raise Fatal(f"version {name!r} is not on issue {key} (current: {base[field]})")
                verbs.append({"remove": {"name": name}})
            updates[field] = verbs
    body = {}
    if fields: body["fields"] = fields
    if updates: body["update"] = updates
    return base, body


def _issue_matches(current, body):
    fields = current.get("fields", {}) or {}
    if "priority" in body.get("fields", {}):
        if (fields.get("priority") or {}).get("name") != body["fields"]["priority"].get("name"):
            return False
    if "parent" in body.get("fields", {}):
        if (fields.get("parent") or {}).get("key") != body["fields"]["parent"].get("key"):
            return False
    if "environment" in body.get("fields", {}):
        if body["fields"]["environment"] != fields.get("environment"):
            return False
    for field, verbs in body.get("update", {}).items():
        names = {str(r.get("name")) for r in (fields.get(field) or []) if isinstance(r, dict)}
        for verb in verbs:
            for verb_name, item in verb.items():
                if verb_name == "add" and item.get("name") not in names: return False
                if verb_name == "remove" and item.get("name") in names: return False
    return True


def _send_issue_set(http, args, base, body_text):
    return http("PUT", f"/rest/api/3/issue/{args['key']}", body_text.encode())


def _readback_issue_set(get, args, base, body_text, result):
    return _issue_matches(get(f"/rest/api/3/issue/{args['key']}", {}), json.loads(body_text))


# --- operation: version-create (Jira) ---------------------------------------

def _validate_version_create(flags, pos=()):
    if pos:
        raise Fatal(f"version-create takes no positional arguments: {pos[0]!r}")
    _check_flags(flags, {"project", "name", "description"}, "version-create")
    for f in ("project", "name", "description"):
        _one(flags, f)
    if not re.match(r"^[A-Z][A-Z0-9_]+$", str(flags.get("project", ""))):
        raise Fatal("--project must be a Jira project key")
    if not str(flags.get("name", "")):
        raise Fatal("--name is required")
    return {"project": str(flags["project"]), "name": str(flags["name"]),
            **({"description": str(flags["description"])} if "description" in flags else {})}


def _plan_version_create(get, args):
    project = get(f"/rest/api/3/project/{args['project']}", {})
    project_id = str(project.get("id", ""))
    if not project_id.isdigit():
        raise Fatal(f"project {args['project']} did not expose a numeric id")
    existing = _names(_jira_get_list(get, f"/rest/api/3/project/{args['project']}/versions",
                                     f"/rest/api/3/project/{args['project']}/versions"))
    if args["name"] in existing:
        raise Fatal(f"a version named {args['name']!r} already exists in {args['project']} "
                    f"(the list is what this account can see)")
    body = {"projectId": project_id, "name": args["name"]}
    if "description" in args:
        body["description"] = args["description"]
    return {"projectId": project_id, "knownVersions": len(existing)}, body


def _send_version_create(http, args, base, body_text):
    return http("POST", "/rest/api/3/version", body_text.encode())


def _readback_version_create(get, args, base, body_text, result):
    vid = str(result.get("id", "")) if isinstance(result, dict) else ""
    if not vid:
        return False
    v = get(f"/rest/api/3/version/{vid}", {})
    return str(v.get("name")) == args["name"] and str(v.get("projectId")) == base["projectId"]


OPERATIONS["issue-set"] = {"product": "jira", "validate": _validate_issue_set,
                           "plan": _plan_issue_set, "send": _send_issue_set,
                           "readback": _readback_issue_set}
OPERATIONS["version-create"] = {"product": "jira", "validate": _validate_version_create,
                                "plan": _plan_version_create, "send": _send_version_create,
                                "readback": _readback_version_create}



# --- operations: page-fetch and page-update (Confluence v2, phase 4) --------

PRESERVE_TYPES = ("extension", "bodiedExtension", "inlineExtension", "panel", "expand",
                  "nestedExpand", "table", "media", "mediaSingle", "mediaGroup", "layoutSection",
                  "taskList", "decisionList", "status", "mention", "inlineCard", "blockCard")


def _node_counts(adf):
    counts = {}

    def walk(node):
        if not isinstance(node, dict):
            return
        t = node.get("type")
        if isinstance(t, str):
            counts[t] = counts.get(t, 0) + 1
        for child in (node.get("content") or []):
            walk(child)

    walk(adf)
    return counts


def _page_snapshot(get, page_id):
    page = get(f"/pages/{page_id}", {"body-format": "atlas_doc_format"})
    val = (page.get("body", {}) or {}).get("atlas_doc_format", {}).get("value", "")
    try:
        adf = json.loads(val)
    except ValueError:
        raise Fatal(f"page {page_id} did not return an ADF body") from None
    version = (page.get("version") or {}).get("number")
    if not isinstance(version, int):
        raise Fatal(f"page {page_id} did not expose a version number")
    return page, adf, version


def _validate_page_fetch(flags, pos):
    extra = sorted(set(flags))
    if extra:
        raise Fatal(f"page-fetch takes no flags (got: {', '.join(f'--{f}' for f in extra)})")
    if len(pos) != 1 or not PAGE_ID_RE.match(str(pos[0])):
        raise Fatal("usage: page-fetch <page id>")
    return {"page": str(pos[0])}


def _plan_page_fetch(get, args):
    page, adf, version = _page_snapshot(get, args["page"])
    d = pathlib.Path.cwd()
    adf_path = d / f"page-{args['page']}-v{version}.adf.json"
    base_path = d / f"page-{args['page']}-v{version}.base.json"
    adf_path.write_text(json.dumps(adf, indent=2, ensure_ascii=False))
    base = {"pageId": str(page.get("id")), "version": version, "title": page.get("title", ""),
            "adfSha": hashlib.sha256(canonical(adf).encode()).hexdigest()}
    base_path.write_text(json.dumps(base))
    return base, {"base": str(base_path), "adf": str(adf_path)}


def _validate_page_update(flags, pos):
    if pos:
        raise Fatal(f"page-update takes no positional arguments: {pos[0]!r}")
    _check_flags(flags, {"base", "body-adf", "title", "allow-node-loss"}, "page-update")
    for f in ("base", "body-adf", "title"):
        _one(flags, f)
    if "base" not in flags:
        raise Fatal("usage: page-update --base <*.base.json> --body-adf <edited.adf.json> [--title T] [--allow-node-loss TYPE]")
    if "body-adf" not in flags:
        raise Fatal("--body-adf is required")
    allow = flags.get("allow-node-loss") or []
    allow = [allow] if isinstance(allow, str) else list(allow)
    unknown = [a for a in allow if a not in PRESERVE_TYPES]
    if unknown:
        raise Fatal(f"--allow-node-loss must name node types it may lose, not {unknown}")
    args = {"base": str(flags["base"]), "body-adf": str(flags["body-adf"]), "allow-node-loss": allow}
    if "title" in flags:
        args["title"] = str(flags["title"])
    return args


def _plan_page_update(get, args):
    base_file = pathlib.Path(args["base"])
    try:
        base = json.loads(base_file.read_text())
    except FileNotFoundError:
        raise Fatal(f"base file {base_file} not found (run page-fetch first)") from None
    except ValueError:
        raise Fatal(f"base file {base_file} is not JSON") from None
    if not isinstance(base, dict) or base.get("adfSha") is None or base.get("pageId") is None:
        raise Fatal(f"base file {base_file} does not hold pageId/version/title/adfSha")
    page, adf, version = _page_snapshot(get, str(base["pageId"]))
    if version != base.get("version") or hashlib.sha256(canonical(adf).encode()).hexdigest() != base["adfSha"]:
        raise Fatal(f"the live page no longer matches the base {(base_file.name)!r} "
                    f"(live version {version}); re-run page-fetch and re-check edits")
    edited = _read_adf(args["body-adf"])
    live_counts, edited_counts = _node_counts(adf), _node_counts(edited)
    dropped = [t for t in PRESERVE_TYPES if live_counts.get(t, 0) > edited_counts.get(t, 0)
               and t not in set(args.get("allow-node-loss") or [])]
    if dropped:
        raise Fatal(f"the edit removes these node types: {dropped}; "
                    f"pass --allow-node-loss <type> only for types you mean to drop")
    title = args.get("title", str(base.get("title", "")))
    wire = {"id": str(base["pageId"]), "status": "current", "title": title,
            "version": {"number": version + 1},
            "body": {"representation": "atlas_doc_format", "value": canonical(edited)}}
    return {"pageId": str(base["pageId"]), "version": version, "title": title,
            "adfSha": base["adfSha"]}, wire


def _send_page_update(http, args, base, body_text):
    return http("PUT", f"/pages/{base['pageId']}", body_text.encode())


def _readback_page_update(get, args, base, body_text, result):
    page, adf, version = _page_snapshot(get, base["pageId"])
    wire = json.loads(body_text)
    return page.get("title") == wire["title"] and version == wire["version"]["number"] \
        and canonical(adf) == canonical(json.loads(wire["body"]["value"]))


def _notes_page_update(args, flags):
    allow = args.get("allow-node-loss") or []
    notes = [f"publishing can discard or conflict with an unpublished draft of this page; check the "
             f"page for a draft first"]
    if allow:
        notes.append(f"--allow-node-loss {' and '.join(allow)}: those node types are dropped by design")
    return notes



OPERATIONS["page-fetch"] = {"product": "confluence", "planOnly": True,
                            "validate": _validate_page_fetch, "plan": _plan_page_fetch}
OPERATIONS["page-update"] = {"product": "confluence", "validate": _validate_page_update,
                             "plan": _plan_page_update, "send": _send_page_update,
                             "readback": _readback_page_update, "notes": _notes_page_update}



def main(argv, opener=None, run=run_command, env_file=ENV_FILE):
    try:
        if len(argv) < 2:
            raise Fatal(USAGE)
        mode, rest = argv[1], argv[2:]
        flags, pos = parse_flags(rest)
        if mode == "plan":
            return do_plan(opener or default_opener(), run, env_file, flags, pos)
        if mode == "apply":
            return do_apply(opener or default_opener(), run, env_file, flags, pos)
        if mode == "page-fetch":
            op = OPERATIONS["page-fetch"]
            args = op["validate"]({k: v for k, v in flags.items() if k != "env-file"}, pos)
            _, _, _, get, _ = resolve_target(opener or default_opener(), run, flags, env_file, op["product"])
            base, body = op["plan"](get, args)
            print(json.dumps({"base": base, "body": body}, ensure_ascii=False))
            return 0
        raise Fatal(USAGE)
    except Fatal as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
