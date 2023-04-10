from enum import Enum
import math
from tkinter import Toplevel, ttk, NW, Canvas
from PIL import ImageTk, Image, ImageOps, ImageDraw
import data.item_sprite_data as item_sprite_data
from data.worlds_data import worlds_data
from data.new_location_data import supertile_overrides

from pathlib import Path


class SelectState(Enum):
    NoneSelected = 0
    SourceSelected = 1


BORDER_SIZE = 20

item_sheet_path = Path("data") / "Item_Sheet.png"

def item_customizer_page(top, parent, tab_world, tab_item_type="standard", eg_img=None, cdims=(1548, 768)):
    def load_yaml(self, yaml_data):
        for loc_name, placed_item in yaml_data.items():
            if loc_name not in worlds_data[tab_world][f"locations_{tab_item_type}"] or not show_item_on_tab(
                tab_item_type, worlds_data[tab_world][f"locations_{tab_item_type}"][loc_name]
            ):
                continue
            item = worlds_data[tab_world][f"locations_{tab_item_type}"][loc_name]["button"]
            if placed_item == "Nothing":
                continue
            if placed_item.startswith("Crystal"):
                crystal_num = int(placed_item[-1])
                if crystal_num in [5, 6]:
                    placed_item = "Red Crystal"
                else:
                    placed_item = "Crystal"
            if loc_name not in self.placed_items:
                self.placed_items[loc_name] = {"name": placed_item, "sprite": None}
            place_item(self, item, placed_item, loc_name)

    def display_world_locations(self):
        objects = self.canvas.find_all()
        for name, loc in worlds_data[tab_world][f"locations_{tab_item_type}"].items():
            if "target" in loc:
                fill_col = "blue"
            else:
                fill_col = "#0f0"
            if "button" not in loc or loc["button"] not in objects:
                location_oval = self.canvas.create_oval(
                    loc["x"] + BORDER_SIZE - 5,
                    loc["y"] + BORDER_SIZE - 5,
                    loc["x"] + BORDER_SIZE + 5,
                    loc["y"] + BORDER_SIZE + 5,
                    fill=fill_col,
                )
                worlds_data[tab_world][f"locations_{tab_item_type}"][name]["button"] = location_oval
            else:
                location_oval = loc["button"]
                self.canvas.itemconfigure((location_oval,), state="normal")
            self.canvas.tag_bind(
                location_oval,
                "<Button-1>",
                lambda event: select_location(self, event),
            )

    def get_loc_by_button(self, button):
        for name, loc in worlds_data[tab_world][f"locations_{tab_item_type}"].items():
            if loc["button"] == button[0]:
                return name
        for name, data in self.placed_items.items():
            if data["image"] == button[0]:
                return name

    def place_item(self, item, placed_item, loc_name):
        self.canvas.itemconfigure(item, state="hidden")

        # Place a new sprite
        try:
            sprite_y, sprite_x = item_sprite_data.item_table[placed_item]
        except KeyError:
            print(f"Error: {placed_item} not found in item table")
            return
        self.placed_items[loc_name]["sprite"] = ImageTk.PhotoImage(
            ImageOps.expand(
                Image.open(item_sheet_path).crop(
                    (sprite_x * 16, sprite_y * 16, sprite_x * 16 + 16, sprite_y * 16 + 16)
                ),
                1,
                "#fff",
            )
        )
        self.placed_items[loc_name]["image"] = self.canvas.create_image(
            worlds_data[tab_world][f"locations_{tab_item_type}"][loc_name]["x"] + BORDER_SIZE,
            worlds_data[tab_world][f"locations_{tab_item_type}"][loc_name]["y"] + BORDER_SIZE,
            image=self.placed_items[loc_name]["sprite"],
        )
        self.canvas.tag_bind(
            self.placed_items[loc_name]["image"],
            "<Button-3>",
            lambda event: remove_item(self, event),
        )

    def select_location(self, event):
        item = self.canvas.find_closest(event.x, event.y)

        # Catch when the user clicks on the world rather than a location
        if item in worlds_data[tab_world]["canvas_image"]:
            return
        # Get the location name from the button
        loc_name = get_loc_by_button(self, item)
        self.currently_selected = loc_name
        self.canvas.itemconfigure(item, fill="orange", state="disabled")

        # Show the sprite sheet
        selected_item = item_sprite_data.show_sprites(self, top, event, prize=True if "Prize" in loc_name else False)
        if selected_item is not None:
            self.placed_items[self.currently_selected] = {"name": selected_item, "sprite": None}

        # Hide the circle
        if loc_name not in self.placed_items:
            self.canvas.itemconfigure(item, fill="#0f0", state="normal")
            return
        placed_item = self.placed_items[loc_name]["name"]
        place_item(self, item, placed_item, loc_name)

    def remove_item(self, event):
        item = self.canvas.find_closest(event.x, event.y)
        if item in [w["canvas_image"] for w in worlds_data.values()]:
            return
        loc_name = get_loc_by_button(self, item)
        self.canvas.itemconfigure(item, state="hidden")
        loc_ref = worlds_data[tab_world][f"locations_{tab_item_type}"][loc_name]["button"]
        self.canvas.itemconfigure((loc_ref,), state="normal", fill="#0f0")
        del self.placed_items[loc_name]["image"]
        del self.placed_items[loc_name]["sprite"]
        self.placed_items[loc_name]["image"] = None
        self.placed_items[loc_name]["sprite"] = None
        del self.placed_items[loc_name]

    def return_placements(placed_items):
        final_placements = {}
        cystals_placed = 0
        red_crystals_placed = 0
        for loc_name, item_data in placed_items.items():
            if item_data["name"] == "Crystal":
                cystals_placed += 1
                final_placements[loc_name] = f"Crystal {cystals_placed}"
            elif item_data["name"] == "Red Crystal":
                red_crystals_placed += 1
                final_placements[loc_name] = f"Crystal {red_crystals_placed + 5}"
            else:
                final_placements[loc_name] = item_data["name"]

        return final_placements

    def show_item_on_tab(tab_item_type, item_data):
        return (tab_item_type == "standard" and item_data["loc_type"] != "pot") or (
            tab_item_type == "pot" and item_data["loc_type"] == "pot"
        )

    def add_item_to_world(item, item_data, scaling_factor, canvas_x, canvas_y, tile_size, adjust_x=0, adjust_y=0):
        worlds_data[tab_world][f"locations_{tab_item_type}"][item] = {
            "x": (item_data["x"] + adjust_x) * scaling_factor + canvas_x * tile_size,
            "y": (item_data["y"] + adjust_y) * scaling_factor + canvas_y * tile_size,
            "loc_type": item_data["loc_type"],
        }

    # Custom Item Pool
    self = ttk.Frame(parent)
    self.cwidth = cdims[0]
    self.cheight = cdims[1]
    self.select_state = SelectState.NoneSelected
    self.placed_items = {}
    self.canvas = Canvas(self, width=self.cwidth + (BORDER_SIZE * 2), height=self.cheight + (BORDER_SIZE * 2))
    self.canvas.pack()

    # Load in the world images
    if worlds_data[tab_world]["map_file"] != None:
        worlds_data[tab_world]["map_image"] = ImageTk.PhotoImage(Image.open(worlds_data[tab_world]["map_file"]).resize((self.cwidth, self.cheight), Image.ANTIALIAS))
        worlds_data[tab_world]["canvas_image"] = (
            self.canvas.create_image(BORDER_SIZE, BORDER_SIZE, anchor=NW, image=worlds_data[tab_world]["map_image"]),
        )
        worlds_data[tab_world][f"locations_{tab_item_type}"] = worlds_data[tab_world][f"locations"].copy()
        if self.cwidth != 1024:
            scale = self.cwidth / 2 / 512
        else :
            scale = 1
        for name, loc in worlds_data[tab_world][f"locations_{tab_item_type}"].items():
            worlds_data[tab_world][f"locations_{tab_item_type}"][name]["x"] *= 2 * scale
            worlds_data[tab_world][f"locations_{tab_item_type}"][name]["y"] *= 2 * scale

    elif worlds_data[tab_world]["map_file"] == None and "supertile_locs" in worlds_data[tab_world]:
        # If there is no image, we'll build the map dynamically here - this is long...

        # Update these to support holding onto many images and different item types
        if type(worlds_data[tab_world]["canvas_image"]) != list:
            worlds_data[tab_world]["canvas_image"] = []
        all_locs = worlds_data[tab_world]["locations"].copy()
        worlds_data[tab_world][f"locations_{tab_item_type}"] = {}
        if type(worlds_data[tab_world]["map_image"]) != list:
            worlds_data[tab_world]["map_image"] = []

        standard_types = set(["chest", "key_pot", "drop", "prize"])
        current_tab_supertiles = worlds_data[tab_world]["supertile_locs"].copy()

        # For each supertile, do we have at least one of the correct type?
        # If not remove the supertile from the list of locs and the map
        for st in current_tab_supertiles.copy():
            items = all_locs[st]
            item_types = [x["loc_type"] for _, x in items.items()]
            if (tab_item_type == "pot" and "pot" not in item_types) or (
                tab_item_type == "standard" and len(set(item_types).intersection(standard_types)) == 0
            ):
                current_tab_supertiles.pop(current_tab_supertiles.index(st))
                # del all_locs[st]  # I don't think this is necessary TODO: Check

        cropped_tiles_data = {}
        h_tiles = 0
        v_tiles = 0
        s_tiles = 0
        f_tiles = 0

        for tile_no, tile in enumerate(current_tab_supertiles):
            tile_x, tile_y = tile

            ############## METHOD 1 - Only relevant tiles ##############
            # We crop each supertile to a 1x1, 1x2, 2x1 or 2x2 image and adjust each item position to match the new image origin being at 0,0
            base_tile_img = eg_img.crop((tile_x * 512, tile_y * 512, tile_x * 512 + 512, tile_y * 512 + 512))
            items_present = {}
            for item, item_data in all_locs[tile].items():
                if not show_item_on_tab(tab_item_type, item_data):
                    continue
                items_present[item] = item_data.copy()

                # Add extra copies of the item around it, to keep tiles where items are on the boundary of quadrants
                for x_adjust in [-32, 0, 32]:
                    for y_adjust in [-32, 0, 32]:
                        items_present[f"{item}_adj_{x_adjust}_{y_adjust}"] = item_data.copy()
                        items_present[f"{item}_adj_{x_adjust}_{y_adjust}"]["x"] += x_adjust
                        items_present[f"{item}_adj_{x_adjust}_{y_adjust}"]["y"] += y_adjust

            # See which quadrants contain items
            if tile not in supertile_overrides:
                quadrants_present = set()
                for quadrant in [(0, 0), (0, 1), (1, 0), (1, 1)]:
                    for item, item_data in items_present.items():
                        if (
                            item_data["x"] >= quadrant[0] * 256
                            and item_data["x"] < (quadrant[0] + 1) * 256
                            and item_data["y"] >= quadrant[1] * 256
                            and item_data["y"] < (quadrant[1] + 1) * 256
                        ):
                            quadrants_present.add(quadrant)
            else:
                quadrants_present = supertile_overrides[tile]

            # Remove those extra items we added
            items_present = {k: v for k, v in items_present.items() if "_adj_" not in k}

            # Check if we only have a single or pair of touching subtiles
            if (
                len(quadrants_present) < 3
                and quadrants_present != {(0, 0), (1, 1)}
                and quadrants_present != {(1, 0), (0, 1)}
            ):
                # Reset origin on map and items to 0, 0
                min_x = min([x[0] for x in quadrants_present])
                min_y = min([x[1] for x in quadrants_present])
                max_x = max([x[0] for x in quadrants_present])
                max_y = max([x[1] for x in quadrants_present])
                x1 = min_x * 256
                y1 = min_y * 256
                x2 = (max_x + 1) * 256
                y2 = (max_y + 1) * 256
                base_tile_img = base_tile_img.crop((x1, y1, x2, y2))
                # ImageDraw.Draw(base_tile_img).line(((x1, y1), (x1, y2), (x2, y2), (x2, y1), (x1, y1)), fill='#f0f0f0', width=3)

                for item, item_data in items_present.items():
                    item_data["x"] -= x1
                    item_data["y"] -= y1

                if len(quadrants_present) == 1:
                    quadrants_present = [(0, 0)]
                    tile_type = "single"
                    s_tiles += 1
                elif quadrants_present == {(1, 0), (1, 1)} or quadrants_present == {(0, 0), (0, 1)}:
                    quadrants_present = [(0, 0), (0, 1)]
                    tile_type = "vertical"
                    v_tiles += 1
                elif quadrants_present == {(0, 1), (1, 1)} or quadrants_present == {(0, 0), (1, 0)}:
                    quadrants_present = [(0, 0), (1, 0)]
                    tile_type = "horizontal"
                    h_tiles += 1
                else:
                    print(
                        f"Something went terrible wrong here: {tab_world} - {tab_item_type} ({tile}: {quadrants_present})"
                    )
            else:
                tile_type = "full"
                f_tiles += 1

            cropped_tiles_data[tile] = {
                "items": items_present,
                "quadrants": quadrants_present,
                "image": base_tile_img,
                "tile_type": tile_type,
            }

        all_quadrants = []
        all_cropped_tiles = []

        for _, cropped_tile_data in cropped_tiles_data.items():
            all_cropped_tiles.append(cropped_tile_data["quadrants"])
            for quadrant in cropped_tile_data["quadrants"]:
                all_quadrants.append(quadrant)

        world_size = math.ceil(len(all_quadrants) / 4)
        for i in range(world_size + 1):
            if i * (i * 2) >= world_size:
                rows = i
                cols = i * 2
                total_tiles = rows * cols
                tile_size = int((self.cwidth / 2) / rows)
                scaling_factor = tile_size / 512
                break
        supertiles_img = Image.new("RGBA", (cols * tile_size, rows * tile_size))

        tile_no = 0
        for tile, tile_data in cropped_tiles_data.copy().items():
            if tile_data["tile_type"] == "full":
                canvas_x = tile_no % cols
                canvas_y = tile_no // cols
                for item, item_data in cropped_tiles_data[tile]["items"].items():
                    add_item_to_world(item, item_data, scaling_factor, canvas_x, canvas_y, tile_size)

                new_tile_img = cropped_tiles_data[tile]["image"].resize((tile_size, tile_size))
                supertiles_img.paste(
                    new_tile_img,
                    (
                        canvas_x * tile_size,
                        canvas_y * tile_size,
                    ),
                )
                del cropped_tiles_data[tile]
                tile_no += 1

        while h_tiles > 1:
            tile_1 = None
            for tile, tile_data in cropped_tiles_data.copy().items():
                if tile_data["tile_type"] == "horizontal" and tile_1 == None:
                    tile_1 = tile
                    continue
                if tile_data["tile_type"] == "horizontal" and tile_1 != None:
                    canvas_x = tile_no % cols
                    canvas_y = tile_no // cols

                    # Combine the two tiles images and items
                    for item, item_data in cropped_tiles_data[tile]["items"].items():
                        add_item_to_world(item, item_data, scaling_factor, canvas_x, canvas_y, tile_size, adjust_y=256)

                    for item, item_data in cropped_tiles_data[tile_1]["items"].items():
                        add_item_to_world(item, item_data, scaling_factor, canvas_x, canvas_y, tile_size)

                    # paste the two tiles together
                    new_tile_img = cropped_tiles_data[tile_1]["image"].crop((0, 0, 512, 512))
                    new_tile_img.paste(cropped_tiles_data[tile]["image"], (0, 256))

                    ImageDraw.Draw(new_tile_img).line(((0, 256), (512, 256)), fill="#f0f0f0", width=3)
                    new_tile_img = new_tile_img.resize((tile_size, tile_size))

                    # Add the new tile to the supertile image
                    supertiles_img.paste(
                        new_tile_img,
                        (
                            canvas_x * tile_size,
                            canvas_y * tile_size,
                        ),
                    )
                    h_tiles -= 2
                    tile_no += 1
                    del cropped_tiles_data[tile]
                    del cropped_tiles_data[tile_1]
                    tile_1 = None

        while v_tiles > 1:
            tile_1 = None
            for tile, tile_data in cropped_tiles_data.copy().items():
                if tile_data["tile_type"] == "vertical" and tile_1 == None:
                    tile_1 = tile
                    continue
                if tile_data["tile_type"] == "vertical" and tile_1 != None:
                    canvas_x = tile_no % cols
                    canvas_y = tile_no // cols
                    # Combine the two tiles images and items

                    for item, item_data in cropped_tiles_data[tile]["items"].items():
                        add_item_to_world(item, item_data, scaling_factor, canvas_x, canvas_y, tile_size, adjust_x=256)

                    for item, item_data in cropped_tiles_data[tile_1]["items"].items():
                        add_item_to_world(item, item_data, scaling_factor, canvas_x, canvas_y, tile_size)

                    # paste the two tiles together
                    new_tile_img = cropped_tiles_data[tile_1]["image"].crop((0, 0, 512, 512))
                    new_tile_img.paste(cropped_tiles_data[tile]["image"], (256, 0))
                    ImageDraw.Draw(new_tile_img).line(((256, 0), (256, 512)), fill="#f0f0f0", width=3)

                    new_tile_img = new_tile_img.resize((tile_size, tile_size))

                    # Add the new tile to the supertile image
                    supertiles_img.paste(
                        new_tile_img,
                        (
                            canvas_x * tile_size,
                            canvas_y * tile_size,
                        ),
                    )
                    v_tiles -= 2
                    tile_no += 1
                    del cropped_tiles_data[tile]
                    del cropped_tiles_data[tile_1]
                    tile_1 = None

        # Clean up any remaining horizontal tiles
        if h_tiles == 1 and s_tiles >= 1:
            h_tile = [
                tile for tile, tile_data in cropped_tiles_data.copy().items() if tile_data["tile_type"] == "horizontal"
            ][0]

            single_tiles = [
                tile for tile, tile_data in cropped_tiles_data.copy().items() if tile_data["tile_type"] == "single"
            ]
            s_tile1 = single_tiles[0]
            if s_tiles > 1:
                s_tile2 = single_tiles[1]
            else:
                s_tile2 = None

            canvas_x = tile_no % cols
            canvas_y = tile_no // cols

            for item, item_data in cropped_tiles_data[h_tile]["items"].items():
                add_item_to_world(item, item_data, scaling_factor, canvas_x, canvas_y, tile_size)
            for item, item_data in cropped_tiles_data[s_tile1]["items"].items():
                add_item_to_world(item, item_data, scaling_factor, canvas_x, canvas_y, tile_size, adjust_y=256)
            if s_tile2 != None:
                for item, item_data in cropped_tiles_data[s_tile2]["items"].items():
                    add_item_to_world(
                        item, item_data, scaling_factor, canvas_x, canvas_y, tile_size, adjust_y=256, adjust_x=256
                    )

            new_tile_img = cropped_tiles_data[h_tile]["image"].crop((0, 0, 512, 512))
            new_tile_img.paste(cropped_tiles_data[s_tile1]["image"], (0, 256))

            if s_tile2 != None:
                new_tile_img.paste(cropped_tiles_data[s_tile2]["image"], (256, 256))

            ImageDraw.Draw(new_tile_img).line(((0, 256), (512, 256)), fill="#f0f0f0", width=3)
            ImageDraw.Draw(new_tile_img).line(((256, 256), (256, 512)), fill="#f0f0f0", width=3)

            new_tile_img = new_tile_img.resize((tile_size, tile_size))

            supertiles_img.paste(
                new_tile_img,
                (
                    canvas_x * tile_size,
                    canvas_y * tile_size,
                ),
            )
            h_tiles -= 1
            s_tiles -= 1 if s_tile2 == None else 2
            tile_no += 1
            del cropped_tiles_data[h_tile]
            del cropped_tiles_data[s_tile1]
            if s_tile2 != None:
                del cropped_tiles_data[s_tile2]

        # Clean up any remaining vertical tiles
        if v_tiles == 1 and s_tiles >= 1:
            v_tile = [
                tile for tile, tile_data in cropped_tiles_data.copy().items() if tile_data["tile_type"] == "vertical"
            ][0]

            single_tiles = [
                tile for tile, tile_data in cropped_tiles_data.copy().items() if tile_data["tile_type"] == "single"
            ]
            s_tile1 = single_tiles[0]
            if s_tiles > 1:
                s_tile2 = single_tiles[1]
            else:
                s_tile2 = None

            canvas_x = tile_no % cols
            canvas_y = tile_no // cols

            for item, item_data in cropped_tiles_data[v_tile]["items"].items():
                add_item_to_world(item, item_data, scaling_factor, canvas_x, canvas_y, tile_size)
            for item, item_data in cropped_tiles_data[s_tile1]["items"].items():
                add_item_to_world(item, item_data, scaling_factor, canvas_x, canvas_y, tile_size, adjust_x=256)
            if s_tile2 != None:
                for item, item_data in cropped_tiles_data[s_tile2]["items"].items():
                    add_item_to_world(
                        item, item_data, scaling_factor, canvas_x, canvas_y, tile_size, adjust_y=256, adjust_x=256
                    )

            new_tile_img = cropped_tiles_data[v_tile]["image"].crop((0, 0, 512, 512))
            new_tile_img.paste(cropped_tiles_data[s_tile1]["image"], (256, 0))
            if s_tile2 != None:
                new_tile_img.paste(cropped_tiles_data[s_tile2]["image"], (256, 256))

            ImageDraw.Draw(new_tile_img).line(((256, 0), (256, 512)), fill="#f0f0f0", width=3)
            ImageDraw.Draw(new_tile_img).line(((256, 256), (512, 256)), fill="#f0f0f0", width=3)
            new_tile_img = new_tile_img.resize((tile_size, tile_size))

            supertiles_img.paste(
                new_tile_img,
                (
                    canvas_x * tile_size,
                    canvas_y * tile_size,
                ),
            )
            v_tiles -= 1
            s_tiles -= 1 if s_tile2 == None else 2
            tile_no += 1
            del cropped_tiles_data[v_tile]
            del cropped_tiles_data[s_tile1]
            if s_tile2 != None:
                del cropped_tiles_data[s_tile2]

        # Finally combine any remaining single tiles
        while s_tiles > 0:
            single_tiles = [
                tile for tile, tile_data in cropped_tiles_data.copy().items() if tile_data["tile_type"] == "single"
            ]
            s_tile1 = single_tiles[0]
            if s_tiles == 1:
                s_tile2, s_tile3, s_tile4 = None, None, None
            elif s_tiles == 2:
                s_tile2 = single_tiles[1]
                s_tile3, s_tile4 = None, None
            elif s_tiles == 3:
                s_tile2, s_tile3 = single_tiles[1:3]
                s_tile4 = None
            else:
                s_tile2, s_tile3, s_tile4 = single_tiles[1:4]
            canvas_x = tile_no % cols
            canvas_y = tile_no // cols

            for item, item_data in cropped_tiles_data[s_tile1]["items"].items():
                add_item_to_world(item, item_data, scaling_factor, canvas_x, canvas_y, tile_size)
            if s_tile2 != None:
                for item, item_data in cropped_tiles_data[s_tile2]["items"].items():
                    add_item_to_world(item, item_data, scaling_factor, canvas_x, canvas_y, tile_size, adjust_x=256)
            if s_tile3 != None:
                for item, item_data in cropped_tiles_data[s_tile3]["items"].items():
                    add_item_to_world(item, item_data, scaling_factor, canvas_x, canvas_y, tile_size, adjust_y=256)
            if s_tile4 != None:
                for item, item_data in cropped_tiles_data[s_tile4]["items"].items():
                    add_item_to_world(
                        item, item_data, scaling_factor, canvas_x, canvas_y, tile_size, adjust_y=256, adjust_x=256
                    )

            new_tile_img = cropped_tiles_data[s_tile1]["image"].crop((0, 0, 512, 512))
            if s_tile2 != None:
                new_tile_img.paste(cropped_tiles_data[s_tile2]["image"], (256, 0))
            if s_tile3 != None:
                new_tile_img.paste(cropped_tiles_data[s_tile3]["image"], (0, 256))
            if s_tile4 != None:
                new_tile_img.paste(cropped_tiles_data[s_tile4]["image"], (256, 256))

            ImageDraw.Draw(new_tile_img).line(((256, 0), (256, 512)), fill="#f0f0f0", width=3)
            ImageDraw.Draw(new_tile_img).line(((0, 256), (512, 256)), fill="#f0f0f0", width=3)
            new_tile_img = new_tile_img.resize((tile_size, tile_size))

            supertiles_img.paste(
                new_tile_img,
                (
                    canvas_x * tile_size,
                    canvas_y * tile_size,
                ),
            )
            s_tiles -= 4
            tile_no += 1
            del cropped_tiles_data[s_tile1]
            if s_tile2 != None:
                del cropped_tiles_data[s_tile2]
            if s_tile3 != None:
                del cropped_tiles_data[s_tile3]
            if s_tile4 != None:
                del cropped_tiles_data[s_tile4]
            s_tile1, s_tile2, s_tile3, s_tile4 = None, None, None, None

        for i in range(cols + 1):
            ImageDraw.Draw(supertiles_img).line(
                ((tile_size * i, 0), (tile_size * i, tile_size * rows)), fill="#f0f0f0", width=3
            )
        for i in range(rows + 1):
            ImageDraw.Draw(supertiles_img).line(
                ((0, tile_size * i), (tile_size * cols, tile_size * i)), fill="#f0f0f0", width=3
            )

        tile_img = ImageTk.PhotoImage(supertiles_img)
        worlds_data[tab_world]["map_image"].append(tile_img)
        worlds_data[tab_world]["canvas_image"].append(
            self.canvas.create_image(BORDER_SIZE, BORDER_SIZE, anchor=NW, image=tile_img)
        )

    display_world_locations(self)

    self.load_yaml = load_yaml
    self.return_placements = return_placements

    # TODO: Add a new button to store this info somwhere as JSON for the generation
    return self
