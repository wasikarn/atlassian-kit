"""Shared parts of acli-rest-write: the OPERATIONS registry, flag parsing and the regexes the operations share."""

import json
import pathlib
import re

from acli_rest_common import Fatal, parse_json


OPERATIONS = {}  # name -> {product, validate(flags)->args, plan(get,args)->(base,body), send(http,args,base,body_text)->text, readback(get,args,base,body_text,result)->bool, notes?(args,flags)->[str], describe?(base,body)->[str]}
KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]+-[0-9]+$")
SPACE_KEY_RE = re.compile(r"^[A-Z][A-Z0-9]*$")
PAGE_ID_RE = re.compile(r"^[0-9]+$")


# --- operation: page-create (Confluence v2) ---------------------------------

def _read_adf(path_str):
    p = pathlib.Path(path_str)
    try:
        raw = p.read_text()
    except FileNotFoundError:
        raise Fatal(f"body file {path_str} not found") from None
    except OSError as e:
        raise Fatal(f"cannot read the body file {path_str}: {type(e).__name__}") from None
    doc = parse_json(raw, str(p))
    if not isinstance(doc, dict) or doc.get("type") != "doc":
        raise Fatal(f"the body file {p} is not an ADF doc (need a {{'type': 'doc', ...}} object)")
    return doc


def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)


def parse_flags(rest):
    flags, pos, i = {}, [], 0
    while i < len(rest):
        if rest[i].startswith("--") and len(rest[i]) > 2:
            if i + 1 >= len(rest):
                raise Fatal(f"flag {rest[i]} needs a value")
            key = rest[i][2:]
            if key in flags:  # a repeated flag collects its values, in order
                if isinstance(flags[key], list):
                    flags[key].append(rest[i + 1])
                else:
                    flags[key] = [flags[key], rest[i + 1]]
            else:
                flags[key] = rest[i + 1]
            i += 2
        else:
            pos.append(rest[i])
            i += 1
    return flags, pos


def _one(flags, name):
    """The single value of --name, refusing a repeated flag."""
    value = flags.get(name)
    if isinstance(value, list):
        raise Fatal(f"--{name} was given more than once; it takes a single value")
    return value


def _check_flags(flags, known, op):
    extra = sorted(set(flags) - set(known))
    if extra:
        raise Fatal(f"unknown flag(s) for {op}: " + ", ".join(f"--{f}" for f in extra))


def _jira_get_list(get, path, source):
    rows = get(path, {})
    if not isinstance(rows, list):
        raise Fatal(f"unexpected shape from {source} (need a list)")
    return rows


def _names(rows):
    return {str(r.get("name")) for r in rows if isinstance(r, dict)}
