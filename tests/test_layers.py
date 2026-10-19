import ast
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Final

import pytest

SOURCE: Final = Path(__file__).resolve().parents[1] / "src" / "alexia_api"
PACKAGE: Final = "alexia_api"

MAY_IMPORT: Final[Mapping[str, frozenset[str]]] = {
    "domain": frozenset(),
    "portal": frozenset({"clock", "domain"}),
    "sim": frozenset({"clock", "domain"}),
    "services": frozenset({"clock", "config", "domain", "portal"}),
    "api": frozenset({"clock", "config", "domain", "services"}),
    "config": frozenset({"domain"}),
    "clock": frozenset(),
    "oserrors": frozenset(),
    "__init__": frozenset(),
}
SHELLS: Final = frozenset({"cli", "demo", "doctor", "logs", "reference", "scaffold"})
WEB_FRAMEWORKS: Final = frozenset({"fastapi", "starlette", "uvicorn", "typer"})
MAY_USE_A_WEB_FRAMEWORK: Final = frozenset({"api", "sim", "demo", "cli"})
DOMAIN_MAY_USE: Final = frozenset({"pydantic"})


def _owner(root: Path, path: Path) -> str:
    parts = path.relative_to(root).parts
    return parts[0] if len(parts) > 1 else path.stem


def _imports(root: Path, path: Path) -> Iterator[str]:
    inside = [PACKAGE, *path.relative_to(root).parts[:-1]]
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = inside[: len(inside) - (node.level - 1)] if node.level else []
            module = ".".join([*base, *([node.module] if node.module else [])])
            if module == PACKAGE:
                for alias in node.names:
                    is_part = (root / alias.name).is_dir() or (root / f"{alias.name}.py").is_file()
                    yield f"{PACKAGE}.{alias.name}" if is_part else PACKAGE
            elif module:
                yield module


def layer_violations(root: Path) -> list[str]:
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        owner = _owner(root, path)
        name = path.relative_to(root).as_posix()
        if owner not in MAY_IMPORT and owner not in SHELLS:
            found.append(f"{name}: {owner} is in no layer, so add it to MAY_IMPORT or SHELLS")
        for module in _imports(root, path):
            top, _, rest = module.partition(".")
            if top == PACKAGE:
                target = rest.partition(".")[0]
                if (
                    target
                    and owner in MAY_IMPORT
                    and target != owner
                    and target not in MAY_IMPORT[owner]
                ):
                    found.append(f"{name}: {owner} imports {target}, which is above it")
            elif top in WEB_FRAMEWORKS and owner not in MAY_USE_A_WEB_FRAMEWORK:
                found.append(f"{name}: {owner} imports the web framework {top}")
            elif (
                owner == "domain"
                and top not in sys.stdlib_module_names
                and top not in DOMAIN_MAY_USE
            ):
                found.append(f"{name}: domain imports {top}, which is not pydantic")
    return found


def _tree(root: Path, files: Mapping[str, str]) -> Path:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def test_the_package_imports_only_downward() -> None:
    assert layer_violations(SOURCE) == []


def test_a_clean_tree_has_no_violations(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            "domain/ids.py": "import re\nfrom pydantic import BaseModel\n",
            "portal/login.py": "from alexia_api.domain import ids\nimport httpx\n",
            "services/cache.py": "from alexia_api.portal import login\n",
            "api/app.py": "from alexia_api.services import cache\nimport fastapi\n",
        },
    )

    assert layer_violations(root) == []


@pytest.mark.parametrize(
    ("file", "text"),
    [
        ("domain/ids.py", "from alexia_api.portal import login\n"),
        ("domain/ids.py", "import alexia_api.api.app\n"),
        ("portal/login.py", "from alexia_api.services import cache\n"),
        ("portal/login.py", "from alexia_api.config import Settings\n"),
        ("services/cache.py", "from alexia_api.api import app\n"),
        ("api/app.py", "from alexia_api.portal import login\n"),
        ("sim/app.py", "from alexia_api.portal import login\n"),
        ("config.py", "from alexia_api.services import cache\n"),
        ("portal/login.py", "from alexia_api.cli import main\n"),
    ],
)
def test_an_import_that_points_up_is_reported(tmp_path: Path, file: str, text: str) -> None:
    root = _tree(tmp_path, {file: text})

    problems = layer_violations(root)

    assert len(problems) == 1
    assert problems[0].startswith(file)
    assert "above it" in problems[0]


def test_a_name_imported_from_the_package_root_is_not_a_layer(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {"api/app.py": "from alexia_api import __version__\nimport alexia_api\n"},
    )

    assert layer_violations(root) == []


def test_a_layer_imported_from_the_package_root_is_still_a_layer(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {"domain/ids.py": "from alexia_api import portal\n", "portal/login.py": ""},
    )

    assert layer_violations(root) == ["domain/ids.py: domain imports portal, which is above it"]


def test_a_module_imported_from_the_package_root_is_still_a_layer(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"domain/ids.py": "from alexia_api import config\n", "config.py": ""})

    assert layer_violations(root) == ["domain/ids.py: domain imports config, which is above it"]


def test_a_relative_import_cannot_hide_an_upward_import(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {"domain/ids.py": "from ..portal import login\n", "portal/login.py": ""},
    )

    problems = layer_violations(root)

    assert problems == ["domain/ids.py: domain imports portal, which is above it"]


def test_a_relative_import_inside_a_layer_is_fine(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {"portal/login.py": "from . import wire\nfrom .wire import Params\n", "portal/wire.py": ""},
    )

    assert layer_violations(root) == []


def test_a_shell_may_import_any_layer(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            "cli/main.py": "from alexia_api.api import app\nfrom alexia_api.portal import login\n",
            "demo.py": "from alexia_api.sim import app\nfrom alexia_api.services import cache\n",
        },
    )

    assert layer_violations(root) == []


def test_a_layer_may_not_import_a_shell(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"api/app.py": "from alexia_api.logs import configure\n"})

    assert layer_violations(root) == ["api/app.py: api imports logs, which is above it"]


@pytest.mark.parametrize("framework", ["fastapi", "starlette", "uvicorn", "typer"])
def test_a_layer_without_a_web_role_may_not_import_the_web_framework(
    tmp_path: Path, framework: str
) -> None:
    root = _tree(tmp_path, {"services/cache.py": f"import {framework}\n"})

    assert layer_violations(root) == [
        f"services/cache.py: services imports the web framework {framework}"
    ]


def test_the_domain_may_use_only_the_standard_library_and_pydantic(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {"domain/ids.py": "import httpx\nimport pydantic\nimport re\nfrom datetime import date\n"},
    )

    assert layer_violations(root) == ["domain/ids.py: domain imports httpx, which is not pydantic"]


def test_a_new_top_level_part_must_be_given_a_place(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"newcomer/thing.py": "x = 1\n"})

    assert layer_violations(root) == [
        "newcomer/thing.py: newcomer is in no layer, so add it to MAY_IMPORT or SHELLS"
    ]


def test_the_scan_sees_the_imports_that_the_design_describes() -> None:
    seen = {
        (_owner(SOURCE, path), module.split(".")[1])
        for path in SOURCE.rglob("*.py")
        for module in _imports(SOURCE, path)
        if module.startswith(f"{PACKAGE}.")
    }

    assert {("api", "services"), ("services", "portal"), ("portal", "domain")} <= seen
