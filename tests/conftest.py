"""Shared fixtures and helpers for the golden tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_fixtures() -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text())
            for p in sorted(FIXTURE_DIR.glob("*.json")) if p.stem != "batches"}


FIXTURES = load_fixtures()
BATCHES = (json.loads((FIXTURE_DIR / "batches.json").read_text())
           if (FIXTURE_DIR / "batches.json").exists() else {})


@pytest.fixture(scope="session")
def engine():
    """The bare model runner: M0 naive path and M1 cached path."""
    from engine.model_runner import ModelRunner
    return ModelRunner()


def make_engine(runner, **cfg):
    from engine.config import EngineConfig
    from engine.scheduler import Engine
    return Engine(EngineConfig(**cfg), runner)
