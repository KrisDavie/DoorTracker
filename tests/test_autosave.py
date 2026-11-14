"""The map kept between launches."""

import pytest
import yaml
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

import DoorsTracker
from support import grow, positions

TAB = "Turtle_Rock"


def links(window):
    return [(x.door, x.linked_door) for x in window.pages[TAB].model.door_links]


@pytest.fixture
def warnings(monkeypatch):
    """Titles of the warnings shown, in place of the dialogs."""
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: shown.append(args[1]))
    return shown


def autosave_of_a_map(window, folder):
    """Text of an autosave of a small map, made by this window."""
    window.start_autosave(folder, restore=True)
    grow(window.pages[TAB].model, 3)
    window.close()
    return (folder / "autosave.yaml").read_text()


def test_a_change_is_saved_and_the_next_window_gets_the_map_back(open_window, tmp_path, monkeypatch):
    monkeypatch.setattr(DoorsTracker, "SAVE_DELAY", 0)
    first = open_window()
    first.start_autosave(tmp_path, restore=True)
    first.seed_seen("0102030405")
    page = first.pages[TAB]
    grow(page.model, 3)
    page.model.toggle_expanded(page.model.nodes()[0])
    first.collected = {"Eastern Palace - Compass Chest"}
    page.rebuild()
    QTest.qWait(50)

    # Saved by the change, before the window closes
    saved = yaml.safe_load((tmp_path / "autosave-0102030405.yaml").read_text())
    assert len(saved[TAB]["door_links"]) == 3

    second = open_window()
    second.start_autosave(tmp_path, restore=True)
    model = second.pages[TAB].model
    assert second.seed_hash == "0102030405"
    assert second.collected == {"Eastern Palace - Compass Chest"}
    assert links(second) == links(first)
    assert model.kept_expanded == page.model.kept_expanded
    assert positions(model) == {node: (round(x, 1), round(y, 1)) for node, (x, y) in positions(page.model).items()}


def test_each_seed_keeps_its_own_map(window, tmp_path):
    window.start_autosave(tmp_path, restore=True)
    window.seed_seen("aaaaaaaaaa")
    grow(window.pages[TAB].model, 2)
    first_map = links(window)

    window.seed_seen("bbbbbbbbbb")
    assert links(window) == []
    grow(window.pages[TAB].model, 1)
    second_map = links(window)

    window.seed_seen("aaaaaaaaaa")
    assert links(window) == first_map
    window.seed_seen("bbbbbbbbbb")
    assert links(window) == second_map


