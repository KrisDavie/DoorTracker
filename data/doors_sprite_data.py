from pathlib import Path
from tkinter import Canvas, Toplevel, NW
from PIL import ImageTk, Image
from data.worlds_data import World

ITEM_SHEET_PATH = Path("data") / "Doors_Sheet.png"

BORDER_SIZE = 20
TILE_BORDER_SIZE = 3


def show_sprites(self, top, parent_event, world):
    def select_sprite(parent, self, event):
        item = self.canvas.find_closest(event.x, event.y)
        if item not in [(x,) for x in self.items.values()]:
            return
        item_name = get_sprite_by_button(self, item)

        sprite_window.selected_item = item_name
        self.destroy()

    def get_sprite_by_button(self, button):
        for name, loc in self.items.items():
            if loc == button[0]:
                return name

    sprite_window = Toplevel(self)
    w = top.winfo_x()
    h = top.winfo_y()
    x = max(0, min(w + parent_event.x - 288, self.winfo_screenwidth() - 288))
    y = max(0, min(h + parent_event.y - 288, self.winfo_screenheight() - 288))
    sprite_window.geometry(f"{288 + (BORDER_SIZE * 2)}x{288 + (BORDER_SIZE * 2)}+{int(x)}+{int(y)}")
    sprite_window.title("Sprites Window")
    sprite_window.focus_set()
    sprite_window.grab_set()

    sprite_window.canvas = Canvas(
        sprite_window, width=288 + (BORDER_SIZE * 2), height=288 + (BORDER_SIZE * 2), background="black"
    )
    sprite_window.canvas.pack()
    sprite_window.spritesheet = ImageTk.PhotoImage(Image.open(ITEM_SHEET_PATH).resize((288, 288)))
    sprite_window.image = sprite_window.canvas.create_image(
        0 + BORDER_SIZE, 0 + BORDER_SIZE, anchor=NW, image=sprite_window.spritesheet
    )
    sprite_window.items = {}
    for item, coords in all_icons.items():
        if (item not in item_table and item not in dungeon_lobbies[world]) or item == "Sanctuary_Mirror":
            disabled = True
        else:
            disabled = False

        y, x = coords
        item_selector = sprite_window.canvas.create_rectangle(
            x * 32 + BORDER_SIZE,
            y * 32 + BORDER_SIZE,
            x * 32 + 33 + BORDER_SIZE,
            y * 32 + 33 + BORDER_SIZE,
            outline="",
            fill="#888" if disabled else "",
            stipple="gray50" if disabled else "",
            state="disabled" if disabled else "normal",
        )
        sprite_window.items[item] = item_selector
        sprite_window.canvas.tag_bind(
            item_selector,
            "<Button-1>",
            lambda event: select_sprite(self, sprite_window, event),
        )
    sprite_window.wait_window(sprite_window)
    sprite_window.grab_release()
    if not hasattr(sprite_window, "selected_item"):
        return
    return sprite_window.selected_item


item_table = {
    "Bomb Door": (0, 0),
    "Slash Door": (0, 1),
    "Dash Door": (0, 2),
    "Key Door": (0, 3),
    "Big Key Door": (0, 4),
    "Trap Door": (0, 5),
    "Somaria": (1, 0),
    "Lamp": (1, 1),
    "Hammer": (1, 2),
    "Flippers": (1, 3),
    "Hookshot": (1, 4),
    "Sanctuary_Mirror": (8, 5),
    "Drop": (7, 5)
}

dungeon_lobbies = {
   World.HyruleCastle: {
    'Hyrule Castle East': (3, 0),
    'Hyrule Castle South': (3, 1),
    'Hyrule Castle West': (3, 2),
    'Sanctuary': (3, 3),
   },
   World.EasternPalace: {
    'Eastern': (3, 4),
   },
   World.DesertPalace: {
    'Desert Back': (4, 0),
    'Desert East': (4, 1),
    'Desert South': (4, 2),
    'Desert West': (4, 3),
   },
   World.TowerOfHera: {
    'Hera': (4, 4),
   },
   World.CastleTower: {
    'Agahnims Tower': (5, 0),
   },
   World.PalaceOfDarkness: {
    'Palace of Darkness': (5, 1),
   },
   World.SwampPalace: {
    'Swamp': (5, 2),
   },
   World.SkullWoods: {
    'Skull 3': (6, 0),
    'Skull 2 East': (6, 1),
    'Skull 1': (6, 2),
    'Skull 2 West': (6, 3),
   },
   World.ThievesTown: {
    'Thieves Town': (7, 0),
   },
   World.IcePalace: {
    'Ice': (7, 1),
   },
   World.MiseryMire: {
    'Mire': (7, 2),
   },
   World.TurtleRock: {
    'Turtle Rock Main': (8, 0),
    'Turtle Rock Chest': (8, 1),
    'Turtle Rock Eye Bridge': (8, 2),
    'Turtle Rock Lazy Eyes': (8, 3),
   },
   World.GanonsTower: {
    'Ganons Tower': (8, 4),
   },
}
# Flatten the dictionary
all_dungeon_lobbies = {k: v for d in dungeon_lobbies.values() for k, v in d.items()}
all_icons = {**item_table, **all_dungeon_lobbies}
