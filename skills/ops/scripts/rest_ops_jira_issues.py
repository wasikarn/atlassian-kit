"""Jira issue and version operations of acli-rest-write: issue-set, issue-delete, version-create/edit/delete."""

import json
import pathlib
import re
import urllib.parse

from acli_rest_common import Fatal, HttpError
from rest_write_base import (
    KEY_RE, OPERATIONS, PAGE_ID_RE, _check_flags, _jira_get_list, _names,
    _one, _read_adf,
)


# --- operation: issue-set (Jira) --------------------------------------------

CHANGE_FLAGS = {"priority", "parent", "environment-adf", "add-fix-version", "remove-fix-version",
                "add-affects-version", "remove-affects-version"}


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


def _readback_version_delete(get, args, base, body_text, result):
    try:
        get(f"/rest/api/3/version/{args['id']}", {})
    except HttpError as e:
        if e.code == 404:
            return True
        raise
    return False


def _validate_version_edit(flags, pos=()):
    _check_flags(flags, {"id", "name", "description", "description-file", "archived", "released",
                         "release-date"}, "version-edit")
    if pos:
        raise Fatal(f"version-edit takes no positional arguments: {pos[0]!r}")
    if "id" not in flags:
        raise Fatal("usage: version-edit --id <version id> [--name N] [--description D | --description-file "
                    "FILE] [--released true|false] [--archived true|false] [--release-date YYYY-MM-DD]")
    if len(flags) == 1:
        raise Fatal("usage: version-edit needs one field besides --id")
    args = {"id": str(flags["id"])}
    if "name" in flags:
        args["name"] = str(flags["name"])
    if "description" in flags:
        args["description"] = str(flags["description"])
    if "description-file" in flags:
        p = pathlib.Path(str(flags["description-file"]))
        try:
            args["description"] = p.read_text()
        except OSError as e:
            raise Fatal(f"cannot read --description-file {p}: {type(e).__name__}") from None
    for boolean in ("released", "archived"):
        if boolean in flags:
            low = str(flags[boolean]).lower()
            if low not in ("true", "false"):
                raise Fatal(f"--{boolean} must be true or false, not {flags[boolean]!r}")
            args[boolean] = low == "true"
    if "release-date" in flags:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(flags["release-date"])):
            raise Fatal("--release-date must be YYYY-MM-DD")
        args["release-date"] = str(flags["release-date"])  # CLI name: apply re-validates the stored args
    return args


_VERSION_EDIT_WIRE = (("name", "name"), ("description", "description"), ("released", "released"),
                      ("archived", "archived"), ("release-date", "releaseDate"))


def _plan_version_edit(get, args):
    if not PAGE_ID_RE.match(args["id"]):
        raise Fatal("--id must be a numeric version id")
    v = get(f"/rest/api/3/version/{args['id']}", {})
    base = {k: v.get(k) for k in ("id", "name", "description", "archived", "released", "releaseDate")}
    body = {wire: args[cli] for cli, wire in _VERSION_EDIT_WIRE if cli in args}
    return base, body


def _send_version_edit(http, args, base, body_text):
    return http("PUT", f"/rest/api/3/version/{args['id']}", body_text.encode())


def _readback_version_edit(get, args, base, body_text, result):
    v = get(f"/rest/api/3/version/{args['id']}", {})
    sent = json.loads(body_text)
    return all(v.get(k) == sent[k] for k in sent)


def _validate_version_delete(flags, pos=()):
    _check_flags(flags, {"id", "delete-fixed-issues", "delete-affected-issues", "move-fixed-to",
                         "move-affected-to"}, "version-delete")
    if pos:
        raise Fatal(f"version-delete takes no positional arguments: {pos[0]!r}")
    if "id" not in flags:
        raise Fatal("usage: version-delete --id <version id> [--delete-fixed-issues true] "
                    "[--delete-affected-issues true] [--move-fixed-to ID] [--move-affected-to ID]")
    args = {"id": str(flags["id"])}
    for toggle in ("delete-fixed-issues", "delete-affected-issues"):
        if str(flags.get(toggle, "")).lower() == "true":
            args[toggle] = True
    for flag in ("move-fixed-to", "move-affected-to"):
        if flag in flags:
            if not PAGE_ID_RE.match(str(flags[flag])):
                raise Fatal(f"--{flag} must be a numeric version id")
            args[flag] = str(flags[flag])
    return args


