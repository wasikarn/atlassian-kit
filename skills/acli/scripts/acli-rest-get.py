#!/usr/bin/env python3
"""acli-rest-get — read-only Jira/Confluence REST lookups that acli cannot do. GET only, stdlib only, no flags.

  acli-rest-get.py transitions ISSUE-KEY
  acli-rest-get.py find-user QUERY
  acli-rest-get.py createmeta PROJECT-KEY [ISSUETYPE-ID]
  acli-rest-get.py api <jira|confluence> <PATH>   (raw GET-only read; jira /rest/api/3/*, confluence /wiki/api/v2/*)

Identity: site and email come from `acli jira auth status` only. The token is read from
~/.claude/atlassian.env, which must be mode 600 and hold the keys written for that identity:
for jira (and the three lookups) the read trio

  ACLI_REST_READ_SITE=<site host>
  ACLI_REST_READ_EMAIL=<email>
  ACLI_REST_READ_TOKEN=<scoped API token>

and for `api confluence` the write script's own trio (its token is the granular Confluence one):

  ACLI_REST_WRITE_SITE=<site host>
  ACLI_REST_WRITE_EMAIL=<email>
  ACLI_REST_WRITE_CONFLUENCE_TOKEN=<granular API token>

The token goes only into the Authorization header sent to api.atlassian.com. It is never printed.
api PATHS are refused unless they are pure /rest/api/3/… or /wiki/api/v2/… segments (no dots, so no
traversal); params may use ?, &, =, %, and ,.

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
    API_HOST, ENV_FILE, Fatal, acli_identity, cloud_id, default_opener,
    http_request, parse_json, read_env_file, run_command,
)

ISSUE_RE = re.compile(r"^[A-Z][A-Z0-9_]+-[0-9]+$")
PROJECT_RE = re.compile(r"^[A-Z][A-Z0-9_]+$")
ISSUETYPE_RE = re.compile(r"^[0-9]+$")
METHOD = "GET"  # the only method this script may send: every request goes through http_request (opener, METHOD, …)
FIND_USER_MAX = 50
USAGE = ("usage: acli-rest-get.py transitions ISSUE-KEY | find-user QUERY | "
         "createmeta PROJECT-KEY [ISSUETYPE-ID] | api <jira|confluence> <PATH>")
API_PATH_RE = re.compile(r"^/(rest/api/3/|wiki/api/v2/)[A-Za-z0-9_?&=%,/-]*$")


def product_token(host, email, env_file, product):
    """Token, and the /ex base without the cloudId, for one product: read token for jira,
    the scoped Confluence token for confluence. Only if the file is written for this identity."""
    values = read_env_file(env_file)
    if product == "jira":
        pairs, token_key = (("ACLI_REST_READ_SITE", host), ("ACLI_REST_READ_EMAIL", email)), "ACLI_REST_READ_TOKEN"
    else:
        pairs, token_key = (("ACLI_REST_WRITE_SITE", host), ("ACLI_REST_WRITE_EMAIL", email)), "ACLI_REST_WRITE_CONFLUENCE_TOKEN"
    for key, want in pairs:
        if values.get(key) != want:
            raise Fatal(f"{key} in {env_file} does not match `acli jira auth status`")
    if not values.get(token_key):
        raise Fatal(f"{token_key} is missing in {env_file}")
    return values[token_key], f"https://{API_HOST}/ex/{product}"


def read_session(opener, run, env_file, product="jira"):
    """Resolve the target and return get(path, params) bound to it, METHOD-only."""
    host, email = acli_identity(run)
    token, base = product_token(host, email, env_file, product)  # before any request
    cid = cloud_id(host, opener)
    print(f"target: {host} ({cid}) as {email}", file=sys.stderr)

    def get(path, params=None):
        url = f"{base}/{cid}" + path + ("?" + urllib.parse.urlencode(params) if params else "")
        return parse_json(http_request(opener, METHOD, url, (email, token)), API_HOST)

    return get


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
    """Validate everything before any subprocess or request. Return (session builder, lookup, its args)."""
    if not args:
        raise Fatal(USAGE)
    cmd, rest = args[0], args[1:]
    if cmd == "transitions" and len(rest) == 1:
        if not ISSUE_RE.match(rest[0]):
            raise Fatal(f"not an issue key: {rest[0]!r}")
        return read_session, transitions, rest
    if cmd == "find-user" and len(rest) == 1:
        return read_session, find_user, rest
    if cmd == "createmeta" and len(rest) in (1, 2):
        if not PROJECT_RE.match(rest[0]):
            raise Fatal(f"not a project key: {rest[0]!r}")
        if len(rest) == 2 and not ISSUETYPE_RE.match(rest[1]):
            raise Fatal(f"not an issue type id (digits only): {rest[1]!r}")
        return read_session, createmeta, rest
    if cmd == "api" and len(rest) == 2:
        if rest[0] not in ("jira", "confluence"):
            raise Fatal(f"product must be jira or confluence, not {rest[0]!r}")
        path = rest[1]
        if not API_PATH_RE.match(path) or (rest[0] == "jira" and not path.startswith("/rest/api/3/")) \
                or (rest[0] == "confluence" and not path.startswith("/wiki/api/v2/")):
            raise Fatal(f"not an api path: path must start with /rest/api/3/ (jira) or /wiki/api/v2/ "
                        f"(confluence), alphanumerics + ?&=%,/ only: {path!r}")
        if "." in path or "." in urllib.parse.unquote(path):
            raise Fatal(f"not an api path: dots are not allowed in or decoded into it: {path!r}")
        product = rest[0]
        return (lambda opener, run, env_file=ENV_FILE: read_session(opener, run, env_file, product)), \
            api_read, (rest[1],)
    raise Fatal(USAGE)


def api_read(get, path):
    return get(path)


def main(argv, opener=None, run=run_command, env_file=ENV_FILE):
    try:
        builder, lookup, args = parse_args(argv[1:])
        result = lookup(builder(opener or default_opener(), run, env_file), *args)
    except Fatal as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
