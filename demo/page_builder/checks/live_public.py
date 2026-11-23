"""Plays a looping console for an audience through its page, in a browser, as a viewer with no key sees it.

  python -m demo.page_builder.checks.live_public --config CONFIG [--next CONFIG] [--page PAGE] [--python PYTHON] [--shots DIR]

Starts `python -m demo.console --loop-days [NEXT] --audience` on the configuration (every part on this computer, the console on a
free port, its key in a new folder) and opens the console's plain address, with no live address and no key in it, on a phone's
screen. Checked: Live opens by itself; no presenter's control shows; the strip has six events, each at least 44 px high; the
first tap fires and the banner says so; a second viewer's tap is a vote, and that viewer's strip takes no second one; when the
cooldown is over the vote fires; a tap that carries anything but its preset is refused; the card for a phone has a QR code drawn
in the page, three links and two lines; at 375x667, 390x844, 430x932, 1440x900 and 1920x1080 nothing is cut and nothing scrolls
sideways; ?replay=1 stays the recording; the presenter's link still shows the controls and no strip; and after the evening has
settled the next one starts by itself, with all its events again. A copy of the page is also given out by a plain file server
of this check's own, under a folder and with a live.json beside it that names the console: there Live opens too, a tap from that
other origin is counted, the screen never names the console's address, and the card's code and links are the copy's own; the
same copy without live.json stays the recording. --next is the configuration of a second day; without it the
same evening plays again. --page is the page file the console gives out (else its own). --python is the interpreter of this repository's own environment. Exit code 1 when a check fails.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from demo.console import crowd as K

from .browser import chrome, js
from .live_run import ROOT, wait_for

PHONES, WIDE = [(375, 667), (390, 844), (430, 932)], [(1440, 900), (1920, 1080)]
HOW = "Murmur_NG_Architecture_and_Data.html"


def feed(port: str) -> dict:
    return json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/live/state.json?since=0", timeout=5)).get("v2") or {}


def tap(port: str, body: bytes) -> int:
    req = urllib.request.Request(f"http://127.0.0.1:{port}/live/surprise", data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        return urllib.request.urlopen(req, timeout=5).status
    except urllib.error.HTTPError as e:
        return e.code


def published(page: Path, live: str) -> tuple[http.server.ThreadingHTTPServer, str]:
    """A copy of the page as a file server gives it out, under site/ with a live.json that names `live`, and under bare/ with none."""
    root = Path(tempfile.mkdtemp(prefix="published-"))
    for name in ("site", "bare"):
        (root / name).mkdir()
        shutil.copy(page, root / name / "index.html")
        shutil.copy(page.with_name(HOW), root / name / HOW)
    (root / "site" / "live.json").write_text(json.dumps({"live": live}))
    (root / "favicon.ico").write_bytes(b"")           # the browser's own question, so that its 404 is not taken for the page's
    quiet = type("Quiet", (http.server.SimpleHTTPRequestHandler,), {"log_message": lambda *a: None})
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(quiet, directory=str(root)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/"


def until(what, seconds: float, every: float = 0.5):
    end = time.time() + seconds
    while time.time() < end:
        got = what()
        if got:
            return got
        time.sleep(every)
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m demo.page_builder.checks.live_public", description="A looping console, as its audience sees it.")
    ap.add_argument("--config", required=True)
    ap.add_argument("--next", default=None, help="a second day's configuration")
    ap.add_argument("--page", default=None, help="the page file the console gives out")
    ap.add_argument("--python", default=sys.executable, help="the interpreter of this repository's environment")
    ap.add_argument("--shots", type=Path)
    a = ap.parse_args(argv)
    keys = Path(tempfile.mkdtemp(prefix="console-key-"))
    out = keys / "console.out"
    days = [*(["--page", a.page] if a.page else []), "--loop-days", *([a.next] if a.next else [])]
    proc = subprocess.Popen([a.python, "-m", "demo.console", "--config", a.config, *days, "--audience", "--port", "0", "--speed", "4", "--key-file", str(keys / "key")],
                            cwd=ROOT, env={"PATH": "/usr/bin:/bin", "PYTHONPATH": "src:."}, stdout=out.open("w"), stderr=subprocess.STDOUT)
    fails: list[str] = []
    site = None

    def check(ok: bool, what: str, seen: object = "") -> None:
        print(f"{'ok   ' if ok else 'FAULT'} {what}" + ("" if ok else f": {str(seen)[:400]}"))
        if not ok:
            fails.append(what)

    def shot(pg, name: str) -> None:
        if a.shots:
            a.shots.mkdir(parents=True, exist_ok=True)
            pg.screenshot(path=str(a.shots / f"live_public_{name}.png"))
    try:
        port = wait_for(out, r"console on http://127\.0\.0\.1:(\d+)/", 300).group(1)
        home, errors = f"http://127.0.0.1:{port}/", []
        with chrome() as browser:
            def viewer(size: tuple[int, int], path: str = "", at: str = home, heard: list[str] = errors):
                ctx = browser.new_context(viewport={"width": size[0], "height": size[1]}, has_touch=size[0] < 700)
                pg = ctx.new_page()
                pg.on("pageerror", lambda e: heard.append(str(e)[:200]))
                pg.on("console", lambda m: heard.append(m.text[:200]) if m.type == "error" else None)
                pg.goto(at + path)
                return pg
            state = lambda pg: pg.evaluate(js("live_public.js#state"))      # noqa: E731
            one = viewer(PHONES[1])
            one.wait_for_selector("#app.lv-aud", timeout=60000)
            check(one.url == home, "the plain address stays as it is: no live address, no key", one.url)
            s = until(lambda: (lambda x: x if x["open"] == 6 else None)(state(one)), 240)
            check(bool(s), "the evening starts by itself and the six events open", state(one))
            s = s or state(one)
            check(s["live"] and s["strip"] and not s["controls"] and s["pills"] == 6, "Live with the strip of six, and no presenter's control", s)
            check(s["press"] >= 44, "what a thumb presses is at least 44 px high", s)
            check(s["mark"] == "LIVE" and s["day"].startswith("Day 1 of 2" if a.next else "Jan "), "the LIVE mark and the day", s)
            most, cool = K.MOST, int(K.COOLDOWN_S)
            check(s["count"].startswith(f"{most}/{most}"), "the evening's events are all still to come", s)
            two = viewer(PHONES[0])                     # the other viewers stand ready: a round of votes is short
            two.wait_for_selector("#app.lv-aud", timeout=60000)
            site, there = published(Path(a.page) if a.page else ROOT / "demo" / "pages" / "index.html", home.rstrip("/"))
            far = viewer(PHONES[2], "site/", there)
            far.wait_for_selector("#app.lv-aud", timeout=60000)
            check(far.url == there + "site/", "a copy published elsewhere finds the console through live.json, its address unchanged", far.url)
            until(lambda: state(two)["open"] == 6 and state(far)["open"] == 6, 20)
            one.click('.lv-ev[data-kind="weather"]')
            f = until(lambda: (lambda c: c if c and c.get("left") == most - 1 else None)(feed(port).get("crowd")), 10)
            check(bool(f) and f["last"]["kind"] == "weather" and f["last"]["by"] == "viewer" and cool - 5 <= f["cooldown_s"] <= cool, "the first tap fires and starts the cooldown", f)
            s = until(lambda: (lambda x: x if x["flash"] else None)(state(one)), 5) or state(one)
            check("Live viewer triggered: Solar drop" in s["flash"] and s["count"].startswith(f"{most - 1}/{most}"), "the banner says what a viewer triggered", s)
            two.click('.lv-ev[data-kind="car_now"]')
            far.click('.lv-ev[data-kind="emergency"]')
            f = until(lambda: (lambda c: c if c and len(c.get("votes") or {}) == 2 else None)(feed(port).get("crowd")), cool) or feed(port).get("crowd") or {}
            check((f.get("votes") or {}).get("car_now") == 1 and f.get("left") == most - 1, "a tap during the cooldown is a vote, not a second event", f)
            check(f.get("votes") == {"car_now": 1, "emergency": 1}, "a tap from the other origin is counted", f)
            s = state(two)
            check(s["open"] == 0 and "1" in s["votes"], "the voter's strip shows the vote and takes no second one", s)
            shot(one, "fired")
            check(not far.evaluate(js("live_public.js#says"), f"127.0.0.1:{port}") and state(far)["mark"] == "LIVE", "the copy's screen never names the console's address", state(far))
            far.click(".lv-qrb")
            c = far.evaluate(js("live_public.js#card"))
            check(c["address"] == there + "site/" and c["links"][0][1] == there + "site/" and c["links"][2][1] == there + "site/" + HOW and bool(c["code"]),
                  "the copy's card has the copy's own address and the architecture page beside it", c)
            bare = viewer(PHONES[2], "bare/", there, [])
            bare.wait_for_timeout(2500)
            check(not state(bare)["live"], "the same copy without live.json stays the recording")
            check(tap(port, b'{"kind": "weather", "note": "free text"}') == 400 and tap(port, b'{"kind": "note"}') == 400 and tap(port, b"weather") == 400,
                  "a tap with anything but one preset is refused")
            f = until(lambda: (lambda c: c if c and c.get("left") == most - 2 else None)(feed(port).get("crowd")), cool + 20) or {}
            check((f.get("last") or {}).get("kind") == "car_now" and (f.get("last") or {}).get("by") == "vote", "when the cooldown ends the vote fires", f)
            one.click(".lv-qrb")
            c = one.evaluate(js("live_public.js#card"))
            check(c["head"] == "Try it on your phone" and [x[0] for x in c["links"]] == ["Open the live demo", "Data view", "How the network works"], "the card and its three links", c)
            check(c["links"][0][1] == home and c["links"][1][1] == home + "#data" and c["links"][2][1] == home + "how" and c["address"] == home, "every link is the console's own address", c)
            check(bool(c["code"]) and c["code"]["ink"] == "#1B2A38" and c["code"]["paper"] == "#FFFFFF" and c["code"]["modules"] > 150 and c["code"]["images"] == 0,
                  "the QR code is drawn in the page, navy on white", c["code"])
            check(len(c["lines"]) == 2 and "answering now" in c["lines"][0] and "played this evening" in c["lines"][1], "two lines of what is live now", c["lines"])
            for size in PHONES + WIDE:
                one.set_viewport_size({"width": size[0], "height": size[1]})
                one.wait_for_timeout(700)
                s = state(one)
                check(s["card"] and not s["cut"] and not s["sideways"] and (size in PHONES or not s["dayCut"]), f"{size[0]}x{size[1]}: nothing cut, nothing sideways", s)
                shot(one, f"card_{size[0]}x{size[1]}")
            one.keyboard.press("Escape")
            shot(one, "wide")
            check(not state(one)["card"], "Escape closes the card")
            old = viewer(WIDE[0], "?replay=1")
            old.wait_for_timeout(2500)
            check(not state(old)["live"], "?replay=1 stays the recording")
            pres = viewer(WIDE[0], (keys / "key.link").read_text().strip()[len(home):])
            pres.wait_for_selector("#lv-bar.lv-pres", timeout=30000)
            s = state(pres)
            check(s["controls"] and not s["strip"] and not s["audience"], "a presenter's key still shows the controls, and no strip", s)
            run = feed(port).get("run")
            said = until(lambda: (lambda x: x if "Next day starting in" in x["words"] else None)(state(two)), 600)
            check(bool(said), "a settled evening says the next day is starting", state(two))
            shot(two, "settled")
            f = until(lambda: (lambda v: v if v.get("run", 0) > run and (v.get("crowd") or {}).get("open") else None)(feed(port)), 300) or {}
            check((f.get("crowd") or {}).get("left") == most and (f.get("loop") or {}).get("day") == (2 if a.next else 1), "the next evening starts by itself, with all its events again", f.get("loop"))
            check(not errors, "no script error", errors)
    finally:
        if site is not None:
            site.shutdown()
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
    print(f"faults: {len(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
