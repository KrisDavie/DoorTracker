# This is copied from EntranceShuffle2.py from aerinon/ALttPDoorRandomizer

drop_map = {
    'Skull Woods First Section Hole (East)': 'Skull Pinball',
    'Skull Woods First Section Hole (West)': 'Skull Left Drop',
    'Skull Woods First Section Hole (North)': 'Skull Pot Circle',
    'Skull Woods Second Section Hole': 'Skull Back Drop',

    'Hyrule Castle Secret Entrance Drop':  'Hyrule Castle Secret Entrance',
    'Kakariko Well Drop': 'Kakariko Well (top)',
    'Bat Cave Drop': 'Bat Cave (right)',
    'North Fairy Cave Drop': 'North Fairy Cave',
    'Lost Woods Hideout Drop': 'Lost Woods Hideout (top)',
    'Lumberjack Tree Tree': 'Lumberjack Tree (top)',
    'Sanctuary Grave': 'Sewer Drop',
    'Pyramid Hole': 'Pyramid',
    'Inverted Pyramid Hole': 'Pyramid'
}

entrance_map = {
    'Desert Palace Entrance (South)': 'Desert Palace Exit (South)',
    'Desert Palace Entrance (West)': 'Desert Palace Exit (West)',
    'Desert Palace Entrance (North)': 'Desert Palace Exit (North)',
    'Desert Palace Entrance (East)': 'Desert Palace Exit (East)',
    
    'Eastern Palace': 'Eastern Palace Exit',
    'Tower of Hera': 'Tower of Hera Exit',
    
    'Hyrule Castle Entrance (South)': 'Hyrule Castle Exit (South)',
    'Hyrule Castle Entrance (West)': 'Hyrule Castle Exit (West)',
    'Hyrule Castle Entrance (East)': 'Hyrule Castle Exit (East)',
    'Agahnims Tower': 'Agahnims Tower Exit',
    'Inverted Agahnims Tower': 'Inverted Agahnims Tower Exit',

    'Thieves Town': 'Thieves Town Exit',
    'Skull Woods First Section Door': 'Skull Woods First Section Exit',
    'Skull Woods Second Section Door (East)': 'Skull Woods Second Section Exit (East)',
    'Skull Woods Second Section Door (West)': 'Skull Woods Second Section Exit (West)',
    'Skull Woods Final Section': 'Skull Woods Final Section Exit',
    'Ice Palace': 'Ice Palace Exit',
    'Misery Mire': 'Misery Mire Exit',
    'Palace of Darkness': 'Palace of Darkness Exit',
    'Swamp Palace': 'Swamp Palace Exit', 
    
    'Turtle Rock': 'Turtle Rock Exit (Front)',
    'Dark Death Mountain Ledge (West)': 'Turtle Rock Ledge Exit (West)',
    'Dark Death Mountain Ledge (East)': 'Turtle Rock Ledge Exit (East)',
    'Turtle Rock Isolated Ledge Entrance': 'Turtle Rock Isolated Ledge Exit',
    'Ganons Tower': 'Ganons Tower Exit',
    'Inverted Ganons Tower': 'Inverted Ganons Tower Exit',

    'Links House': 'Links House Exit',
    'Inverted Links House': 'Inverted Links House Exit',


    'Hyrule Castle Secret Entrance Stairs':  'Hyrule Castle Secret Entrance Exit',
    'Kakariko Well Cave': 'Kakariko Well Exit',
    'Bat Cave Cave': 'Bat Cave Exit',
    'North Fairy Cave': 'North Fairy Cave Exit',
    'Lost Woods Hideout Stump': 'Lost Woods Hideout Exit',
    'Lumberjack Tree Cave': 'Lumberjack Tree Exit',
    'Sanctuary': 'Sanctuary Exit',
    'Pyramid Entrance': 'Pyramid Exit',
    'Inverted Pyramid Entrance': 'Pyramid Exit',

    'Elder House (East)': 'Elder House Exit (East)',
    'Elder House (West)': 'Elder House Exit (West)',
    'Two Brothers House (East)': 'Two Brothers House Exit (East)',
    'Two Brothers House (West)': 'Two Brothers House Exit (West)',
    'Old Man Cave (West)': 'Old Man Cave Exit (West)',
    'Old Man Cave (East)': 'Old Man Cave Exit (East)',
    'Old Man House (Bottom)': 'Old Man House Exit (Bottom)',
    'Old Man House (Top)': 'Old Man House Exit (Top)',
    'Death Mountain Return Cave (East)': 'Death Mountain Return Cave Exit (East)',
    'Death Mountain Return Cave (West)': 'Death Mountain Return Cave Exit (West)',
    'Fairy Ascension Cave (Bottom)': 'Fairy Ascension Cave Exit (Bottom)',
    'Fairy Ascension Cave (Top)': 'Fairy Ascension Cave Exit (Top)',
    'Spiral Cave': 'Spiral Cave Exit (Top)',
    'Spiral Cave (Bottom)': 'Spiral Cave Exit',
    'Bumper Cave (Bottom)': 'Bumper Cave Exit (Bottom)',
    'Bumper Cave (Top)': 'Bumper Cave Exit (Top)',
    'Hookshot Cave': 'Hookshot Cave Front Exit',
    'Hookshot Cave Back Entrance': 'Hookshot Cave Back Exit',
    'Superbunny Cave (Top)': 'Superbunny Cave Exit (Top)',
    'Superbunny Cave (Bottom)': 'Superbunny Cave Exit (Bottom)',

    'Spectacle Rock Cave Peak': 'Spectacle Rock Cave Exit (Peak)',
    'Spectacle Rock Cave (Bottom)': 'Spectacle Rock Cave Exit',
    'Spectacle Rock Cave': 'Spectacle Rock Cave Exit (Top)',
    'Paradox Cave (Bottom)': 'Paradox Cave Exit (Bottom)',
    'Paradox Cave (Middle)': 'Paradox Cave Exit (Middle)',
    'Paradox Cave (Top)': 'Paradox Cave Exit (Top)',
    'Inverted Dark Sanctuary': 'Inverted Dark Sanctuary Exit',
}


