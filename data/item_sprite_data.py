from pathlib import Path
from tkinter import Canvas, Toplevel, NW
from PIL import ImageTk, Image

ITEM_SHEET_PATH = Path(__file__).parent / "Item_Sheet.png"

BORDER_SIZE = 20
TILE_BORDER_SIZE = 3


def show_sprites(self, top, parent_event, prize=False):
    prize_names = [
        "Green Pendant",
        "Red Pendant",
        "Blue Pendant",
        "Crystal",
        "Red Crystal",
    ]

    def select_sprite(parent, self, event):
        item = self.canvas.find_closest(event.x, event.y)
        print(item)
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
    x = max(0, min(w + parent_event.x - 544, self.winfo_screenwidth() - 544))
    y = max(0, min(h + parent_event.y - 288, self.winfo_screenheight() - 288))
    sprite_window.geometry(f"{544 + (BORDER_SIZE * 2)}x{288 + (BORDER_SIZE * 2)}+{int(x)}+{int(y)}")
    sprite_window.title("Sprites Window")
    sprite_window.focus_set()
    sprite_window.grab_set()

    sprite_window.canvas = Canvas(
        sprite_window, width=544 + (BORDER_SIZE * 2), height=288 + (BORDER_SIZE * 2), background="black"
    )
    sprite_window.canvas.pack()
    sprite_window.spritesheet = ImageTk.PhotoImage(Image.open(ITEM_SHEET_PATH).resize((544, 288)))
    sprite_window.image = sprite_window.canvas.create_image(
        0 + BORDER_SIZE, 0 + BORDER_SIZE, anchor=NW, image=sprite_window.spritesheet
    )
    sprite_window.items = {}
    for item, coords in item_table.items():
        if (prize and item not in prize_names) or (not prize and item in prize_names):
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
            stipple="gray12" if disabled else "",
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
    return sprite_window.selected_item


