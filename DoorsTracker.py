import argparse
import asyncio
import math
from pathlib import Path
import pickle
import sys
from tkinter import Tk, TOP, BOTH, Toplevel, ttk, filedialog
from PIL import Image
import logging
import grpc.aio
import sni.sni_pb2_grpc as sni
import sni.sni_pb2 as sni_pb2
from gui.Doors.overview import door_customizer_page
from gui.Entrances.overview import entrance_customizer_page
from gui.Items.overview import item_customizer_page
from SpoilerToYaml import parse_dr_spoiler
from data.worlds_data import dungeon_worlds
from data.doors_data import eg_tile_multiuse, door_coordinates, dark_tiles, doors_data

import os
import yaml

dungeon_ids = {
    '00': 'Hyrule_Castle',
    '02': 'Hyrule_Castle',
    '04': "Eastern_Palace",
    '06': "Desert_Palace",
    '14': "Tower_of_Hera",
    '08': "Castle_Tower",
    '0c': "Palace_of_Darkness",
    '0a': "Swamp_Palace",
    '10': "Skull_Woods",
    '16': "Thieves_Town",
    '12': "Ice_Palace",
    '0e': "Misery_Mire",
    '18': "Turtle_Rock",
    '1a': "Ganons_Tower",

}

def customizerGUI(mainWindow, args=None):
   
    window_size = (1548, 768)
    
    if args:
        if args.size == 'small': 
            window_size = (1024, 512)
        elif args.size == 'large':
            window_size = (2048, 1024) 

    self = mainWindow

    mainWindow.wm_title("Jank Door Tracker")

    def _save_vanilla(self):
        data = {}
        # Tile map, tile_size, map_dims
        for dungeon in dungeon_worlds.keys():
            if dungeon in ["Overworld", "Underworld"]:
                continue
            data[dungeon] = {
                'tiles': {k: {'map_tile': v['map_tile']} for k, v in self.pages["doors"].pages[dungeon].content.tiles.items() if 'map_tile' in v },
                "tile_size": self.pages["doors"].pages[dungeon].content.tile_size,
                "map_dims": self.pages["doors"].pages[dungeon].content.map_dims,
                'x_offset': self.pages["doors"].pages[dungeon].content.x_offset,
                'y_offset': self.pages["doors"].pages[dungeon].content.y_offset,
            }
        with open("vanilla_layout.pickle", "wb") as f:
            pickle.dump(data, f, pickle.HIGHEST_PROTOCOL)

    def load_yaml(self):
        file = filedialog.askopenfilename(
            filetypes=[("Yaml Files", (".yaml", ".yml")), ("All Files", "*")], initialdir=os.path.join(".")
        )
        with open(file, mode="r") as fh:
            try:
                yaml_data = yaml.safe_load(fh)
            except:
                print("Error loading yaml file. Attempting to load DR spoiler log.")
                try:
                    fh.seek(0)
                    yaml_data = parse_dr_spoiler(fh)
                except Exception as e:
                    print(f"Error loading DR spoiler log. {e}")
                    return

        for dungeon in dungeon_worlds.keys():
            self.pages["items"].pages[dungeon].content.load_yaml(
                self.pages["items"].pages[dungeon].content,
                yaml_data["placements"][1] if "placements" in yaml_data else {},
            )
            if dungeon == "Overworld":
                continue
            self.pages["pots"].pages[dungeon].content.load_yaml(
                self.pages["pots"].pages[dungeon].content,
                yaml_data["placements"][1] if "placements" in yaml_data else {},
            )
            if dungeon == "Underworld":
                continue

            if "doors" in yaml_data:
                self.pages["doors"].pages[dungeon].content.load_yaml(
                    self.pages["doors"].pages[dungeon].content, yaml_data["doors"][1]
                )

        if "entrances" in yaml_data:
            all_entrances = {**yaml_data["entrances"][1]["entrances"], **yaml_data["entrances"][1]["two-way"]}
            self.pages["entrances"].content.load_yaml(self.pages["entrances"].content, all_entrances)

    def save_yaml(self, save=True):
        yaml_data = {}
        entrances, er_type = self.pages["entrances"].content.return_connections(
            self.pages["entrances"].content.defined_connections
        )
        if er_type:
            yaml_data["settings"] = {1: {"shuffle": er_type}}

        if len(entrances["entrances"]) + len(entrances["two-way"]) + len(entrances["exits"]) > 0:
            yaml_data["entrances"] = {1: entrances}

        # Save doors
        yaml_data["doors"] = {1: {"doors": {}, "lobbies": {}}}

        for item_world in self.pages["doors"].pages:
            doors_data, doors_type = (
                self.pages["doors"]
                .pages[item_world]
                .content.return_connections(
                    self.pages["doors"].pages[item_world].content.door_links,
                    self.pages["doors"].pages[item_world].content.lobby_doors,
                    self.pages["doors"].pages[item_world].content.special_doors,
                )
            )
            yaml_data["doors"][1]["doors"].update(doors_data["doors"])
            yaml_data["doors"][1]["lobbies"].update(doors_data["lobbies"])

        if len(yaml_data["doors"][1]) == 0:
            del yaml_data["doors"]

        # Save items
        yaml_data["placements"] = {1: {}}

        for item_world in self.pages["items"].pages:
            for loc, item in (
                self.pages["items"]
                .pages[item_world]
                .content.return_placements(self.pages["items"].pages[item_world].content.placed_items)
                .items()
            ):

                yaml_data["placements"][1].update({loc: item})
        if len(yaml_data["placements"][1]) == 0:
            del yaml_data["placements"]

        # Save Pots
        if "placements" not in yaml_data:
            yaml_data["placements"] = {1: {}}

        for pot_world in self.pages["pots"].pages:
            for loc, item in (
                self.pages["pots"]
                .pages[pot_world]
                .content.return_placements(self.pages["pots"].pages[pot_world].content.placed_items)
                .items()
            ):

                yaml_data["placements"][1].update({loc: item})
        if len(yaml_data["placements"][1]) == 0:
            del yaml_data["placements"]

        if not save:
            if len(yaml_data) == 0:
                return None
            else:
                return yaml_data
        file = filedialog.asksaveasfilename(
            filetypes=[("Yaml Files", (".yaml", ".yml")), ("All Files", "*")], initialdir=os.path.join(".")
        )
        with open(file, mode="w") as fh:
            yaml.dump(yaml_data, fh)

    self.notebook = ttk.Notebook(self)

    def hide_dont_close(self):
        self.eg_tile_window.grab_release()
        self.eg_tile_window.withdraw()

    # make array for pages
    self.pages = {}

    # make array for frames
    self.frames = {}

    self.pages["entrances"] = ttk.Frame(self.notebook)
    self.pages["items"] = ttk.Frame(self.notebook)
    self.pages["pots"] = ttk.Frame(self.notebook)
    self.pages["doors"] = ttk.Frame(self.notebook)

    self.notebook.add(self.pages["entrances"], text="Entrances")
    self.notebook.add(self.pages["items"], text="Items")
    self.notebook.add(self.pages["pots"], text="Pots")
    self.notebook.add(self.pages["doors"], text="Doors")
    self.notebook.pack()

    self.pages["items"].notebook = ttk.Notebook(self.pages["items"])
    self.pages["items"].pages = {}

    self.pages["pots"].notebook = ttk.Notebook(self.pages["pots"])
    self.pages["pots"].pages = {}

    self.pages["doors"].notebook = ttk.Notebook(self.pages["doors"])
    self.pages["doors"].pages = {}



    self.pages["entrances"].content = entrance_customizer_page(self, self.pages["entrances"], cdims=window_size)
    self.pages["entrances"].content.pack(side=TOP, fill=BOTH, expand=True)

    eg_map = Path("data") / "maps" / "egmap.png"
    eg_img = Image.open(eg_map)

    self.eg_tile_window = Toplevel(self)
    self.eg_tile_window.wm_title("EG Tiles")
    self.eg_tile_window.title("EG Map Window")
    self.eg_tile_window.protocol("WM_DELETE_WINDOW", lambda: hide_dont_close(self))
    self.eg_tile_window.notebook = ttk.Notebook(self.eg_tile_window)
    self.eg_tile_window.pages = {}
    with open(Path("data/vanilla_layout.pickle"), "rb") as f:
        vanilla_layout = pickle.load(f)

    self.eg_tile_multiuse = eg_tile_multiuse.copy()
    self.disabled_eg_tiles = {}
    for dungeon, world in dungeon_worlds.items():
        self.pages["items"].pages[dungeon] = ttk.Frame(self.pages["items"].notebook)
        self.pages["items"].notebook.add(self.pages["items"].pages[dungeon], text=dungeon.replace("_", " "))
        self.pages["items"].pages[dungeon].content = item_customizer_page(
            self, self.pages["items"].pages[dungeon], world, tab_item_type="standard", eg_img=eg_img, cdims=window_size
        )
        self.pages["items"].pages[dungeon].content.pack(side=TOP, fill=BOTH, expand=True)

        if dungeon == "Overworld":
            continue

        self.pages["pots"].pages[dungeon] = ttk.Frame(self.pages["pots"].notebook)
        self.pages["pots"].notebook.add(self.pages["pots"].pages[dungeon], text=dungeon.replace("_", " "))
        self.pages["pots"].pages[dungeon].content = item_customizer_page(
            self, self.pages["pots"].pages[dungeon], world, tab_item_type="pot", eg_img=eg_img, cdims=window_size
        )
        self.pages["pots"].pages[dungeon].content.pack(side=TOP, fill=BOTH, expand=True)

        if dungeon == "Underworld":
            continue

        self.pages["doors"].pages[dungeon] = ttk.Frame(self.pages["doors"].notebook)
        self.pages["doors"].notebook.add(self.pages["doors"].pages[dungeon], text=dungeon.replace("_", " "))
        self.pages["doors"].pages[dungeon].content = door_customizer_page(
            self, self.pages["doors"].pages[dungeon], world, eg_img=eg_img, cdims=window_size
        )
        self.pages["doors"].pages[dungeon].content.pack(side=TOP, fill=BOTH, expand=True)

        self.eg_tile_window.pages[dungeon] = ttk.Frame(self.eg_tile_window.notebook)
        self.eg_tile_window.notebook.add(self.eg_tile_window.pages[dungeon], text=dungeon.replace("_", " "))
        self.eg_tile_window.pages[dungeon].content = door_customizer_page(
            self, self.eg_tile_window.pages[dungeon], world, 
            eg_img=eg_img, 
            eg_selection_mode=True, 
            vanilla_data=vanilla_layout[dungeon],
            plando_window=self.pages["doors"].notebook,
            cdims=window_size)
        self.eg_tile_window.pages[dungeon].content.pack(side=TOP, fill=BOTH, expand=True)

    self.pages["items"].notebook.pack()
    self.pages["pots"].notebook.pack()
    self.pages["doors"].notebook.pack()
    self.eg_tile_window.notebook.pack()
    save_data_button = ttk.Button(self, text="Save Tracker Data", command=lambda: save_yaml(self))
    save_data_button.pack()
    load_data_button = ttk.Button(self, text="Load Tracker Data", command=lambda: load_yaml(self))
    load_data_button.pack()
    self.eg_tile_window.withdraw()

    # save_vanilla_button = ttk.Button(self, text="Save Vanilla Data", command=lambda: _save_vanilla(self))
    # save_vanilla_button.pack()

    def close_window():
        self.eg_tile_window.destroy()
        self.destroy()
        # kill asyncio loop
        self.loop.stop()

    mainWindow.protocol("WM_DELETE_WINDOW", close_window)
    doors_page = get_named_page(mainWindow.notebook, mainWindow.pages, 'doors')
    mainWindow.notebook.select(doors_page)

