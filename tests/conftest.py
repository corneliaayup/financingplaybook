from pathlib import Path

import pytest

from fpb.config import load_config

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def bundle():
    return load_config(REPO / "config")
