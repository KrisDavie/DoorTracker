import argparse
import asyncio
import math
from pathlib import Path
import sys
from tkinter import BooleanVar, Menu, Tk, TOP, BOTH, Toplevel, ttk, filedialog
from PIL import Image
import logging
import grpc.aio
import sni.sni_pb2_grpc as sni
import sni.sni_pb2 as sni_pb2
from gui.Doors.overview import door_customizer_page
from SpoilerToYaml import parse_dr_spoiler
from data.worlds_data import dungeon_worlds
from data.doors_data import eg_tile_multiuse, door_coordinates, dark_tiles, doors_data
from data.vanilla_data import vanilla_layout_optimized, vanilla_layout_original

import os
import yaml

dungeon_ids = {
    "00": "Hyrule_Castle",
    "02": "Hyrule_Castle",
    "04": "Eastern_Palace",
    "06": "Desert_Palace",
    "14": "Tower_of_Hera",
    "08": "Castle_Tower",
    "0c": "Palace_of_Darkness",
    "0a": "Swamp_Palace",
    "10": "Skull_Woods",
    "16": "Thieves_Town",
    "12": "Ice_Palace",
    "0e": "Misery_Mire",
    "18": "Turtle_Rock",
    "1a": "Ganons_Tower",
}

MAIN_X_PAD = 40
MAIN_Y_PAD = 120


def reconnect(mainWindow, forced=False, device=None):
    kill_sni_tracking(mainWindow)
    mainWindow.sni_task = start_sni_tracking(mainWindow, mainWindow.args, forced_autotrack=forced, device=device)


def race_rom_warning(self):
    main_x = self.winfo_rootx()
    main_y = self.winfo_rooty()
    main_width = self.winfo_width()
    main_height = self.winfo_height()
    top = Toplevel(self)
    top.geometry(f"700x175+{(main_x + main_width // 2) - 700 // 2}+{(main_y + main_height // 2) - 175 // 2}")
    top.title("Warning - Race Rom Detected")
    top.resizable(False, False)
    top.grab_set()
    top.focus_set()
    button_frame = ttk.Frame(top)

    def force_autotracking():
        self.autotracking_forced = True
        reconnect(mainWindow, forced=True, device=mainWindow.device)
        top.destroy()

    ttk.Label(
        top,
        text="A Race Rom has been detected, auto-tracking has been automatically disabled.\n\nWhen auto-tracking is enabled, this tracker does not abide by the current auto-tracking rules set by the racing council.\nYou can continue to use this tracker, but you will need to manually track layouts.\n\nIf you would like to continue using auto-tracking, you can force it to be enabled by clicking the button below.",
        justify="center",
    ).pack(padx=20, pady=20)
    ttk.Button(button_frame, text="OK", command=top.destroy).pack(side="left")
    ttk.Button(button_frame, text="Force Auto-Tracking", command=force_autotracking).pack(side="left")
    button_frame.pack()


window_sizes = {
    "small": (1024, 512),
    "medium": (1548, 768),
    "large": (2048, 1024),
}


