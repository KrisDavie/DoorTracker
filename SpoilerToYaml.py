def parse_entrances(entrance_data):
    entrances = {"entrances": {}, "exits": {}, "two-way": {}}
    for line in entrance_data:
        if "<=>" in line:
            entrance, exit = line.split(" <=> ")
            entrances["two-way"][entrance.strip()] = exit.strip()
        elif "=>" in line:
            entrance, exit = line.split(" => ")
            entrances["entrances"][entrance.strip()] = exit.strip()
        elif "<=" in line:
            entrance, exit = line.split(" <= ")
            entrances["exits"][entrance.strip()] = exit.strip()
    return entrances


def parse_doors(door_data):
    mode = "doors"
    doors = {"doors": {}, "lobbies": {}}
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
            if "<=>" in line:
                door, linked_door = line.split(" <=> ")
            elif "=>" in line:
                door, linked_door = line.split(" => ")
            else:
                print("Error parsing door data (decoupled not yet supported): " + line)
                continue
            ld_list = linked_door.split(" (")  # Remove dungeon names
            doors["doors"][door.strip()] = " (".join(ld_list[:-1]).strip()
        if mode == "lobbies":
            lobby, door = line.split(": ")
            doors["lobbies"][lobby.strip()] = door.strip()
        if mode == "types":
            if line.endswith(" Big Key Door"):
                door = " ".join(line.split(" ")[:-3]).strip()
                if door in doors["doors"]:
                    doors["doors"][door] = {"dest": doors["doors"][door], "type": "Big Key Door"}
                else:
                    doors["doors"][door] = {"type": "Big Key Door"}
            elif line.endswith(" Key Door"):
                if " <-> " in line:
                    door, linked_door = " ".join(line.split(" ")[:-2]).strip().split(" <-> ")
                else:
                    door = " ".join(line.split(" ")[:-2]).strip()
                    linked_door = None
                if door in doors["doors"]:
                    doors["doors"][door] = {"dest": doors["doors"][door], "type": "Key Door"}
                elif linked_door in doors["doors"]:
                    doors["doors"][linked_door] = {"dest": door, "type": "Key Door"}
                else:
                    doors["doors"][door] = {"type": "Key Door"}
            elif line.endswith(" Trap Door"):
                door = " ".join(line.split(" ")[:-2]).strip()
                if door in doors["doors"]:
                    doors["doors"][door] = {"dest": doors["doors"][door], "type": "Trap Door"}
                else:
                    doors["doors"][door] = {"type": "Trap Door"}
            elif line.endswith(" Bomb Door"):
                door = " ".join(line.split(" ")[:-2]).strip()
                if door in doors["doors"]:
                    doors["doors"][door] = {"dest": doors["doors"][door], "type": "Bomb Door"}
                else:
                    doors["doors"][door] = {"type": "Bomb Door"}
            elif line.endswith(" Dash Door"):
                door = " ".join(line.split(" ")[:-2]).strip()
                if door in doors["doors"]:
                    doors["doors"][door] = {"dest": doors["doors"][door], "type": "Dash Door"}
                else:
                    doors["doors"][door] = {"type": "Dash Door"}
    return doors


def parse_placements(placement_data):
    placements = {}
    for line in placement_data:
        if ":" in line:
            location, item = line.split(": ")
            if "@" in location:
                location = location.split(" @")[0]
            placements[location.strip()] = item.strip()
    return placements


def parse_dr_spoiler(fh):
    yaml_data = {"placements": {1: {}}}
    fh.seek(0)
    spoiler_data = [line.strip() for line in fh.readlines()]
    # Entrances -> Doors -> Dungeon Lobbies -> Door Types -> Locations -> Shops -> Playthrough
    log_locs = {
        "Entrances:": None,
        "Doors:": None,
        "Locations:": None,
        "Shops:": None,
        "Playthrough:": None,
    }
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
        if section == "Entrances:":
            yaml_data["entrances"] = {1: {}}
            yaml_data["entrances"][1] = parse_entrances(data)
        elif section == "Doors:":
            yaml_data["doors"] = {1: {}}
            yaml_data["doors"][1] = parse_doors(data)
        elif section == "Locations:":
            yaml_data["placements"][1] = parse_placements(data)
    return yaml_data
