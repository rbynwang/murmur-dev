"""The simulated home's fixed figures: the battery's backup refill, when a car must be done, and the notes a home keeps waiting."""
from __future__ import annotations

import os


DONE_BY = {"dish": "23:30", "dryer": "22:45"}      # the owner's done-by times: a held machine finishes by then


BACKUP = os.environ.get("MURMUR_BATTERY_MODE") == "backup"   # benchmark: the battery is held for grid events


SUB = 3                     # 5-minute parts of a 15-minute step (control_mode rolling)


NOTES_WAITING = 4           # unread notes a newer one pushed aside, kept to be read: a person writing more than this before anyone reads them is the door's to stop
