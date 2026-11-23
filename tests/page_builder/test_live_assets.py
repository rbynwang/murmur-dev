"""How Live is put into the two-view page: one script element of its own after the main one, its files in order, its style sheet's
rules all its own, and none of its scripts writing markup or style text."""
from __future__ import annotations

import re
from pathlib import Path

from demo.page_builder import assets

STATIC = Path(assets.__file__).resolve().parent / "static" / "replay"
LIVE = [STATIC / "js" / f"{name}.js" for name in assets._LIVE]


def test_the_two_view_page_has_the_main_script_and_live_s_and_the_others_have_no_live():
    assert [len(x) > 0 for x in assets.scripts("two_view")] == [True, True]
    assert len(assets.scripts("three_view")) == 1 and len(assets.scripts("year")) == 1
    assert "live_open" not in "".join(map(str, assets.scripts("three_view") + assets.scripts("year")))


def test_live_is_one_function_opened_by_its_first_file_and_ended_by_its_last():
    text = "".join(f.read_text() for f in LIVE)
    assert LIVE[0].read_text().lstrip().startswith("/*") and "(function () {" in LIVE[0].read_text()
    assert LIVE[-1].read_text().rstrip().endswith("})();")
    assert text.count("(function () {") == 1


def test_no_live_script_writes_markup_or_style_text():
    for f in LIVE:
        t = f.read_text()
        assert not re.search(r"\.(innerHTML|outerHTML)\s*=|insertAdjacentHTML|document\.write|\beval\(|new Function", t), f.name
        assert not re.search(r"\.style\.(cssText|background|color|font)|setAttribute\('style'", t), f.name


def test_every_rule_of_live_s_style_sheet_is_live_s_own_and_none_touches_the_split_view_s_lit_states():
    css = (STATIC / "css" / "live.css").read_text()
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    selectors = [s.strip() for block in re.findall(r"([^{}@]+)\{[^{}]*\}", css) for s in block.split(",") if s.strip()]
    assert selectors
    for s in selectors:
        assert "#app.lv" in s or ".lv-" in s or "#lv-" in s or s in (".lq",), s
        assert not re.search(r"\.wires|\.blk\.on|\.blk\.now|#pill|#layer\b", s), s


def test_the_main_script_lets_a_live_story_grow_and_wait():
    main = "".join(str(x) for x in assets.scripts("two_view")[:1])
    assert "FG.grow = {" in main and "st.live && S.m >= st.moments.length - 1" in main
