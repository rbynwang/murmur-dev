"""Offline experiments on ENGIE's two open data releases of one 200-bus grid with 80 participants.

  meter_cleaning   ENGIE's 2025 grid readings are noisy snapshots, not ground truth. The cleaner rebuilds each hour from the few patterns the 66
                   transformer readings share, the proof runs it on the 2023 true grid state with the same faults added, and the ruler reads each
                   transformer's true response to the batteries off the 2023 state.
  peak_allocation  the 80 participants' batteries held for the evening peak: at 14:00 a plan that reads only the grid's loading (no price) asks
                   each battery for its share, and a replay of the whole year counts the hours a transformer stays at 80% or more.
  referee          for every report slot, at ENGIE's two deadlines, trusted / untrusted / unverifiable, and which participants are compromised.
                   A note can only lower trust: code knows the everyday sentences, a small model reads only the unfamiliar words.
  year_runs        the year's 48 evenings chosen by rule, and the comparison of recorded evening runs with and without the community agent.

Each runs as `python -m experiments.engie.<name> --data-dir DIR --out DIR` from the repository root; the data folder may also come from
$MURMUR_ENGIE_DATA_DIR. `experiments.engie.data` describes the folder layout. Nothing here contacts a network service unless a run is given a
model server's address for the referee's note reader.
"""
