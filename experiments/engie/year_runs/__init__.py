"""The year runs: the year's 48 evenings chosen by rule, the recorded evening runs with and without the community agent, and a recorded
evening's signed messages between the aggregator and the participants that answer it.

  python -m experiments.engie.year_runs choose --data-dir DIR --out OUT     the 48 evenings from ENGIE's 2025 prices, against the recorded choice
  python -m experiments.engie.year_runs compare --out OUT [--recording F]   with and without the community agent, from the recorded runs
  python -m experiments.engie.year_runs evening --out OUT [--recording F]   who answers the aggregator, in which signed messages

  choose    the rule, and the evenings it picks
  compare   the measures of the runs, counted the same way with the agent and without it
  evening   the envelopes of a recorded evening, by participant

`evening_runs.json.gz` beside this file is the recording `compare` reads: the 48 evenings as chosen before any run, and the 576 runs made
on them offline (48 evenings, three tiers, two versions of the weather, with the community agent and without it), each as its promise and
its members' delivery by half hour, summed from the run's own member rows, and its money. Only `choose` needs pandas and ENGIE's data.
"""
