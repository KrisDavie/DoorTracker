"""The door randomizer's rules: the items it takes to go through a door or passage, or to collect a check.

Read when the tracker starts, out of the randomizer (gui/Doors/randomizer.py): Rules.py sets the rules, and
BaseClasses.py defines the tests they use, like can_lift_rocks. The files are read as text and not run. The randomizer only has
rules once it has generated a whole seed, and by then one that holds in every seed looks the same as one that
depends on that seed's settings.

Only what holds in every seed is kept. A rule set under an "if" depends on the seed, and so do key doors, crystal
barriers, bosses and dark rooms; and the tracker cannot read events like "Open Floodgate". All of those count as
met, so a rule here never asks for more than the randomizer does.
"""

import ast

from data.doors_data import logical_connections, regions_to_doors
from gui.Doors.checks import checks
from gui.Doors.logic import READABLE, Rule
from gui.Doors.randomizer import parse

# The functions in Rules.py whose rules do not depend on the seed's settings
FUNCTIONS = ("global_rules", "bomb_rules")
# Tests whose definition asks about the seed's settings: the item that stands for them
TESTS_BY_HAND = {
    "can_use_bombs": "Bombs",  # needs the bomb bag where there is one: read as room for bombs
    "can_shoot_arrows": "Bow",  # also needs arrows to buy, in retro
}


def called(node: ast.AST) -> str | None:
    """The name a call is made by: f(...) or anything.f(...)."""
    if not isinstance(node, ast.Call):
        return None
    if isinstance(node.func, ast.Name):
        return node.func.id
    return node.func.attr if isinstance(node.func, ast.Attribute) else None