def _plan_version_delete(get, args):
    if not PAGE_ID_RE.match(args["id"]):
        raise Fatal("--id must be a numeric version id")
    v = get(f"/rest/api/3/version/{args['id']}", {})
    base = {"id": str(v.get("id")), "name": v.get("name"), "projectId": v.get("projectId"),
            "description": v.get("description")}
    return base, {}


_DELETE_QUERY = (("delete-fixed-issues", "deleteFixedIssues"), ("delete-affected-issues", "deleteAffectedIssues"),
                 ("move-fixed-to", "moveFixedIssuesTo"), ("move-affected-to", "moveAffectedIssuesTo"))


def _send_version_delete(http, args, base, body_text):
    query = [(wire, "true" if args[cli] is True else args[cli]) for cli, wire in _DELETE_QUERY if cli in args]
    qs = ("?" + urllib.parse.urlencode(query)) if query else ""
    return http("DELETE", f"/rest/api/3/version/{args['id']}{qs}", None)


OPERATIONS["issue-set"] = {"product": "jira", "validate": _validate_issue_set,
                           "plan": _plan_issue_set, "send": _send_issue_set,
                           "readback": _readback_issue_set}
OPERATIONS["version-create"] = {"product": "jira", "validate": _validate_version_create,
                                "plan": _plan_version_create, "send": _send_version_create,
                                "readback": _readback_version_create}
OPERATIONS["version-edit"] = {"product": "jira", "validate": _validate_version_edit,
                              "plan": _plan_version_edit, "send": _send_version_edit,
                              "readback": _readback_version_edit}
OPERATIONS["version-delete"] = {"product": "jira", "validate": _validate_version_delete,
                                "plan": _plan_version_delete, "send": _send_version_delete,
                                "readback": _readback_version_delete}


# --- operation: issue-delete (Jira, irreversible) -----------------------------
# Jira has no trash: a deleted issue is gone. The plan lists what goes with it; an issue with
# sub-tasks is refused unless --delete-subtasks true is given.

def _validate_issue_delete(flags, pos=()):
    if pos:
        raise Fatal(f"issue-delete takes no positional arguments: {pos[0]!r}")
    _check_flags(flags, {"key", "delete-subtasks"}, "issue-delete")
    for f in ("key", "delete-subtasks"):
        _one(flags, f)
    if "key" not in flags or not KEY_RE.match(str(flags["key"])):
        raise Fatal("usage: issue-delete --key <issue key> [--delete-subtasks true]")
    if "delete-subtasks" in flags and str(flags["delete-subtasks"]).lower() != "true":
        raise Fatal("--delete-subtasks takes only true; leave it out to refuse deleting sub-tasks")
    args = {"key": str(flags["key"])}
    if str(flags.get("delete-subtasks", "")).lower() == "true":
        args["delete-subtasks"] = True
    return args


def _plan_issue_delete(get, args):
    f = get(f"/rest/api/3/issue/{args['key']}",
            {"fields": "summary,issuetype,status,subtasks,issuelinks"}).get("fields") or {}
    subtasks = [s.get("key") for s in f.get("subtasks") or []]
    if subtasks and "delete-subtasks" not in args:
        raise Fatal(f"{args['key']} has sub-tasks ({', '.join(subtasks)}); pass --delete-subtasks true to delete them too")
    base = {"key": args["key"], "summary": f.get("summary"), "type": (f.get("issuetype") or {}).get("name"),
            "status": (f.get("status") or {}).get("name"), "subtasks": subtasks,
            "links": len(f.get("issuelinks") or [])}
    return base, {}


def _notes_issue_delete(args, flags):
    return ["IRREVERSIBLE: Jira has no trash for issues. To keep it recoverable, transition the issue to a "
            "cancelled status instead (list names with acli-rest-get.py transitions KEY)."]


def _send_issue_delete(http, args, base, body_text):
    qs = "?deleteSubtasks=true" if args.get("delete-subtasks") else ""
    return http("DELETE", f"/rest/api/3/issue/{base['key']}{qs}", None)


def _readback_issue_delete(get, args, base, body_text, result):
    try:
        get(f"/rest/api/3/issue/{base['key']}", {"fields": "summary"})
    except HttpError as e:
        if e.code == 404:
            return True
        raise
    return False


OPERATIONS["issue-delete"] = {"product": "jira", "validate": _validate_issue_delete,
                              "plan": _plan_issue_delete, "send": _send_issue_delete,
                              "readback": _readback_issue_delete, "notes": _notes_issue_delete}
