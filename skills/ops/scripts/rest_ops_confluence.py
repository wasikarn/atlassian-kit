"""Confluence operations of acli-rest-write: page-create, page-fetch, page-update, page-delete, attachment-upload."""

import hashlib
import json
import pathlib
import re
import secrets
import urllib.parse

from acli_rest_common import Fatal, HttpError
from rest_write_base import OPERATIONS, PAGE_ID_RE, SPACE_KEY_RE, _check_flags, _one, _read_adf, canonical


def _conf_paged(get, path, params):
    out, cursor = [], None
    while True:
        qs = dict(params)
        if cursor:
            qs["cursor"] = cursor
        page = get(path, qs)
        results = page.get("results") if isinstance(page, dict) else None
        if not isinstance(results, list):
            raise Fatal(f"unexpected shape from {path} (need results[])")
        out.extend(results)
        nxt = page.get("_links", {}).get("next") if isinstance(page.get("_links"), dict) else None
        if not nxt:
            return out
        cursor = (urllib.parse.parse_qs(urllib.parse.urlsplit(nxt).query).get("cursor") or [""])[0]
        if not cursor:
            raise Fatal(f"the next link of {path} has no cursor")


def _validate_page_create(flags, pos=()):
    if pos:
        raise Fatal(f"page-create takes no positional arguments: {pos[0]!r}")
    _check_flags(flags, {"space", "title", "parent", "body-adf"}, "page-create")
    for f in ("space", "title", "parent", "body-adf"):
        _one(flags, f)
    if not SPACE_KEY_RE.match(str(flags.get("space", ""))):
        raise Fatal("--space must be an uppercase space key")
    if not str(flags.get("title", "")):
        raise Fatal("--title is required")
    if "parent" in flags and not PAGE_ID_RE.match(str(flags["parent"])):
        raise Fatal("--parent must be a page id (digits)")
    if "body-adf" not in flags:
        raise Fatal("--body-adf FILE is required")
    return dict(flags)


def _plan_page_create(get, args):
    doc = _read_adf(args["body-adf"])
    spaces = _conf_paged(get, "/spaces", {"keys": args["space"]})
    matching = [sp for sp in spaces if str(sp.get("key", "")) == args["space"]]
    if len(matching) != 1:
        raise Fatal(f"expected exactly one space named {args['space']}, found {len(matching)} "
                    f"(the listing only shows what this account can see)")
    space_id = str(matching[0]["id"])
    dup = _conf_paged(get, "/pages", {"space-id": space_id, "title": args["title"]})
    if dup:
        raise Fatal(f"a page titled {args['title']!r} already exists in that space (the listing only "
                    f"shows what this account can see, so an empty result is not proof)")
    parent_id = None
    if "parent" in args:
        parent = get(f"/pages/{args['parent']}", {})
        if str(parent.get("spaceId")) != space_id:
            raise Fatal(f"parent page {args['parent']} lives in space {parent.get('spaceId')}, not {space_id}")
        parent_id = str(args["parent"])
    return {"spaceId": space_id, "parentId": parent_id}, doc


def _send_page_create(http, args, base, body_text):
    wire = {"spaceId": base["spaceId"], "status": "current", "title": args["title"],
            "body": {"representation": "atlas_doc_format", "value": body_text}}
    if base.get("parentId"):
        wire["parentId"] = base["parentId"]
    return http("POST", "/pages", json.dumps(wire).encode())


def _readback_page_create(get, args, base, body_text, result):
    pid = str(result.get("id", "")) if isinstance(result, dict) else ""
    if not PAGE_ID_RE.match(pid):
        return False
    page = get(f"/pages/{pid}", {"body-format": "atlas_doc_format"})
    sent_adf = json.loads(body_text)
    val = (page.get("body", {}).get("atlas_doc_format", {}) or {}).get("value", "")
    try:
        back = json.loads(val)
    except (ValueError, AttributeError):
        return False
    return canonical(back) == canonical(sent_adf) and page.get("title") == args["title"]


OPERATIONS["page-create"] = {"product": "confluence", "validate": _validate_page_create,
                             "plan": _plan_page_create, "send": _send_page_create,
                             "readback": _readback_page_create}