def customizerGUI(mainWindow, args=None):
    window_size = (1548, 768)

    if args and args.size:
        window_size = window_sizes[args.size]

    self = mainWindow
    self.args = args

    def load_yaml(self):
        file = filedialog.askopenfilename(
            filetypes=[("Yaml Files", (".yaml", ".yml")), ("All Files", "*")],
            initialdir=os.path.join("."),
        )
        with open(file, mode="r") as fh:
            try:
                yaml_data = yaml.safe_load(fh)
            except Exception as e:
                print(f"Error loading yaml. {e}")
                return
            for dungeon, dungeon_data in yaml_data.items():
                self.pages[dungeon].content.load_yaml(self.pages[dungeon].content, dungeon_data)

    def save_yaml(self, save=True):
        yaml_data = {}

        for dungeon in self.pages:
            doors_data = self.pages[dungeon].content.return_connections(self.pages[dungeon].content)
            yaml_data[dungeon] = doors_data

        if not save:
            if len(yaml_data) == 0:
                return None
            else:
                return yaml_data
        file = filedialog.asksaveasfilename(
            filetypes=[("Yaml Files", (".yaml", ".yml")), ("All Files", "*")],
            initialdir=os.path.join("."),
        )

        if file == "":
            return
        if not file.endswith(".yaml") or not file.endswith(".yml"):
            file += ".yaml"
        with open(file, mode="w") as fh:
            yaml.dump(yaml_data, fh)

    self.notebook = ttk.Notebook(self)

    def hide_dont_close(self):
        self.notebook.setvar("selected_eg_tile", BooleanVar(value=False))
        self.eg_tile_window.grab_release()
        self.eg_tile_window.withdraw()

    # make array for pages
    self.pages = {}

    # make array for frames
    self.frames = {}

    eg_map = Path(__file__).parent / "data" / "maps" / "egmap.png"
    eg_img = Image.open(eg_map)

    self.eg_tile_window = Toplevel(self)
    self.eg_tile_window.wm_title("EG Tiles")
    self.eg_tile_window.title("EG Map Window")
    self.eg_tile_window.protocol("WM_DELETE_WINDOW", lambda: hide_dont_close(self))
    self.eg_tile_window.notebook = ttk.Notebook(self.eg_tile_window)  # type: ignore
    self.eg_tile_window.pages = {}  # type: ignore
    self.show_all_doors = False

    self.eg_tile_multiuse = eg_tile_multiuse.copy()
    self.disabled_eg_tiles = {}

    self.experimental_flags = {
        "hide_single_route_tiles": False,
        "prefer_fill_map": False,
        "decoupled_doors": False,
    }

    def create_vanilla_window(layout_name: str):
        if layout_name == "Optimized":
            layout = vanilla_layout_optimized
        elif layout_name == "Original":
            layout = vanilla_layout_original
            if "Other Lobby Tiles" in self.eg_tile_window.pages:
                try:
                    self.eg_tile_window.notebook.forget(
                        list(self.eg_tile_window.pages.keys()).index("Other Lobby Tiles")
                    )
                    del self.eg_tile_window.pages["Other Lobby Tiles"]
                except Exception:
                    pass
        else:
            return
        for dungeon, world in dungeon_worlds.items():
            if dungeon == "Overworld":
                continue
            if dungeon == "Underworld":
                continue
            if dungeon in self.eg_tile_window.pages:
                self.eg_tile_window.notebook.forget(list(self.eg_tile_window.pages.keys()).index(dungeon))
                del self.eg_tile_window.pages[dungeon]
            self.eg_tile_window.pages[dungeon] = ttk.Frame(self.eg_tile_window.notebook)  # type: ignore
            self.eg_tile_window.notebook.add(  # type: ignore
                self.eg_tile_window.pages[dungeon], text=dungeon.replace("_", " ")  # type: ignore
            )
            self.eg_tile_window.pages[dungeon].content = door_customizer_page(  # type: ignore
                self,
                self.eg_tile_window.pages[dungeon],  # type: ignore
                world,
                eg_img=eg_img,
                eg_selection_mode=True,
                vanilla_data=layout[dungeon],
                plando_window=self.notebook,  # type: ignore
                cdims=window_size,
            )
            self.eg_tile_window.pages[dungeon].content.pack(side=TOP, fill=BOTH, expand=True)  # type: ignore
            self.eg_tile_window.notebook.pack()  # type: ignore
        if layout_name == "Optimized":
            self.eg_tile_window.pages["Other Lobby Tiles"] = ttk.Frame(self.eg_tile_window.notebook)  # type: ignore
            self.eg_tile_window.notebook.add(  # type: ignore
                self.eg_tile_window.pages["Other Lobby Tiles"], text="Other Lobby Tiles"  # type: ignore
            )
            self.eg_tile_window.pages["Other Lobby Tiles"].content = door_customizer_page(  # type: ignore
                self,
                self.eg_tile_window.pages["Other Lobby Tiles"],  # type: ignore
                world,
                eg_img=eg_img,
                eg_selection_mode=True,
                vanilla_data=layout["Lobbyable_Tiles"],
                plando_window=self.notebook,  # type: ignore
                cdims=window_size,
            )
            self.eg_tile_window.pages["Other Lobby Tiles"].content.pack(side=TOP, fill=BOTH, expand=True)  # type: ignore
            self.eg_tile_window.notebook.pack()  # type: ignore

    for dungeon, world in dungeon_worlds.items():
        if dungeon == "Overworld":
            continue
        if dungeon == "Underworld":
            continue

        self.pages[dungeon] = ttk.Frame(self.notebook)  # type: ignore
        self.notebook.add(  # type: ignore
            self.pages[dungeon], text=dungeon.replace("_", " ")  # type: ignore
        )
        self.pages[dungeon].content = door_customizer_page(  # type: ignore
            self,
            self.pages[dungeon],  # type: ignore
            world,
            eg_img=eg_img,
            cdims=window_size,
        )
        self.pages[dungeon].content.pack(side=TOP, fill=BOTH, expand=True)  # type: ignore

    self.notebook.pack()  # type: ignore

    menu = Menu(self)
    self.config(menu=menu)
    fileMenu = Menu(menu, tearoff="off")  # type: ignore
    menu.add_cascade(label="File", menu=fileMenu)
    viewMenu = Menu(menu, tearoff="off")  # type: ignore
    menu.add_cascade(label="View", menu=viewMenu)
    # Add a button to the top level menu to redraw all
    menu.add_command(label="Redraw All", command=lambda: redraw_all(self))
    menu.add_command(label="Show All Doors", command=lambda: show_all_doors(self, menu))

    fileMenu.add_command(label="Load Tracker Data", command=lambda: load_yaml(self))
    fileMenu.add_command(label="Save Tracker Data", command=lambda: save_yaml(self))
    fileMenu.add_separator()
    fileMenu.add_command(label="Stop Auto-tracking", command=lambda: kill_sni_tracking(self))
    fileMenu.add_command(label="Reconnect to SNI", command=lambda: reconnect(self))
    devicesMenu = Menu(fileMenu, tearoff="off")  # type: ignore
    fileMenu.add_cascade(label="Devices", menu=devicesMenu)
    devicesMenu.add_radiobutton(label="No Devices...")
    devicesMenu.entryconfig("No Devices...", state="disabled")
    mainWindow.devicesMenu = devicesMenu

    fileMenu.add_separator()
    fileMenu.add_command(label="Reset Tracker", command=lambda: reset_tracker(self))
    fileMenu.add_separator()
    fileMenu.add_command(label="Exit", command=lambda: self.destroy())

    aspectRatioMenu = Menu(viewMenu, tearoff="off")  # type: ignore
    viewMenu.add_cascade(label="Aspect Ratio", menu=aspectRatioMenu)
    aspectRatioMenu.add_radiobutton(label="2:1", command=lambda: set_aspect_ratio(self, (1, 2)))
    aspectRatioMenu.add_radiobutton(label="4:3", command=lambda: set_aspect_ratio(self, (3, 4)))
    aspectRatioMenu.invoke(0)

    sizeMenu = Menu(viewMenu, tearoff="off")  # type: ignore
    viewMenu.add_cascade(label="Size", menu=sizeMenu)
    for size in window_sizes:
        sizeMenu.add_radiobutton(label=size.capitalize(), command=lambda size=size: set_size(self, size))
    sizeMenu.invoke(1)

    vanillaLayoutMenu = Menu(viewMenu, tearoff="off")  # type: ignore
    viewMenu.add_cascade(label="Vanilla Layout", menu=vanillaLayoutMenu)
    vanillaLayoutMenu.add_radiobutton(
        label="Optimized",
        command=lambda: create_vanilla_window("Optimized"),
    )
    vanillaLayoutMenu.add_radiobutton(
        label="Original",
        command=lambda: create_vanilla_window("Original"),
    )
    vanillaLayoutMenu.invoke(0)

    experimentalMenu = Menu(viewMenu, tearoff="off")  # type: ignore
    menu.add_cascade(label="Experimental", menu=experimentalMenu)
    experimentalMenu.add_checkbutton(
        label="Hide Single Route Tiles", command=lambda: set_experimental_flag(self, "hide_single_route_tiles")
    )
    experimentalMenu.add_checkbutton(
        label="Fill Map to 80%", command=lambda: set_experimental_flag(self, "prefer_fill_map")
    )
    experimentalMenu.add_checkbutton(
        label="Enable Decoupled Support", command=lambda: set_experimental_flag(self, "decoupled_doors")
    )

    self.eg_tile_window.withdraw()

    def close_window():
        self.eg_tile_window.destroy()
        self.destroy()
        # kill asyncio loop
        asyncio.get_event_loop().stop()

    mainWindow.protocol("WM_DELETE_WINDOW", close_window)


