"""Peak allocation: the 80 participants' batteries held for the evening peak on ENGIE's 2025 records, the plan reading only the grid's loading.

  python -m experiments.engie.peak_allocation --data-dir DIR --out OUT [--cleaning DIR]

It stands on three things, each proven before use: the readings cleaned with the past only and the ruler by kind of participant (both from the
meter cleaning: --cleaning names a folder a meter-cleaning run wrote; when it lacks them, that run is made into OUT/meter_cleaning first), and
each battery's recorded behaviour (experiments.engie.fleet). Three cases are replayed over the whole year: every battery asked, the solar-and-
battery plants left out, the communities alone. Writes OUT/peak_allocation.json.
"""
