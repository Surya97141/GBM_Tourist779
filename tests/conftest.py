import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# main.py loads its weights file by a relative path, so anything that
# imports track_B_CV.main (directly or via agent_orchestrator.app) needs
# the process cwd sitting inside track_B_CV/ to find it.
os.chdir(str(REPO_ROOT / "track_B_CV"))

import pytest

from shared.barrier_store import barrier_store


@pytest.fixture(autouse=True)
def clean_barrier_store():
    barrier_store._entries.clear()
    yield
    barrier_store._entries.clear()
