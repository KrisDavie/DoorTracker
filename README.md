# Janker Door Tracker

Based on Muffins' Jank (Auto)Door Tracker.

## **Under the [current standard racing ruleset](http://alttp.mymm1.com/wiki/ALTTPR_Racing_Ruleset), auto-tracking using this tracker is illegal to use while racing unless explicitly allowed or agreed upon on a per-race basis**

A getting started document, including screenshots, controls nd more technical details can be found [here](https://docs.google.com/document/d/1fN7ge8Tu9MSFbcTuvMs_V3Tb8xwC9ftmlpK6ZS5yaco/edit?usp=sharing), I will attempt to keep this up to date.

This tracker will auto-track dungeon layouts from the Doors branch of ALttPR using SNI.

- When visiting a dungeon, that dungeons tab will be auto-selected
- Players position is displayed as a red 'x'
- Unvisited supertiles are automatically added to the map
- Entering or exiting a dungeon will automatically add a lobby to the door
- Mirroring will add a lobby to the door mirrored to

## Basic Usage

The map is drawn as a graph. Every supertile is a card (a cluster of its doors, drawn at their real positions on a thumbnail of the room) and every door link is an edge between two doors. Cards are laid out automatically so that a link through a north door puts the linked room above, an east door to the right, and so on. Cards are coloured by the dungeon the supertile originally belongs to, which is what you want in crossed door shuffle.

Rooms whose linked doorways fit together (a north door onto a south door, an east door onto a west door) are joined: they snap together wall to wall into one bigger block that moves as a single piece, and the shared doorway is drawn as an opening in the wall instead of a line. Links that cannot be joined (stairs, drops, or rooms that would land on top of each other) stay as edges between the blocks.

Auto-tracking will track supertiles, links between doors and lobbies. Dark rooms are only visible if the player has a lamp or a torch lit, otherwise they are obscured. The card the player is in is outlined in red.

Green doors are still unexplored, grey doors are linked. Hover anything to see its name in the toolbar. Hovering a room also fades every link that does not touch it. Lobbies hang off the door they lead to as a small entrance node.

The map is kept between launches: it is saved a second after each change and when the tracker closes, and loaded again the next time it starts. Starting the tracker with a file on the command line loads that file instead. File -> New (Ctrl+N) starts an empty map that belongs to no seed; while auto-tracking is connected to a game it warns first, as the new map then replaces the one saved for that game's seed, and otherwise it asks first if the map on screen would be lost. Untick File -> Autosave to stop both the saving and the loading at launch. If an autosave cannot be read or written, a warning says so and Autosave is turned off until you tick it again or restart.

Each seed has its own autosave. When auto-tracking finds the game is a different seed from the map, the map is put away and that seed's map is shown, or an empty one if it has none. This also happens for a race ROM, although it is not tracked. You are asked what to do in the two cases where a map could be lost: the map cannot be put away (Autosave is off, or saving failed), or the map has not been seen in a game yet and this seed already has a saved map. One of the answers is Disconnect, which stops auto-tracking and leaves every map as it is; File -> Reconnect to SNI starts it again. The files are `autosave-<seed hash>.yaml` (`autosave.yaml` for a map not yet seen in a game), in `%LOCALAPPDATA%\JankerDoorTracker` on Windows and `~/.config/JankerDoorTracker` on Linux. They are ordinary tracker files and are never deleted; `latest.txt` names the one loaded at the next launch.

You can also save the current state of the tracker with File -> Save Tracker Data (Ctrl+S), including where you dragged the cards and where the view was, and open it again with File -> Open Tracker Data (Ctrl+O). Files saved by older versions open fine and are laid out automatically.

## Installation

### Windows users

Download the latest release from the releases page. Run the `DoorsTracker_vx.x.x.exe` file.

### Other users

Clone the repo with its submodule, the door randomizer, which the tracker reads the checks and item rules from: `git clone --recurse-submodules`, or `git submodule update --init` in a clone made without it. Install the requirements.
`python DoorsTracker.py`

With [uv](https://docs.astral.sh/uv/) no install step is needed, dependencies come from `pyproject.toml`:
`uv run DoorsTracker.py`

## Usage

Start SNI and launch the tracker. The tracker will automatically connect to SNI and start tracking. Use `--no-autotrack` to run without SNI.

## Controls

- Mouse wheel - Zoom, drag the background - Pan, `Fit` - Show everything. The view only ever moves when you move it: laying out again, resizing the window or new rooms appearing never zoom or scroll
- Drag a card - Move it, together with everything joined to it. It stays exactly where you drop it and nothing else moves (unless `Simulate` is on). It is not pinned, so a later layout may move it
- Ctrl+click a card, or right click it -> Pin in place - Pin it (a pushpin appears in its corner). Pinned cards never move. Do the same again to unpin, or right click the background -> Unpin all
- `Re-layout` - Lay the whole graph out again around the cards you placed. This also re-picks which doorways get joined so that as many links as possible become shared doorways
- Left click door, then another door - Link them (Esc cancels). Until the second click every door is shown, as with View -> Show All Doors
- Right click door - Add annotation or lobby. Right click the annotation to remove it
- Right click link - Remove link
- Middle click a joined doorway - Split the two rooms apart. Middle click a link - Join the rooms on it (takes priority over automatic joining)
- Double click the background (or right click -> Add supertile here) - Add a supertile from the EG map
- Double click an unlinked door - Add a supertile next to that door
- Right click a card -> Remove supertile… - Remove it, after a confirmation. There is deliberately no shortcut for this
- Middle click a card - Keep it expanded (green border): every part of its supertile is shown, not only the parts in use, and it is never collapsed by "Hide Single Route Tiles". Middle click it again to undo

### Options

The toolbar is above the tabs: what it sets is the same in every tab. `Fit` and `Re-layout` float over the top left corner of each tab's map, as they act on that tab only. Everything on it, the menu options, the selected tab and the window's size and place are kept between launches, in `settings.yaml` beside the autosaves.

- Experimental -> Split Partitioned Rooms - Some supertiles hold places you cannot walk between without leaving, like the compass room beside TR Main Lobby or the bridge in Mire that passes over two corridors. With this on (the default) each such part is its own block, named after its own room, and moves and joins independently. Only the parts in use are drawn: ones with a link, entrance or icon, ones the player has been in, and ones a fixed drop or warp leads to. Middle click a card to show the rest of its supertile
- Experimental -> Trim Rooms - Supertile pictures often include blank rooms the game never uses. With this on (the default) those are painted out and each card shrinks to the rooms that have doors, so other rooms can sit in the space. A part of a split room shrinks to its own area. The list of live and dead rooms is in `data/room_bounds.py`, generated by `tools/find_rooms.py`
- `Spacing` slider - The gap rooms keep from each other: rooms closer than this are pushed apart. Links can still pull two rooms somewhat closer. Towards the left end it also shortens the links. The map moves to its new resting place as you drag the slider; the other tabs follow when you next open them
- `Dead-end pull` slider (experimental) - How much harder links pull on a block whose links all lead to one other block, so it tucks in beside that block. Far left is no extra pull
- `Simulate` - Keep the forces running all the time, so the map keeps adjusting, including while you drag a block through it. When it is off nothing moves on its own: the only thing that rearranges the map is moving the slider, which does it in one step
- `Follow player` - Centre the view on the player's room whenever it is not fully on screen. Off by default
- `Join fitting rooms` - Join rooms automatically as links are made. Turn it off to only join the links you middle click
- View -> Show Checks - Draw each dungeon chest, boss, prize, key pot and key drop as a square on its room (on by default). Like the doors, a square is green until the check is collected and grey after, and hovering it shows its name. Auto-tracking reads what has been collected from the game about once a second; without auto-tracking the squares are only a map of where the checks are. Ordinary pots are not shown. Which flag in the game marks each check as collected comes from the door randomizer's own tables, read out of the `ALttPDoorRandomizer` submodule each time the tracker starts
  - A square is red when the items you hold do not get you the check: either the check itself takes an item (the big chest in Thieves' Town takes the hammer), or every way to it on the map does (a gap that takes the hookshot). A big chest also takes the big key of the dungeon whose tab it is on. Auto-tracking reads your items along with the checks; until it has, nothing is red. The rules are the door randomizer's, read out of the submodule in the same way. Only rules that hold in every seed are used, so a square can be green when the seed's logic says no: key doors, crystal barriers, bosses and dark rooms without the lamp all count as passable. What is done in one place to open another, like draining the swamp, counts once the map leads to where it is done
  - A panel over the bottom right corner of the map shows your items: the game's item menu, then a column of abilities and one of equipment, with what you do not hold greyed out, and under them each dungeon's small keys and big key. Auto-tracking fills it in. You can also click anything in it to add it or step it up, and right click to step it back, with or without auto-tracking; the next read from the game puts back whatever the game does not agree with. The arrow on its tab closes and opens it. Silver arrows and what is in the bottles are not shown
  - A square is hollow when the map does not lead to the check yet: its room is on the map, but no entrance on the map leads to the part of the room it is in. That is so for every check of a supertile added by hand, until it is linked up. Its outline is red when the check itself takes an item you do not hold
  - The drops into a dungeon and the mirror route into the sanctuary are on the map from the start, which does not say you can get to them. Each shows a question mark, and is not counted as a way in, until auto-tracking sees you come in by it or you click it. Right click it to take that back
  - Click a check's square to mark it collected and right click it to take that back, with or without auto-tracking; the next read from the game puts back whatever the game does not agree with
- View -> Show FPS - At the right of the toolbar: how many times the tab in view was drawn in the last second, and how long the last drawing took. The map is only drawn when something changes, so it reads 0 when nothing is happening
- Experimental -> Hide Single Route Tiles - Fully linked pass-through rooms shrink to a small pill instead of a full card

## Command Line Arguments

- `tracker_file` - Optional path to saved tracker data to load on startup, e.g. `uv run DoorsTracker.py my_seed.yaml`
- `--no-autotrack` - Run without connecting to SNI
- `--size` - Size of the tracker window ('small', 'medium', 'large'), instead of the size it last had
- `--port` - Port to use for SNI connection
- `--debug` - Show debug messages
- `--no-gl` - Draw without OpenGL, if the map area stays blank on your machine

## Requirements

- [SNI](https://github.com/alttpo/sni) is **required** to use this tracker - it will not work with (q)usb2snes

If you are using the Windows release, no other dependencies are required.

If you are running from source, you will need the following dependencies:

- Python 3.10+
- PySide6
- grpcio
- protobuf
- PyYAML
- Pillow

## Known Issues

- When autotracking, multiple different dark rooms in the same dungeon will be obscured separately, providing the player with a little extra information
- Certain supertiles with many connections (Mire lobby, Mire Big chest Supertile) or long transition edges (Desert Main, TT Lobbies) can have issues tracking. This usually results in a wrong connection, or a missed connection.

