"""ISSUE-40: the GuessLanguage YAML option seeds the client's starting guess
language. It must reach slot_data as the client's own language codes, which
differ from the YAML option keys for roomaji and the two Chinese variants."""
from test.bases import WorldTestBase


class TestGuessLanguageSlotDataDefault(WorldTestBase):
    game = "Pokepelago"

    def test_defaults_to_global(self):
        self.assertEqual(self.world.fill_slot_data()["guess_language"], "global")


class TestGuessLanguageSlotDataRoomaji(WorldTestBase):
    game = "Pokepelago"
    options = {"guess_language": 7}

    def test_roomaji_client_code(self):
        self.assertEqual(self.world.fill_slot_data()["guess_language"], "roomaji")


class TestGuessLanguageSlotDataZhHant(WorldTestBase):
    game = "Pokepelago"
    options = {"guess_language": 9}

    def test_zh_hant_client_code(self):
        self.assertEqual(self.world.fill_slot_data()["guess_language"], "zh-Hant")


class TestGuessLanguageSlotDataZhHans(WorldTestBase):
    game = "Pokepelago"
    options = {"guess_language": 10}

    def test_zh_hans_client_code(self):
        self.assertEqual(self.world.fill_slot_data()["guess_language"], "zh-Hans")
