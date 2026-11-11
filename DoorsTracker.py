import argparse
import asyncio
from pathlib import Path
import sys
from tkinter import BooleanVar, Menu, Tk, TOP, BOTH, Toplevel, ttk, filedialog
from PIL import Image
import logging
from gui.Doors.overview import door_customizer_page
from gui.Doors.graph_view import GraphDoorPage
from SpoilerToYaml import parse_dr_spoiler
from data.worlds_data import dungeon_worlds
from data.doors_data import eg_tile_multiuse
from sni_tracker import sni_probe
from data.vanilla_data import vanilla_layout_optimized, vanilla_layout_original

import os
import yaml

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

    def load_yaml(self, file=None):
        if file is None:
            file = filedialog.askopenfilename(
                filetypes=[("Yaml Files", (".yaml", ".yml")), ("All Files", "*")],
                initialdir=os.path.join("."),
            )
        if not file:
            return
        with open(file, mode="r") as fh:
            try:
                yaml_data = yaml.safe_load(fh)
            except Exception as e:
                # try:
                yaml_data = parse_dr_spoiler(fh)
                # except Exception as e2:
                #     print(f"Error loading yaml. {e2}")
                #     return
            if 'Agahnims_Tower' in yaml_data:
                yaml_data['Castle_Tower'] = yaml_data['Agahnims_Tower']
                del yaml_data['Agahnims_Tower']
            for dungeon, dungeon_data in yaml_data.items():
                self.pages[dungeon].content.load_yaml(dungeon_data)

    self.load_tracker_file = lambda file: load_yaml(self, file)

    def save_yaml(self, save=True):
        yaml_data = {}

        for dungeon in self.pages:
            doors_data = self.pages[dungeon].content.return_connections()
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
        "vanilla_drops": True,
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
        self.pages[dungeon].content = GraphDoorPage(  # type: ignore
            self,
            self.pages[dungeon],  # type: ignore
            world,
            eg_img=eg_img,
            cdims=window_size,
        )
        self.pages[dungeon].content.pack(side=TOP, fill=BOTH, expand=True)  # type: ignore

    self.notebook.pack(fill=BOTH, expand=True)  # type: ignore

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
    # On by default, so the menu entry has to start ticked
    self.vanilla_drops_var = BooleanVar(value=self.experimental_flags["vanilla_drops"])
    experimentalMenu.add_checkbutton(
        label="Drops Are Not Shuffled",
        variable=self.vanilla_drops_var,
        command=lambda: set_experimental_flag(self, "vanilla_drops"),
    )

    self.eg_tile_window.withdraw()

    def close_window():
        self.eg_tile_window.destroy()
        self.destroy()

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
            content.init_page()
            content.redraw_canvas()
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
        content.redraw_canvas()


def show_all_doors(self, menu):
    self.show_all_doors = not self.show_all_doors
    if self.show_all_doors:
        menu.entryconfig(4, label="Show Reachable Doors")
    else:
        menu.entryconfig(4, label="Show All Doors")
    for world in self.pages:
        content = self.pages[world].content
        content.show_all_doors = self.show_all_doors
        content.redraw_canvas()


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
        self.pages[world].content.update_size((new_width, new_height))
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
        self.pages[world].content.update_size((new_width, new_height))
    self.geometry(
        f"{new_width + MAIN_X_PAD}x{new_height + MAIN_Y_PAD}+{int(sc_width/2 - new_width/2)}+{int(sc_height/2 - new_height/2)}"
    )


def set_experimental_flag(self, flag: str):
    self.experimental_flags[flag] = not self.experimental_flags[flag]
    for world in self.pages:
        self.pages[world].content.experimental_flags = self.experimental_flags
        self.pages[world].content.redraw_canvas()
        self.eg_tile_window.pages[world].content.experimental_flags = self.experimental_flags
        self.eg_tile_window.pages[world].content.draw_vanilla_eg_map(self.eg_tile_window.pages[world].content)


def pump_asyncio(root, loop, interval_ms=10):
    """Give asyncio (the SNI polling) a turn, then hand control straight back to Tk.

    Tk owns the main loop so the window redraws as fast as the display allows. Running it the other
    way round, with asyncio calling root.update() between sleeps, capped the whole UI at 20 fps.
    """
    loop.call_soon(loop.stop)
    loop.run_forever()
    root.after(interval_ms, pump_asyncio, root, loop, interval_ms)


class TkTrackerUI:
    """What the shared tracking loop (sni_tracker.py) needs from the window, for the Tk window."""

    def __init__(self, window):
        self.window = window
        self.pages = {name: frame.content for name, frame in window.pages.items()}

    @property
    def device(self):
        return getattr(self.window, "device", None)

    @device.setter
    def device(self, value):
        self.window.device = value

    def set_title(self, text):
        self.window.wm_title(text)

    def set_devices(self, uris):
        menu = self.window.devicesMenu
        menu.delete(0, "end")
        for uri in uris:
            menu.add_radiobutton(label=uri, command=lambda device=uri: reconnect(self.window, device=device))

    def race_rom_warning(self):
        race_rom_warning(self.window)

    def highlight_dungeon(self, name):
        notebook = self.window.notebook
        for page in self.window.pages.values():
            notebook.tab(page, underline=-1)
        if name is not None:
            notebook.tab(self.window.pages[name], underline=0)

    def select_dungeon(self, name):
        self.window.notebook.select(self.window.pages[name])


def start_sni_tracking(mainWindow, args, forced_autotrack=False, device=None):
    sn_probe = asyncio.ensure_future(
        sni_probe(TkTrackerUI(mainWindow), args=args, forced_autotrack=forced_autotrack, device=device)
    )
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
    parser.add_argument(
        "tracker_file", nargs="?", default=None, help="Tracker data (yaml) or spoiler to load on startup"
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
    if args.tracker_file:
        mainWindow.load_tracker_file(args.tracker_file)  # type: ignore

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    sn_probe = None
    if not args.no_autotrack:
        sn_probe = start_sni_tracking(mainWindow, args)

    mainWindow.sni_task = sn_probe  # type: ignore

    pump_asyncio(mainWindow, loop)
    try:
        mainWindow.mainloop()
    except KeyboardInterrupt:
        pass

    if sn_probe:
        sn_probe.cancel()  # type: ignore
