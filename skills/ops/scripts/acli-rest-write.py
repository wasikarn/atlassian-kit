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
ACLI_REST_WRITE_JIRA_TOKEN, ACLI_REST_WRITE_CONFLUENCE_TOKEN (plus ACLI_REST_WRITE_CONFLUENCE_FILE_TOKEN,
a classic token with only write:confluence-file, for attachment-upload). The default file is ~/.claude/atlassian.env
and must agree with `acli jira auth status`. --env-file names an alternate target (a test site); it must
be a different site than acli's, and the preview labels it ALTERNATE TARGET. The acli-guard hook
denies every subagent call of this script; approving a preview covers calls made through it and
nothing else.
Operations: Confluence page-create / page-fetch (read-only; writes the base+adf files) / page-update /
page-delete (to the trash, never purge) / attachment-upload (one image, v1 multipart);
Jira issue-set / version-create / version-edit / version-delete / issue-delete / filter-create / board-columns-set / board-delete / board-property-set.
"""

import datetime
import hashlib
import json
import os
import pathlib
import sys
import tempfile
import urllib.parse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from acli_rest_common import (  # noqa: E402
    ENV_FILE, Fatal, HOST_RE, HttpError, NetError, acli_identity,
    cloud_id, default_opener, http_request, read_env_file, run_command,
)
from rest_write_base import OPERATIONS, _check_flags, _one, canonical, parse_flags  # noqa: E402
import rest_ops_confluence, rest_ops_jira_boards, rest_ops_jira_issues  # noqa: E402,F401  (each registers its operations)

PRODUCT_BASE = {"jira": f"https://api.atlassian.com/ex/jira",
                "confluence": f"https://api.atlassian.com/ex/confluence"}
MAX_AGE = 30 * 60
FILE_KEYS = {"schema", "created", "operation", "args", "target", "base", "body_text"}
USAGE = ("usage: acli-rest-write.py plan <operation> [--... VALUE] [--env-file FILE] | "
         "apply <request-file> --confirm <12hex> [--env-file FILE]")


def resolve_target(opener, run, flags, env_file, product, send_api=None, send_token_key=None):
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
    send_key = send_token_key or token_key  # reads always use token_key; only the write call may use another
    if not env.get(send_key):
        raise Fatal(f"{send_key} is missing in {used}")
    cid = cloud_id(thost, opener)
    target = {"host": thost, "cloudId": cid, "email": temail}
    api_suffix = {"jira": "", "confluence": "/wiki/api/v2"}[product]
    base_url = f"{PRODUCT_BASE[product]}/{cid}{api_suffix}"

    def get(path, params=None):
        url = base_url + path + ("?" + urllib.parse.urlencode(params) if params else "")
        return json.loads(http_request(opener, "GET", url, (temail, env[token_key])))

    send_base = base_url if send_api is None else f"{PRODUCT_BASE[product]}/{cid}{send_api}"
    return label, target, env[send_key], get, send_base


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
    label, target, token, get, _ = resolve_target(opener, run, flags, env_file, op["product"], None,
                                                   op.get("send_token_key"))
    base, body = op["plan"](get, args)
    if op.get("planOnly"):
        print(json.dumps({"base": base, "body": body}, ensure_ascii=False))
        return 0
    for note in (op.get("notes") or _notes)(args, flags):
        print(f"note: {note}")
    for note in (op.get("describe") or (lambda b, y: []))(base, body):
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
    label, target, token, get, send_base = resolve_target(opener, run, flags, env_file, op["product"], op.get("send_api"),
                                                           op.get("send_token_key"))
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
    http = lambda method, path, payload, ctype="application/json", extra=None: http_request(
        opener, method, send_base + path, auth, payload, ctype, extra)
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
    except (Fatal, ValueError, TypeError, KeyError, AttributeError, HttpError, NetError) as e:
        return _exit3(f"the read-back failed ({e})")
    if not ok:
        return _exit3("the read-back does not match what was sent", str(result)[:200])
    print(f"applied to {target['host']} and verified by read-back")
    if data["operation"] == "filter-create" and isinstance(result, dict):
        print(f"filter id: {result.get('id')}")
    path.unlink()
    return 0



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