single_entrance_map = {
    'Mimic Cave': 'Mimic Cave', 'Dark Death Mountain Fairy': 'Dark Death Mountain Healer Fairy',
    'Cave Shop (Dark Death Mountain)': 'Cave Shop (Dark Death Mountain)', 'Spike Cave': 'Spike Cave',
    'Dark Desert Fairy': 'Dark Desert Healer Fairy', 'Dark Desert Hint': 'Dark Desert Hint', 'Mire Shed': 'Mire Shed',
    'Archery Game': 'Archery Game', 'Dark World Potion Shop': 'Dark World Potion Shop',
    'Dark World Lumberjack Shop': 'Dark World Lumberjack Shop', 'Dark World Shop': 'Village of Outcasts Shop',
    'Fortune Teller (Dark)': 'Fortune Teller (Dark)', 'Dark Sanctuary Hint': 'Dark Sanctuary Hint',
    'Red Shield Shop': 'Red Shield Shop', 'Dark World Hammer Peg Cave': 'Dark World Hammer Peg Cave',
    'Chest Game': 'Chest Game', 'C-Shaped House': 'C-Shaped House', 'Brewery': 'Brewery',
    'Bonk Fairy (Dark)': 'Bonk Fairy (Dark)', 'Hype Cave': 'Hype Cave',
    'Dark Lake Hylia Ledge Hint': 'Dark Lake Hylia Ledge Hint',
    'Dark Lake Hylia Ledge Spike Cave': 'Dark Lake Hylia Ledge Spike Cave',
    'Dark Lake Hylia Ledge Fairy': 'Dark Lake Hylia Ledge Healer Fairy',
    'Dark Lake Hylia Fairy': 'Dark Lake Hylia Healer Fairy',
    'Dark Lake Hylia Shop': 'Dark Lake Hylia Shop', 'Big Bomb Shop': 'Big Bomb Shop',
    'Palace of Darkness Hint': 'Palace of Darkness Hint', 'East Dark World Hint': 'East Dark World Hint',
    'Pyramid Fairy': 'Pyramid Fairy', 'Hookshot Fairy': 'Hookshot Fairy', '50 Rupee Cave': '50 Rupee Cave',
    'Ice Rod Cave': 'Ice Rod Cave', 'Bonk Rock Cave': 'Bonk Rock Cave', 'Library': 'Library',
    'Kakariko Gamble Game': 'Kakariko Gamble Game', 'Potion Shop': 'Potion Shop', '20 Rupee Cave': '20 Rupee Cave',
    'Good Bee Cave': 'Good Bee Cave', 'Long Fairy Cave': 'Long Fairy Cave', 'Mini Moldorm Cave': 'Mini Moldorm Cave',
    'Checkerboard Cave': 'Checkerboard Cave', 'Graveyard Cave': 'Graveyard Cave', 'Cave 45': 'Cave 45',
    'Kakariko Shop': 'Kakariko Shop', 'Light World Bomb Hut': 'Light World Bomb Hut',
    'Tavern (Front)': 'Tavern (Front)', 'Bush Covered House': 'Bush Covered House',
    'Snitch Lady (West)': 'Snitch Lady (West)', 'Snitch Lady (East)': 'Snitch Lady (East)',
    'Fortune Teller (Light)': 'Fortune Teller (Light)', 'Lost Woods Gamble': 'Lost Woods Gamble',
    'Sick Kids House': 'Sick Kids House', 'Blacksmiths Hut': 'Blacksmiths Hut', 'Capacity Upgrade': 'Capacity Upgrade',
    'Cave Shop (Lake Hylia)': 'Cave Shop (Lake Hylia)', 'Sahasrahlas Hut': 'Sahasrahlas Hut',
    'Aginahs Cave': 'Aginahs Cave', 'Chicken House': 'Chicken House', 'Tavern North': 'Tavern',
    'Kings Grave': 'Kings Grave', 'Desert Fairy': 'Desert Healer Fairy', 'Light Hype Fairy': 'Swamp Healer Fairy',
    'Lake Hylia Fortune Teller': 'Lake Hylia Fortune Teller', 'Lake Hylia Fairy': 'Lake Hylia Healer Fairy',
    'Bonk Fairy (Light)': 'Bonk Fairy (Light)', 'Lumberjack House': 'Lumberjack House', 'Dam': 'Dam',
    'Blinds Hideout': 'Blinds Hideout', 'Waterfall of Wishing': 'Waterfall of Wishing',
    'Inverted Bomb Shop': 'Inverted Bomb Shop'
}