# --- operations: page-fetch and page-update (Confluence v2, phase 4) --------

PRESERVE_TYPES = ("extension", "bodiedExtension", "inlineExtension", "panel", "expand",
                  "nestedExpand", "table", "media", "mediaSingle", "mediaGroup", "layoutSection",
                  "taskList", "decisionList", "status", "mention", "inlineCard", "blockCard")


def _node_counts(adf):
    counts = {}

    def walk(node):
        if not isinstance(node, dict):
            return
        t = node.get("type")
        if isinstance(t, str):
            counts[t] = counts.get(t, 0) + 1
        for child in (node.get("content") or []):
            walk(child)

    walk(adf)
    return counts


def _page_snapshot(get, page_id):
    page = get(f"/pages/{page_id}", {"body-format": "atlas_doc_format"})
    val = (page.get("body", {}) or {}).get("atlas_doc_format", {}).get("value", "")
    try:
        adf = json.loads(val)
    except ValueError:
        raise Fatal(f"page {page_id} did not return an ADF body") from None
    version = (page.get("version") or {}).get("number")
    if not isinstance(version, int):
        raise Fatal(f"page {page_id} did not expose a version number")
    return page, adf, version


def _validate_page_fetch(flags, pos):
    extra = sorted(set(flags))
    if extra:
        raise Fatal(f"page-fetch takes no flags (got: {', '.join(f'--{f}' for f in extra)})")
    if len(pos) != 1 or not PAGE_ID_RE.match(str(pos[0])):
        raise Fatal("usage: page-fetch <page id>")
    return {"page": str(pos[0])}


def _plan_page_fetch(get, args):
    page, adf, version = _page_snapshot(get, args["page"])
    d = pathlib.Path.cwd()
    adf_path = d / f"page-{args['page']}-v{version}.adf.json"
    base_path = d / f"page-{args['page']}-v{version}.base.json"
    adf_path.write_text(json.dumps(adf, indent=2, ensure_ascii=False))
    base = {"pageId": str(page.get("id")), "version": version, "title": page.get("title", ""),
            "adfSha": hashlib.sha256(canonical(adf).encode()).hexdigest()}
    base_path.write_text(json.dumps(base))
    return base, {"base": str(base_path), "adf": str(adf_path)}


def _validate_page_update(flags, pos):
    if pos:
        raise Fatal(f"page-update takes no positional arguments: {pos[0]!r}")
    _check_flags(flags, {"base", "body-adf", "title", "allow-node-loss"}, "page-update")
    for f in ("base", "body-adf", "title"):
        _one(flags, f)
    if "base" not in flags:
        raise Fatal("usage: page-update --base <*.base.json> --body-adf <edited.adf.json> [--title T] [--allow-node-loss TYPE]")
    if "body-adf" not in flags:
        raise Fatal("--body-adf is required")
    allow = flags.get("allow-node-loss") or []
    allow = [allow] if isinstance(allow, str) else list(allow)
    unknown = [a for a in allow if a not in PRESERVE_TYPES]
    if unknown:
        raise Fatal(f"--allow-node-loss must name node types it may lose, not {unknown}")
    args = {"base": str(flags["base"]), "body-adf": str(flags["body-adf"]), "allow-node-loss": allow}
    if "title" in flags:
        args["title"] = str(flags["title"])
    return args


