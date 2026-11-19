#!/usr/bin/env python3
"""acli-rest-get — read-only Jira REST lookups that acli cannot do. GET only, stdlib only, no flags.

  acli-rest-get.py transitions ISSUE-KEY
  acli-rest-get.py find-user QUERY
  acli-rest-get.py createmeta PROJECT-KEY [ISSUETYPE-ID]

Identity: site and email come from `acli jira auth status` only. The token is read from
~/.claude/atlassian.env, which must be mode 600 and hold three lines written for that identity:

  ACLI_REST_READ_SITE=<site host>
  ACLI_REST_READ_EMAIL=<email>
  ACLI_REST_READ_TOKEN=<scoped API token>

The token goes only into the Authorization header sent to api.atlassian.com. It is never printed.

find-user is a best-effort search with two limits: it returns one page of at most 50 users, and
Jira searches at most 1,000 users, so an empty result is not proof the user does not exist (a
caller without permission also gets an empty list).

Checked against a live site on 2026-11-19 with a scoped token (read:jira-work, read:jira-user).
"""
import base64
import json
import pathlib
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
ENV_FILE = pathlib.Path.home() / ".claude" / "atlassian.env"
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


def env_token(host, email, env_file):
    """Return the token from env_file, only if the file is private and written for this site and email."""
    try:
        if env_file.stat().st_mode & 0o077:
            raise Fatal(f"{env_file} is readable by group or others; run: chmod 600 {env_file}")
        text = env_file.read_text()
    except FileNotFoundError:
        raise Fatal(f"token file {env_file} not found (see the script docstring)") from None
    pairs = re.findall(r"^\s*(?:export\s+)?(ACLI_REST_READ_[A-Z]+)=(.*?)\s*$", text, re.M)
    values = {k: v[1:-1] if len(v) > 1 and v[0] == v[-1] and v[0] in "\"'" else v for k, v in pairs}
    for key, want in (("ACLI_REST_READ_SITE", host), ("ACLI_REST_READ_EMAIL", email)):
        if values.get(key) != want:
            raise Fatal(f"{key} in {env_file} does not match `acli jira auth status`")
    if not values.get("ACLI_REST_READ_TOKEN"):
        raise Fatal(f"ACLI_REST_READ_TOKEN is missing in {env_file}")
    return values["ACLI_REST_READ_TOKEN"]


def jira_session(opener, run, env_file):
    """Resolve the target and return jira_get(path, params) bound to it."""
    host, email = acli_identity(run)
    token = env_token(host, email, env_file)  # before any request
    cid = cloud_id(host, opener)
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


def main(argv, opener=None, run=run_command, env_file=ENV_FILE):
    try:
        lookup, args = parse_args(argv[1:])
        result = lookup(jira_session(opener or default_opener(), run, env_file), *args)
    except Fatal as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