mem_addresses = {
        'link_y': (0xF50020, 0x2),
        'link_x': (0xF50022, 0x2),
        'layer': (0xF500EE, 0x1),
        'indoors': (0xF5001B, 0x1),
        'dungeon': (0xF5040C, 0x1),
        'dungeon_room': (0xF5048E, 0x1),
        'transitioning': (0xF500B0, 0x1),
        'falling': (0xF5005B, 0x1),
        'dead': (0xF5010A, 0x1),
        'lampcone': (0xF50458, 0x1),
        'torches': (0xF5045A, 0x1),
    }

def build_multi_request(add_space, mem_mapping):
    requests = {}
    for name, (address, size) in mem_addresses.items():
        request = sni_pb2.ReadMemoryRequest()
        request.requestAddressSpace = add_space
        request.requestMemoryMapping = mem_mapping
        request.requestAddress = address
        request.size = size
        requests[name] = request
    return requests

def des_data(mem_request_names, mem_data):
    data = {mem_request_names[n]: x.data.hex() for n, x in enumerate(mem_data.responses)}
    return data

async def tk_main(root):
    while True:
        root.update()
        await asyncio.sleep(0.05)

def get_cur_page(nb):
    return nb.index(nb.select())

def get_named_page(nb, pages, name):
    return nb.index(pages[name])

