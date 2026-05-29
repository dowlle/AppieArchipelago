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


class TestGateCategoriesSlotData(WorldTestBase):
    """DEVEX-15: slot_data carries the exact gate classification this APWorld used."""
    game = "Pokepelago"

    def test_gate_categories_match_data(self):
        from worlds.pokepelago import data
        gc = self.world.fill_slot_data()["gate_categories"]
        self.assertEqual(set(gc["legendary_sub"]), set(data.LEGENDARY_SUB_IDS))
        self.assertEqual(set(gc["legendary_box"]), set(data.LEGENDARY_BOX_IDS))
        self.assertEqual(set(gc["legendary_mythic"]), set(data.LEGENDARY_MYTHIC_IDS))
        self.assertEqual(set(gc["baby"]), set(data.BABY_IDS))
        self.assertEqual(set(gc["trade_evo"]), set(data.TRADE_EVO_IDS))
        self.assertEqual(set(gc["fossil"]), set(data.FOSSIL_IDS))
        self.assertEqual(set(gc["ultra_beast"]), set(data.ULTRA_BEAST_IDS))
        self.assertEqual(set(gc["paradox"]), set(data.PARADOX_IDS))
        self.assertEqual(set(gc["stone_evo"].keys()), set(data.STONE_EVO_GROUPS.keys()))
        # Spot-check the BUG-16 fixes are carried over the wire
        self.assertIn(773, gc["legendary_sub"])      # Silvally
        self.assertIn(489, gc["legendary_mythic"])   # Phione (moved to mythic)
        self.assertIn(804, gc["ultra_beast"])        # Naganadel
