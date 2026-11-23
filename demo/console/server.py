"""The console's door: one small server, on this computer only, for the page, the live state, the audience's taps and the
presenter's commands.

  GET  /                   the page file's bytes as they are, whatever the query: the page itself asks this door for the live state
  GET  /how                the architecture page beside the page file (HOW), as its bytes are; 404 where there is none
  GET  /live/state.json    the feed's answer (feed.Log.answer), with ?since=N the moments after N; open to any origin
  POST /live/surprise      a viewer's tap on one of the six presets (crowd.py): exactly {"kind": "<preset>"} in at most 256 bytes,
                           sent as application/json; no key. 200 {"did": fire | vote | again | done | closed}, or 400 {"error": words}
  GET  /console/state      the driver's state, for whoever holds the key
  POST /console/do         one command as a JSON object of at most 4,096 bytes: 202, or 400 {"error": words}

Every route answers 403 unless the request's Host is one of the door's own two names, 127.0.0.1:PORT and localhost:PORT. The two
console routes also want the key in X-Murmur-Console, compared in constant time, and a command an Origin that is absent or the
door's own. OPTIONS is 403, so no other origin's page is ever let through to them. A tap is JSON, which another origin's page may
not send without asking first, and that one question is answered: on a console started for an audience, OPTIONS /live/surprise is
204 and says that any origin may post a tap with a viewer's token, so that a copy of the page published elsewhere can send one
(a tap's own answer then says the same). Any other method is 405, any other path 404. Every answer says no-store, nosniff and no-referrer. None
carries an address, a path or an error's text, or anything of what was sent.

A tap carries nothing but its preset. Who taps is told apart by the page's own token in X-Murmur-Viewer (16 to 64 letters, digits,
"-" and "_"), else by the caller's address: the last one a gateway in front of the door wrote in X-Forwarded-For, else the
connection's own. Neither is kept beyond a round of votes, and neither leaves in any answer.

The key is a file (mode 600) that a pair of consoles shares, made when it is absent. The link a presenter opens carries the key
after "#", which no browser sends to a server; it is written beside the key file, as KEYFILE.link (mode 600).

The driver is whatever plays the evening: facts() is what a command is checked against (commands.check), do(command) takes a
checked command and gives None, or the entry of commands.SAY it is refused with, state() is what /console/state shows, and
tap(preset, viewer, address) takes a viewer's tap and gives one of crowd's five words. All are called from the door's own threads.
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from . import commands, crowd, feed

logger = logging.getLogger("murmur.console")
NAME = "murmur-console"
HEADER = "X-Murmur-Console"
VIEWER = "X-Murmur-Viewer"
TOKEN = re.compile(r"[A-Za-z0-9_-]{16,64}")
HOW = "Murmur_NG_Architecture_and_Data.html"        # the architecture page, beside the page file
LIMIT = 4096                                        # the longest command, in bytes
TAP_LIMIT = 256                                     # the longest tap of a viewer's
DRAIN = 1 << 20                                     # how much of a longer body is read away before the answer
KEY_MIN = 16
ALWAYS = (("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer"))
JSON, HTML = "application/json", "text/html; charset=utf-8"
OPEN = (("Access-Control-Allow-Origin", "*"),)      # as the read-only feed sends it: a page opened from a file may read the state
TAP = "/live/surprise"
MAY_TAP = (*OPEN, ("Access-Control-Allow-Methods", "POST"), ("Access-Control-Allow-Headers", "Content-Type, X-Murmur-Viewer"), ("Access-Control-Max-Age", "600"))
Headers = tuple[tuple[str, str], ...]


def read_key(path: str | Path) -> str:
    """The console's key: the key file's, made first (mode 600) when there is none. Two consoles that start together end with the
    same key: the file appears whole or not at all, and whoever comes second reads it."""
    path = Path(path)
    if not path.exists():
        new = path.with_name(f"{path.name}.{secrets.token_hex(4)}.new")
        fd = os.open(new, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, (secrets.token_urlsafe(24) + "\n").encode())
            os.link(new, path)                        # never over a key another console has just made
        except FileExistsError:
            pass
        finally:
            os.close(fd)
            os.unlink(new)
    os.chmod(path, 0o600)
    key = path.read_text().strip()
    if len(key) < KEY_MIN or not key.isascii() or not key.isprintable() or " " in key:
        raise ValueError("the key file holds no key")
    return key


def write_link(key_file: str | Path, port: int, key: str) -> str:
    """Writes the link a presenter opens to KEYFILE.link (mode 600) and gives it back."""
    base = f"http://127.0.0.1:{int(port)}"
    link, path = f"{base}/?live={base}#k={key}", Path(key_file)
    new = path.with_name(f"{path.name}.link.{secrets.token_hex(4)}.new")
    fd = os.open(new, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(fd, 0o600)                          # whatever the process's mask leaves of it
        os.write(fd, (link + "\n").encode())
    finally:
        os.close(fd)
    os.replace(new, path.with_name(path.name + ".link"))
    return link


class Door(BaseHTTPRequestHandler):
    server: Any
    timeout = 10                                    # a caller that says nothing is let go

    def __getattr__(self, name: str) -> Any:
        """Every method comes to route(): the base class looks for do_GET, do_POST and so on."""
        if name.startswith("do_"):
            return self.route
        raise AttributeError(name)

    def version_string(self) -> str:
        return NAME

    def log_message(self, *args: Any) -> None:
        return

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        """What the base class refuses by itself (a line it cannot read) is answered as everything else is: no text of the request."""
        if self.request_version == "HTTP/0.9":        # the line's version was never read: the answer still has its headers
            self.request_version = "HTTP/1.0"
        self.answer(int(code))

    def answer(self, code: int, body: bytes = b"", kind: str = JSON, more: Headers = ()) -> None:
        try:
            self.send_response(code)
            for name, value in (*ALWAYS, *more, *((("Content-Type", kind),) if body else ())):
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError:                               # the caller has gone
            self.close_connection = True

    def tell(self, code: int, value: Any, more: Headers = ()) -> None:
        self.answer(code, feed.raw(feed.text(value)), JSON, more)

    def sent(self) -> tuple[bytes | None, str]:
        """The request's body when it is a command's size, else None and why: the entry of commands.SAY. A longer body is
        read away, so that the answer reaches a caller that is still sending."""
        try:
            n = int(self.headers.get("Content-Length") or "")
        except ValueError:
            return None, "unreadable"
        if 0 <= n <= LIMIT:
            return self.rfile.read(n), ""
        left = min(n, DRAIN)
        while left > 0:
            got = self.rfile.read(min(left, 65536))
            left -= len(got) or left
        return None, "too_long" if n > 0 else "unreadable"

    def route(self) -> None:
        s = self.server
        body, why = self.sent()
        hosts = self.headers.get_all("Host") or []
        if len(hosts) != 1 or hosts[0].strip().lower() not in s.hosts:
            return self.answer(403)
        try:
            url = urlsplit(self.path)
        except ValueError:
            return self.answer(403 if self.command == "OPTIONS" else 400)
        if self.command == "OPTIONS":                 # the one question another origin's page may ask: may it post a viewer's tap?
            return self.answer(204, more=MAY_TAP) if url.path == TAP and self.audience() else self.answer(403)
        if url.path == "/favicon.ico" and self.command == "GET":       # the page has no icon: the browser's own question, answered quietly
            return self.answer(204)
        if url.path not in ROUTES:
            return self.answer(404)
        method, keyed, way = ROUTES[url.path]
        if self.command != method:
            return self.answer(405, more=(("Allow", method),))
        if keyed and not hmac.compare_digest((self.headers.get(HEADER) or "").encode("utf-8", "replace"), s.key):
            return self.answer(403)
        try:
            way(self, url, body, why)
        except Exception:                             # whatever fails behind the door, the answer names none of it
            logger.exception("the console's door, %s", url.path)
            self.answer(500)

    # ------------------------------------------------------------------ the six routes
    def page(self, url: Any, body: bytes | None, why: str) -> None:
        try:
            self.answer(200, self.server.page.read_bytes(), HTML)
        except OSError:
            self.answer(503)

    def how(self, url: Any, body: bytes | None, why: str) -> None:
        try:
            self.answer(200, self.server.page.with_name(HOW).read_bytes(), HTML)
        except OSError:
            self.answer(404)

    def caller(self) -> str:
        """Who asks, as far as the door can tell: the last address a gateway in front of it wrote, else the connection's own."""
        hops = [h.strip() for h in ",".join(self.headers.get_all("X-Forwarded-For") or []).split(",") if h.strip()]
        return (hops[-1] if hops else str(self.client_address[0]))[:64]

    def audience(self) -> bool:
        """Whether another origin's page may send a tap: on a console started for an audience, unless a gateway in front of the
        door says such things for it (serve's cors)."""
        return self.server.cors and getattr(getattr(self.server.driver, "crowd", None), "on", False) is True

    def surprise(self, url: Any, body: bytes | None, why: str) -> None:
        kind, more = None, OPEN if self.audience() else ()
        if body is not None and len(body) <= TAP_LIMIT and (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() == JSON:
            try:
                sent = json.loads(body.decode("utf-8"))
            except (ValueError, RecursionError):
                sent = None
            kind = sent["kind"] if isinstance(sent, dict) and list(sent) == ["kind"] and isinstance(sent["kind"], str) else None
        tap = getattr(self.server.driver, "tap", None)
        if kind not in crowd.PRESETS or tap is None:
            return self.tell(400, {"error": commands.say("preset")}, more)
        token, address = self.headers.get(VIEWER) or "", self.caller()
        self.tell(200, {"did": tap(kind, token if TOKEN.fullmatch(token) else address, address)}, more)

    def state(self, url: Any, body: bytes | None, why: str) -> None:
        s = self.server
        since = parse_qs(url.query, keep_blank_values=True).get("since") or []
        self.tell(200, s.log.answer(s.v1() if callable(s.v1) else s.v1, since[0] if len(since) == 1 else None), OPEN if s.cors else ())

    def console(self, url: Any, body: bytes | None, why: str) -> None:
        self.tell(200, self.server.driver.state())

    def do(self, url: Any, body: bytes | None, why: str) -> None:
        s = self.server
        origin = self.headers.get_all("Origin") or []
        if len(origin) > 1 or (origin and origin[0].strip().lower() not in s.origins):
            return self.answer(403)
        command, no = None, commands.say(why or "unreadable")
        if body is not None:
            try:
                command, no = commands.check(json.loads(body.decode("utf-8")), facts(s.driver))
            except (ValueError, RecursionError):                # no JSON: the reader's own words are not repeated
                pass
        if command is not None and command["do"] != "hello":
            refused = s.driver.do(command)
            no = commands.say(refused) if refused else None
        if no:
            return self.tell(400, {"error": no})
        self.tell(202, {"ok": True})


ROUTES: dict[str, tuple[str, bool, Callable[..., None]]] = {      # path: its method, whether it wants the key, what answers
    "/": ("GET", False, Door.page), "/how": ("GET", False, Door.how), "/live/state.json": ("GET", False, Door.state),
    TAP: ("POST", False, Door.surprise), "/console/state": ("GET", True, Door.console), "/console/do": ("POST", True, Door.do)}


def facts(driver: Any) -> dict[str, Any]:
    """What the driver knows now, for commands.check: its facts(), or its facts when that is the dict itself."""
    known = driver.facts
    return known() if callable(known) else known


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64                         # every viewer's page asks a few times a second, each on a connection of its own


def serve(host: str, port: int, page: str | Path, log: Any, driver: Any, key: str, v1: Any, cors: bool = True) -> Server:
    """Starts the door on `host` (port 0: a free one) and returns its server, already serving.

    page: the page file, read anew at every load; log: the feed.Log; driver: see the module's own words; key: read_key()'s;
    v1: what gives the runner's state (demo.runner.feed.state) each time it is called, or that state itself; cors: False where
    a gateway in front of the door says for it that any origin may read the state and post a tap, so that a browser hears it once."""
    if len(key) < KEY_MIN:
        raise ValueError("the console's key is too short to be one")
    srv = Server((host, int(port)), Door)
    names = [f"{name}:{srv.server_address[1]}" for name in ("127.0.0.1", "localhost")]
    srv.hosts, srv.origins = frozenset(names), frozenset(f"http://{n}" for n in names)
    srv.page, srv.log, srv.driver, srv.key, srv.v1, srv.cors = Path(page), log, driver, key.encode(), v1, bool(cors)
    threading.Thread(target=srv.serve_forever, daemon=True, name="console-door").start()
    return srv
