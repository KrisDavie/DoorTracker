from collections import defaultdict
from data.doors_data import (
    doors_data,
    doors_to_regions,
    regions_to_doors,
    interior_doors,
    default_door_connections,
    default_one_way_connections,
    spiral_staircases,
    straight_staircases,
    open_edges,
    ladders,
)

vanilla_connections = {}
for data in [
        default_door_connections,
        default_one_way_connections,
        spiral_staircases,
        straight_staircases,
        open_edges,
        ladders,
        interior_doors,
    ]:
        for door, linked_door in data:
            vanilla_connections[door] = linked_door
vanilla_connections_rev = {v: k for k, v in vanilla_connections.items()}

def parse_doors(door_data):
    mode = "doors"
    doors = defaultdict(lambda: dict([("door_links", []), ("lobby_doors", []), ("special_doors", {}), ("tiles", {})]))

    for line in door_data:
        if line.strip() == "":
            continue
        if line.startswith("Dungeon Lobbies"):
            mode = "lobbies"
            print("Lobbies")
            continue
        if line.startswith("Door Types"):
            mode = "types"
            print("Types")
            continue

        if mode == "doors":
            if " <=> " in line:
                door, linked_door = line.split(" <=> ")
            elif  " => " in line:
                door, linked_door = line.split(" => ")
            else:
                print("Error parsing door data (decoupled not yet supported): " + line)
                continue
            dungeon_name = linked_door.split(" (")[-1].strip(")").replace(" ", "_")
            ld_list = linked_door.split(" (")  # Remove dungeon names
            linked_door = " (".join(ld_list[:-1]).strip()
            doors[dungeon_name]["door_links"].append({"door": door.strip(), "linked_door": linked_door})
            door_tile = f"{int(doors_data[door][0]) % 16}__{int(doors_data[door][0]) // 16}"
            linked_door_tile = f"{int(doors_data[linked_door][0]) % 16}__{int(doors_data[linked_door][0]) // 16}"
            doors[dungeon_name]["tiles"][door_tile] = True
            doors[dungeon_name]["tiles"][linked_door_tile] = True
            cur_links = {x["door"]: x["linked_door"] for x in doors[dungeon_name]["door_links"]}
            door_region = doors_to_regions[door]
            linked_door_region = doors_to_regions[linked_door]
            final_regions = []
            for i in [door_region, linked_door_region]:
                if type(i) == list:
                    final_regions += i
                else:
                    final_regions.append(i)
            r_doors = [regions_to_doors[x] for x in final_regions]
            r_doors = [item for sublist in r_doors for item in sublist]

            for r_door in r_doors:
                if r_door not in cur_links.keys() and r_door not in cur_links.values():
                    if r_door in vanilla_connections:
                        doors[dungeon_name]["door_links"].append({"door": r_door, "linked_door": vanilla_connections[r_door]})
                    elif r_door in vanilla_connections_rev:
                        doors[dungeon_name]["door_links"].append({"door": r_door, "linked_door": vanilla_connections_rev[r_door]})
        if mode == "lobbies":
            lobby, door = line.split(": ")
            doors["lobbies"][lobby.strip()] = door.strip()
        if mode == "types":
            # Extract dungeon name from brackets
            dsplit = line.split("(")
            door_type = dsplit[-1].split(")")[-1].strip()
            dungeon = dsplit[-1].split(")")[0].strip().replace(" ", "_")
            door = "(".join(dsplit[:-1])
            if " <-> " in door:
                door, linked_door = door.split(" <-> ")
                doors[dungeon]["special_doors"][door.strip()] = door_type
                doors[dungeon]["special_doors"][linked_door.strip()] = door_type
            else:
                doors[dungeon]["special_doors"][door.strip()] = door_type
    return doors


def parse_dr_spoiler(fh):
    yaml_data = {"placements": {1: {}}}
    fh.seek(0)
    spoiler_data = [line.strip() for line in fh.readlines()]
    log_locs = {"Doors:": None, "Locations:": None, "Playthrough:": None}
    for section in log_locs.keys():
        try:
            log_locs[section] = spoiler_data.index(section)
        except ValueError:
            pass
    log_locs = {k: v for k, v in log_locs.items() if v is not None}
    for n, (section, index) in enumerate(log_locs.items()):
        if section == "Playthrough:":
            continue
        data = spoiler_data[index + 1 : list(log_locs.values())[n + 1] - 1]
        if section == "Doors:":
            return parse_doors(data)
    return yaml_data
