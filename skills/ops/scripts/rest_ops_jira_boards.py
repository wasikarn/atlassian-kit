"""Jira Software operations of acli-rest-write: filter-create, board-columns-set, board-delete, board-property-set."""

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


# --- operations: board-columns-set, board-delete, board-property-set (Jira Software) ----------
# No public API sets board columns, so board-columns-set uses Jira's internal greenhopper API. The board model
# (column ids, status ids AND names) is read from GET .../rapidviewconfig/editmodel; the PUT payload shape comes
# from third-party documentation and is UNVERIFIED until the first apply, which the plan says.

BOARD_ID_RE = re.compile(r"^[0-9]{1,9}$")
PROP_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,255}$")  # no dot: ".." must not reach the URL
EDITMODEL_PATH = "/rest/greenhopper/1.0/rapidviewconfig/editmodel"
COLUMNS_PATH = "/rest/greenhopper/1.0/rapidviewconfig/columns"


def _board_flag(flags, usage):
    value = _one(flags, "board")
    if value is None or not BOARD_ID_RE.match(str(value)):
        raise Fatal(f"usage: {usage}")
    return str(value)


def _parse_columns(raw):
    try:
        cols = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        raise Fatal("--columns is not valid JSON") from None
    if not isinstance(cols, list) or not cols:
        raise Fatal('--columns must be a non-empty JSON list: [{"name": "To Do", "statuses": ["To Do"]}, ...]')
    out, names, seen = [], set(), set()
    for c in cols:
        if not isinstance(c, dict) or set(c) != {"name", "statuses"}:
            raise Fatal("each column needs exactly the keys name and statuses")
        name, sts = c["name"], c["statuses"]
        if not isinstance(name, str) or not name.strip():
            raise Fatal("a column name must be a non-empty string")
        if not isinstance(sts, list) or not all(isinstance(s, str) and s.strip() for s in sts):
            raise Fatal(f"statuses of column {name!r} must be a list of non-empty status names")
        if name.strip().lower() in names:
            raise Fatal(f"column name {name!r} appears twice")
        names.add(name.strip().lower())
        for s in sts:
            if s.strip().lower() in seen:
                raise Fatal(f"status {s!r} is mapped to more than one column")
            seen.add(s.strip().lower())
        out.append({"name": name.strip(), "statuses": [s.strip() for s in sts]})
    return out


def _validate_board_columns_set(flags, pos=()):
    usage = "board-columns-set --board <id> --columns '<JSON list of {name, statuses}>'"
    if pos:
        raise Fatal(f"board-columns-set takes no positional arguments: {pos[0]!r}")
    _check_flags(flags, {"board", "columns"}, "board-columns-set")
    board = _board_flag(flags, usage)
    raw = _one(flags, "columns")
    if raw is None:
        raise Fatal(f"usage: {usage}")
    return {"board": board, "columns": canonical(_parse_columns(raw))}


def _plan_board_columns_set(get, args):
    model = get(EDITMODEL_PATH, {"rapidViewId": args["board"]})
    rl = model.get("rapidListConfig") if isinstance(model, dict) else None
    if not isinstance(rl, dict) or not isinstance(rl.get("mappedColumns"), list):
        raise Fatal("the board model has no rapidListConfig.mappedColumns; the internal API may have changed")
    current = [{"id": c.get("id"), "name": c.get("name"), "kan": bool(c.get("isKanPlanColumn")),
                "statuses": [{"id": str(s.get("id")), "name": s.get("name")} for s in c.get("mappedStatuses") or []]}
               for c in rl["mappedColumns"]]
    unmapped = [{"id": str(s.get("id")), "name": s.get("name")} for s in rl.get("unmappedStatuses") or []]
    by_name = {}
    for s in [s for c in current for s in c["statuses"]] + unmapped:
        by_name.setdefault(str(s["name"]).lower(), []).append(s["id"])
    old = {str(c["name"]).lower(): c for c in current}
    wanted, cols, new_ids = json.loads(args["columns"]), [], set()
    for w in wanted:
        ids = []
        for sname in w["statuses"]:
            found = by_name.get(sname.lower(), [])
            if not found:
                raise Fatal(f"status {sname!r} is not on board {args['board']} (statuses there: "
                            f"{', '.join(sorted({str(s['name']) for c in current for s in c['statuses']} | {str(u['name']) for u in unmapped}))})")
            if len(found) > 1:
                raise Fatal(f"status name {sname!r} matches {len(found)} statuses on the board; cannot choose")
            ids.append(found[0])
        new_ids.update(ids)
        prev = old.get(w["name"].lower())
        col = {"name": w["name"], "isKanPlanColumn": bool(prev and prev["kan"]), "mappedStatuses": [{"id": i} for i in ids]}
        if prev:
            col["id"] = prev["id"]
        cols.append(col)
    leaving = [str(s["name"]) for c in current for s in c["statuses"] if s["id"] not in new_ids]
    base = {"board": args["board"], "current": current, "new": wanted, "willUnmap": leaving}
    return base, {"rapidViewId": int(args["board"]), "mappedColumns": cols}


def _describe_board_columns_set(base, body):
    def show(cols):
        return "; ".join(f"{c['name']}[{', '.join(s if isinstance(s, str) else str(s['name']) for s in c['statuses'])}]"
                         for c in cols)
    return [f"OVERWRITES the whole column set of board {base['board']} ({len(base['current'])} columns now, {len(base['new'])} after)",
            f"current: {show(base['current'])}",
            f"new: {show(base['new'])}",
            "statuses leaving the board: " + (", ".join(base["willUnmap"]) if base["willUnmap"] else "none"),
            "UNVERIFIED: the internal greenhopper payload shape has not been confirmed on this site; apply it on one "
            "board first and check the board in the UI (columns can be set back there)."]


def _send_board_columns_set(http, args, base, body_text):
    return http("PUT", COLUMNS_PATH, body_text.encode(), "application/json", {"X-Atlassian-Token": "no-check"})


def _readback_board_columns_set(get, args, base, body_text, result):
    cfg = get(f"/rest/agile/1.0/board/{args['board']}/configuration", {})
    cols = (cfg.get("columnConfig") or {}).get("columns") or []
    want = json.loads(body_text)["mappedColumns"]
    if [c.get("name") for c in cols] != [w["name"] for w in want]:
        return False
    return all({str(s.get("id")) for s in c.get("statuses") or []} == {str(m["id"]) for m in w["mappedStatuses"]}
               for c, w in zip(cols, want))


OPERATIONS["board-columns-set"] = {"product": "jira", "validate": _validate_board_columns_set,
                                   "plan": _plan_board_columns_set, "send": _send_board_columns_set,
                                   "readback": _readback_board_columns_set, "describe": _describe_board_columns_set}


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
