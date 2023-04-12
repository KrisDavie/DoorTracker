# Muffins' Jank (Auto)Door Tracker

## **Under the [current standard racing ruleset](http://alttp.mymm1.com/wiki/ALTTPR_Racing_Ruleset), this tracker is illegal to use while racing**

** This tracker is currently very experimental and may not work as expected. Documentation is also lacking. **

This tracker will auto-track dungeon layouts from the Doors branch of ALttPR using SNI.

* When visiting a dungeon, that dungeons tab will be auto-selected
* Players position is displayed as a red 'x'
* Unvisited supertiles are automatically added to the map
* Entering or exiting a dungeon will automatically add a lobby to the door
* Mirroring will add a lobby to the door mirrored to

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