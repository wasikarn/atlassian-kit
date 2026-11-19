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
rejected by the server (4xx); 3 sent but unverified — timeout or connection error once the write
started, a 5xx, or a read-back that does not match. Do not re-run `apply` at 3 before checking.

Credentials come from a mode-600 env file: ACLI_REST_WRITE_SITE, ACLI_REST_WRITE_EMAIL,
ACLI_REST_WRITE_JIRA_TOKEN, ACLI_REST_WRITE_CONFLUENCE_TOKEN. The default file is ~/.claude/atlassian.env
and must agree with `acli jira auth status`. --env-file names an alternate target (a test site); it must
be a different site than acli's, and the preview labels it ALTERNATE TARGET. The acli-guard hook sees
every call of this script; approving a preview covers calls made through it and nothing else.
Phase 1 registers no operation.
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
    http_request, read_env_file, run_command,
)

PRODUCT_BASE = {"jira": f"https://api.atlassian.com/ex/jira",
                "confluence": f"https://api.atlassian.com/ex/confluence"}
MAX_AGE = 30 * 60
FILE_KEYS = {"schema", "created", "operation", "args", "target", "base", "body_text"}
USAGE = ("usage: acli-rest-write.py plan <operation> [--... VALUE] [--env-file FILE] | "
         "apply <request-file> --confirm <12hex> [--env-file FILE]")

OPERATIONS = {}  # name -> {product, validate(flags)->args, plan(get,args)->(base,body), send(http,args,body_text)->text, readback(get,args,base,body_text,result)->bool}


def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)


def parse_flags(rest):
    flags, pos, i = {}, [], 0
    while i < len(rest):
        if rest[i].startswith("--") and len(rest[i]) > 2:
            if i + 1 >= len(rest):
                raise Fatal(f"flag {rest[i]} needs a value")
            flags[rest[i][2:]] = rest[i + 1]
            i += 2
        else:
            pos.append(rest[i])
            i += 1
    return flags, pos


def resolve_target(opener, run, flags, env_file, product):
    """Validate the target before any token is used. Return (label, host, email, cid, token, get)."""
    host, email = acli_identity(run)
    env = read_env_file(env_file)
    if "env-file" in flags:
        thost = env.get("ACLI_REST_WRITE_SITE", "")
        if not HOST_RE.match(thost):
            raise Fatal(f"ACLI_REST_WRITE_SITE in {env_file} is not a *.atlassian.net host")
        if thost == host:
            raise Fatal(f"the --env-file target is the same site as acli's; refusing to treat it as an alternate target")
        temail = env.get("ACLI_REST_WRITE_EMAIL", "")
        label = f"ALTERNATE TARGET {thost}"
    else:
        if env.get("ACLI_REST_WRITE_SITE") != host or env.get("ACLI_REST_WRITE_EMAIL") != email:
            raise Fatal(f"ACLI_REST_WRITE_SITE/EMAIL in {env_file} do not match the acli identity; the target may have changed")
        thost, temail, label = host, email, f"PRODUCTION {host}"
    for key, want in (("ACLI_REST_WRITE_SITE", thost), ("ACLI_REST_WRITE_EMAIL", temail)):
        if env.get(key) != want:
            raise Fatal(f"{key} in {env_file} does not name the target")
    token_key = f"ACLI_REST_WRITE_{product.upper()}_TOKEN"
    if not env.get(token_key):
        raise Fatal(f"{token_key} is missing in {env_file}")
    cid = cloud_id(thost, opener)
    target = {"host": thost, "cloudId": cid, "email": temail}
    base_url = f"{PRODUCT_BASE[product]}/{cid}"

    def get(path, params=None):
        url = base_url + path + ("?" + urllib.parse.urlencode(params) if params else "")
        return json.loads(http_request(opener, "GET", url, (temail, env[token_key])))

    return label, target, env[token_key], get


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
        raise Fatal(f"unknown operation: {pos[0]!r} (registered: none in phase 1)" if not OPERATIONS
                    else f"unknown operation: {pos[0]!r} (registered: {', '.join(sorted(OPERATIONS))})")
    args = op["validate"]({k: v for k, v in flags.items() if k != "env-file"})
    label, target, token, get = resolve_target(opener, run, flags, env_file, op["product"])
    base, body = op["plan"](get, args)
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
    if len(pos) != 1 or "confirm" not in flags:
        raise Fatal(USAGE)
    path, want = pathlib.Path(pos[0]), flags["confirm"]
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
    args = op["validate"](data["args"])
    label, target, token, get = resolve_target(opener, run, flags, env_file, op["product"])
    if data["target"].get("host") != target["host"] or data["target"].get("email") != target["email"]:
        raise Fatal("the target changed since the plan; plan again")
    base, body = op["plan"](get, args)
    if canonical(base) != canonical(data["base"]):
        raise Fatal("the live state changed since the plan; plan again")
    body_text = canonical(json.loads(data["body_text"]))
    if body_text != canonical(body):
        raise Fatal("the rebuilt request body does not match the previewed one; plan again")
    auth = (target["email"], token)
    send_base = f"{PRODUCT_BASE[op['product']]}/{target['cloudId']}"
    http = lambda method, path, payload: http_request(opener, method, send_base + path, auth, payload)
    try:
        result_text = op["send"](http, args, data["body_text"])
    except HttpError as e:
        if e.code < 500:
            return _exit2(e.code, f"HTTP {e.code} from the write")
        return _exit3(f"HTTP {e.code} from the write")
    except NetError as e:
        return _exit3(f"no answer from the server ({e})")
    try:
        result = json.loads(result_text)
    except ValueError:
        result = result_text[:200]
    if not op["readback"](get, args, base, data["body_text"], result):
        return _exit3("the read-back does not match what was sent", str(result)[:200])
    print(f"applied to {target['host']} and verified by read-back")
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
        raise Fatal(USAGE)
    except Fatal as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
