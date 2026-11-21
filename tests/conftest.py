"""The test session's environment: the synthetic dataset in tests/fixtures/data, a configuration folder of its own, and no outside service.

The package reads $MURMUR_DATA_DIR and $MURMUR_CONFIG_DIR when it is first imported, so they are set here, before any test imports it."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"
CONFIG = Path(tempfile.mkdtemp(prefix="murmur-test-config-"))
os.environ["MURMUR_DATA_DIR"] = str(FIXTURES / "data")
os.environ["MURMUR_CONFIG_DIR"] = str(CONFIG)
os.environ["MURMUR_LOG_DIR"] = str(CONFIG / "logs")
os.environ["MURMUR_MODELS_DIR"] = str(FIXTURES / "models")
os.environ["MURMUR_DEVICES"] = "hpwh,dryer,v2h,fans,plugs"
for k in [k for k in os.environ if k.startswith("MURMUR_") and k not in ("MURMUR_DATA_DIR", "MURMUR_CONFIG_DIR", "MURMUR_LOG_DIR", "MURMUR_MODELS_DIR", "MURMUR_DEVICES",
                                                                              "MURMUR_ENGIE_DATA_DIR", "MURMUR_PUBLISHED_DIR")]:
    del os.environ[k]


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(CONFIG, ignore_errors=True)


@pytest.fixture
def agent_config():
    """Writes the node's agent.json for one test, and takes it away after."""
    path = CONFIG / "agent.json"

    def write(**cfg):
        path.write_text(json.dumps(cfg))
        return cfg
    yield write
    path.unlink(missing_ok=True)


@pytest.fixture
def sites() -> dict:
    return json.loads((FIXTURES / "sites.json").read_text())["sites"]


def pytest_collection_modifyitems(config, items):
    if os.environ.get("MURMUR_ENGIE_DATA_DIR"):
        return
    skip = pytest.mark.skip(reason="needs ENGIE's dataset: set MURMUR_ENGIE_DATA_DIR to run it")
    for item in items:
        if "engie_data" in item.keywords:
            item.add_marker(skip)
