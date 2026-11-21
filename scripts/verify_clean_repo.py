#!/usr/bin/env python3
"""Fails when a tracked file holds a trace of a private machine, a private network or an earlier project.

  python scripts/verify_clean_repo.py [ROOT] [--list] [--add TERM ...]

It reads every file git tracks under ROOT (default: the repository this script is in; every file below ROOT when it is not a git repository),
including what is packed inside a page (base64 gzip in a script tag) and inside .gz files, and exits 1 on the first kind of trace it finds:

  names     machine and host names, operating-system user names, names of earlier projects, courses and private tools, old node names,
            names of remote-login and port-forwarding tools, and the port numbers those links used
  ids       old participant ids written with hyphens, matched on any two to four hyphen-joined parts
  addresses private network addresses (the 10, 172.16 to 172.31, 192.168 and 100.64 to 100.127 ranges), e-mail addresses (but for
            example.* addresses and the public no-reply address a commit's author line carries: ...@users.noreply.github.com)
  paths     a user's home folder written out

The names are not written in this file. Each is kept as a salted SHA-256 hash, so the check itself carries no trace of what it looks for:
`--add TERM` prints the line to paste for a new name. A name is matched three ways, as the lists below say: as a whole word, as part of a
longer word, or as two words in a row. Matching ignores case unless the entry was added with a capital letter.

Every network link of the system is an address in a configuration file. 127.0.0.1 and localhost are allowed: they name no machine.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import re
import subprocess
import sys
from pathlib import Path

SALT = b"murmur-clean-repo-v1:"
# hashes of whole words (lower case, or as written when the entry has a capital), of stems that may stand inside a longer word, and of two words in a row
WORDS: frozenset[str] = frozenset({
    # WORDS-BEGIN
    "374bdc36235f9a9771b5",
    "2a755987b244b2f2d68b",
    "dc484ca46ba333febe6f",
    "688100d9eeb3883f1078",
    "8e54b5537081eb40a6d1",
    "dc7ce71aebea38d1c793",
    "c8f142a92ad342a6fd42",
    "30015ba45f4dcebba2d3",
    "5a8fd313327515e22757",
    "2a16e64141e20221bf57",
    "95eeeafd34c082e9d692",
    "6a39b77c6ad2a3926280",
    "b0705b0a6bbae6380389",
    "4352cd1b3608d0761bd5",
    "9fce49110ebac3bfeffc",
    "d636991e0f5158daf6fc",
    "5a1898a16ccab145755f",
    "8b293c99254f7fb203e2",
    "fafaa1f6d2487eeac571",
    "ce401cd8555df3ff7cf2",
    "ed00dc7c94dbd707dd0a",
    "b31f6c14cb2e64122752",
    "2c075828d6530860aa90",
    "ab2fc26e97a4efb5ed5b",
    "b13ebac546c6ef232f3c",
    "19dec484e00d98cee916",
    "419c6ae6abebfec0636b",
    "244fbe0597ddd4b9561a",
    "abfaa655bc7f3f516d52",
    "4e00718342474dcfd63d",
    "9cb0d0de9b9858af4eb4",
    "b48f582861d4c01a7637",
    "e76680e7fa9be362915d",
    "b1d931fd0f071c066792",
    "2d635c915ca3172682da",
    "633df6760722775eff82",
    "f086c902145df00e859b",
    # WORDS-END
})
STEMS: frozenset[str] = frozenset({
    # STEMS-BEGIN
    "5a8fd313327515e22757",
    "95eeeafd34c082e9d692",
    "b7e3268e3a8e178ef19e",
    "b0705b0a6bbae6380389",
    "4352cd1b3608d0761bd5",
    "ce401cd8555df3ff7cf2",
    "e3e9372be610d338e82b",
    "ed00dc7c94dbd707dd0a",
    "b31f6c14cb2e64122752",
    "19dec484e00d98cee916",
    "419c6ae6abebfec0636b",
    "abfaa655bc7f3f516d52",
    "9dac4e454d9778aaddbf",
    "4e00718342474dcfd63d",
    "2d635c915ca3172682da",
    "2485c3db1ed94abb84ee",
    "f086c902145df00e859b",
    # STEMS-END
})
PAIRS: frozenset[str] = frozenset({
    # PAIRS-BEGIN
    "fdbf9d0d4b9593ea1b34",
    "f533966ac1c3573eea72",
    "633f52db21b434d7c333",
    "11e83d3d53bd539ee07b",
    "f13a7999facf17b26226",
    "d63365129538df9f7d96",
    "942b6a173d2134e9d99b",
    "081d355eed0eaa782480",
    "a24d41fb2eae6090b926",
    "762e355cb91f1dacfd05",
    "f3811e1fa6b84d2d61f4",
    # PAIRS-END
})
IDS: frozenset[str] = frozenset({
    # IDS-BEGIN
    "60815b8b352243b8d3ac",
    "e2a581e75bf394135b07",
    "5ba493cdb23a000cd94a",
    "c0d87b890c0cec0af3fe",
    "438a0824f2c8e06dcec3",
    "b545d4240a2515431acd",
    "106ed7d4c33ea833bbe5",
    "b660642b13253eeffde8",
    "f5ef24f83403b538abf8",
    "9e7ef4d9307d7e2bb26e",
    "45602777195ee5e57139",
    "1cf2f210fafafdffbe7a",
    "c3fb29b4d52926b4bbf5",
    "093acf03cbfc58abe7a2",
    "9d8288eee4d18d1bf8e5",
    "d2f0f174318af0ae212e",
    "0ac98df1ed001703cdd5",
    # IDS-END
})
STEM_LENGTHS: tuple[int, ...] = (6, 7, 8, 9, 10, 11)      # the lengths the stems have
STEM_STARTS: frozenset[str] = frozenset({'au', 'cl', 'fl', 'ho', 'ja', 'je', 'la', 'ma', 'mo', 'op', 'pe', 'ro', 'ta', 'tu', 'wx'})      # their first two letters: a quick test before a window is hashed

ADDRESS = [
    ("a private network address", re.compile(r"(?<![\d.])(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01])|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7]))\.\d{1,3}\.\d{1,3}(?![\d.])")),
    ("an e-mail address", re.compile(r"(?<![A-Za-z0-9._%-])[A-Za-z0-9][A-Za-z0-9._%+-]*@(?!example\.)"
                                     r"(?!users\.noreply\.github\.com\b)[A-Za-z0-9-]+\.[A-Za-z]{2,}")),      # an address starts with a letter or digit: a patch's "+@decorator" is none
    ("a user's home folder", re.compile(r"(?<![\w.])/(?:Users|home)/[A-Za-z][A-Za-z0-9_.-]*")),
    ("an old node name", re.compile(r"\bhh-\d{3}\b")),
]
RUN = re.compile(r"[A-Za-z0-9]+")
HYPHENED = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+")
PACK = re.compile(r'<script type="text/plain"[^>]*>([A-Za-z0-9+/=\s]{200,})</script>')
EMBEDDED = re.compile(r"data:[a-z0-9.+/-]+;base64,[A-Za-z0-9+/=]+")
BINARY = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".pdf", ".npy", ".npz", ".parquet", ".zip", ".pyc"}


def h(term: str) -> str:
    return hashlib.sha256(SALT + term.encode("utf-8")).hexdigest()[:20]


def texts(path: Path) -> list[tuple[str, str]]:
    """(where, text) for a file: its own text, and every pack found in it."""
    raw = path.read_bytes()
    if b"\0" in raw[:4096] and path.suffix != ".gz":      # not text
        return []
    if path.suffix == ".gz":
        try:
            raw = gzip.decompress(raw)
        except OSError:
            return []
    text = raw.decode("utf-8", "replace")
    out = []
    for n, m in enumerate(PACK.finditer(text)):
        try:
            out.append((f" (pack {n + 1})", gzip.decompress(base64.b64decode(m.group(1))).decode("utf-8", "replace")))
        except (OSError, ValueError):
            pass
    # what is packed or embedded is read unpacked, or is a picture: its base64 letters are not words
    text = PACK.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    text = EMBEDDED.sub("", text)
    return [("", text)] + out


def scan(text: str) -> list[tuple[int, str, str]]:
    """(offset, kind, excerpt) for every trace in a text. The excerpt is cut around the place, with the name itself left out."""
    hits = []
    for kind, pat in ADDRESS:
        hits += [(m.start(), kind, "") for m in pat.finditer(text)]
    prev = None
    for m in RUN.finditer(text):
        raw = m.group()
        low = raw.lower()
        if low.isdigit():                                # a figure inside a decimal number is not a port
            before, after = text[m.start() - 1: m.start()], text[m.end(): m.end() + 2]
            if before in (".", ",") or (len(after) == 2 and after[0] == "." and after[1].isdigit()):
                prev = m
                continue
        if h(low) in WORDS or (raw != low and h(raw) in WORDS):
            hits.append((m.start(), "a listed name", ""))
        elif not low.isdigit():
            for n in STEM_LENGTHS:
                if len(low) >= n and any(low[i:i + 2] in STEM_STARTS and h(low[i:i + n]) in STEMS for i in range(len(low) - n + 1)):
                    hits.append((m.start(), "a listed name inside a word", ""))
                    break
        if prev is not None and m.start() - prev.end() <= 2 and h(prev.group().lower() + " " + low) in PAIRS:
            hits.append((prev.start(), "a listed pair of words", ""))
        prev = m
    for m in HYPHENED.finditer(text):
        parts = m.group().lower().split("-")
        if any(h("-".join(parts[i:j])) in IDS for i in range(len(parts)) for j in range(i + 2, min(len(parts), i + 4) + 1)):
            hits.append((m.start(), "an old participant id", ""))
    return hits


def tracked(root: Path) -> list[Path]:
    got = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True)
    if got.returncode == 0 and got.stdout:
        return [root / p for p in got.stdout.decode().split("\0") if p]
    return sorted(p for p in root.rglob("*") if p.is_file() and not {".git", "__pycache__", ".venv", ".pytest_cache"} & set(p.relative_to(root).parts))


def main(argv: list[str]) -> int:
    if "--add" in argv:
        for term in argv[argv.index("--add") + 1:]:
            print(f'    "{h(term if term != term.lower() and " " not in term else term.lower())}",')
        return 0
    root = Path(next((a for a in argv if not a.startswith("--")), Path(__file__).resolve().parents[1])).resolve()
    files, skipped, found = tracked(root), 0, {}
    for path in files:
        if path.suffix.lower() in BINARY or not path.is_file():
            skipped += 1
            continue
        for where, text in texts(path):
            for at, kind, _ in scan(text):
                line = text.count("\n", 0, at) + 1
                found.setdefault((str(path.relative_to(root)) + where, kind), []).append(line)
    show = sorted(found.items()) if "--list" in argv else sorted(found.items())[:40]
    for (name, kind), lines in show:
        print(f"{name}: {kind} x{len(lines)} (line {', '.join(str(n) for n in lines[:8])}{' ...' if len(lines) > 8 else ''})")
    if len(found) > len(show):
        print(f"... and {len(found) - len(show)} more places (--list shows all)")
    total = sum(len(v) for v in found.values())
    kinds = {}
    for (_, kind), lines in found.items():
        kinds[kind] = kinds.get(kind, 0) + len(lines)
    print(f"{len(files)} files read ({skipped} binary files not opened): {total} traces in {len({k[0].split(' (pack')[0] for k in found})} files" + (f" {kinds}" if kinds else ""))
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
