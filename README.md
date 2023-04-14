# Muffins' Jank (Auto)Door Tracker

## **Under the [current standard racing ruleset](http://alttp.mymm1.com/wiki/ALTTPR_Racing_Ruleset), auto-tracking using this tracker is illegal to use while racing**

**This tracker is currently very experimental and may not work as expected. Documentation is also lacking**

This tracker will auto-track dungeon layouts from the Doors branch of ALttPR using SNI.

* When visiting a dungeon, that dungeons tab will be auto-selected
* Players position is displayed as a red 'x'
* Unvisited supertiles are automatically added to the map
* Entering or exiting a dungeon will automatically add a lobby to the door
* Mirroring will add a lobby to the door mirrored to


## Basic Usage
Auto-tracking will track supertiles, links between doors and lobbies. Dark rooms are only tracked if the player has a lamp or a torch lit. Entering a dungeon into a dark room will not mark the lobby (this can cause issues with links past that room). 

Manually link doors with left click. Right click a line to remove a link.

Right click a door to place an annotation or lobby on that door. Lobbies are the white squares and are used to start mapping a dungeon. Right click an annotation to remove it.

Add new tiles by clicking an empty grey square. Ctrl-Right click to remove a tile. (sometimes comes back after a redraw). Middle click a supertile to grey it out.

You can save the current state of the tracker by clicking the save button. This will save the current layout and the current annotations. You can load a saved layout by clicking the load button and selecting a file.


## Usage
Start SNI and launch the tracker. The tracker will automatically connect to SNI and start tracking.

`python DoorsTracker.py`

## Arguments
* `--size` - Size of the tracker window ('small', 'medium', 'large')
* `--port` - Port to use for SNI connection
* `--darkpos` - Show player position on map when in dark rooms without lamp and without any torches lit
* `--debug` - Show debug messages


## Requirements
* [SNI](https://github.com/alttpo/sni) is **required** to use this tracker - it will not work with (q)usb2snes

- Python 3.10+
- grpcio
- grpcio-tools
- PyYAML
- Pillow


## Known Issues
* Lots of old code leftover from plando tool