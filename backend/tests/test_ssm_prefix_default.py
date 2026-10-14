"""The SSM namespace default must match the documented one (SIGV2-1279).

Alerts were arriving under "ThothGraph Intelligence Analyzer", the brand
retired when the product was renamed. The cause was not in any template: the
sender name comes from `EMAIL_FROM_NAME`, which is overlaid from AWS SSM, and
two namespaces had drifted apart.

  /thothgraph/EMAIL_FROM_NAME   = "Qiko Signal"
  /qiko-signal/EMAIL_FROM_NAME  = "ThothGraph Intelligence Analyzer"

The code defaulted to `/thothgraph/` while the README,
`deploy/VPS_DEPLOYMENT_RO.md` and `scripts/seed_ssm.py` all documented
`/qiko-signal/`, so which values an environment loaded depended on whether
anyone had set the variable. An environment that followed the documentation
got the retired brand on every outbound email.

The value is corrected in Parameter Store; this pins the default so the
mismatch cannot return, and so the next person reading the README is right.
"""

import ast
import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
RETIRED_NAMESPACE = "/thothgraph/"
CURRENT_NAMESPACE = "/qiko-signal/"


def test_the_ssm_prefix_default_is_the_current_namespace() -> None:
    from core import env_bootstrap

    source = Path(env_bootstrap.__file__).read_text(encoding="utf-8")
    match = re.search(r'os\.getenv\("SSM_PARAM_PREFIX"\)\s*or\s*"([^"]+)"', source)

    assert match is not None, "the SSM_PARAM_PREFIX fallback is no longer a literal default"
    assert match.group(1) == CURRENT_NAMESPACE


def test_the_default_agrees_with_the_seeding_script() -> None:
    """The script that writes the parameters and the app that reads them must
    agree, or seeding fills a namespace nothing loads."""
    from core import env_bootstrap

    app_source = Path(env_bootstrap.__file__).read_text(encoding="utf-8")
    seed_source = (REPO_ROOT / "scripts" / "seed_ssm.py").read_text(encoding="utf-8")

    app_default = re.search(r'os\.getenv\("SSM_PARAM_PREFIX"\)\s*or\s*"([^"]+)"', app_source)
    seed_default = re.search(r'os\.getenv\("SSM_PARAM_PREFIX",\s*"([^"]+)"\)', seed_source)

    assert app_default is not None and seed_default is not None
    assert app_default.group(1) == seed_default.group(1)


def test_no_runtime_module_uses_the_retired_namespace_as_a_value() -> None:
    """Shipped code may not point at the retired namespace.

    A stale namespace in runtime code is how an environment silently reads a
    set of values nobody maintains any more.

    Only string *values* count. Comments and docstrings are allowed to name
    the old namespace, because explaining why it was retired is how the next
    reader avoids reintroducing it, and a test that forbids the explanation
    would delete its own rationale.
    """
    offenders: list[str] = []
    for directory in ("core", "services", "routers", "app"):
        root = BACKEND_ROOT / directory
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except SyntaxError:
                continue
            docstrings = {
                ast.get_docstring(node, clean=False)
                for node in ast.walk(tree)
                if isinstance(
                    node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                )
            }
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                    continue
                if RETIRED_NAMESPACE not in node.value:
                    continue
                if node.value in docstrings:
                    continue
                offenders.append(f"{path.relative_to(BACKEND_ROOT)}:{node.lineno}")

    assert offenders == [], f"retired SSM namespace used as a value in: {offenders}"
