# Contributing to Murmur

This repository is where Murmur is developed. Work happens on branches, and collaborators change `main` only through pull requests
that the repository's owner reviews. [README.md](README.md) says what Murmur is and maps the folders; [docs/](docs/) holds the
architecture, the protocol and its safety rules, and the data with its limits.

## Set up

```bash
git clone <this repository> murmur && cd murmur
python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
pytest -q
```

Python 3.11 or newer. The suite runs in seconds on the synthetic fixtures in `tests/fixtures/`: no dataset, no network beyond
127.0.0.1, no fixed port. For the ENGIE experiments and their tests, add the `experiments` extra (`pip install -e ".[dev,experiments]"`);
without it those tests are skipped. Tests that need ENGIE's data carry `@pytest.mark.engie_data` and run only when
`MURMUR_ENGIE_DATA_DIR` is set.

## Before every pull request

Run these from the repository's root and paste their last lines into the pull request:

```bash
pytest -q
python scripts/verify_clean_repo.py .
git diff --name-only --diff-filter=AM main -- '*.py' '*.js' '*.css' | xargs wc -l
```

A change to the pages also rebuilds them and runs the browser checks, which need Playwright (`pip install playwright`, then
`python -m playwright install chromium`):

```bash
python -m demo.page_builder.build --out demo/pages
python -m demo.page_builder.checks.fit demo/pages     # no word cut, at many window sizes
python -m demo.page_builder.checks.walk demo/pages    # every moment, every part
python -m demo.page_builder.checks.site demo/pages    # links and script errors: what a visitor could meet
python -m demo.page_builder.checks.live demo/pages    # the optional Live view, against feeds the check serves itself
```

## Engineering rules

- **File size.** Every `.py`, `.js` and `.css` source file stays at or below 500 lines (aim for 350); a test file at or below 400.
  Split a module by single responsibility before it grows past that.
- **No text patching.** Never build or change HTML, CSS or JS with `.replace()` on strings or by joining code inside Python
  strings. Templates (`demo/page_builder/templates/`), style sheets and scripts (`demo/page_builder/static/`) are files of their own.
- **No dead code.** Delete obsolete code and unused functions; nothing stays commented out or marked "legacy" or "unused".
- **No private traces.** No machine or host names, private network addresses, home-folder paths, e-mail addresses (but for
  `example.*` ones), remote-access tools, or names of earlier projects or courses in any tracked file: code, comments, tests,
  fixtures, pages, docs. Every address a part listens on or calls is a setting (`agent.json` or a `MURMUR_*` variable);
  `127.0.0.1` and `localhost` name no machine. `python scripts/verify_clean_repo.py .` must report 0 traces. It keeps its names
  as salted hashes; `python scripts/verify_clean_repo.py --add TERM` prints the line to paste for a new one.
- **Tests that run anywhere.** The default `pytest` passes on a fresh clone in a new virtual environment with no dataset. Tests
  bind only to port 0 (the system picks a free one) or to ports 51000 and up.
- **No secrets in the repository.** Keys, bus tokens and run grants live in each process's `$MURMUR_CONFIG_DIR/secrets/`; what
  the demo writes goes to `out/`, which git ignores.
- **Code decides every amount.** The language model only reads what people write and words the reports; a note can only become
  a limit. [docs/PROTOCOL_AND_SAFETY.md](docs/PROTOCOL_AND_SAFETY.md) has the protocol and the safety rules a change must keep.

## Branches, commits and pull requests

- Branch from `main`, one topic per branch (`feature/<topic>`, `fix/<topic>`), and open a pull request to `main`.
- Keep commits small and their messages plain: what changed and why. Commit under your own GitHub identity; GitHub's no-reply
  address keeps your e-mail address out of the history. Commit messages carry no tool attribution lines (such as a
  `Co-Authored-By` line for an assistant).
- A pull request says what it changes and why, and carries the outputs of the checks above.

## The demo, replayed and live

The pages replay recorded evenings (`demo/recordings/`): open `demo/pages/index.html`. To run a whole evening on your own computer,
every part its own process:

```bash
python -m demo.runner example
python -m demo.runner evening --config demo/runner/config.example.json
```

`evening` prints the address of its read-only state feed. Open `demo/pages/index.html?live=<that address>` and the page adds its
Live view beside the replay. `python -m demo.runner feed --run FOLDER` serves the feed of a run folder under `out/runs/`.

To present an evening, start the presenter's console instead: `python -m demo.console --config demo/runner/config.example.json
--port 0`. It writes its link, with the presenter's key, beside its key file; the page it serves plays the running network in the
split view, with Start, Hold, Step, the speeds, eight surprises and a timeline. `python -m demo.page_builder.checks.live demo/pages`
and `python -m demo.page_builder.checks.live_run --config demo/runner/config.example.json` check it in a browser. With `--loop-days`
and `--audience` the console plays evening after evening by itself and lets every viewer trigger one of six preset events;
`python -m demo.page_builder.checks.live_public --config demo/runner/config.example.json` checks that.