@pytest.mark.parametrize("damage", ["not yaml", "cut short", "missing"])
def test_a_damaged_autosave_is_reported_and_left_alone(open_window, tmp_path, warnings, damage):
    whole = autosave_of_a_map(open_window(), tmp_path)
    file = tmp_path / "autosave.yaml"
    if damage == "missing":
        file.unlink()
    else:
        # Cut at the end of a line, which is still yaml
        file.write_text("{{{{" if damage == "not yaml" else whole[: whole.index("\n", len(whole) // 2) + 1])
    left = file.read_text() if file.exists() else None

    window = open_window()
    window.start_autosave(tmp_path, restore=True)
    assert warnings == ["Autosave not loaded"]
    assert not window.autosave_action.isChecked()
    assert window.settings["autosave"] is True

    # Nothing is saved over it, even on close
    grow(window.pages[TAB].model, 1)
    window.pages[TAB].rebuild()
    window.close()
    assert (file.read_text() if file.exists() else None) == left


def test_a_save_that_fails_is_reported_once(window, tmp_path, warnings, monkeypatch):
    monkeypatch.setattr(DoorsTracker, "SAVE_DELAY", 0)
    window.start_autosave(tmp_path / "no such folder", restore=True)
    for _ in range(2):
        grow(window.pages[TAB].model, 1)
        window.pages[TAB].rebuild()
        QTest.qWait(50)
    assert warnings == ["Autosave failed"]
    assert not window.autosave_action.isChecked()


def test_a_seed_whose_autosave_is_damaged_gets_an_empty_map(window, tmp_path, warnings):
    window.start_autosave(tmp_path, restore=True)
    window.seed_seen("aaaaaaaaaa")
    grow(window.pages[TAB].model, 2)
    damaged = tmp_path / "autosave-bbbbbbbbbb.yaml"
    damaged.write_text("{{{{")

    window.seed_seen("bbbbbbbbbb")
    assert warnings == ["Autosave not loaded"]
    assert links(window) == []
    window.close()
    assert damaged.read_text() == "{{{{"
    # The map that was on screen was put away first
    assert len(yaml.safe_load((tmp_path / "autosave-aaaaaaaaaa.yaml").read_text())[TAB]["door_links"]) == 2


def test_a_latest_file_that_is_not_text_is_reported(open_window, tmp_path, warnings):
    whole = autosave_of_a_map(open_window(), tmp_path)
    (tmp_path / "latest.txt").write_bytes(b"\x81\x8d\x8f")

    window = open_window()
    window.start_autosave(tmp_path, restore=True)
    assert warnings == ["Autosave not loaded"]
    assert not window.autosave_action.isChecked()
    window.close()
    assert (tmp_path / "autosave.yaml").read_text() == whole


@pytest.mark.parametrize("use_saved", [True, False])
def test_a_map_with_no_seed_only_replaces_a_seeds_saved_map_if_told_to(window, tmp_path, monkeypatch, use_saved):
    window.start_autosave(tmp_path, restore=True)
    window.seed_seen("aaaaaaaaaa")
    grow(window.pages[TAB].model, 2)
    saved_map = links(window)
    window._write_autosave()
    # Another map with no seed, as after loading a file from an older version
    window._clear_map()
    window.seed_hash = None
    grow(window.pages[TAB].model, 1)
    loose_map = links(window)
    asked = []
    answer = DoorsTracker.USE_SAVED if use_saved else DoorsTracker.KEEP_MAP
    monkeypatch.setattr(window, "_ask", lambda title, *rest: asked.append(title) or answer)

    assert window.seed_seen("aaaaaaaaaa")
    assert asked == ["Saved map found"]
    assert window.seed_hash == "aaaaaaaaaa"
    assert links(window) == (saved_map if use_saved else loose_map)
    if use_saved:
        # The map with no seed was put away, not lost
        assert len(yaml.safe_load((tmp_path / "autosave.yaml").read_text())[TAB]["door_links"]) == 1


def test_new_clears_the_map_and_its_seed(window, tmp_path, monkeypatch):
    window.start_autosave(tmp_path, restore=True)
    window.seed_seen("aaaaaaaaaa")
    grow(window.pages[TAB].model, 2)
    asked = []
    monkeypatch.setattr(window, "_ask", lambda title, *rest, **more: asked.append(title) or DoorsTracker.NEW_MAP)

    window.new_map()
    assert (links(window), window.seed_hash, asked) == ([], None, [])
    # The seed's map is still in its autosave
    assert len(yaml.safe_load((tmp_path / "autosave-aaaaaaaaaa.yaml").read_text())[TAB]["door_links"]) == 2


@pytest.mark.parametrize("go_ahead", [True, False])
def test_new_asks_first_when_the_map_would_be_lost(window, tmp_path, monkeypatch, go_ahead):
    # No seed: the new map would take this one's place in the autosave
    window.start_autosave(tmp_path, restore=True)
    grow(window.pages[TAB].model, 2)
    old_map = links(window)
    asked = []
    answer = DoorsTracker.NEW_MAP if go_ahead else DoorsTracker.CANCEL
    monkeypatch.setattr(window, "_ask", lambda title, *rest, **more: asked.append(title) or answer)

    window.new_map()
    assert asked == ["Start a new map?"]
    assert links(window) == ([] if go_ahead else old_map)
    # With nothing on the map there is nothing to ask about
    window.new_map()
    assert len(asked) == (1 if go_ahead else 2)


@pytest.mark.parametrize("go_ahead", [True, False])
def test_new_while_connected_warns_first(window, tmp_path, monkeypatch, go_ahead):
    window.start_autosave(tmp_path, restore=True)
    window.seed_seen("aaaaaaaaaa")
    grow(window.pages[TAB].model, 2)
    old_map = links(window)
    window.connected = True
    asked = []
    answer = DoorsTracker.NEW_MAP if go_ahead else DoorsTracker.CANCEL
    monkeypatch.setattr(window, "_ask", lambda title, *rest, **more: asked.append(title) or answer)

    window.new_map()
    # The tracker reads the game again straight away
    window.seed_seen("aaaaaaaaaa")
    assert asked == ["Connected to a game"]
    assert window.seed_hash == "aaaaaaaaaa"
    assert links(window) == ([] if go_ahead else old_map)


@pytest.mark.parametrize("new_map", [True, False])
def test_with_autosave_off_a_different_seed_asks_before_the_map_changes_seed(window, monkeypatch, new_map):
    window.seed_seen("aaaaaaaaaa")
    grow(window.pages[TAB].model, 2)
    old_map = links(window)
    asked = []
    answer = DoorsTracker.NEW_MAP if new_map else DoorsTracker.KEEP_MAP
    monkeypatch.setattr(window, "_ask", lambda title, *rest: asked.append(title) or answer)

    window.seed_seen("bbbbbbbbbb")
    window.seed_seen("bbbbbbbbbb")
    assert asked == ["Different seed"]
    assert window.seed_hash == "bbbbbbbbbb"
    assert links(window) == ([] if new_map else old_map)


def test_disconnecting_leaves_the_map_and_its_seed_alone(window, monkeypatch):
    window.seed_seen("aaaaaaaaaa")
    grow(window.pages[TAB].model, 2)
    old_map = links(window)
    monkeypatch.setattr(window, "_ask", lambda *args: DoorsTracker.DISCONNECT)

    # False tells the tracker to stop
    assert window.seed_seen("bbbbbbbbbb") is False
    assert (links(window), window.seed_hash) == (old_map, "aaaaaaaaaa")