def text(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def combine(kind: str, parts: list[Rule]) -> Rule:
    """("all" | "any", rules) with the constants folded away and rules of the same kind merged in."""
    empty = kind == "all"  # an empty "all" is met, an empty "any" is not
    kept: list[Rule] = []
    for part in parts:
        if part is (not empty):
            return not empty
        for inner in part[1:] if isinstance(part, tuple) and part[0] == kind else [part]:
            if inner is not empty and inner not in kept:
                kept.append(inner)
    if not kept:
        return empty
    return kept[0] if len(kept) == 1 else (kind, *kept)


class Reader:
    """Turns what the randomizer writes for a rule into a Rule."""

    def __init__(self, events: set[str]) -> None:
        """events: what the randomizer counts as items that the tracker works out for itself; see read()."""
        self.events = events
        self.tests = {}  # the tests of CollectionState, by name
        for node in ast.walk(parse("BaseClasses.py")):
            if isinstance(node, ast.ClassDef) and node.name == "CollectionState":
                self.tests = {f.name: f for f in node.body if isinstance(f, ast.FunctionDef)}

    def test(self, name: str) -> Rule:
        """A test as a rule: its body, when that is one expression."""
        if name in TESTS_BY_HAND:
            return TESTS_BY_HAND[name]
        body = [s for s in self.tests[name].body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
        if len(body) == 1 and isinstance(body[0], ast.Return) and body[0].value is not None:
            return self.rule(body[0].value)
        return True

    def rule(self, node: ast.AST) -> Rule:
        """A rule as Rules.py writes it, or an expression inside a test. Whatever is not understood is met."""
        if isinstance(node, ast.Name) and node.id in ("TRUE", "FALSE"):
            return node.id == "TRUE"
        if isinstance(node, ast.BoolOp):
            return combine("all" if isinstance(node.op, ast.And) else "any", [self.rule(v) for v in node.values])
        name = called(node)
        if not isinstance(node, ast.Call) or name is None:
            return True
        if name in ("Has", "has"):
            item = text(node.args[0])
            # An item the tracker can neither read nor work out, or more than one of it, counts as held
            return item if item is not None and (item in READABLE or item in self.events) and len(node.args) == 2 else True
        if name in ("and_rule", "or_rule"):
            return combine("all" if name == "and_rule" else "any", [self.rule(a) for a in node.args])
        if name == "Primitive" and len(node.args) == 2:
            return self.test(str(text(node.args[0])))
        on_self = isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "self"
        if on_self and name in self.tests and len(node.args) == 1:
            return self.test(name)
        return True


def spot(node: ast.AST, loop: dict[str, list[str]]) -> list[tuple[str, str]]:
    """What a rule is set on: [(kind, name)] for world.get_entrance(name, player) or get_location."""
    kind = called(node)
    if not isinstance(node, ast.Call) or kind not in ("get_entrance", "get_location") or not node.args:
        return []
    named, literal = node.args[0], text(node.args[0])
    names = [literal] if literal else loop.get(named.id, []) if isinstance(named, ast.Name) else []
    return [(kind, name) for name in names]


def read_rules(reader: Reader) -> dict[tuple[str, str], Rule]:
    """(kind, name) -> rule, for every rule set outright or in a loop over a list of names."""
    found: dict[tuple[str, str], Rule] = {}
    lists: dict[str, list[str]] = {}

    def statement(node: ast.stmt, loop: dict[str, list[str]]) -> None:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.List) and isinstance(node.targets[0], ast.Name):
            lists[node.targets[0].id] = [name for name in map(text, node.value.elts) if name]
        elif isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            over = node.iter
            names = lists.get(over.id, []) if isinstance(over, ast.Name) else [n for n in map(text, over.elts) if n] if isinstance(over, ast.List) else []
            for inner in node.body:
                statement(inner, {node.target.id: names})
        elif isinstance(node, ast.Expr) and called(node.value) in ("set_rule", "add_rule"):
            assert isinstance(node.value, ast.Call)
            for key in spot(node.value.args[0], loop):
                rule = reader.rule(node.value.args[1])
                found[key] = rule if called(node.value) == "set_rule" else combine("all", [found.get(key, True), rule])

    for function in parse("Rules.py").body:
        if isinstance(function, ast.FunctionDef) and function.name in FUNCTIONS:
            for node in function.body:
                statement(node, {})
    return found


def assigned(module: ast.Module, name: str):
    """A list or dict assigned to a name at the top of one of the randomizer's files."""
    for node in module.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name:
            return ast.literal_eval(node.value)
    raise LookupError(name)


def read() -> tuple[dict[str, Rule], dict[str, Rule], dict[str, str], dict[str, tuple[str, Rule]]]:
    """(passage rules, check rules, each check's region, events)."""
    module = parse("Regions.py")
    # Location -> the randomizer's region, and exit -> its region, from the dungeon regions
    where, exit_region = {}, {}
    for node in ast.walk(module):
        if called(node) == "create_dungeon_region":
            assert isinstance(node, ast.Call)
            region, things = ast.literal_eval(node.args[1]), [ast.literal_eval(a) or [] for a in node.args[3:5]]
            where.update(dict.fromkeys(things[0], region))
            exit_region.update(dict.fromkeys(things[1] if len(things) > 1 else [], region))
    # A location in a region the tracker does not have is put in the region the randomizer leads into it from
    leads = {region: exit_region[name] for name, region in logical_connections if name in exit_region}

    def region_of(location: str) -> str | None:
        """The tracker's region for a location; None when it is not in a dungeon the tracker knows."""
        region = where.get(location)
        while region is not None and region not in regions_to_doors:
            region = leads.get(region)
        return region

    # The randomizer gives an "item" for doing something somewhere, like pulling the lever that drains the swamp.
    # The tracker cannot read those, but for the ones done in a dungeon it can work out whether the place can be
    # reached. Event -> where it is done
    gives = assigned(module, "location_events")
    done_at = {event: location for location, event in gives.items() if list(gives.values()).count(event) == 1 and region_of(location)}

    found = read_rules(Reader(set(done_at)))
    walked = {name for names in regions_to_doors.values() for name in names}
    passages = {name: rule for (kind, name), rule in found.items() if kind == "get_entrance" and name in walked and rule is not True}
    of_checks = {name: rule for (kind, name), rule in found.items() if kind == "get_location" and name in checks and rule is not True}
    regions = {name: str(region_of(name)) for name in checks}
    happen = {event: (str(region_of(location)), found.get(("get_location", location), True)) for event, location in done_at.items()}
    return passages, of_checks, regions, happen


# What leaving a region through a door or passage takes; what collecting a check takes, once in its region; the
# region each check is in; and event -> (the region it is done in, what doing it takes)
passage_rules, check_rules, check_regions, events = read()