def reset_tracker(self):
    main_x = self.winfo_rootx()
    main_y = self.winfo_rooty()
    main_width = self.winfo_width()
    main_height = self.winfo_height()
    top = Toplevel(self)
    top.geometry(f"300x110+{(main_x + main_width // 2) - 300 // 2}+{(main_y + main_height // 2) - 110 // 2}")
    top.title("Reset?")
    top.resizable(False, False)
    top.grab_set()
    top.focus_set()
    button_frame = ttk.Frame(top)

    def force_reset():
        for world in self.pages:
            content = self.pages[world].content
            content.init_page(content)
            content.redraw_canvas(content)
        top.destroy()

    ttk.Label(
        top,
        text="This will reset your tracker, losing all connections etc.\nAre you sure you want to continue?",
        justify="center",
    ).pack(padx=20, pady=20)
    ttk.Button(button_frame, text="Cancel", command=top.destroy).pack(side="left")
    ttk.Button(button_frame, text="Reset", command=force_reset).pack(side="left")
    button_frame.pack()


def redraw_all(self):
    for world in self.pages:
        content = self.pages[world].content
        content.redraw_canvas(content)


def show_all_doors(self, menu):
    self.show_all_doors = not self.show_all_doors
    if self.show_all_doors:
        menu.entryconfig(4, label="Show Reachable Doors")
    else:
        menu.entryconfig(4, label="Show All Doors")
    for world in self.pages:
        content = self.pages[world].content
        content.show_all_doors = self.show_all_doors
        content.redraw_canvas(content)