item_table = {
    "Bow": (0, 0),
    "Progressive Bow": (0, 1),
    "Silver Arrows": (0, 3),
    "Blue Boomerang": (0, 4),
    "Red Boomerang": (0, 5),
    "Hookshot": (0, 6),
    "Mushroom": (0, 7),
    "Magic Powder": (0, 8),
    "Fire Rod": (1, 0),
    "Ice Rod": (1, 1),
    "Bombos": (1, 2),
    "Ether": (1, 3),
    "Quake": (1, 4),
    "Lamp": (1, 5),
    "Hammer": (1, 6),
    "Shovel": (1, 7),
    "Ocarina": (1, 8),
    "Bug Catching Net": (2, 0),
    "Book of Mudora": (2, 1),
    "Cane of Somaria": (2, 2),
    "Cane of Byrna": (2, 3),
    "Cape": (2, 4),
    "Magic Mirror": (2, 5),
    "Single Bomb": (2, 6),
    "Bombs (3)": (2, 7),
    "Bombs (10)": (2, 8),
    "Bottle": (3, 0),
    "Bottle (Red Potion)": (3, 1),
    "Bottle (Green Potion)": (3, 2),
    "Bottle (Blue Potion)": (3, 3),
    "Bottle (Bee)": (3, 4),
    "Bottle (Good Bee)": (3, 5),
    "Bottle (Fairy)": (3, 6),
    "Bomb Upgrade (+5)": (3, 7),
    "Bomb Upgrade (+10)": (3, 8),
    "Progressive Armor": (4, 0),
    "Blue Mail": (4, 1),
    "Red Mail": (4, 2),
    "Pegasus Boots": (4, 3),
    "Power Glove": (4, 4),
    "Titans Mitts": (4, 5),
    "Progressive Glove": (4, 6),
    "Flippers": (4, 7),
    "Moon Pearl": (4, 8),
    "Piece of Heart": (5, 0),
    "Boss Heart Container": (5, 1),
    "Small Heart": (5, 2),
    "Small Magic": (5, 3),
    "Big Magic": (5, 4),
    "Sanctuary Heart Container": (5, 5),
    "Magic Upgrade (1/2)": (5, 6),
    "Arrow Upgrade (+5)": (5, 7),
    "Rupee (1)": (6, 0),
    "Rupees (5)": (6, 1),
    "Rupees (20)": (6, 2),
    "Rupees (50)": (6, 3),
    "Rupees (100)": (6, 4),
    "Rupees (300)": (6, 5),
    "Single Arrow": (6, 6),
    "Arrows (5)": (6, 7),
    "Arrows (10)": (6, 8),
    "Fighter Sword": (7, 0),
    "Master Sword": (7, 1),
    "Tempered Sword": (7, 2),
    "Golden Sword": (7, 3),
    "Blue Shield": (7, 4),
    "Red Shield": (7, 5),
    "Mirror Shield": (7, 6),
    "Progressive Sword": (7, 7),
    "Progressive Shield": (7, 8),
    "Big Key (Escape)": (0, 10),
    "Big Key (Eastern Palace)": (0, 11),
    "Big Key (Desert Palace)": (0, 12),
    "Big Key (Tower of Hera)": (0, 13),
    "Big Key (Agahnims Tower)": (0, 14),
    "Big Key (Palace of Darkness)": (0, 15),
    "Big Key (Swamp Palace)": (0, 16),
    "Big Key (Skull Woods)": (4, 10),
    "Big Key (Thieves Town)": (4, 11),
    "Big Key (Ice Palace)": (4, 12),
    "Big Key (Misery Mire)": (4, 13),
    "Big Key (Turtle Rock)": (4, 14),
    "Big Key (Ganons Tower)": (4, 15),
    "Small Key (Escape)": (1, 10),
    "Small Key (Eastern Palace)": (1, 11),
    "Small Key (Desert Palace)": (1, 12),
    "Small Key (Tower of Hera)": (1, 13),
    "Small Key (Agahnims Tower)": (1, 14),
    "Small Key (Palace of Darkness)": (1, 15),
    "Small Key (Swamp Palace)": (1, 16),
    "Small Key (Skull Woods)": (5, 10),
    "Small Key (Thieves Town)": (5, 11),
    "Small Key (Ice Palace)": (5, 12),
    "Small Key (Misery Mire)": (5, 13),
    "Small Key (Turtle Rock)": (5, 14),
    "Small Key (Ganons Tower)": (5, 15),
    "Small Key (Universal)": (5, 16),
    "Map (Escape)": (2, 10),
    "Map (Eastern Palace)": (2, 11),
    "Map (Desert Palace)": (2, 12),
    "Map (Tower of Hera)": (2, 13),
    "Map (Agahnims Tower)": (2, 14),
    "Map (Palace of Darkness)": (2, 15),
    "Map (Swamp Palace)": (2, 16),
    "Map (Skull Woods)": (6, 10),
    "Map (Thieves Town)": (6, 11),
    "Map (Ice Palace)": (6, 12),
    "Map (Misery Mire)": (6, 13),
    "Map (Turtle Rock)": (6, 14),
    "Map (Ganons Tower)": (6, 15),
    "Compass (Escape)": (3, 10),
    "Compass (Eastern Palace)": (3, 11),
    "Compass (Desert Palace)": (3, 12),
    "Compass (Tower of Hera)": (3, 13),
    "Compass (Agahnims Tower)": (3, 14),
    "Compass (Palace of Darkness)": (3, 15),
    "Compass (Swamp Palace)": (3, 16),
    "Compass (Skull Woods)": (7, 10),
    "Compass (Thieves Town)": (7, 11),
    "Compass (Ice Palace)": (7, 12),
    "Compass (Misery Mire)": (7, 13),
    "Compass (Turtle Rock)": (7, 14),
    "Compass (Ganons Tower)": (7, 15),
    "Green Pendant": (8, 10),
    "Blue Pendant": (8, 11),
    "Red Pendant": (8, 12),
    "Crystal": (8, 13),
    "Red Crystal": (8, 14),
    "Triforce Piece": (8, 15),
    "Triforce": (8, 16),
    "Chicken": (8, 0),
    "Red Potion": (8, 1),
    "Green Potion": (8, 2),
    "Blue Potion": (8, 3),
    "Bee Trap": (8, 4),
    "Fairy": (8, 5),
}