def _plan_page_update(get, args):
    base_file = pathlib.Path(args["base"])
    try:
        base = json.loads(base_file.read_text())
    except FileNotFoundError:
        raise Fatal(f"base file {base_file} not found (run page-fetch first)") from None
    except ValueError:
        raise Fatal(f"base file {base_file} is not JSON") from None
    if not isinstance(base, dict) or base.get("adfSha") is None or base.get("pageId") is None:
        raise Fatal(f"base file {base_file} does not hold pageId/version/title/adfSha")
    page, adf, version = _page_snapshot(get, str(base["pageId"]))
    if version != base.get("version") or hashlib.sha256(canonical(adf).encode()).hexdigest() != base["adfSha"]:
        raise Fatal(f"the live page no longer matches the base {(base_file.name)!r} "
                    f"(live version {version}); re-run page-fetch and re-check edits")
    edited = _read_adf(args["body-adf"])
    live_counts, edited_counts = _node_counts(adf), _node_counts(edited)
    dropped = [t for t in PRESERVE_TYPES if live_counts.get(t, 0) > edited_counts.get(t, 0)
               and t not in set(args.get("allow-node-loss") or [])]
    if dropped:
        raise Fatal(f"the edit removes these node types: {dropped}; "
                    f"pass --allow-node-loss <type> only for types you mean to drop")
    title = args.get("title", str(base.get("title", "")))
    wire = {"id": str(base["pageId"]), "status": "current", "title": title,
            "version": {"number": version + 1},
            "body": {"representation": "atlas_doc_format", "value": canonical(edited)}}
    return {"pageId": str(base["pageId"]), "version": version, "title": title,
            "adfSha": base["adfSha"]}, wire


def _send_page_update(http, args, base, body_text):
    return http("PUT", f"/pages/{base['pageId']}", body_text.encode())


def _readback_page_update(get, args, base, body_text, result):
    page, adf, version = _page_snapshot(get, base["pageId"])
    wire = json.loads(body_text)
    return page.get("title") == wire["title"] and version == wire["version"]["number"] \
        and canonical(adf) == canonical(json.loads(wire["body"]["value"]))


def _notes_page_update(args, flags):
    allow = args.get("allow-node-loss") or []
    notes = [f"publishing can discard or conflict with an unpublished draft of this page; check the "
             f"page for a draft first"]
    if allow:
        notes.append(f"--allow-node-loss {' and '.join(allow)}: those node types are dropped by design")
    return notes



OPERATIONS["page-fetch"] = {"product": "confluence", "planOnly": True,
                            "validate": _validate_page_fetch, "plan": _plan_page_fetch}
OPERATIONS["page-update"] = {"product": "confluence", "validate": _validate_page_update,
                             "plan": _plan_page_update, "send": _send_page_update,
                             "readback": _readback_page_update, "notes": _notes_page_update}


# --- operation: page-delete (Confluence v2) ----------------------------------
# Moves one page to the Confluence trash (recoverable); never purges. Refuses a space homepage,
# a page with children, and a page that is not current.

def _validate_page_delete(flags, pos=()):
    if pos:
        raise Fatal(f"page-delete takes no positional arguments: {pos[0]!r}")
    _check_flags(flags, {"page"}, "page-delete")
    _one(flags, "page")
    if "page" not in flags or not PAGE_ID_RE.match(str(flags["page"])):
        raise Fatal("usage: page-delete --page <page id>")
    return {"page": str(flags["page"])}


def _plan_page_delete(get, args):
    page = get(f"/pages/{args['page']}", {})
    if page.get("status") != "current":
        raise Fatal(f"page {args['page']} is not current (status {page.get('status')!r}); nothing to trash")
    space_id = str(page.get("spaceId"))
    if str(get(f"/spaces/{space_id}", {}).get("homepageId")) == args["page"]:
        raise Fatal(f"page {args['page']} is the homepage of its space; refusing to trash it")
    if get(f"/pages/{args['page']}/children", {}).get("results"):
        raise Fatal(f"page {args['page']} has child pages; trash or move them first")
    version = (page.get("version") or {}).get("number")
    return {"pageId": str(page.get("id")), "spaceId": space_id, "title": page.get("title", ""),
            "version": version}, {}


def _send_page_delete(http, args, base, body_text):
    return http("DELETE", f"/pages/{base['pageId']}", None)


def _readback_page_delete(get, args, base, body_text, result):
    try:
        page = get(f"/pages/{base['pageId']}", {})
    except HttpError as e:
        if e.code == 404:
            return True
        raise
    return page.get("status") in ("trashed", "deleted")


OPERATIONS["page-delete"] = {"product": "confluence", "validate": _validate_page_delete,
                             "plan": _plan_page_delete, "send": _send_page_delete,
                             "readback": _readback_page_delete}


