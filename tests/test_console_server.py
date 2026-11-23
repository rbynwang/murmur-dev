"""The console's door on a free port, with a made-up driver behind it: its routes, methods, codes and headers, the key, the
Origin and the Host it wants, the page's bytes, the key file and its link file."""
from __future__ import annotations

import http.client
import json
import socket
import stat
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from demo.console import commands as C
from demo.console import feed as F
from demo.console import server as S
from demo.console import timeline as T
from demo.runner import feed as runner_feed

KEY = "a-test-key_0123456789-ABCDEFGHIJ"
PAGE = b"the page file, byte for byte\r\ncaf\xc3\xa9 \xff\x00 \xe2\x80\xa6 as it is\n"
ALWAYS = {"cache-control": "no-store", "x-content-type-options": "nosniff", "referrer-policy": "no-referrer"}
STATE = {"schema": "murmur.console.v1", "play": "held", "busy": "", "error": "", "warn": "", "link": "", "run": 1, "clock": "2025-01-28 17:00"}
FACTS = {"play": "held", "now": "2025-01-28 17:00", "span": ["2025-01-27 10:00", "2025-01-29 02:45"],
         "roster": {"homes": [{"id": "home-01", "name": "Home 1", "battery": True}], "buildings": [{"id": "building-01", "name": "the shops"}], "buyers": ["utility"]},
         "follow": {"home": "home-01", "building": "building-01"}}


def v1() -> dict:
    return runner_feed.state({"bus": {"ok": True}, "summary": {"now": "2025-01-28 17:00", "events": {}}}, {"bus": 99.0}, "c1", 100.0)


class Driver:
    """What stands in for the running console: it keeps every checked command it is given."""

    def __init__(self) -> None:
        self.got: list[dict] = []
        self.no: str | None = None                   # the entry of commands.SAY it refuses with
        self.broken = False

    def facts(self) -> dict:
        return FACTS

    def state(self) -> dict:
        if self.broken:
            raise RuntimeError("boom at /private/run/secret, http://127.0.0.1:51999")
        return STATE

    def do(self, command: dict) -> str | None:
        self.got.append(command)
        return self.no


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    """One door for the whole file, on a port the system picks."""
    page = tmp_path_factory.mktemp("console") / "index.html"
    log = F.Log()
    log.reset(1, {"key": "one", "boxes": ["town"]}, T.build({"date": "2025-01-28", "window": ["18:00", "21:00"]}, []))
    log.add([{"tq": 1, "n": "The buyers order", "w": "", "sd": "", "b": ["town"], "l": []}], {"tq": 1, "id": "orders", "n": "The buyers order"})
    srv = S.serve("127.0.0.1", 0, page, log, None, KEY, v1)
    yield SimpleNamespace(srv=srv, port=srv.server_address[1], page=page, log=log)
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def door(served):
    """The door as each test finds it: the page in place, a driver that has been given nothing yet."""
    served.page.write_bytes(PAGE)
    served.driver = served.srv.driver = Driver()
    served.srv.v1 = v1
    return served


def ask(door, method: str, path: str, headers: dict | None = None, body: bytes | str | None = None) -> SimpleNamespace:
    """One request to the door, under its own Host unless the headers name another."""
    conn = http.client.HTTPConnection("127.0.0.1", door.port, timeout=10)
    try:
        conn.request(method, path, body=body, headers={"Host": f"127.0.0.1:{door.port}"} | (headers or {}))
        r = conn.getresponse()
        return SimpleNamespace(code=r.status, headers={k.lower(): v for k, v in r.getheaders()}, body=r.read())
    finally:
        conn.close()


def keyed(more: dict | None = None) -> dict:
    return {"X-Murmur-Console": KEY} | (more or {})


def do(door, body, headers: dict | None = None) -> SimpleNamespace:
    return ask(door, "POST", "/console/do", keyed(headers), body if isinstance(body, (bytes, str)) else json.dumps(body))


