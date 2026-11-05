"""Enforces one-way dependency boundaries between core, opportunities, and ugc."""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "jevtrends"


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


@pytest.mark.parametrize(
    ("subpackage", "forbidden_prefixes"),
    [
        ("core", ("jevtrends.opportunities", "jevtrends.ugc", "jevtrends.cli")),
        ("opportunities", ("jevtrends.ugc", "jevtrends.cli")),
        ("ugc", ("jevtrends.opportunities", "jevtrends.cli")),
    ],
)
def test_package_import_boundaries(subpackage: str, forbidden_prefixes: tuple[str, ...]):
    violations: list[str] = []
    for path in sorted((SRC / subpackage).rglob("*.py")):
        for mod in imported_modules(path):
            if mod.startswith(forbidden_prefixes):
                violations.append(f"{path.relative_to(SRC)}: imports {mod}")
    assert violations == []
