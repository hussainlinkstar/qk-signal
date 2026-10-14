import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect

import models


def test_workspaces_model_has_role_mode_column():
    cols = {c.name: c for c in inspect(models.Workspace).columns}
    assert "role_mode" in cols, "role_mode column missing on Workspace model"
    assert cols["role_mode"].nullable is True


def test_role_mode_enum_values():
    from routers.workspace_router import RoleMode

    assert {m.value for m in RoleMode} == {
        "marketer",
        "specialist",
        "agency",
        "enterprise",
        "explorer",
    }
