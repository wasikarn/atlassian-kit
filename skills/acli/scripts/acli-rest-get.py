#!/usr/bin/env python3
"""acli-rest-get — read-only Jira REST lookups that acli cannot do. GET only, stdlib only, no flags.

  acli-rest-get.py transitions ISSUE-KEY
  acli-rest-get.py find-user QUERY
  acli-rest-get.py createmeta PROJECT-KEY [ISSUETYPE-ID]

Identity: site and email come from `acli jira auth status` only. The token is read from the macOS
Keychain (service acli-rest-read:<host>, account <email>) and goes only into the Authorization
header sent to api.atlassian.com. It is never printed.

find-user is a best-effort search with two limits: it returns one page of at most 50 users, and
Jira searches at most 1,000 users, so an empty result is not proof the user does not exist (a
caller without permission also gets an empty list).

Checked against a live site on 2026-11-19 with a scoped token (read:jira-work, read:jira-user).
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
ISSUETYPE_RE = re.compile(r"^[0-9]+$")
API_HOST = "api.atlassian.com"
METHOD = "GET"  # the only method this script may send
TIMEOUT = 30
FIND_USER_MAX = 50
USAGE = ("usage: acli-rest-get.py transitions ISSUE-KEY | find-user QUERY | "
         "createmeta PROJECT-KEY [ISSUETYPE-ID]")


class Fatal(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # a 3xx then raises HTTPError: never follow it with the credential attached


def default_opener():
    return urllib.request.build_opener(_NoRedirect)


def run_command(cmd, spawn=subprocess.run):
    try:
        return spawn(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        raise Fatal(f"`{cmd[0]}` not found on PATH") from None


def parse_json(text, source):
    try:
        return json.loads(text)
    except ValueError:
        raise Fatal(f"response from {source} is not JSON") from None


def acli_identity(run):
    r = run(["acli", "jira", "auth", "status"])
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


def http_get(opener, url, auth=None):
    """GET url and return the body text. auth=(email, token) is sent only to api.atlassian.com."""
    netloc = urllib.parse.urlsplit(url).netloc
    headers = {"Accept": "application/json"}
    if auth is not None:
        if netloc != API_HOST:
            raise Fatal(f"refusing to send the credential to {netloc}")
        raw = f"{auth[0]}:{auth[1]}".encode()
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode()
    req = urllib.request.Request(url, headers=headers, method=METHOD)
    try:
        with opener.open(req, timeout=TIMEOUT) as resp:
            return resp.read().decode()
    except urllib.error.HTTPError as e:
        detail = e.read(500).decode(errors="replace")
        raise Fatal(f"HTTP {e.code} from {netloc}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise Fatal(f"request to {netloc} failed: {type(e).__name__}") from None


def cloud_id(host, opener):
    info = parse_json(http_get(opener, f"https://{host}/_edge/tenant_info"), host)
    cid = info.get("cloudId", "") if isinstance(info, dict) else ""
    if not isinstance(cid, str) or not UUID_RE.match(cid):
        raise Fatal("cloudId lookup did not return a UUID")
    return cid


def keychain_token(host, email, run):
    service = f"acli-rest-read:{host}"
    r = run(["security", "find-generic-password", "-s", service, "-a", email, "-w"])
    if r.returncode != 0:
        raise Fatal(f"no Keychain item for service {service!r}, account {email!r}")
    return r.stdout.rstrip("\n")


def jira_session(opener, run):
    """Resolve the target and return jira_get(path, params) bound to it."""
    host, email = acli_identity(run)
    cid = cloud_id(host, opener)
    token = keychain_token(host, email, run)
    print(f"target: {host} ({cid}) as {email}", file=sys.stderr)
    base = f"https://{API_HOST}/ex/jira/{cid}"

    def jira_get(path, params=None):
        url = base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        return parse_json(http_get(opener, url, (email, token)), API_HOST)

    return jira_get


def transitions(jira_get, key):
    data = jira_get(f"/rest/api/3/issue/{key}/transitions")
    return [{"id": t["id"], "name": t["name"], "to": (t.get("to") or {}).get("name")}
            for t in data.get("transitions", [])]


def find_user(jira_get, query):
    rows = jira_get("/rest/api/3/user/search", {"query": query, "maxResults": FIND_USER_MAX})
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


def createmeta(jira_get, project, issuetype=None):
    path, items_key = f"/rest/api/3/issue/createmeta/{project}/issuetypes", "issueTypes"
    if issuetype is not None:
        path, items_key = f"{path}/{issuetype}", "fields"
    out = []
    while True:
        page = jira_get(path, {"startAt": len(out), "maxResults": 50})
        items, total = page.get(items_key), page.get("total")
        if not isinstance(items, list) or not isinstance(total, int):
            raise Fatal(f"unexpected createmeta shape (need {items_key}[] and total)")
        out.extend(items)
        if len(out) >= total:
            return out
        if not items:
            raise Fatal("createmeta returned an empty page before reaching total")


def parse_args(args):
    """Validate everything before any subprocess or request. Return (lookup function, its args)."""
    if not args:
        raise Fatal(USAGE)
    cmd, rest = args[0], args[1:]
    if cmd == "transitions" and len(rest) == 1:
        if not ISSUE_RE.match(rest[0]):
            raise Fatal(f"not an issue key: {rest[0]!r}")
        return transitions, rest
    if cmd == "find-user" and len(rest) == 1:
        return find_user, rest
    if cmd == "createmeta" and len(rest) in (1, 2):
        if not PROJECT_RE.match(rest[0]):
            raise Fatal(f"not a project key: {rest[0]!r}")
        if len(rest) == 2 and not ISSUETYPE_RE.match(rest[1]):
            raise Fatal(f"not an issue type id (digits only): {rest[1]!r}")
        return createmeta, rest
    raise Fatal(USAGE)


def main(argv, opener=None, run=run_command):
    try:
        lookup, args = parse_args(argv[1:])
        result = lookup(jira_session(opener or default_opener(), run), *args)
    except Fatal as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