# --- operation: attachment-upload (Confluence v1 multipart; v2 has no upload) --
# One image file to one current page. Never replaces: a name the page already has is refused.

ATTACH_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".svg")
ATTACH_MAX = 10 * 1024 * 1024
ATTACH_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
ATTACH_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
                ".svg": "image/svg+xml"}


def _validate_attachment_upload(flags, pos=()):
    if pos:
        raise Fatal(f"attachment-upload takes no positional arguments: {pos[0]!r}")
    _check_flags(flags, {"page", "file", "name"}, "attachment-upload")
    for f in ("page", "file", "name"):
        _one(flags, f)
    if "page" not in flags or not PAGE_ID_RE.match(str(flags["page"])) or "file" not in flags:
        raise Fatal("usage: attachment-upload --page <page id> --file <image path> [--name NAME]")
    path = pathlib.Path(str(flags["file"])).expanduser().resolve()
    name = str(flags.get("name") or path.name)
    if not ATTACH_NAME_RE.match(name):
        raise Fatal(f"--name {name!r} must be 1-100 chars of letters, digits, dot, dash, underscore, "
                    f"not starting with a dot")
    for label, value in (("file", path.name.lower()), ("name", name.lower())):
        if not value.endswith(ATTACH_EXTS):
            raise Fatal(f"the {label} must end in one of {', '.join(ATTACH_EXTS)} (images only)")
    return {"page": str(flags["page"]), "file": str(path), "name": name}


def _attach_bytes(args):
    path = pathlib.Path(args["file"])
    if not path.is_file():
        raise Fatal(f"file {path} not found")
    size = path.stat().st_size
    if size == 0:
        raise Fatal(f"file {path} is empty")
    if size > ATTACH_MAX:
        raise Fatal(f"file {path} is {size} bytes; the limit is 10 MB")
    return path.read_bytes()


def _plan_attachment_upload(get, args):
    data = _attach_bytes(args)
    page = get(f"/pages/{args['page']}", {})
    if page.get("status") != "current":
        raise Fatal(f"page {args['page']} is not current (status {page.get('status')!r})")
    existing = get(f"/pages/{args['page']}/attachments", {"filename": args["name"]}).get("results") or []
    if any(a.get("title") == args["name"] for a in existing):
        raise Fatal(f"page {args['page']} already has an attachment named {args['name']!r}; "
                    f"pick another --name (this operation never replaces)")
    body = {"filename": args["name"], "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    return {"pageId": str(page.get("id")), "spaceId": str(page.get("spaceId")), **body}, body


def _send_attachment_upload(http, args, base, body_text):
    data = _attach_bytes(args)
    if hashlib.sha256(data).hexdigest() != base["sha256"]:
        raise Fatal("the file changed since the plan; plan again")
    boundary = "acli" + secrets.token_hex(16)
    ctype = ATTACH_TYPES[pathlib.Path(args["name"]).suffix.lower()]
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"minorEdit\"\r\n\r\ntrue\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{args['name']}\"\r\n"
            f"Content-Type: {ctype}\r\n\r\n").encode()
    payload = head + data + f"\r\n--{boundary}--\r\n".encode()
    return http("POST", f"/content/{base['pageId']}/child/attachment", payload,
                f"multipart/form-data; boundary={boundary}", {"X-Atlassian-Token": "no-check"})


def _readback_attachment_upload(get, args, base, body_text, result):
    rows = get(f"/pages/{base['pageId']}/attachments", {"filename": base["filename"]}).get("results") or []
    return len(rows) == 1 and rows[0].get("title") == base["filename"] and rows[0].get("fileSize") == base["size"]


# Confluence v1 uploads reject granular tokens (401 scope mismatch); the write call uses a separate
# classic token holding only write:confluence-file. Reads and the read-back keep the granular token.
OPERATIONS["attachment-upload"] = {"product": "confluence", "send_api": "/wiki/rest/api",
                                   "send_token_key": "ACLI_REST_WRITE_CONFLUENCE_FILE_TOKEN",
                                   "validate": _validate_attachment_upload, "plan": _plan_attachment_upload,
                                   "send": _send_attachment_upload, "readback": _readback_attachment_upload}
