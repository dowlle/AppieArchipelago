"""Tests for the Hide Spoilers option (GitHub issue #35).

With the option on, the generated room's datapackage shows each per-Pokemon
location as ``Guess Pokemon {dex}`` instead of ``Guess {name}``. Clients, hints
and the server/tracker all resolve location names from that datapackage, so it
is the single surface the option has to touch. The world's registered name/id
map and its Location objects stay untouched.
"""
from test.bases import WorldTestBase
from worlds.pokepelago import PokepelagoWorld
from worlds.pokepelago.Items import ITEM_ID_OFFSET, LINE_UNLOCK_OFFSET
from worlds.pokepelago.Locations import LOCATION_ID_OFFSET


def _room_package() -> dict:
    return {"datapackage": {"Pokepelago": PokepelagoWorld.get_data_package_data()}}


class TestHideSpoilersOn(WorldTestBase):
    game = "Pokepelago"
    options = {"hide_spoilers": 1}

    def test_guess_locations_become_dex_numbers(self):
        multidata = _room_package()
        self.world.modify_multidata(multidata)
        names = multidata["datapackage"]["Pokepelago"]["location_name_to_id"]

        self.assertNotIn("Guess Bulbasaur", names)
        self.assertIn("Guess Pokemon 1", names)
        self.assertEqual(names["Guess Pokemon 1"], LOCATION_ID_OFFSET + 1)

        # Every surviving guess name is a dex-number label.
        self.assertTrue(any(name.startswith("Guess ") for name in names))
        for name in names:
            if name.startswith("Guess "):
                self.assertRegex(name, r"^Guess Pokemon \d+$")

        # Non-Pokemon locations are untouched.
        self.assertIn("Guessed 1 Pokemon", names)
        self.assertIn("Pokedex Received", names)

    def test_line_unlock_items_become_dex_numbers(self):
        multidata = _room_package()
        self.world.modify_multidata(multidata)
        package = multidata["datapackage"]["Pokepelago"]
        items = package["item_name_to_id"]

        self.assertNotIn("Bulbasaur Line", items)
        self.assertIn("Pokemon 1 Line", items)
        self.assertEqual(items["Pokemon 1 Line"], ITEM_ID_OFFSET + LINE_UNLOCK_OFFSET + 1)
        for name in items:
            if name.endswith(" Line"):
                self.assertRegex(name, r"^Pokemon \d+ Line$")

        # Other items keep their names.
        self.assertIn("Master Ball", items)
        self.assertIn("Grass Type Key", items)
        self.assertNotIn("Bulbasaur Unlock", items)
        self.assertEqual(items["Pokemon 1 Unlock"], ITEM_ID_OFFSET + 1)

        # The item group follows the rename.
        group = package["item_name_groups"]["Line Unlocks"]
        self.assertIn("Pokemon 1 Line", group)
        self.assertNotIn("Bulbasaur Line", group)

    def test_checksum_is_recomputed(self):
        original = PokepelagoWorld.get_data_package_data()
        multidata = {"datapackage": {"Pokepelago": original}}
        self.world.modify_multidata(multidata)
        self.assertNotEqual(
            multidata["datapackage"]["Pokepelago"]["checksum"], original["checksum"]
        )

    def test_class_map_not_mutated(self):
        multidata = _room_package()
        self.world.modify_multidata(multidata)
        self.assertIn("Guess Bulbasaur", PokepelagoWorld.location_name_to_id)
        self.assertIn("Bulbasaur Line", PokepelagoWorld.item_name_to_id)

    def test_idempotent(self):
        multidata = _room_package()
        self.world.modify_multidata(multidata)
        first = dict(multidata["datapackage"]["Pokepelago"]["location_name_to_id"])
        self.world.modify_multidata(multidata)
        second = multidata["datapackage"]["Pokepelago"]["location_name_to_id"]
        self.assertEqual(first, second)


class TestHideSpoilersOff(WorldTestBase):
    game = "Pokepelago"
    options = {"hide_spoilers": 0}

    def test_no_change(self):
        original = PokepelagoWorld.get_data_package_data()
        multidata = {"datapackage": {"Pokepelago": original}}
        self.world.modify_multidata(multidata)
        self.assertEqual(
            multidata["datapackage"]["Pokepelago"]["location_name_to_id"],
            original["location_name_to_id"],
        )
        self.assertIn("Guess Bulbasaur", multidata["datapackage"]["Pokepelago"]["location_name_to_id"])
        self.assertIn("Bulbasaur Line", multidata["datapackage"]["Pokepelago"]["item_name_to_id"])
