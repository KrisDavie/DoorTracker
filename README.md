# Muffins' Jank (Auto)Door Tracker

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

Rooms whose linked doorways fit together (a north door onto a south door, an east door onto a west door) are stacked: they snap together wall to wall into one bigger block that moves as a single piece, and the shared doorway is drawn as an opening in the wall instead of a line. Links that cannot be stacked (stairs, drops, or rooms that would land on top of each other) stay as edges between the blocks.

Auto-tracking will track supertiles, links between doors and lobbies. Dark rooms are only visible if the player has a lamp or a torch lit, otherwise they are obscured. The card the player is in is outlined in red.

Green doors are still unexplored, grey doors are linked. Hover anything to see its name in the toolbar. Hovering a room also fades every link that does not touch it. Lobbies hang off the door they lead to as a small entrance node.

You can save the current state of the tracker with File -> Save Tracker Data, including where you dragged the cards. Files saved by older versions load fine and are laid out automatically.

## Installation

### Windows users

Download the latest release from the releases page. Run the `DoorsTracker_vx.x.x.exe` file.

### Other users

Clone the repo and install the requirements.
`python DoorsTracker.py`

With [uv](https://docs.astral.sh/uv/) no install step is needed:
`uv run --with grpcio --with protobuf --with pyyaml --with pillow python DoorsTracker.py`

## Usage

Start SNI and launch the tracker. The tracker will automatically connect to SNI and start tracking. Use `--no-autotrack` to run without SNI.

## Controls

- Mouse wheel - Zoom, drag the background - Pan, `Fit` - Show everything
- Drag a card - Move it, together with everything stacked on it. Dragged cards stay where you put them (yellow dot); middle click one to hand it back to the layout
- `Re-layout` - Lay the whole graph out again around the cards you placed. This also re-picks which doorways get stacked so that as many links as possible become shared doorways
- Left click door, then another door - Link them (Esc cancels)
- Right click door - Add annotation or lobby. Right click the annotation to remove it
- Right click link - Remove link
- Middle click a stacked doorway - Split the two rooms apart. Middle click a link - Stack the rooms on it (takes priority over automatic stacking)
- Double click the background (or right click -> Add supertile here) - Add a supertile from the EG map
- Double click an unlinked door - Add a supertile next to that door
- Ctrl+Right click card - Remove supertile
- Middle click card - Pin it (never collapsed by "Hide Single Route Tiles")

### Options

- `Stack fitting rooms` - Stack rooms automatically as links are made. Turn it off to only stack the links you middle click
- `Group by original dungeon` - Pull supertiles of the same vanilla dungeon together and draw a hull around them
- Experimental -> Hide Single Route Tiles - Fully linked pass-through rooms shrink to a small pill instead of a full card

## Command Line Arguments

- `--size` - Size of the tracker window ('small', 'medium', 'large')
- `--port` - Port to use for SNI connection
- `--debug` - Show debug messages

## Requirements

- [SNI](https://github.com/alttpo/sni) is **required** to use this tracker - it will not work with (q)usb2snes

If you are using the Windows release, no other dependencies are required.

If you are running from source, you will need the following dependencies:

- Python 3.10+
- grpcio
- grpcio-tools
- PyYAML
- Pillow

## Known Issues

- When autotracking, multiple different dark rooms in the same dungeon will be obscured separately, providing the player with a little extra information
- Certain supertiles with many connections (Mire lobby, Mire Big chest Supertile) or long transition edges (Desert Main, TT Lobbies) can have issues tracking. This usually results in a wrong connection, or a missed connection.

