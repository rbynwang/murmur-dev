"""HTML templates and static files for the demo pages.

A template is an HTML file under `templates/`. A file may hold several named snippets, each starting at a marker line
`<!-- @name -->`; the snippet is the text after its marker line up to the next marker (or the end of the file), less one
trailing newline. A file without markers is one template. Slots are written `{{name}}`. A value is HTML-escaped unless it
is `Markup` (already HTML, such as another rendered snippet). Every slot must be filled and every value used, so a typo
fails the build instead of leaving a hole in a page.

Style sheets and scripts are plain files under `static/`; `static()` reads them, in the order given, for a page's
`<style>` or `<script>` element.
"""
from __future__ import annotations

import html
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE / "templates"
STATIC = HERE / "static"
MARKER = re.compile(r"^<!-- @([a-z][a-z0-9_]*) -->\n", re.M)
SLOT = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")


class Markup(str):
    """Text that is already HTML: placed into a slot as it is."""


def esc(value: Any) -> str:
    """The escaped text of a value, or the value itself when it is Markup."""
    return value if isinstance(value, Markup) else html.escape(str(value), quote=True)


@lru_cache(maxsize=None)
def snippets(rel: str) -> dict[str, str]:
    """The named snippets of one template file (one snippet named after the file when it has no markers)."""
    text = (TEMPLATES / rel).read_text(encoding="utf-8")
    marks = list(MARKER.finditer(text))
    if not marks:
        return {Path(rel).stem: text[:-1] if text.endswith("\n") else text}
    if text[: marks[0].start()].strip():
        raise ValueError(f"{rel}: text before the first snippet marker")
    out: dict[str, str] = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.end():end]
        if m.group(1) in out:
            raise ValueError(f"{rel}: two snippets named {m.group(1)}")
        out[m.group(1)] = body[:-1] if body.endswith("\n") else body
    return out


def render(ref: str, **values: Any) -> Markup:
    """Fill a template. `ref` is "path/file.html" or "path/file.html#snippet"."""
    rel, _, name = ref.partition("#")
    parts = snippets(rel)
    key = name or Path(rel).stem
    if key not in parts:
        raise KeyError(f"{ref}: no such snippet (has {', '.join(sorted(parts))})")
    text = parts[key]
    wanted = set(SLOT.findall(text))
    missing, unused = wanted - set(values), set(values) - wanted
    if missing or unused:
        raise KeyError(f"{ref}: slots without a value {sorted(missing)}, values without a slot {sorted(unused)}")
    return Markup(SLOT.sub(lambda m: esc(values[m.group(1)]), text))


def join(parts: Iterable[str], sep: str = "") -> Markup:
    """Rendered pieces placed one after another (each one escaped unless it is Markup)."""
    return Markup(sep.join(esc(p) for p in parts))


def static(*rels: str) -> Markup:
    """The contents of static files (style sheets or scripts), one after another."""
    return Markup("".join((STATIC / r).read_text(encoding="utf-8") for r in rels))


def script_json(value: Any, **dumps: Any) -> Markup:
    """JSON that can stand inside a <script> element: every "</" is written "<\\/" so the element cannot end early."""
    text = json.dumps(value, ensure_ascii=False, **dumps)
    return Markup("<\\/".join(text.split("</")))