# ---------------------------------------------------------------------- the page and the state
def test_the_page_is_served_as_its_bytes_are_and_read_anew_at_every_load(door):
    r = ask(door, "GET", f"/?live=http://127.0.0.1:{door.port}")
    assert (r.code, r.body, r.headers["content-type"], r.headers["content-length"]) == (200, PAGE, "text/html; charset=utf-8", str(len(PAGE)))
    assert "access-control-allow-origin" not in r.headers and ALWAYS.items() <= r.headers.items()
    door.page.write_bytes(PAGE + b"built again\n")
    assert ask(door, "GET", "/?live=http://localhost:1&x=1").body == PAGE + b"built again\n"
    door.page.unlink()
    r = ask(door, "GET", "/?live=x")
    assert (r.code, r.body) == (503, b"") and ALWAYS.items() <= r.headers.items()


@pytest.mark.parametrize("path", ["/", "/?", "/?live=", "/?x=1", "/?since=0", "/?replay=1", "//", "///?x=1"])
def test_the_page_needs_no_live_address_and_no_caller_is_sent_elsewhere(door, path):
    for host in (f"127.0.0.1:{door.port}", f"LocalHost:{door.port}"):
        r = ask(door, "GET", path, {"Host": host})
        assert (r.code, r.body) == (200, PAGE) and "location" not in r.headers and ALWAYS.items() <= r.headers.items()


def test_the_architecture_page_is_the_file_beside_the_page_and_404_where_there_is_none(door):
    assert (ask(door, "GET", "/how").code, ask(door, "GET", "/how").body) == (404, b"")
    how = door.page.with_name(S.HOW)
    how.write_bytes(b"how the network works")
    try:
        r = ask(door, "GET", "/how?x=1")
        assert (r.code, r.body, r.headers["content-type"]) == (200, b"how the network works", "text/html; charset=utf-8") and ALWAYS.items() <= r.headers.items()
    finally:
        how.unlink()


@pytest.mark.parametrize("query", ["", "?", "?since=", "?since=-1", "?since=1.5", "?since=abc", "?since=1&since=2", "?since=%2B1", "?since=1%20", "?x=0", "?Since=0"])
def test_the_state_without_a_valid_since_is_the_runners_state_exactly(door, query):
    r = ask(door, "GET", "/live/state.json" + query)
    assert r.code == 200 and r.headers["access-control-allow-origin"] == "*" and r.headers["content-type"] == "application/json"
    assert json.loads(r.body) == v1() and r.body == json.dumps(v1()).encode()         # as the read-only feed writes it
    assert ALWAYS.items() <= r.headers.items() and len(r.body) < 65_536


def test_the_state_with_a_since_adds_the_second_form(door):
    r = ask(door, "GET", "/live/state.json?since=0")
    out = json.loads(r.body)
    assert r.code == 200 and r.headers["access-control-allow-origin"] == "*" and list(out) == [*v1(), "v2"] and {k: out[k] for k in v1()} == v1()
    assert out["v2"]["run"] == 1 and [m["q"] for m in out["v2"]["moments"]] == [1] and [s["i"] for s in out["v2"]["steps"]] == [0]
    assert out == door.log.answer(v1(), "0") and b", " not in r.body
    assert json.loads(ask(door, "GET", "/live/state.json?since=1&x=y").body)["v2"]["moments"] == []
    door.srv.v1 = v1()                                                                # the state itself in place of what gives it
    assert json.loads(ask(door, "GET", "/live/state.json").body) == v1()


def test_a_door_behind_a_gateway_leaves_the_open_origin_to_the_gateway(door):
    srv = S.serve("127.0.0.1", 0, door.page, door.log, Driver(), KEY, v1, cors=False)
    try:
        for path in ("/live/state.json", "/live/state.json?since=0"):
            r = ask(SimpleNamespace(port=srv.server_address[1]), "GET", path)
            assert r.code == 200 and "access-control-allow-origin" not in r.headers and ALWAYS.items() <= r.headers.items()
            assert json.loads(r.body) == json.loads(ask(door, "GET", path).body)
    finally:
        srv.shutdown()
        srv.server_close()


