# Muffins' Jank (Auto)Door Tracker

## **Under the [current standard racing ruleset](http://alttp.mymm1.com/wiki/ALTTPR_Racing_Ruleset), this tracker is illegal to use while racing**

This tracker will auto-track dungeon layouts from the Doors branch of ALttPR using SNI.

* When visiting a dungeon, that dungeons tab will be auto-selected
* Players position is displayed as a red 'x'
* Unvisited supertiles are automatically added to the map
* Entering a dungeon will automatically add a lobby to the entered door

## Usage
Start SNI and launch the tracker. The tracker will automatically connect to SNI and start tracking.

`python DoorsTracker.py`

## Arguments
* `--size` - Size of the tracker window ('small', 'medium', 'large')
* `--port` - Port to use for SNI connection
* `--darkpos` - Show player position on map when in dark rooms without lamp and without any torches lit
* `--debug` - Show debug messages


## Requirements
* Python 3.6+
* grpcio
* grpcio-tools

* TODO...

In the meantime use the requirements from the Doors branch and add `Pillow`, `grpcio` and `grpcio-tools` to it.

## Known Issues
* Lots of old code leftover from plando tool
* Sometimes the auto-tracking will stop working and you'll have to restart the tracker (losing all of the maps) - let me know if you come across this