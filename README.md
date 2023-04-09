# Muffins' Jank (Auto)Door Tracker

## **Under current rules, this tracker is illegal to use while racing**

This tracker will auto-track dungeon layouts from the Doors branch of ALttPR using SNI.

* When visiting a dungeon, that dungeons tab will be auto-selected
* Players position is displayed as a red 'x'
* Unvisited supertiles are automatically added to the map
* Entering a dungeon will automatically add a lobby to the entered door

## Usage
Start SNI and launch the tracker. The tracker will automatically connect to SNI and start tracking.

`python tracker.py`

## Arguments
* `--size` - Size of the tracker window ('small', 'medium', 'large')
* `--port` - Port to use for SNI connection


## Requirements
* Python 3.6+
* TODO...

In the meantime use the requirements from the Doors branch and add `Pillow`

## Known Issues
* Currently there are no exceptions for dark rooms, these will be added
* Lots of old code leftover from plando tool
* Dropdowns won't be marked as lobbies, and links will be lost from them
* There is no error checking in most of the code. If a device is not found when starting the tracker, auto-tracking won't work until reloading
* Saving and loading is not tested (but _might_ work)
* Sometimes the auto-tracking will stop working and you'll have to restart the tracker (losing all of the maps)