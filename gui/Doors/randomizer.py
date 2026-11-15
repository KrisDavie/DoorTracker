"""The door randomizer, the ALttPDoorRandomizer submodule, which the tracker takes its checks and rules from.

Import this before importing anything from ALttPDoorRandomizer.
"""

import ast
import sys
import types
from functools import cache
from pathlib import Path

FOLDER = Path(__file__).resolve().parent.parent.parent / "ALttPDoorRandomizer"
if not (FOLDER / "Rules.py").exists():
    raise FileNotFoundError(f"The door randomizer is not in {FOLDER}: run  git submodule update --init")

# This copy of the randomizer imports Archipelago's Utils by bare name, for a function the tracker never reaches
_utils = types.ModuleType("Utils")
setattr(_utils, "parse_yaml", None)
sys.modules.setdefault("Utils", _utils)


@cache
def parse(name: str) -> ast.Module:
    """One of its files, read as text and not run."""
    return ast.parse((FOLDER / name).read_text(encoding="utf-8"))


def literals(name: str, *wanted: str) -> list:
    """The lists and dicts one of its files assigns to these names, anywhere in the file."""
    found = {}
    for node in ast.walk(parse(name)):
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in wanted:
            found[node.targets[0].id] = ast.literal_eval(node.value)
    return [found[name] for name in wanted]


def numbers(name: str) -> dict[str, int]:
    """The whole numbers one of its files names at the top, some as sums of ones named before."""
    found: dict[str, int] = {}

    def number(node: ast.expr) -> int | None:
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return node.value
        if isinstance(node, ast.Name):
            return found.get(node.id)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, right = number(node.left), number(node.right)
            return None if left is None or right is None else left + right
        return None

    for node in parse(name).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            worth = number(node.value)
            if worth is not None:
                found[node.targets[0].id] = worth
    return found


def dungeon_name(tab: str) -> str:
    """The randomizer's name for a dungeon, from the tracker's name for its tab."""
    return "Agahnims Tower" if tab == "Castle_Tower" else tab.replace("_", " ")
