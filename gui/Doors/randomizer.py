"""The door randomizer, the ALttPDoorRandomizer submodule, which the tracker takes its checks and rules from.

Import this before importing anything from ALttPDoorRandomizer.
"""

import ast
import sys
import types
from pathlib import Path

FOLDER = Path(__file__).resolve().parent.parent.parent / "ALttPDoorRandomizer"
if not (FOLDER / "Rules.py").exists():
    raise FileNotFoundError(f"The door randomizer is not in {FOLDER}: run  git submodule update --init")

# This copy of the randomizer imports Archipelago's Utils by bare name, for a function the tracker never reaches
_utils = types.ModuleType("Utils")
setattr(_utils, "parse_yaml", None)
sys.modules.setdefault("Utils", _utils)


def parse(name: str) -> ast.Module:
    """One of its files, read as text and not run."""
    return ast.parse((FOLDER / name).read_text(encoding="utf-8"))
