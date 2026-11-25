"""Jira Software operations of acli-rest-write: filter-create, board-delete, board-property-set."""

import json
import re

from acli_rest_common import Fatal, HttpError
from rest_write_base import OPERATIONS, _check_flags, _one, canonical


# --- operation: filter-create (Jira) ----------------------------------------
# Creates one saved filter. Without --share-project the filter is private to the token's user, so a board
# built on it is invisible to everyone else.

def _validate_filter_create(flags, pos=()):
    if pos:
        raise Fatal(f"filter-create takes no positional arguments: {pos[0]!r}")
    _check_flags(flags, {"name", "jql", "description", "share-project"}, "filter-create")
    for f in ("name", "jql", "description", "share-project"):
        _one(flags, f)
    if not str(flags.get("name", "")).strip() or not str(flags.get("jql", "")).strip():
        raise Fatal("usage: filter-create --name <name> --jql <jql> [--description <text>] [--share-project KEY]")
    if "share-project" in flags and not re.match(r"^[A-Z][A-Z0-9_]+$", str(flags["share-project"])):
        raise Fatal("--share-project must be a Jira project key")
    return {k: str(flags[k]) for k in ("name", "jql", "description", "share-project") if k in flags}


def _plan_filter_create(get, args):
    found = get("/rest/api/3/filter/search", {"filterName": args["name"]}).get("values") or []
    if any(str(f.get("name")) == args["name"] for f in found):
        raise Fatal(f"a filter named {args['name']!r} already exists (the list is what this account can see)")
    body = {"name": args["name"], "jql": args["jql"]}
    if "description" in args:
        body["description"] = args["description"]
    base: dict = {"shareProjectId": None}
    if "share-project" in args:
        pid = str(get(f"/rest/api/3/project/{args['share-project']}", {}).get("id", ""))
        if not pid.isdigit():
            raise Fatal(f"project {args['share-project']} did not expose a numeric id")
        body["sharePermissions"] = [{"type": "project", "project": {"id": pid}}]
        base["shareProjectId"] = pid
    return base, body


def _send_filter_create(http, args, base, body_text):
    return http("POST", "/rest/api/3/filter", body_text.encode())


def _readback_filter_create(get, args, base, body_text, result):
    fid = str(result.get("id", "")) if isinstance(result, dict) else ""
    if not fid:
        return False
    f = get(f"/rest/api/3/filter/{fid}", {"expand": "sharePermissions"})
    if str(f.get("name")) != args["name"]:
        return False
    if base["shareProjectId"] is None:
        return True
    return any(str((s.get("project") or {}).get("id")) == base["shareProjectId"] for s in f.get("sharePermissions") or [])


OPERATIONS["filter-create"] = {"product": "jira", "validate": _validate_filter_create,
                               "plan": _plan_filter_create, "send": _send_filter_create,
                               "readback": _readback_filter_create}


# --- operations: board-delete, board-property-set (Jira Software) ----------
BOARD_ID_RE = re.compile(r"^[0-9]{1,9}$")
PROP_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,255}$")  # no dot: ".." must not reach the URL


def _board_flag(flags, usage):
    value = _one(flags, "board")
    if value is None or not BOARD_ID_RE.match(str(value)):
        raise Fatal(f"usage: {usage}")
    return str(value)


def _validate_board_delete(flags, pos=()):
    usage = "board-delete --board <id>"
    if pos:
        raise Fatal(f"board-delete takes no positional arguments: {pos[0]!r}")
    _check_flags(flags, {"board"}, "board-delete")
    return {"board": _board_flag(flags, usage)}


def _plan_board_delete(get, args):
    b = get(f"/rest/agile/1.0/board/{args['board']}", {})
    return {"board": args["board"], "name": b.get("name"), "type": b.get("type"),
            "project": (b.get("location") or {}).get("projectKey")}, {}


def _describe_board_delete(base, body):
    return [f"IRREVERSIBLE: board {base['board']} ({base['name']!r}, {base['type']}, project {base['project']}) is deleted. "
            "Jira keeps its filter and issues; a new board on that filter needs acli jira board create --filter-id."]


def _send_board_delete(http, args, base, body_text):
    return http("DELETE", f"/rest/agile/1.0/board/{base['board']}", None)


def _readback_board_delete(get, args, base, body_text, result):
    try:
        get(f"/rest/agile/1.0/board/{base['board']}", {})
    except HttpError as e:
        if e.code == 404:
            return True
        raise
    return False


OPERATIONS["board-delete"] = {"product": "jira", "validate": _validate_board_delete,
                              "plan": _plan_board_delete, "send": _send_board_delete,
                              "readback": _readback_board_delete, "describe": _describe_board_delete}


def _validate_board_property_set(flags, pos=()):
    usage = "board-property-set --board <id> --key <property key> --value '<JSON>'"
    if pos:
        raise Fatal(f"board-property-set takes no positional arguments: {pos[0]!r}")
    _check_flags(flags, {"board", "key", "value"}, "board-property-set")
    board, key, raw = _board_flag(flags, usage), _one(flags, "key"), _one(flags, "value")
    if key is None or not PROP_KEY_RE.match(str(key)) or raw is None:
        raise Fatal(f"usage: {usage}")
    try:
        value = json.loads(raw)
    except ValueError:
        raise Fatal("--value is not valid JSON") from None
    return {"board": board, "key": str(key), "value": canonical(value)}


def _plan_board_property_set(get, args):
    try:
        cur = get(f"/rest/agile/1.0/board/{args['board']}/properties/{args['key']}", {}).get("value")
        exists = True
    except HttpError as e:
        if e.code != 404:
            raise
        cur, exists = None, False
    return {"board": args["board"], "key": args["key"], "exists": exists, "current": cur}, json.loads(args["value"])


def _describe_board_property_set(base, body):
    return [f"board {base['board']} property {base['key']}: "
            f"{'current ' + canonical(base['current']) if base['exists'] else 'not set yet'} -> new {canonical(body)}"]


def _send_board_property_set(http, args, base, body_text):
    return http("PUT", f"/rest/agile/1.0/board/{base['board']}/properties/{base['key']}", body_text.encode())


def _readback_board_property_set(get, args, base, body_text, result):
    got = get(f"/rest/agile/1.0/board/{base['board']}/properties/{base['key']}", {}).get("value")
    return canonical(got) == body_text


OPERATIONS["board-property-set"] = {"product": "jira", "validate": _validate_board_property_set,
                                    "plan": _plan_board_property_set, "send": _send_board_property_set,
                                    "readback": _readback_board_property_set, "describe": _describe_board_property_set}
