"""The door randomizer, the ALttPDoorRandomizer submodule, which the tracker takes its checks and rules from.

Import this before importing anything from ALttPDoorRandomizer.
"""

import ast
import inspect
import sys
import textwrap
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


def syntax(thing: types.FunctionType | type) -> ast.FunctionDef | ast.ClassDef:
    """One of its functions or classes as written: its syntax tree, for what running it would not give."""
    (definition,) = ast.parse(textwrap.dedent(inspect.getsource(thing))).body
    assert isinstance(definition, ast.FunctionDef | ast.ClassDef)
    return definition


def tables_in(function: types.FunctionType, *wanted: str) -> list:
    """The lists and dicts one of its functions assigns to these names. They are the function's own, made and
    dropped each time it runs, so they are read from how it is written."""
    found = []
    for target in wanted:
        places = [
            node
            for node in ast.walk(syntax(function))
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id == target
        ]
        if len(places) != 1:
            raise LookupError(f"{function.__qualname__} assigns {target} in {len(places)} places")
        found.append(ast.literal_eval(places[0].value))
    return found


class _World:
    """As much of the randomizer's world as building its regions asks of one."""

    def __init__(self) -> None:
        self.mode = {1: "open"}  # the regions come out the same in standard mode
        self.regions: list = []

    def initialize_regions(self) -> None:
        pass

    def get_region(self, name: str, player: int):
        return next(region for region in self.regions if region.name == name)


@cache
def dungeon_regions() -> tuple:
    """The randomizer's dungeon regions, built by its own code. Each has a name, and its exits and locations
    have names."""
    from ALttPDoorRandomizer import Regions
    from ALttPDoorRandomizer.BaseClasses import RegionType

    world = _World()
    # The first makes a region in a dungeon too: where the drop into the sewers lands
    Regions.create_regions(world, 1)
    Regions.create_dungeon_regions(world, 1)
    return tuple(region for region in world.regions if region.type == RegionType.Dungeon)


def dungeon_name(tab: str) -> str:
    """The randomizer's name for a dungeon, from the tracker's name for its tab."""
    return "Agahnims Tower" if tab == "Castle_Tower" else tab.replace("_", " ")
