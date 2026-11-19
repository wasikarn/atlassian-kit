#!/usr/bin/env python3
"""acli-rest-get — read-only Jira REST lookups that acli cannot do. GET only, stdlib only, no flags.

  acli-rest-get.py transitions ISSUE-KEY
  acli-rest-get.py find-user QUERY
  acli-rest-get.py createmeta PROJECT-KEY [ISSUETYPE-ID]
  acli-rest-get.py api <jira|confluence> <PATH>   (raw GET-only read; jira /rest/api/3/*, confluence /wiki/api/v2/*)

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
import json
import pathlib
import re
import sys
import urllib.parse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from acli_rest_common import (  # noqa: E402  (shared with acli-rest-write.py)
    API_HOST, ENV_FILE, Fatal, acli_identity, cloud_id, default_opener, http_get,
    parse_json, read_env_file, run_command,
)

ISSUE_RE = re.compile(r"^[A-Z][A-Z0-9_]+-[0-9]+$")
PROJECT_RE = re.compile(r"^[A-Z][A-Z0-9_]+$")
ISSUETYPE_RE = re.compile(r"^[0-9]+$")
METHOD = "GET"  # the only method this script may send
FIND_USER_MAX = 50
USAGE = ("usage: acli-rest-get.py transitions ISSUE-KEY | find-user QUERY | "
         "createmeta PROJECT-KEY [ISSUETYPE-ID] | api <jira|confluence> <PATH>")
API_PATH_RE = re.compile(r"^/(rest/api/3/|wiki/api/v2/)[A-Za-z0-9_?&=./-]*$")


def env_token_for(host, email, env_file, product):
    """Token for an api read: the read token for jira, the scoped Confluence token for confluence."""
    values = read_env_file(env_file)
    if product == "jira":
        keys, token_key, want = (("ACLI_REST_READ_SITE", host), ("ACLI_REST_READ_EMAIL", email)), "ACLI_REST_READ_TOKEN", None
    else:
        keys, token_key, want = (("ACLI_REST_WRITE_SITE", host), ("ACLI_REST_WRITE_EMAIL", email)), "ACLI_REST_WRITE_CONFLUENCE_TOKEN", None
    for key, w in keys:
        if values.get(key) != w:
            raise Fatal(f"{key} in {env_file} does not match `acli jira auth status`")
    if not values.get(token_key):
        raise Fatal(f"{token_key} is missing in {env_file}")
    return values[token_key], base_url_for(product)


def base_url_for(product):
    # the api-version prefix rides inside PATH (path starts /rest/api/3/ or /wiki/api/v2/)
    return f"https://{API_HOST}/ex/{product}"


def api_session(opener, run, env_file, product):
    host, email = acli_identity(run)
    token, base = env_token_for(host, email, env_file, product)
    cid = cloud_id(host, opener)
    print(f"target: {host} ({cid}) as {email}", file=sys.stderr)
    def raw_get(path, params=None):
        url = base + f"/{cid}" + path + ("?" + urllib.parse.urlencode(params) if params else "")
        return parse_json(http_get(opener, url, (email, token)), API_HOST)
    return raw_get


def api_read(get, _product, path):
    return get(path)


def env_token(host, email, env_file):
    """Return the read token from env_file, only if the file is written for this site and email."""
    values = read_env_file(env_file)
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
    if cmd == "api" and len(rest) == 2:
        if rest[0] not in ("jira", "confluence"):
            raise Fatal(f"product must be jira or confluence, not {rest[0]!r}")
        if not API_PATH_RE.match(rest[1]) or (rest[0] == "jira" and not rest[1].startswith("/rest/api/3/")) \
                or (rest[0] == "confluence" and not rest[1].startswith("/wiki/api/v2/")):
            raise Fatal(f"path must start with /rest/api/3/ (jira) or /wiki/api/v2/ (confluence): {rest[1]!r}")
        return api_read, rest
    raise Fatal(USAGE)


def main(argv, opener=None, run=run_command, env_file=ENV_FILE):
    try:
        lookup, args = parse_args(argv[1:])
        if lookup is api_read:
            session = api_session(opener or default_opener(), run, env_file, args[0])
        else:
            session = jira_session(opener or default_opener(), run, env_file)
        result = lookup(session, *args)
    except Fatal as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
