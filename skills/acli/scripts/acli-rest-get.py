#!/usr/bin/env python3
"""acli-rest-get — read-only Jira REST lookups that acli cannot do. GET only, stdlib only.

  acli-rest-get.py transitions ISSUE-KEY
  acli-rest-get.py find-user QUERY
  acli-rest-get.py createmeta PROJECT-KEY [ISSUETYPE-ID]

Identity: site and email come from `acli jira auth status` only (no override flag). The token is read
from the macOS Keychain (service acli-rest-read:<host>, account <email>) and goes only into the
Authorization header sent to api.atlassian.com. It is never printed.

Unverified until the first live call: the response key "values" for createmeta, and the
tenant_info endpoint used to resolve the cloudId.
"""
import base64
import json
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

HOST_RE = re.compile(r"^[a-z0-9-]+\.atlassian\.net$")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
ISSUE_RE = re.compile(r"^[A-Z][A-Z0-9_]+-[0-9]+$")
PROJECT_RE = re.compile(r"^[A-Z][A-Z0-9_]+$")
API = "https://api.atlassian.com"
TIMEOUT = 30
FIND_USER_MAX = 50


class Fatal(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # a 3xx then raises HTTPError: never follow it with the credential attached


def default_opener():
    return urllib.request.build_opener(_NoRedirect)


def acli_identity(run=None):
    run = run or (lambda: subprocess.run(["acli", "jira", "auth", "status"], capture_output=True, text=True))
    r = run()
    if r.returncode != 0:
        raise Fatal("acli jira auth status failed; run `acli jira auth login` first")
    sites = re.findall(r"^\s*Site:\s*(\S+)\s*$", r.stdout, re.M)
    emails = re.findall(r"^\s*Email:\s*(\S+)\s*$", r.stdout, re.M)
    if len(sites) != 1 or len(emails) != 1:
        raise Fatal("acli jira auth status: expected exactly one Site and one Email")
    host = re.sub(r"^https?://", "", sites[0]).rstrip("/")
    if not HOST_RE.match(host):
        raise Fatal(f"site {host!r} is not a *.atlassian.net host")
    if "@" not in emails[0]:
        raise Fatal("acli jira auth status: Email is not an email address")
    return host, emails[0]


def call(opener, url, auth=None):
    """GET url and return the body text. auth=(email, token) is sent only to api.atlassian.com."""
    netloc = urllib.parse.urlsplit(url).netloc
    headers = {"Accept": "application/json"}
    if auth is not None:
        if netloc != "api.atlassian.com":
            raise Fatal(f"refusing to send the credential to {netloc}")
        raw = f"{auth[0]}:{auth[1]}".encode()
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode()
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with opener.open(req, timeout=TIMEOUT) as resp:
            return resp.read().decode()
    except urllib.error.HTTPError as e:
        detail = e.read(500).decode(errors="replace")
        raise Fatal(f"HTTP {e.code} from {netloc}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise Fatal(f"request to {netloc} failed: {type(e).__name__}") from None


def cloud_id(host, opener):
    cid = json.loads(call(opener, f"https://{host}/_edge/tenant_info")).get("cloudId", "")
    if not UUID_RE.match(cid):
        raise Fatal("cloudId lookup did not return a UUID")
    return cid


def keychain_token(host, email, run=None):
    service = f"acli-rest-read:{host}"
    run = run or (lambda: subprocess.run(
        ["security", "find-generic-password", "-s", service, "-a", email, "-w"],
        capture_output=True, text=True))
    r = run()
    if r.returncode != 0:
        raise Fatal(f"no Keychain item for service {service!r}, account {email!r}")
    return r.stdout.rstrip("\n")


def session(opener, run_acli=None, run_keychain=None):
    host, email = acli_identity(run_acli)
    cid = cloud_id(host, opener)
    token = keychain_token(host, email, run_keychain)
    print(f"target: {host} ({cid}) as {email}", file=sys.stderr)
    base = f"{API}/ex/jira/{cid}"

    def get(path, params=None):
        url = base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        return json.loads(call(opener, url, (email, token)))

    return get


def transitions(get, key):
    if not ISSUE_RE.match(key):
        raise Fatal(f"not an issue key: {key!r}")
    data = get(f"/rest/api/3/issue/{key}/transitions")
    return [{"id": t["id"], "name": t["name"], "to": (t.get("to") or {}).get("name")}
            for t in data.get("transitions", [])]


def find_user(get, query):
    rows = get("/rest/api/3/user/search", {"query": query, "maxResults": FIND_USER_MAX})
    if not isinstance(rows, list):
        raise Fatal("unexpected user/search shape (expected an array)")
    if not rows:
        print("warning: no match found. This is not proof the user does not exist: the search covers "
              "at most 1,000 users, and a caller without permission also gets an empty list.",
              file=sys.stderr)
    elif len(rows) >= FIND_USER_MAX:
        print(f"warning: {FIND_USER_MAX} results (one page), narrow the query", file=sys.stderr)
    return [{"accountId": u.get("accountId"), "displayName": u.get("displayName"), "active": u.get("active")}
            for u in rows]


def paged(get, path):
    out, start = [], 0
    while True:
        page = get(path, {"startAt": start, "maxResults": 50})
        values, is_last = page.get("values"), page.get("isLast")
        if not isinstance(values, list) or not isinstance(is_last, bool):
            raise Fatal("unexpected createmeta shape (need values[] and isLast)")
        if not values and not is_last:
            raise Fatal("createmeta returned an empty page before the last one")
        out.extend(values)
        start += len(values)
        if is_last:
            return out


def createmeta(get, project, issuetype=None):
    if not PROJECT_RE.match(project):
        raise Fatal(f"not a project key: {project!r}")
    base = f"/rest/api/3/issue/createmeta/{project}/issuetypes"
    return paged(get, base if issuetype is None else f"{base}/{issuetype}")


USAGE = ("usage: acli-rest-get.py transitions ISSUE-KEY | find-user QUERY | "
         "createmeta PROJECT-KEY [ISSUETYPE-ID]")


def main(argv, opener=None, run_acli=None, run_keychain=None):
    try:
        if len(argv) < 2:
            raise Fatal(USAGE)
        cmd, args = argv[1], argv[2:]
        get = session(opener or default_opener(), run_acli, run_keychain)
        if cmd == "transitions" and len(args) == 1:
            result = transitions(get, args[0])
        elif cmd == "find-user" and len(args) == 1:
            result = find_user(get, args[0])
        elif cmd == "createmeta" and len(args) in (1, 2):
            result = createmeta(get, *args)
        else:
            raise Fatal(USAGE)
    except Fatal as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