# ---------------------------------------------------------------------- the console's two routes
def test_the_consoles_state_is_for_whoever_holds_the_key(door):
    r = ask(door, "GET", "/console/state", keyed())
    assert (r.code, json.loads(r.body)) == (200, STATE) and "access-control-allow-origin" not in r.headers and ALWAYS.items() <= r.headers.items()
    for headers in ({}, {"X-Murmur-Console": ""}, {"X-Murmur-Console": KEY[:-1]}, {"X-Murmur-Console": KEY + "x"}, {"X-Murmur-Console": KEY.upper()},
                    {"X-Murmur-Console": "clé"}, {"Authorization": f"Bearer {KEY}"}, {"Cookie": f"k={KEY}"}):
        r = ask(door, "GET", "/console/state", headers)
        assert (r.code, r.body) == (403, b"") and "access-control-allow-origin" not in r.headers
    assert ask(door, "GET", f"/console/state?k={KEY}").code == 403                    # the key is never read from an address


def test_the_key_is_compared_in_constant_time(door, monkeypatch):
    seen = []

    def compare(a, b):
        seen.append((a, b))
        return a == b
    monkeypatch.setattr(S.hmac, "compare_digest", compare)
    assert ask(door, "GET", "/console/state", {"X-Murmur-Console": "guess"}).code == 403 and ask(door, "GET", "/console/state", keyed()).code == 200
    assert do(door, {"do": "hello"}).code == 202 and ask(door, "POST", "/console/do", {"X-Murmur-Console": "guess"}, "{}").code == 403
    assert seen == [(b"guess", KEY.encode()), (KEY.encode(), KEY.encode()), (KEY.encode(), KEY.encode()), (b"guess", KEY.encode())]


def test_a_checked_command_reaches_the_driver_with_its_defaults(door):
    r = do(door, {"do": "surprise", "kind": "battery_low"})
    assert (r.code, json.loads(r.body), r.headers["content-type"]) == (202, {"ok": True}, "application/json")
    assert "access-control-allow-origin" not in r.headers and ALWAYS.items() <= r.headers.items()
    assert do(door, {"do": "run_to", "ts": "2025-01-28 18:00"}).code == 202 and do(door, {"do": "hello"}).code == 202
    assert door.driver.got == [{"do": "surprise", "kind": "battery_low", "who": "home-01", "pct": 10}, {"do": "run_to", "ts": "2025-01-28 18:00"}]
    door.srv.driver.facts = FACTS                                                     # a driver may also hold its facts as they are
    assert do(door, {"do": "step"}).code == 202 and door.driver.got[-1] == {"do": "step"}


@pytest.mark.parametrize("body, words", [
    ({"do": "dance"}, "The console does not know that command."), ({"do": "run_to", "ts": "2025-01-28 12:00"}, "The time must be a quarter-hour of this evening, after the clock's."),
    ({"do": "surprise", "kind": "note", "who": "home-09"}, "That home is not in this network."), ([1, 2], "The console does not know that command."),
    ("{not json", "The command is not a JSON object the console can read."), ("", "The command is not a JSON object the console can read."),
    (b"\xff\xfe{}", "The command is not a JSON object the console can read."), ("[" * 4000, "The command is not a JSON object the console can read."),
    ("NaN", "The console does not know that command."), ('{"do": "surprise", "kind": "weather", "pv": 1' + "0" * 400 + "}", "The number pv must be from 0 to 1."),
    ('{"do": "surprise", "kind": "emergency", "kw": 1e999}', "The number kw must be from 1 to 2000."), (b'{"do": "hello", "pad": "' + b"x" * 4096 + b'"}', "The command is longer than 4,096 bytes."),
    (b"x" * 300_000, "The command is longer than 4,096 bytes.")])
