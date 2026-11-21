"""What a person hears about a note: that it was heard, what it keeps, and what it costs a sale already made, in the person's own terms."""
from __future__ import annotations

from typing import Any

from murmur.node.note_reader import BLOCKS, next_day, quoted

SAYS = {"keep_battery_full": "The owner needs the battery kept full.", "keep_car_ready": "The owner needs the car ready.",
        "keep_house_as_is": "The owner asked to leave the house as it is.", "keep_hot_water": "The owner needs hot water.", "keep_machines_on": "The owner needs the machines left to run.",
        "keep_lights_on": "The manager needs the lights kept up."}


# A person's note that takes kW out of a sale is measured against the amount without it, since a rule can't read a note, flagged, and the person is told
# in their own terms that it was heard and what it costs. A receipt measured against code's plan under the wish would show no cost, and an owner who
# asks for a full battery tonight would never hear what keeping it out of the sale takes.
FOR_NOTE = "less, for the person's note"


KEEPING = {"keep_battery_full": "keeping the battery full", "keep_car_ready": "keeping the car ready", "keep_house_as_is": "leaving the heating and cooling as they are",
           "keep_hot_water": "keeping the hot water on", "keep_machines_on": "leaving the machines to run", "keep_lights_on": "keeping the lights up"}


TAKEN_BACK = "The owner took back a need, so what it kept out can be used again."


def when_of(start: str, now: str) -> str:
    """When a sale falls, said from now: tonight, tomorrow night, or its date."""
    evening = start[11:13] >= "17"
    if start[:10] == now[:10]:
        return "tonight" if evening else "today"
    if start[:10] == next_day(now):
        return "tomorrow night" if evening else "tomorrow"
    return f"on {start[:10]}"


def got_it(wishes: list[dict[str, Any]], gives: float, would: float, when: str, fmt: Any) -> str:
    """The person hears that the note was heard, and what it costs: what the node gives now, against what it would give without the note."""
    doing = " and ".join(dict.fromkeys(KEEPING[w["wish"]] for w in wishes if w.get("wish") in KEEPING)) or "doing as you asked"
    return f"Got it: {doing}, as you asked, so I'm giving {fmt(gives)} kW {when} instead of {fmt(would)}."


def heard(wishes: list[dict[str, Any]]) -> str:
    """The person hears that it was heard, when it takes nothing out of a sale."""
    return f'Got it: {" and ".join(dict.fromkeys(KEEPING[w["wish"]] for w in wishes if w.get("wish") in KEEPING))}, as you asked.'


def not_kept(note: str) -> str:
    """A note the model read and wouldn't say why: what it read isn't kept, and the person hears that."""
    return f'I couldn\'t act on your note, so nothing has changed: "{quoted(note, 120)}"'


def says(wishes: list[dict[str, Any]], who: str = "owner") -> str:
    """What the wishes ask, as the receipt's reason, in the person's role."""
    out = " ".join(dict.fromkeys(SAYS[w["wish"]] for w in wishes if w.get("wish") in SAYS))
    return out.replace("The owner", "The manager") if who == "manager" else out


def why(tool: str, wishes: list[dict[str, Any]]) -> str:
    return next((SAYS[w["wish"]] for w in wishes if tool in BLOCKS[w["wish"]]), "The owner asked for this to stay as it is.")
