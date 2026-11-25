"""Shared by acli-rest-get.py and acli-rest-write.py: identity from acli, the env file, one HTTP helper.
Stdlib only. Nothing here decides what may be sent; each script does that."""
import base64
import json
import pathlib
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request

HOST_RE = re.compile(r"^[a-z0-9-]+\.atlassian\.net$")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
API_HOST = "api.atlassian.com"
TIMEOUT = 30
ENV_FILE = pathlib.Path.home() / ".claude" / "atlassian.env"
ALLOWED_METHODS = ("GET", "POST", "PUT", "DELETE")


class Fatal(Exception):
    """Stop with a FATAL line. Nothing was sent unless the caller says so."""


class HttpError(Fatal):
    """The server answered with a non-2xx status. The request was sent."""

    def __init__(self, code, netloc, detail):
        super().__init__(f"HTTP {code} from {netloc}: {detail}")
        self.code = code


class NetError(Fatal):
    """No usable answer: timeout, refused or dropped connection. Whether the server acted is unknown."""


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


def http_request(opener, method, url, auth=None, body=None, content_type="application/json", headers=None):
    """Send one request and return the body text. auth=(email, token) only ever goes to api.atlassian.com.
    HttpError when the server answers non-2xx; NetError when there is no answer."""
    if method not in ALLOWED_METHODS:
        raise Fatal(f"method {method!r} is not allowed")
    netloc = urllib.parse.urlsplit(url).netloc
    headers_out = {"Accept": "application/json"}
    if auth is not None:
        if netloc != API_HOST:
            raise Fatal(f"refusing to send the credential to {netloc}")
        raw = f"{auth[0]}:{auth[1]}".encode()
        headers_out["Authorization"] = "Basic " + base64.b64encode(raw).decode()
    for k, v in (headers or {}).items():  # extra headers (Confluence XSRF opt-out); never the credential
        headers_out[k] = v
    if body is not None:
        headers_out["Content-Type"] = content_type
    req = urllib.request.Request(url, data=body, headers=headers_out, method=method)
    try:
        with opener.open(req, timeout=TIMEOUT) as resp:
            return resp.read().decode()
    except urllib.error.HTTPError as e:
        detail = e.read(500).decode(errors="replace")
        raise HttpError(e.code, netloc, detail) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise NetError(f"request to {netloc} failed: {type(e).__name__}") from None


def http_get(opener, url, auth=None):
    return http_request(opener, "GET", url, auth)


def cloud_id(host, opener):
    info = parse_json(http_get(opener, f"https://{host}/_edge/tenant_info"), host)
    cid = info.get("cloudId", "") if isinstance(info, dict) else ""
    if not isinstance(cid, str) or not UUID_RE.match(cid):
        raise Fatal("cloudId lookup did not return a UUID")
    return cid


PRODUCT_TOKEN_KEYS = {
    "ACLI_JIRA_TOKEN": ("ACLI_REST_READ_TOKEN", "ACLI_REST_WRITE_JIRA_TOKEN"),
    "ACLI_CONFLUENCE_TOKEN": ("ACLI_REST_WRITE_CONFLUENCE_TOKEN", "ACLI_REST_WRITE_CONFLUENCE_V1_TOKEN",
                              "ACLI_REST_WRITE_CONFLUENCE_FILE_TOKEN"),
}


def read_env_file(env_file):
    """Return {KEY: value} from a KEY=value file. Refuses a file readable by group or others."""
    try:
        if env_file.stat().st_mode & 0o077:
            raise Fatal(f"{env_file} is readable by group or others; run: chmod 600 {env_file}")
        text = env_file.read_text()
    except FileNotFoundError:
        raise Fatal(f"token file {env_file} not found (see the script docstring)") from None
    pairs = re.findall(r"^\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)=(.*?)\s*$", text, re.M)
    values = {k: v[1:-1] if len(v) > 1 and v[0] == v[-1] and v[0] in "\"'" else v for k, v in pairs}
    for product_key, keys in PRODUCT_TOKEN_KEYS.items():  # one key per product; a per-operation key still wins
        for key in keys:
            if product_key in values:
                values.setdefault(key, values[product_key])
    return values