def test_a_command_that_is_not_taken_is_answered_400_in_the_fixed_words(door, body, words):
    r = do(door, body)
    assert (r.code, json.loads(r.body)) == (400, {"error": words}) and words in C.sentences() and door.driver.got == []
    assert ALWAYS.items() <= r.headers.items() and "access-control-allow-origin" not in r.headers
    assert not [w for w in ("Expecting", "char", "line 1", "decode", "codec", "Recursion", "home-09", "dance") if w in r.body.decode()]


def test_a_command_of_4096_bytes_is_still_read_and_one_without_a_length_is_not(door):
    body = json.dumps({"do": "surprise", "kind": "note", "text": "x" * 200}).ljust(4096)
    assert len(body) == 4096 == S.LIMIT and do(door, body).code == 202 and len(door.driver.got) == 1
    for length in (None, "-5", "many", "1e3", ""):
        conn = http.client.HTTPConnection("127.0.0.1", door.port, timeout=10)
        conn.putrequest("POST", "/console/do")
        conn.putheader("X-Murmur-Console", KEY)
        if length is not None:
            conn.putheader("Content-Length", length)
        conn.endheaders()
        r = conn.getresponse()
        assert (r.status, json.loads(r.read())) == (400, {"error": "The command is not a JSON object the console can read."})
        conn.close()
    assert len(door.driver.got) == 1


def test_the_driver_may_refuse_a_checked_command_in_the_fixed_words(door):
    door.driver.no = "starting_already"
    r = do(door, {"do": "hold"})
    assert (r.code, json.loads(r.body)) == (400, {"error": "The network is already starting."}) and door.driver.got == [{"do": "hold"}]
    door.driver.no = "http://127.0.0.1:51999/x failed"                                # whatever a driver gives, only a sentence of the list leaves
    assert json.loads(do(door, {"do": "go"}).body) == {"error": "The console cannot say more."}


@pytest.mark.parametrize("origin, code", [(None, 202), ("http://127.0.0.1:{port}", 202), ("http://localhost:{port}", 202), ("HTTP://LOCALHOST:{port}", 202),
                                          ("null", 403), ("", 403), ("http://127.0.0.1", 403), ("http://127.0.0.1:1", 403), ("https://127.0.0.1:{port}", 403),
                                          ("http://example.org", 403), ("http://127.0.0.1:{port}.example.org", 403), ("http://localhost:{port}/", 403)])
def test_a_command_wants_an_origin_that_is_absent_or_the_doors_own(door, origin, code):
    r = do(door, {"do": "hold"}, None if origin is None else {"Origin": origin.format(port=door.port)})
    assert r.code == code and len(door.driver.got) == (code == 202) and (code == 202 or r.body == b"")
    assert ask(door, "GET", "/console/state", keyed({"Origin": "http://example.org"})).code == 200       # reading the state asks for the key alone


def test_without_the_key_no_command_is_read(door):
    for headers in ({}, {"X-Murmur-Console": "guess"}, {"X-Murmur-Console": KEY + " x"}):
        r = ask(door, "POST", "/console/do", headers, json.dumps({"do": "start"}))
        assert (r.code, r.body) == (403, b"") and ALWAYS.items() <= r.headers.items()
    assert ask(door, "POST", "/console/do", {}, b"x" * 100_000).code == 403 and door.driver.got == []


# ---------------------------------------------------------------------- hosts, methods, paths
@pytest.mark.parametrize("host", ["example.org", "example.org:{port}", "127.0.0.1", "localhost", "127.0.0.1:1", "localhost:80", "127.0.0.1:{port}.example.org",
                                  "[::1]:{port}", "0.0.0.0:{port}", "127.1:{port}", "127.0.0.1:{port}:{port}", "127.0.0.1:0{port}", ""])
def test_every_route_answers_403_unless_the_host_is_one_of_the_doors_own_names(door, host):
    wrong = {"Host": host.format(port=door.port)}
    for method, path in (("GET", f"/?live=http://127.0.0.1:{door.port}"), ("GET", "/"), ("GET", "/live/state.json"), ("GET", "/live/state.json?since=0"),
                         ("GET", "/console/state"), ("POST", "/console/do"), ("GET", "/nowhere"), ("PUT", "/"), ("OPTIONS", "/live/state.json")):
        r = ask(door, method, path, keyed(wrong), "{}" if method == "POST" else None)
        assert (r.code, r.body) == (403, b"") and ALWAYS.items() <= r.headers.items() and "location" not in r.headers, (method, path)
    assert door.driver.got == []