def find_closest_door(x, y, tile, layer):
    try:
        doors = door_coordinates[tile] # dict of door coordinates
        # Filter by layer
        doors = [door for door in doors if doors_data[door['name']][2] == layer]
        if len(doors) == 0:
            print(f'No doors found for {tile} layer {layer}')
            doors = door_coordinates[tile]
    except KeyError:
        return None
    closest_door = None
    closest_distance = 128 # max distance between player and door
    for door in doors:
        distance = math.sqrt((x - door['x'])**2 + (y - door['y'])**2)
        if distance < closest_distance:
            closest_distance = distance
            closest_door = door['name']
    return closest_door



async def sni_probe(mainWindow, port: int = 8191, debug: bool = False, darkpos: bool = False):
    # While loop to auto reconnect if the channel is closed?
    while True:
        async with grpc.aio.insecure_channel(f'localhost:{port}') as channel:
            stub = sni.DevicesStub(channel)
            response = await stub.ListDevices(sni_pb2.DevicesRequest(kinds=''))
            print("Found device: " + response.devices[0].uri)
            dev_uri = response.devices[0].uri
            dev_addrspace = response.devices[0].defaultAddressSpace
            mem_stub = sni.DeviceMemoryStub(channel)
            mem_mapping = await mem_stub.MappingDetect(sni_pb2.DetectMemoryMappingRequest(uri=dev_uri))
            mem_mapping = mem_mapping.memoryMapping
            mem_request = build_multi_request(dev_addrspace, mem_mapping)
            mem_request_names = list(mem_request.keys())

            main_nb = mainWindow.notebook
            doors_page = get_named_page(main_nb, mainWindow.pages, 'doors')
            doors_nb = mainWindow.pages['doors'].notebook

            current_tile = None
            previous_tile = None
            current_x = None
            current_y = None
            previous_x = None
            previous_y = None
            previous_layer = None
            was_transitioning = False
            was_falling = False
            was_dead = False
            cycle_skipped = False
            old_data = {k: None for k in mem_request_names}

            while True:
                mem_req = sni_pb2.MultiReadMemoryRequest(uri=dev_uri, requests=list(mem_request.values()))
                mem_data = await mem_stub.MultiRead(mem_req)
                data = des_data(mem_request_names, mem_data)
                data_diff = {k: v for k, v in data.items() if v != old_data[k]}
                old_data = data
                if len(data_diff) != 0 and args.debug:
                    print(data_diff)

                if data['dungeon'] not in dungeon_ids.keys() or data['indoors'] != '01':
                    current_tile = None
                    previous_tile = None
                    current_x = None
                    current_y = None
                    previous_x = None
                    previous_y = None
                    previous_layer = None
                    cycle_skipped = False
                    await asyncio.sleep(0.1)
                    continue
                
                # Select the doors tab and the dungeon page
                if get_cur_page(main_nb) != doors_page:
                    mainWindow.notebook.select(doors_page)
                dungeon_page = get_named_page(doors_nb, mainWindow.pages['doors'].pages, dungeon_ids[data["dungeon"]])
                if get_cur_page(doors_nb) != dungeon_page:
                    doors_nb.select(dungeon_page)

                if data['transitioning'] != '00':
                    was_transitioning = True
                    await asyncio.sleep(0.1)
                    continue

                # Both dying and falling can change supertile with no real doors
                if data['dead'] == '01':
                    previous_tile = current_tile = None
                    was_dead = True
                    continue 

                if data['falling'] != '00' and data['falling'] != '01':
                    previous_tile = current_tile = None
                    was_falling = True
                    continue
                    
                if not cycle_skipped and (was_transitioning or was_falling or was_dead):
                    cycle_skipped = True
                    continue

                cycle_skipped = False

                # TODO: Check doors to see if they're entrances and add lobbies?                

                eg_tile = (int(data['dungeon_room'], 16) % 16, int(data['dungeon_room'], 16) // 16)
                current_x_supertile = int(data['link_x'][2:], 16) // 2
                current_y_supertile = int(data['link_y'][2:], 16) // 2

                if eg_tile != (current_x_supertile, current_y_supertile):
                    print(f"Supertile mismatch: {eg_tile} != {current_x_supertile}, {current_y_supertile}")
                    continue

                dp_content = mainWindow.pages['doors'].pages[dungeon_ids[data["dungeon"]]].content
                if 'map_tile' not in dp_content.tiles[eg_tile]:
                    print(f"Adding tile {eg_tile}")
                    dp_content.auto_add_tile(dp_content, eg_tile)

                
                current_x_subtile = int(data['link_x'][2:], 16) % 2
                current_y_subtile = int(data['link_y'][2:], 16) % 2
                current_x = (current_x_subtile * 255) + int(data['link_x'][:2], 16) 
                current_y = (current_y_subtile * 255) + int(data['link_y'][:2], 16)

                if eg_tile not in dark_tiles or darkpos or (eg_tile in dark_tiles and (data['lampcone'] != '00' or data['torches'] != '00')):
                    dp_content.auto_draw_player(dp_content, current_x, current_y, eg_tile)

                if previous_tile != eg_tile and previous_tile == None:
                    previous_tile = eg_tile
                    current_tile = eg_tile
                    if was_falling or was_dead:
                        was_falling = False
                        was_dead = False
                        continue
                    # We just entered a new dungeon, add an entrance
                    if eg_tile == (2, 1):
                        continue
                    new_door = find_closest_door(current_x, current_y, eg_tile, data['layer'])
                    dp_content.auto_add_lobby(dp_content, new_door)

                elif (previous_tile != eg_tile and previous_tile != None) or was_transitioning:     
                    was_transitioning = False         
                    previous_tile = current_tile
                    current_tile = eg_tile
                    
                    old_door = find_closest_door(previous_x, previous_y, previous_tile, previous_layer)
                    new_door = find_closest_door(current_x, current_y, eg_tile, data['layer'])
                    if old_door == new_door:
                        continue
                    dp_content.auto_add_door_link(dp_content, old_door, new_door)

                previous_x = current_x
                previous_y = current_y
                previous_layer = data['layer']

                await asyncio.sleep(0.1)

if __name__ == "__main__":
    logging.basicConfig()
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--size", choices=['small', 'medium', 'large'], default='medium')
    parser.add_argument('--port', type=int, default=8191)
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--darkpos', action='store_true')
    parser.add_argument('--help', action='store_true')

    args, _ = parser.parse_known_args()
    if args.help:
        parser.print_help()
        sys.exit(0)
        
    mainWindow = Tk()

    customizerGUI(mainWindow, args=args)

    tkmain = asyncio.ensure_future(tk_main(mainWindow))
    sn_probe = asyncio.ensure_future(sni_probe(mainWindow, port=args.port, debug=args.debug, darkpos=args.darkpos))

    loop = asyncio.get_event_loop()
    mainWindow.loop = loop
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass

    tkmain.cancel()
    sn_probe.cancel()
