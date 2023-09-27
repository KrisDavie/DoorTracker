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


def parse_dr_spoiler(fh):
    yaml_data = {"placements": {1: {}}}
    fh.seek(0)
    spoiler_data = [line.strip() for line in fh.readlines()]
    log_locs = {"Doors:": None}
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
            yaml_data["doors"] = {1: {}}
            yaml_data["doors"][1] = parse_doors(data)
    return yaml_data
