"""Tests for the 0.6.2 option additions: FEAT-14 (Pokedex/Pokegear filler) and
FEAT-03 (stop-autosubmit-on-goal slot_data default)."""
from BaseClasses import ItemClassification
from test.bases import WorldTestBase


class TestPokegearPokedexFillerOn(WorldTestBase):
    """FEAT-14: with the option on, Pokedex/Pokegear are filler, not useful."""
    game = "Pokepelago"
    options = {"pokegear_pokedex_filler": 1}

    def test_demoted_to_filler(self):
        for name in ("Pokedex", "Pokegear"):
            self.assertEqual(self.world.create_item(name).classification, ItemClassification.filler)
        # Master Ball must be unaffected.
        self.assertEqual(self.world.create_item("Master Ball").classification, ItemClassification.useful)


class TestPokegearPokedexFillerOff(WorldTestBase):
    """FEAT-14: default keeps Pokedex/Pokegear as useful (backward compatible)."""
    game = "Pokepelago"
    options = {"pokegear_pokedex_filler": 0}

    def test_useful_by_default(self):
        for name in ("Pokedex", "Pokegear"):
            self.assertEqual(self.world.create_item(name).classification, ItemClassification.useful)


class TestStopAutosubmitSlotData(WorldTestBase):
    """FEAT-03: the YAML option round-trips into slot_data for the client to read."""
    game = "Pokepelago"
    options = {"stop_autosubmit_on_goal": 1}

    def test_slot_data_flag_present(self):
        self.assertIs(self.world.fill_slot_data()["stop_autosubmit_on_goal"], True)