def test_a_request_with_no_host_or_two_is_refused_and_either_own_name_in_any_case_is_taken(door):
    for hosts in ([], [f"127.0.0.1:{door.port}", "example.org"], [f"127.0.0.1:{door.port}", f"127.0.0.1:{door.port}"]):
        conn = http.client.HTTPConnection("127.0.0.1", door.port, timeout=10)
        conn.putrequest("GET", "/live/state.json", skip_host=True)
        for h in hosts:
            conn.putheader("Host", h)
        conn.endheaders()
        assert conn.getresponse().status == 403
        conn.close()
    for own in (f"127.0.0.1:{door.port}", f"localhost:{door.port}", f"LOCALHOST:{door.port}", f" localhost:{door.port} "):
        assert ask(door, "GET", "/live/state.json", {"Host": own}).code == 200 and ask(door, "GET", "/console/state", keyed({"Host": own})).code == 200


@pytest.mark.parametrize("path, allowed", [("/", "GET"), ("/how", "GET"), ("/live/state.json", "GET"), ("/live/surprise", "POST"), ("/console/state", "GET"),
                                           ("/console/do", "POST")])
def test_any_other_method_is_405_and_options_is_403(door, path, allowed):
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "TRACE", "BREW"):
        if method != allowed:
            r = ask(door, method, path, keyed(), "{}" if method in ("POST", "PUT", "PATCH") else None)
            assert (r.code, r.body, r.headers["allow"]) == (405, b"", allowed) and ALWAYS.items() <= r.headers.items(), method
    r = ask(door, "OPTIONS", path, keyed({"Origin": "http://example.org", "Access-Control-Request-Method": allowed, "Access-Control-Request-Headers": "x-murmur-console"}))
    assert (r.code, r.body) == (403, b"") and not [h for h in r.headers if h.startswith("access-control")] and ALWAYS.items() <= r.headers.items()
    assert door.driver.got == []


@pytest.mark.parametrize("path", ["/index.html", "/live", "/live/state.json/", "/console", "/console/do/", "/Console/State", "/live/surprise/", "/how/", "//example.org/", "/../console/state", "/%2e%2e/console/state", "/console/state;x"])
def test_any_other_path_is_404(door, path):
    for method in ("GET", "POST"):
        r = ask(door, method, path, keyed(), "{}" if method == "POST" else None)
        assert (r.code, r.body) == (404, b"") and ALWAYS.items() <= r.headers.items()


def test_the_browser_s_question_for_an_icon_is_answered_quietly_and_only_by_get(door):
    r = ask(door, "GET", "/favicon.ico", None, None)
    assert (r.code, r.body) == (204, b"") and ALWAYS.items() <= r.headers.items()
    assert ask(door, "POST", "/favicon.ico", keyed(), "{}").code == 404


def test_what_fails_behind_the_door_is_answered_500_with_none_of_its_text(door, caplog):
    door.driver.broken = True
    r = ask(door, "GET", "/console/state", keyed())
    assert (r.code, r.body) == (500, b"") and ALWAYS.items() <= r.headers.items() and "boom" in caplog.text
    assert not [h for h in r.headers.values() if "boom" in h or "secret" in h]
    door.srv.v1 = lambda: 1 / 0
    r = ask(door, "GET", "/live/state.json?since=0")
    assert (r.code, r.body) == (500, b"") and ALWAYS.items() <= r.headers.items() and "ZeroDivisionError" in caplog.text


