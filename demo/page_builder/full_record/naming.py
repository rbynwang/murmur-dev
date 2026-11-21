"""Homes and buildings by the names the Full record gives them.

A recording names a home or a building by its id, and the page never shows one. A home is "Home 71" wherever it stands. A
building is "the shopping center", with a capital where the page text before it, spaces aside, ends with an element's
opening tag or a sentence: a ">", ".", "!" or "?", or where nothing comes before it. In an attribute or in the page's data
the name follows a quote, so it keeps its small letter.
"""
from __future__ import annotations

import html
import re
from typing import Any

from ..names import HOME_NUMBER, name_of

NODE = re.compile(r"\b(home-\d{2}|building-\d{2})\b")
HOME = re.compile(r"home-\d{2}")
BUILDING = re.compile(r"building-\d{2}")
OPENERS = ">.!?"
TAG = ">"          # the page character an element's text starts after
QUOTE = '"'        # the page character an attribute's or a data string's text starts after


def is_home(who: Any) -> bool:
    return bool(HOME.fullmatch(str(who or "")))


def is_building(who: Any) -> bool:
    return bool(BUILDING.fullmatch(str(who or "")))


def numbered(number: int) -> str:
    """The home that is number `number` among the community's homes."""
    return f"Home {number}"


def number_of(node: str) -> int:
    return HOME_NUMBER[node]


def shown(node: Any, head: str) -> str:
    """One node's name; any other word stays as it is. `head`: the last page character before it that is not a space
    ("" where nothing comes before it, which opens a name too)."""
    if not (is_home(node) or is_building(node)):
        return str(node)
    return name_of(node, start=is_home(node) or head in OPENERS)


def named(text: Any, before: str) -> str:
    """A recorded text with every home and building id in it named. `before`: the page text just ahead of it. The text
    is escaped where it is placed, so the character that counts is the last one of its escaped form."""
    text = str(text)

    def put(m: re.Match[str]) -> str:
        own = text[:m.start()].rstrip(" ")
        return shown(m.group(1), html.escape(own, quote=False)[-1:] if own else before.rstrip(" ")[-1:])
    return NODE.sub(put, text)


def data(text: Any) -> str:
    """A recorded text as it stands in the page's data, where every string opens after a quote."""
    return named(text, QUOTE)
