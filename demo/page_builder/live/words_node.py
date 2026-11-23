"""The fixed words of the steps made from a followed node's record: its agent's steps 1 to 9, a device call through the guard and the
driver, the small model's reading of a note and its report, and what the node told its person.

The titles begin as the recorded evenings' do ("Steps 1 to 4", "Step 5", ..., "Guard:", "Seal and write to"), because the node card
counts the steps by them and the chain card finds the guard's step by its layer (replay/panels.py).
"""
from __future__ import annotations

from .shape import Row


def R(beat: str, stage: str, layer: str, title: str, plain: str, key: bool = False, say: bool = False, box: str = "{side}-agent") -> Row:
    return Row(beat, stage, layer, title, plain, key, say, box)


ROWS = {
    "safe": R("home-safe", "offers", "agent", "Steps 1 to 4: the safe figure",
              "Code reads the node's schedule, forecasts the evening, checks its devices and works out what it can safely sell. That figure is "
              "the rule's plan, and code makes the offer from it: no model is asked.", key=True, say=True),
    "offer": R("home-model", "offers", "agent", "Step 5: code's offer, on a receipt",
               "Code makes the offer: {kw} kW at most per half hour. {by}", key=True, say=True),
    "commitment": R("node-contract", "contract", "agent", "Step 6: code answers the contract",
                    "Code answers the contract: {answer}. {facts} {by}"),
    "opening": R("watch-home", "prepare", "agent", "Step 7: code's opening", "{Name} opens the sale's device calls: {facts} {by}", key=True, say=True),
    "exception": R("exc-model", "exception", "agent", "Step 8: code's answer, on a receipt",
                   "Code answers a change ({changed}): it opens {opens}, which leaves {left} kW uncovered. {by}", key=True, say=True),
    "own_plan": R("exc-model", "exception", "agent", "Code carries out its own plan",
                  "The plan keeps every running call and opens {opens}. The guard checks every call in it."),
    "guard": R("watch-home", "prepare", "guard", "Guard: {tool} {status}", "The guard reads the call against the node's facts, and says {status}.",
               key=True, box="{side}-guard"),
    "driver": R("watch-home", "prepare", "driver", "Seal and write to {target}",
                "The guard seals exactly what it passed, and the driver takes only that sealed command.", key=True, box="{side}-driver"),
    "note_model": R("note-read", "exception", "model", "The small model reads the note",
                    "Code hands the note to the small model, which may only call the tools it is given. The model answers: {answer}.",
                    key=True, say=True, box="{side}-model"),
    "note_more": R("note-read", "exception", "model", "The small model reads the note again",
                   "The small model is asked once more. The model answers: {answer}.", box="{side}-model"),
    "note_decision": R("note-read", "exception", "agent", "The note's reading, on the record", "Code writes down what was read: {said}"),
    "note_receipt": R("note-read", "exception", "agent", "The receipt for the note", "{reason}"),
    "report_model": R("report", "report", "model", "Step 9: the model words the report",
                      "Code gathers {name}'s facts and marks where each came from, and the model only words them. The model answers: {answer}.",
                      key=True, say=True, box="{side}-model"),
    "report": R("report", "report", "agent", "The report for {name}", "{summary}"),
    "told": R("told", "report", "person", "The {to} is told", "{Name} tells the {to} in plain words: {text}", key=True, say=True,
              box="{side}-person"),
}
