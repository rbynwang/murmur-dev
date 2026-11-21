"""The referee, on ENGIE's 2025 trust data: for every report slot, at ENGIE's two deadlines, trusted, unverifiable or untrusted, citing the rows
the call rests on, and which participants are compromised.

  python -m experiments.engie.referee --data-dir DIR --out OUT [--readings FILE]

  inputs    what is read of the release, and the constants of the checks
  slots     one row per participant and slot, with the moment each piece became known
  calls     the calls, the reasons, who is compromised, ENGIE's two files
  notes     the notes: code knows the everyday sentences, a small model reads only the new words, and a note can only lower trust
  plant     lies of known kind and size planted in ENGIE's own reports, and what is caught
  pipeline  all of it in one run (README.md beside this file holds the results)
"""