def set_aspect_ratio(self, ratio):
    if self.aspect_ratio == ratio:
        return
    self.aspect_ratio = ratio
    new_height = window_sizes[self.size][1]
    new_width = int(new_height * ratio[1] / ratio[0])
    sc_width = mainWindow.winfo_screenwidth()
    sc_height = mainWindow.winfo_screenheight()
    for world in self.pages:
        # Update canvas dimensions, aspect ratio, and redraw
        self.pages[world].content.aspect_ratio = ratio
        self.pages[world].content.cwidth = new_width
        self.pages[world].content.cheight = new_height
        self.pages[world].content.redraw_canvas(self.pages[world].content)
    self.geometry(
        f"{new_width + MAIN_X_PAD}x{new_height + MAIN_Y_PAD}+{int(sc_width/2 - new_width/2)}+{int(sc_height/2 - new_height/2)}"
    )


def set_size(self, size):
    if self.size == size:
        return
    self.size = size
    new_height = window_sizes[size][1]
    new_width = int(new_height * self.aspect_ratio[1] / self.aspect_ratio[0])
    sc_width = mainWindow.winfo_screenwidth()
    sc_height = mainWindow.winfo_screenheight()
    for world in self.pages:
        self.pages[world].content.cheight = new_height
        self.pages[world].content.cwidth = new_width
        self.pages[world].content.redraw_canvas(self.pages[world].content)
    self.geometry(
        f"{new_width + MAIN_X_PAD}x{new_height + MAIN_Y_PAD}+{int(sc_width/2 - new_width/2)}+{int(sc_height/2 - new_height/2)}"
    )


def set_experimental_flag(self, flag: str):
    self.experimental_flags[flag] = not self.experimental_flags[flag]
    for world in self.pages:
        self.pages[world].content.experimental_flags = self.experimental_flags
        self.pages[world].content.redraw_canvas(self.pages[world].content)
        self.eg_tile_window.pages[world].content.experimental_flags = self.experimental_flags
        self.eg_tile_window.pages[world].content.draw_vanilla_eg_map(self.eg_tile_window.pages[world].content)