default_connections = {'Links House': 'Links House',
                       'Links House Exit': 'Light World',
                       'Waterfall of Wishing': 'Waterfall of Wishing',
                       'Blinds Hideout': 'Blinds Hideout',
                       'Dam': 'Dam',
                       'Lumberjack House': 'Lumberjack House',
                       'Hyrule Castle Secret Entrance Drop': 'Hyrule Castle Secret Entrance',
                       'Hyrule Castle Secret Entrance Stairs': 'Hyrule Castle Secret Entrance',
                       'Hyrule Castle Secret Entrance Exit': 'Hyrule Castle Courtyard',
                       'Bonk Fairy (Light)': 'Bonk Fairy (Light)',
                       'Lake Hylia Fairy': 'Lake Hylia Healer Fairy',
                       'Lake Hylia Fortune Teller': 'Lake Hylia Fortune Teller',
                       'Light Hype Fairy': 'Swamp Healer Fairy',
                       'Desert Fairy': 'Desert Healer Fairy',
                       'Kings Grave': 'Kings Grave',
                       'Tavern North': 'Tavern',
                       'Chicken House': 'Chicken House',
                       'Aginahs Cave': 'Aginahs Cave',
                       'Sahasrahlas Hut': 'Sahasrahlas Hut',
                       'Cave Shop (Lake Hylia)': 'Cave Shop (Lake Hylia)',
                       'Capacity Upgrade': 'Capacity Upgrade',
                       'Kakariko Well Drop': 'Kakariko Well (top)',
                       'Kakariko Well Cave': 'Kakariko Well (bottom)',
                       'Kakariko Well Exit': 'Light World',
                       'Blacksmiths Hut': 'Blacksmiths Hut',
                       'Bat Cave Drop': 'Bat Cave (right)',
                       'Bat Cave Cave': 'Bat Cave (left)',
                       'Bat Cave Exit': 'Light World',
                       'Sick Kids House': 'Sick Kids House',
                       'Elder House (East)': 'Elder House',
                       'Elder House (West)': 'Elder House',
                       'Elder House Exit (East)': 'Light World',
                       'Elder House Exit (West)': 'Light World',
                       'North Fairy Cave Drop': 'North Fairy Cave',
                       'North Fairy Cave': 'North Fairy Cave',
                       'North Fairy Cave Exit': 'Light World',
                       'Lost Woods Gamble': 'Lost Woods Gamble',
                       'Fortune Teller (Light)': 'Fortune Teller (Light)',
                       'Snitch Lady (East)': 'Snitch Lady (East)',
                       'Snitch Lady (West)': 'Snitch Lady (West)',
                       'Bush Covered House': 'Bush Covered House',
                       'Tavern (Front)': 'Tavern (Front)',
                       'Light World Bomb Hut': 'Light World Bomb Hut',
                       'Kakariko Shop': 'Kakariko Shop',
                       'Lost Woods Hideout Drop': 'Lost Woods Hideout (top)',
                       'Lost Woods Hideout Stump': 'Lost Woods Hideout (bottom)',
                       'Lost Woods Hideout Exit': 'Light World',
                       'Lumberjack Tree Tree': 'Lumberjack Tree (top)',
                       'Lumberjack Tree Cave': 'Lumberjack Tree (bottom)',
                       'Lumberjack Tree Exit': 'Light World',
                       'Cave 45': 'Cave 45',
                       'Graveyard Cave': 'Graveyard Cave',
                       'Checkerboard Cave': 'Checkerboard Cave',
                       'Mini Moldorm Cave': 'Mini Moldorm Cave',
                       'Long Fairy Cave': 'Long Fairy Cave',  # near East Light World Teleporter
                       'Good Bee Cave': 'Good Bee Cave',
                       '20 Rupee Cave': '20 Rupee Cave',
                       '50 Rupee Cave': '50 Rupee Cave',
                       'Ice Rod Cave': 'Ice Rod Cave',
                       'Bonk Rock Cave': 'Bonk Rock Cave',
                       'Library': 'Library',
                       'Kakariko Gamble Game': 'Kakariko Gamble Game',
                       'Potion Shop': 'Potion Shop',
                       'Two Brothers House (East)': 'Two Brothers House',
                       'Two Brothers House (West)': 'Two Brothers House',
                       'Two Brothers House Exit (East)': 'Light World',
                       'Two Brothers House Exit (West)': 'Maze Race Ledge',

                       'Sanctuary': 'Sanctuary Portal',
                       'Sanctuary Grave': 'Sewer Drop',
                       'Sanctuary Exit': 'Light World',

                       'Old Man Cave (West)': 'Old Man Cave Ledge',
                       'Old Man Cave (East)': 'Old Man Cave',
                       'Old Man Cave Exit (West)': 'Light World',
                       'Old Man Cave Exit (East)': 'Death Mountain',
                       'Old Man House (Bottom)': 'Old Man House',
                       'Old Man House Exit (Bottom)': 'Death Mountain',
                       'Old Man House (Top)': 'Old Man House Back',
                       'Old Man House Exit (Top)': 'Death Mountain',
                       'Death Mountain Return Cave (East)': 'Death Mountain Return Cave (right)',
                       'Death Mountain Return Cave (West)': 'Death Mountain Return Cave (left)',
                       'Death Mountain Return Cave Exit (West)': 'Death Mountain Return Ledge',
                       'Death Mountain Return Cave Exit (East)': 'Death Mountain',
                       'Spectacle Rock Cave Peak': 'Spectacle Rock Cave (Peak)',
                       'Spectacle Rock Cave (Bottom)': 'Spectacle Rock Cave (Bottom)',
                       'Spectacle Rock Cave': 'Spectacle Rock Cave (Top)',
                       'Spectacle Rock Cave Exit': 'Death Mountain',
                       'Spectacle Rock Cave Exit (Top)': 'Death Mountain',
                       'Spectacle Rock Cave Exit (Peak)': 'Death Mountain',
                       'Paradox Cave (Bottom)': 'Paradox Cave Front',
                       'Paradox Cave (Middle)': 'Paradox Cave',
                       'Paradox Cave (Top)': 'Paradox Cave',
                       'Paradox Cave Exit (Bottom)': 'East Death Mountain (Bottom)',
                       'Paradox Cave Exit (Middle)': 'East Death Mountain (Bottom)',
                       'Paradox Cave Exit (Top)': 'East Death Mountain (Top)',
                       'Hookshot Fairy': 'Hookshot Fairy',
                       'Fairy Ascension Cave (Bottom)': 'Fairy Ascension Cave (Bottom)',
                       'Fairy Ascension Cave (Top)': 'Fairy Ascension Cave (Top)',
                       'Fairy Ascension Cave Exit (Bottom)': 'Fairy Ascension Plateau',
                       'Fairy Ascension Cave Exit (Top)': 'Fairy Ascension Ledge',
                       'Spiral Cave': 'Spiral Cave (Top)',
                       'Spiral Cave (Bottom)': 'Spiral Cave (Bottom)',
                       'Spiral Cave Exit': 'East Death Mountain (Bottom)',
                       'Spiral Cave Exit (Top)': 'Spiral Cave Ledge',

                       'Pyramid Fairy': 'Pyramid Fairy',
                       'East Dark World Hint': 'East Dark World Hint',
                       'Palace of Darkness Hint': 'Palace of Darkness Hint',
                       'Big Bomb Shop': 'Big Bomb Shop',
                       'Dark Lake Hylia Shop': 'Dark Lake Hylia Shop',
                       'Dark Lake Hylia Fairy': 'Dark Lake Hylia Healer Fairy',
                       'Dark Lake Hylia Ledge Fairy': 'Dark Lake Hylia Ledge Healer Fairy',
                       'Dark Lake Hylia Ledge Spike Cave': 'Dark Lake Hylia Ledge Spike Cave',
                       'Dark Lake Hylia Ledge Hint': 'Dark Lake Hylia Ledge Hint',
                       'Hype Cave': 'Hype Cave',
                       'Bonk Fairy (Dark)': 'Bonk Fairy (Dark)',
                       'Brewery': 'Brewery',
                       'C-Shaped House': 'C-Shaped House',
                       'Chest Game': 'Chest Game',
                       'Dark World Hammer Peg Cave': 'Dark World Hammer Peg Cave',
                       'Bumper Cave (Bottom)': 'Bumper Cave (bottom)',
                       'Bumper Cave (Top)': 'Bumper Cave (top)',
                       'Red Shield Shop': 'Red Shield Shop',
                       'Dark Sanctuary Hint': 'Dark Sanctuary Hint',
                       'Fortune Teller (Dark)': 'Fortune Teller (Dark)',
                       'Dark World Shop': 'Village of Outcasts Shop',
                       'Dark World Lumberjack Shop': 'Dark World Lumberjack Shop',
                       'Dark World Potion Shop': 'Dark World Potion Shop',
                       'Archery Game': 'Archery Game',
                       'Bumper Cave Exit (Top)': 'Bumper Cave Ledge',
                       'Bumper Cave Exit (Bottom)': 'West Dark World',
                       'Mire Shed': 'Mire Shed',
                       'Dark Desert Hint': 'Dark Desert Hint',
                       'Dark Desert Fairy': 'Dark Desert Healer Fairy',
                       'Spike Cave': 'Spike Cave',
                       'Hookshot Cave': 'Hookshot Cave (Front)',
                       'Superbunny Cave (Top)': 'Superbunny Cave (Top)',
                       'Cave Shop (Dark Death Mountain)': 'Cave Shop (Dark Death Mountain)',
                       'Dark Death Mountain Fairy': 'Dark Death Mountain Healer Fairy',
                       'Superbunny Cave (Bottom)': 'Superbunny Cave (Bottom)',
                       'Superbunny Cave Exit (Top)': 'Dark Death Mountain (Top)',
                       'Superbunny Cave Exit (Bottom)': 'Dark Death Mountain (East Bottom)',
                       'Hookshot Cave Front Exit': 'Dark Death Mountain (Top)',
                       'Hookshot Cave Back Exit': 'Death Mountain Floating Island (Dark World)',
                       'Hookshot Cave Back Entrance': 'Hookshot Cave (Back)',
                       'Mimic Cave': 'Mimic Cave',

                       'Pyramid Hole': 'Pyramid',
                       'Pyramid Exit': 'Pyramid Ledge',
                       'Pyramid Entrance': 'Bottom of Pyramid'
                       }