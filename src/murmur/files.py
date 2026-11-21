"""Files a service writes beside its state: written whole or not at all, and set aside rather than trusted when they can't be read."""
from __future__ import annotations

import hashlib
import logging
import os
import threading
from pathlib import Path

from murmur import config

log = logging.getLogger("murmur.files")


def write_atomic(path: Path, data: bytes) -> None:
    """The file is the old one or the new one, whatever happens: the bytes go to disk under another name in the same folder, then that name takes over."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stem = f".{path.name}."
    tmp = path.with_name(f"{stem}{os.getpid()}.{threading.get_ident()}")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    try:                                                  # the rename itself, past a power cut
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        with os.scandir(path.parent) as found:            # a kill before the rename leaves its temp file, and nothing else would ever remove it
            for f in found:
                if f.name.startswith(stem):
                    os.unlink(f.path)
    except OSError:
        pass


def set_aside(path: Path) -> None:
    """A file that can't be used, moved out of the way and kept for a person to look at."""
    try:
        Path(path).replace(Path(path).with_name(Path(path).name + ".old"))
    except OSError as exc:
        log.error("%s couldn't be set aside: %s", path, exc)


def code_stamp() -> str:
    """A short hash of the package's code as this process found it at its start (GET /health "code")."""
    h = hashlib.sha1()
    for p in sorted(config.CODE_DIR.rglob("*.py")):
        h.update(str(p.relative_to(config.CODE_DIR)).encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:12]
