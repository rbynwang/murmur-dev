"""The whole picture's markup for one evening: every box of the tree open, at the place the tree's geometry gives it, with its
paragraph, its notes and an empty terminal the page fills; Where it stands and the trade beside the buyers; each level's name.
The structure is `templates/replay/world.html`."""
from __future__ import annotations

from typing import Any

from .. import templating as T
from . import status, words as W
from .notes import notes_for

R = "replay/world.html#"


def place(g: list[int]) -> dict[str, int]:
    return {"x": g[0], "y": g[1], "w": g[2], "h": g[3]}


def extra(ev: Any, b: str) -> T.Markup:
    """A box's own list: a node agent's nine steps, the guard's six checks, what a person can write and hear."""
    if b in ("h-agent", "b-agent"):
        return T.render(R + "nine", rows=T.join(T.render(R + "step", mdl="mdl" if who == "model" else "", n=n, name=name,
                                                         who=who) for n, name, who in W.NINE))
    if b in ("h-guard", "b-guard"):
        return T.render(R + "six", rows=T.join(T.render(R + "check", n=n, name=name, does=d) for n, name, d in W.CHECKS))
    if b in ("h-person", "b-person"):
        return T.render(R + "says", write=T.join(T.render(R + "say", word=a, does=d) for a, d in W.SAYS),
                        hear=T.join(T.render(R + "say", word=a, does=d) for a, d in W.HEARS))
    return T.Markup("")


def notes(ev: Any, b: str) -> T.Markup:
    revs, gaps = notes_for(ev, b)
    if not revs and not gaps:
        return T.Markup("")
    return T.render(R + "notes", revs=T.join(T.render(R + "rev", title=t, tag=tag, was=was, now=now) for t, tag, was, now in revs),
                    gaps=T.join(T.render(R + "gap", title=t, text=a) for t, a in gaps))


def block(ev: Any, b: str, g: list[int]) -> T.Markup:
    _, name, hue, kind, _ = ev.map.by[b]
    return T.render(R + "block", hue=hue, b=b, **place(g), full=ev.map.full(b), tag=T.render(R + "kind", kind=kind) if kind else T.Markup(""),
                    para=ev.map.about.get(b, ""), extra=extra(ev, b), notes=notes(ev, b), cols=g[4], term=g[5])


def where_it_stands(ev: Any, g: list[int]) -> T.Markup:
    cols = T.join(T.render(R + "column", lists=T.join((T.render(R + "list", head=head, items=T.join(T.render(R + "item", text=t) for t in items))
                                                       for head, items in col), "\n")) for col in status.columns(ev))
    return T.render(R + "status", **place(g), title=W.WHO_TITLE, scope=W.WHO_SCOPE,
                    rows=T.join(T.render(R + "who_row", who=a, does=d) for a, d in W.WHO_ROWS), cols=cols)


def world(ev: Any, d: dict[str, Any]) -> T.Markup:
    """The tree of open boxes for one evening: the page puts it in when the evening is chosen."""
    tree = d["tree"]
    b = tree["b"]
    inp = b["input"]
    return T.render(R + "world", w=tree["W"], h=tree["H"], root=T.render(R + "root", **place(inp), term=inp[5]),
                    status=where_it_stands(ev, b["status"]),
                    trade=T.render(R + "trade", **place(b["trade"]), rows=T.join(T.render(R + "figure", key=k, label=lab) for k, lab in ev.tv)),
                    blocks=T.join(block(ev, x, b[x]) for x in ev.map.ids if x in b),
                    levels=T.join(T.render(R + "level", x=x, y=y, name=name) for x, y, name in tree["lv"]))
