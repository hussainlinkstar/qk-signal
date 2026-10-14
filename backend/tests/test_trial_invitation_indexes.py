import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["SSM_ENABLED"] = "0"

import models  # noqa: E402


def test_trial_invitation_index_names_are_unique() -> None:
    table = models.TrialInvitation.__table__
    index_names = [index.name for index in table.indexes if index.name]

    assert len(index_names) == len(set(index_names))
