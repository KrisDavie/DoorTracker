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
# Its client, MultiClient.py, imports three packages to talk to a server. The tracker only takes tables from it,
# so an empty module stands in for each that is not installed
for _name in ("aioconsole", "colorama", "websockets"):
    sys.modules.setdefault(_name, types.ModuleType(_name))


@cache
def parse(name: str) -> ast.Module:
    """One of its files, read as text and not run."""
    return ast.parse((FOLDER / name).read_text(encoding="utf-8"))


def literals(name: str, *wanted: str) -> list:
    """The lists and dicts one of its files assigns to these names: at the top of the file, or else the one
    place inside a function."""
    module = parse(name)
    found = []
    for target in wanted:

        def assigns(node: ast.AST) -> bool:
            return isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id == target

        places = [node for node in module.body if assigns(node)] or [node for node in ast.walk(module) if assigns(node)]
        if len(places) != 1:
            raise LookupError(f"{name} assigns {target} in {len(places)} places")
        assert isinstance(places[0], ast.Assign)
        found.append(ast.literal_eval(places[0].value))
    return found


def dungeon_name(tab: str) -> str:
    """The randomizer's name for a dungeon, from the tracker's name for its tab."""
    return "Agahnims Tower" if tab == "Castle_Tower" else tab.replace("_", " ")