def test_a_request_line_the_server_cannot_read_is_answered_with_the_same_headers_and_no_text_of_it(door):
    lines = {b"NOT A REQUEST AT ALL javascript:alert(1)\r\n": b"400", b"GET / HTTP/9.9\r\n": b"505", b"BREW / FTP/1.0\r\n": b"400",
             b"GET /" + b"a" * 65_532: b"414"}                                        # each sent whole and no further: the server reads all of it
    for line, code in lines.items():
        with socket.create_connection(("127.0.0.1", door.port), timeout=10) as s:
            s.sendall(line)
            got = b""
            while chunk := s.recv(65536):
                got += chunk
        head, _, body = got.lower().partition(b"\r\n\r\n")
        assert head.split()[:2] == [b"http/1.0", code] and body == b"" and b"alert" not in got and b"aaaa" not in got
        assert all(f"{k}: {v}".encode() in head for k, v in ALWAYS.items())
        assert b"python" not in head and b"server: murmur-console" in head


def test_no_answer_holds_the_key(door):
    asked = [ask(door, "GET", f"/?live=http://127.0.0.1:{door.port}", keyed()), ask(door, "GET", "/", keyed()), ask(door, "GET", "/live/state.json?since=0", keyed()),
             ask(door, "GET", "/console/state", keyed()), do(door, {"do": "hello"}), do(door, {"do": KEY}), do(door, KEY), ask(door, "GET", f"/{KEY}", keyed()),
             ask(door, "GET", "/console/state", {"X-Murmur-Console": KEY, "Host": KEY})]
    assert [r.code for r in asked] == [200, 200, 200, 200, 202, 400, 400, 404, 403]
    assert not [r for r in asked if KEY.encode() in r.body or KEY in json.dumps(r.headers)]


# ---------------------------------------------------------------------- the key file and the link file
def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_the_key_file_is_made_when_absent_with_mode_600_and_a_pair_shares_it(tmp_path):
    path = tmp_path / "console.key"
    key = S.read_key(path)
    assert len(key) == 32 and set(key) <= set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_") and mode(path) == 0o600
    assert path.read_text() == key + "\n" and S.read_key(path) == key == S.read_key(str(path))        # the second console reads the first one's
    assert sorted(p.name for p in tmp_path.iterdir()) == ["console.key"]
    assert S.read_key(tmp_path / "other.key") != key
    path.chmod(0o644)
    assert S.read_key(path) == key and mode(path) == 0o600                            # a key file left open to others is closed again


def test_consoles_that_start_together_end_with_one_key(tmp_path):
    path, keys = tmp_path / "pair.key", []
    threads = [threading.Thread(target=lambda: keys.append(S.read_key(path))) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(keys) == 12 and len(set(keys)) == 1 and path.read_text().strip() == keys[0] and [p.name for p in tmp_path.iterdir()] == ["pair.key"]


@pytest.mark.parametrize("text", ["", "\n", "short", "two words that are long enough", "a-key-with-a-café-in-it-0123456789", "x" * 15])
def test_a_key_file_that_holds_no_key_is_refused(tmp_path, text):
    path = tmp_path / "console.key"
    path.write_text(text)
    with pytest.raises(ValueError, match="holds no key"):
        S.read_key(path)
    with pytest.raises(ValueError, match="too short"):
        S.serve("127.0.0.1", 0, tmp_path / "index.html", F.Log(), Driver(), "x" * 15, v1)


def test_the_link_is_written_beside_the_key_file_with_mode_600(tmp_path):
    path = tmp_path / "console.key"
    key = S.read_key(path)
    link = S.write_link(path, 51234, key)
    assert link == f"http://127.0.0.1:51234/?live=http://127.0.0.1:51234#k={key}"
    assert (tmp_path / "console.key.link").read_text() == link + "\n" and mode(tmp_path / "console.key.link") == 0o600
    (tmp_path / "console.key.link").chmod(0o644)
    again = S.write_link(str(path), 51235, key)                                       # the next start writes it anew, closed again
    assert (tmp_path / "console.key.link").read_text() == again + "\n" != link + "\n" and mode(tmp_path / "console.key.link") == 0o600
    assert sorted(p.name for p in tmp_path.iterdir()) == ["console.key", "console.key.link"]