mem_addresses = {
    "race": (0x180213, 0x1),
    "gamemode": (0xF50010, 0x1),
    "indoors": (0xF5001B, 0x1),
    "link_y": (0xF50020, 0x2),
    "link_x": (0xF50022, 0x2),
    "falling": (0xF5005B, 0x1),
    "mirror": (0xF50095, 0x1),
    "transitioning": (0xF500B0, 0x1),
    "layer": (0xF500EE, 0x1),
    "dead": (0xF5010A, 0x1),
    "dungeon": (0xF5040C, 0x1),
    "lampcone": (0xF50458, 0x1),
    "torches": (0xF5045A, 0x1),
    "dungeon_room": (0xF5048E, 0x1),
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


def find_closest_door(x, y, tile, layer, closest_distance=128):
    #  X and Y are none when dropping in a hole
    try:
        doors = door_coordinates[tile]  # dict of door coordinates
        # Filter by layer
        doors = [door for door in doors if doors_data[door["name"]][2] == layer]  # type: ignore
        if len(doors) == 0:
            print(f"No doors found for {tile} layer {layer}")
            doors = door_coordinates[tile]
    except KeyError:
        return None
    closest_door = None
    for door in doors:
        distance = math.sqrt((x - door["x"]) ** 2 + (y - door["y"]) ** 2)
        if distance < closest_distance:
            closest_distance = distance
            closest_door = door["name"]
    return closest_door


def reset_dungeon_names(mainWindow):
    doors_nb = mainWindow.notebook
    for dungeon, page in mainWindow.pages.items():
        doors_nb.tab(page, underline=-1)


def highlight_dungeon_name(mainWindow, dungeon_name):
    reset_dungeon_names(mainWindow)
    doors_nb = mainWindow.notebook
    dungeon_page = get_named_page(doors_nb, mainWindow.pages, dungeon_name)
    doors_nb.tab(dungeon_page, underline=0)


async def sni_probe(mainWindow, args: argparse.Namespace, forced_autotrack: bool = False, device: str = None):
    forced_autotrack = True
    port = args.port
    debug = args.debug
    channel = grpc.aio.insecure_channel(f"localhost:{port}")
    stub = sni.DevicesStub(channel)
    while True:
        response = await stub.ListDevices(sni_pb2.DevicesRequest(kinds=""))
        if len(response.devices) > 0:
            break
        else:
            mainWindow.wm_title(f"Jank Door Tracker - Waiting for devices...")
            await asyncio.sleep(1)
    mainWindow.devicesMenu.delete(0, "end")
    for _device in response.devices:
        mainWindow.devicesMenu.add_radiobutton(
            label=_device.uri, command=lambda device=_device.uri: reconnect(mainWindow, device=device)
        )

    if device and device in [x.uri for x in response.devices]:
        dev_uri = device
    else:
        dev_uri = response.devices[0].uri
    mainWindow.device = dev_uri
    if debug:
        print("Found device: " + response.devices[0].uri)
    dev_addrspace = 0
    mem_stub = sni.DeviceMemoryStub(channel)
    mem_mapping = await mem_stub.MappingDetect(sni_pb2.DetectMemoryMappingRequest(uri=dev_uri))
    mem_mapping = mem_mapping.memoryMapping
    mem_request = build_multi_request(dev_addrspace, mem_mapping)
    mem_request_names = list(mem_request.keys())

    if not forced_autotrack:
        mainWindow.wm_title(f"Jank Door Tracker - Auto-tracking Enabled (Connected to {dev_uri})")
    else:
        mainWindow.wm_title(
            f"Jank Door Tracker - Auto-tracking Forced (!! Race Rom Detected !!) (Connected to {dev_uri})"
        )

    doors_nb = mainWindow.notebook

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
    was_mirroring = False
    previous_dungeon = False
    tab_changed = False
    is_dark = False
    boss_just_killed = False
    old_data = {k: None for k in mem_request_names}
    eg_tile = (0, 0)

    # Main loop for data collection
    while True:
        if channel.get_state() in [
            grpc.ChannelConnectivity.SHUTDOWN,
            grpc.ChannelConnectivity.TRANSIENT_FAILURE,
            grpc.ChannelConnectivity.CONNECTING,
        ]:
            mainWindow.wm_title(f"Jank Door Tracker - DISCONNECTED FROM SNI")
            await asyncio.sleep(1)
            continue
        # Lazy error handling - won't actually catch disconnects
        try:
            mem_req = sni_pb2.MultiReadMemoryRequest(uri=dev_uri, requests=list(mem_request.values()))
            mem_data = await mem_stub.MultiRead(mem_req)
            data = des_data(mem_request_names, mem_data)
            data_diff = {k: v for k, v in data.items() if v != old_data[k]}
            old_data = data
            if len(data_diff) != 0 and args.debug:
                print(data_diff)

            if boss_just_killed:
                if data["gamemode"] != "09":
                    await asyncio.sleep(0.1)
                    continue

            # Are we even in game?
            if int(data["gamemode"], 16) <= 0x5 or int(data["gamemode"], 16) >= 0x0B:
                if data["gamemode"] == "16":
                    boss_just_killed = True
                    await asyncio.sleep(0.1)
                    continue
                if data["mirror"] == "f7":
                    was_mirroring = True

                await asyncio.sleep(0.1)
                continue

            if data["race"] == "01" and not forced_autotrack:
                race_rom_warning(mainWindow)
                mainWindow.wm_title(f"Jank Door Tracker - Auto-tracking Disabled")
                break

            # if args.darkpos:
            #     is_dark = False
            # else:
            is_dark = data["lampcone"] == "00" and data["torches"] == "00"

            if data["dungeon"] not in dungeon_ids.keys() or data["indoors"] != "01":
                if (
                    previous_dungeon in dungeon_ids.keys()
                    and data["indoors"] == "00"
                    and data["mirror"] != "0f"
                    and not boss_just_killed
                ):
                    reset_dungeon_names(mainWindow)
                    # Just left a dungeon, add the last door as a lobby
                    new_door = find_closest_door(current_x, current_y, eg_tile, previous_layer)
                    dp_content.auto_add_lobby(dp_content, new_door)  # type: ignore
                current_tile = None
                previous_tile = None
                current_x = None
                current_y = None
                previous_x = None
                previous_y = None
                previous_layer = None
                cycle_skipped = False
                was_mirroring = False
                previous_dungeon = False
                tab_changed = False
                is_dark = False
                boss_just_killed = False
                await asyncio.sleep(0.1)
                continue

            previous_dungeon = data["dungeon"]
            highlight_dungeon_name(mainWindow, dungeon_ids[data["dungeon"]])

            if not tab_changed:
                tab_changed = True
                # mainWindow.notebook.select(doors_page)
                dungeon_page = get_named_page(
                    doors_nb,
                    mainWindow.pages,
                    dungeon_ids[data["dungeon"]],
                )
                doors_nb.select(dungeon_page)

            if data["transitioning"] != "00":
                was_transitioning = True
                await asyncio.sleep(0.1)
                continue

            # Both dying and falling can change supertile with no real doors
            if data["dead"] == "01":
                previous_tile = current_tile = None
                was_dead = True
                continue

            if data["falling"] != "00" and data["falling"] != "01":
                previous_tile = current_tile = None
                was_falling = True
                continue

            if not cycle_skipped and (was_transitioning or was_falling or was_dead):
                cycle_skipped = True
                continue

            cycle_skipped = False

            # TODO: Check doors to see if they're entrances and add lobbies?

            eg_tile = (
                int(data["dungeon_room"], 16) % 16,
                int(data["dungeon_room"], 16) // 16,
            )
            current_x_supertile = int(data["link_x"][2:], 16) // 2
            current_y_supertile = int(data["link_y"][2:], 16) // 2

            if eg_tile != (current_x_supertile, current_y_supertile):
                print(f"Supertile mismatch: {eg_tile} != {current_x_supertile}, {current_y_supertile}")
                continue

            dp_content = mainWindow.pages[dungeon_ids[data["dungeon"]]].content

            current_x_subtile = int(data["link_x"][2:], 16) % 2
            current_y_subtile = int(data["link_y"][2:], 16) % 2
            current_x = (current_x_subtile * 255) + int(data["link_x"][:2], 16)
            current_y = (current_y_subtile * 255) + int(data["link_y"][:2], 16)

            if eg_tile not in dp_content.tiles:
                dp_content.auto_add_tile(dp_content, eg_tile, was_lit=not is_dark)
            else:
                if not dp_content.tiles[eg_tile]["has_been_lit"] and not is_dark:
                    dp_content.tiles[eg_tile]["has_been_lit"] = True
                    dp_content.redraw_canvas(dp_content)

            if eg_tile not in dark_tiles or not is_dark:
                dp_content.auto_draw_player(dp_content, current_x, current_y, eg_tile)
            else:
                dp_content.canvas.delete("player")

            if (previous_tile != eg_tile and previous_tile == None) or (was_mirroring and data["mirror"] != "0f"):
                previous_tile = eg_tile
                current_tile = eg_tile
                if was_falling or was_dead:
                    was_falling = False
                    was_dead = False
                    continue
                # We just entered a new dungeon, add an entrance
                if eg_tile == (2, 1):
                    continue
                new_door = find_closest_door(
                    current_x,
                    current_y,
                    eg_tile,
                    data["layer"],
                    closest_distance=32 if was_mirroring else 128,
                )
                dp_content.auto_add_lobby(dp_content, new_door)
                was_mirroring = False

            elif (previous_tile != eg_tile and previous_tile != None) or was_transitioning:
                was_transitioning = False
                previous_tile = current_tile
                current_tile = eg_tile

                new_door = find_closest_door(current_x, current_y, eg_tile, data["layer"])
                try:
                    old_door = find_closest_door(previous_x, previous_y, previous_tile, previous_layer)
                except TypeError:
                    # We likely fell in a hole to a dungeon, so we don't have a previous door
                    continue
                if old_door == new_door:
                    continue
                dp_content.auto_add_door_link(dp_content, old_door, new_door)

            previous_x = current_x
            previous_y = current_y
            previous_layer = data["layer"]

            await asyncio.sleep(0.1)
        except grpc.aio.AioRpcError as e:
            mainWindow.wm_title(f"Jank Door Tracker - DISCONNECTED FROM SNI")
            print(e)
            break
        # except Exception as e:
        #     print(e)
        #     await asyncio.sleep(1)


def start_sni_tracking(mainWindow, args, forced_autotrack=False, device=None):
    sn_probe = asyncio.ensure_future(sni_probe(mainWindow, args=args, forced_autotrack=forced_autotrack, device=device))
    return sn_probe


def kill_sni_tracking(mainWindow):
    mainWindow.wm_title(f"Jank Door Tracker - Auto-tracking disabled")
    sn_probe = mainWindow.sni_task
    if sn_probe:
        sn_probe.cancel()


if __name__ == "__main__":
    logging.basicConfig()
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--size",
        choices=["small", "medium", "large"],
        default="medium",
        help="Set the window size",
    )
    parser.add_argument("--port", type=int, default=8191, help="SNI connection port")
    parser.add_argument("--debug", action="store_true", default=False, help="Enable debug logging")
    # parser.add_argument(
    #     "--darkpos",
    #     action="store_true",
    #     default=False,
    #     help="Show the players position in dark rooms even without a light source",
    # )
    parser.add_argument("--help", action="store_true", help="Show this help message and exit")
    parser.add_argument(
        "--no-autotrack",
        action="store_true",
        default=False,
        help="Don't automatically track doors (No SNI connection - Race Legal)",
    )
    # parser.add_argument('--no-warn', action='store_true', default=False, help="Don't show the warning message about the tracker being non-race legal")

    args, _ = parser.parse_known_args()
    if args.help:
        parser.print_help()
        sys.exit(0)

    mainWindow = Tk()
    mainWindow.wm_title("Jank Door Tracker")
    sc_width = mainWindow.winfo_screenwidth()
    sc_height = mainWindow.winfo_screenheight()
    window_size = window_sizes[args.size]
    window_size = (window_size[0] + MAIN_X_PAD, window_size[1] + MAIN_Y_PAD)
    mainWindow.geometry(
        f"{window_size[0]}x{window_size[1]}+{int(sc_width/2 - window_size[0]/2)}+{int(sc_height/2 - window_size[1]/2)}"
    )
    mainWindow.aspect_ratio = (1, 2)  # type: ignore
    mainWindow.size = args.size
    customizerGUI(mainWindow, args=args)

    tkmain = asyncio.ensure_future(tk_main(mainWindow))
    if not args.no_autotrack:
        sn_probe = start_sni_tracking(mainWindow, args)

    mainWindow.sni_task = sn_probe  # type: ignore

    loop = asyncio.get_event_loop()
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass

    tkmain.cancel()
    if not args.no_autotrack:
        sn_probe.cancel()  # type: ignore
