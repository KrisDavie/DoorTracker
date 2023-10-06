# Muffins' Jank (Auto)Door Tracker

## **Under the [current standard racing ruleset](http://alttp.mymm1.com/wiki/ALTTPR_Racing_Ruleset), auto-tracking using this tracker is illegal to use while racing**

**This tracker is currently very experimental and may not work as expected. Documentation is also lacking**

This tracker will auto-track dungeon layouts from the Doors branch of ALttPR using SNI.

- When visiting a dungeon, that dungeons tab will be auto-selected
- Players position is displayed as a red 'x'
- Unvisited supertiles are automatically added to the map
- Entering or exiting a dungeon will automatically add a lobby to the door
- Mirroring will add a lobby to the door mirrored to

## Basic Usage

Auto-tracking will track supertiles, links between doors and lobbies. Dark rooms are only visible if the player has a lamp or a torch lit, otherwise they are obscured.

Manually link doors with left click. Right click a line to remove a link.

Right click a door to place an annotation or lobby on that door. Lobbies are the white squares and are used to start mapping a dungeon. Right click an annotation to remove it.

Add new tiles by clicking an empty grey square. Ctrl-Right click to remove a tile.

~~You can save the current state of the tracker with File -> Save Tracker Data. This will save the current layout and the current annotations. You can load a saved layout File -> Load Tracker Data and selecting a file.~~

The size and aspect ratio of the tracker can be modified under the view menu.

## Installation

### Windows users

Download the latest release from the releases page. Run the `DoorsTracker.exe` file.

### Other users

Clone the repo and install the requirements.
`python DoorsTracker.py`

## Usage

Start SNI and launch the tracker. The tracker will automatically connect to SNI and start tracking.

## Controls

- Left click empty tile - Add a new tile
- Left click door - Start link, select another door to complete
- Right click door - Add annotation or lobby
- Right click link - Remove link
- Ctrl+Right click tile - Remove tile

### Advanced Controls

- Double left click door - Start link and add new tile
- Middle click tile - Pin tile (prevents tile being hidden in "hide simple tiles" mode)

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

- Save and load is currently broken
- Multiple different dark rooms in the same dungeon will be obscured separately, providing the player with a little extra information
