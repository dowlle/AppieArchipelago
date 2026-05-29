"""Guards the gate-classification sets in data.py against the PokeAPI source of truth.

The expected values live in ``tools/classification_snapshot.json``, generated from PokeAPI
by ``tools/build_classification_data.py``. This test is offline -- it only compares
``data.py`` against that committed snapshot, so CI never depends on PokeAPI being up.

These sets were hand-curated originally and drifted every generation (the 2026-05-29 audit
found 8 missing/mis-tiered legendaries, 2 missing Ultra Beasts, Toxel missing from babies,
2 missing trade evolutions). This test exists so that can't happen silently again.

When a new generation/DLC lands, run:
    python worlds/pokepelago/tools/build_classification_data.py --check
to diff data.py against live PokeAPI, fix data.py (and any documented exclusions in the
tool), then refresh this fixture with --snapshot.
"""
import json
import os
import unittest

from worlds.pokepelago.data import (
    LEGENDARY_SUB_IDS, LEGENDARY_BOX_IDS, LEGENDARY_MYTHIC_IDS,
    BABY_IDS, TRADE_EVO_IDS, FOSSIL_IDS, ULTRA_BEAST_IDS, PARADOX_IDS,
    STONE_EVO_GROUPS,
)

_SNAPSHOT = os.path.join(os.path.dirname(__file__), "..", "tools", "classification_snapshot.json")


class TestClassificationSets(unittest.TestCase):
    """Each gate set must match the authoritative snapshot derived from PokeAPI."""

    @classmethod
    def setUpClass(cls):
        with open(_SNAPSHOT, encoding="utf-8") as fh:
            cls.snap = json.load(fh)

    def test_legendary_union_matches_is_legendary(self):
        # data.py splits PokeAPI's is_legendary set into SUB (6-badge) and BOX (7-badge)
        # tiers for gating; their union must equal the authoritative legendary set.
        self.assertEqual(set(LEGENDARY_SUB_IDS) | set(LEGENDARY_BOX_IDS), set(self.snap["legendary"]))

    def test_mythical_matches_is_mythical(self):
        self.assertEqual(set(LEGENDARY_MYTHIC_IDS), set(self.snap["mythical"]))

    def test_baby_matches_is_baby(self):
        self.assertEqual(set(BABY_IDS), set(self.snap["baby"]))

    def test_ultra_beast(self):
        self.assertEqual(set(ULTRA_BEAST_IDS), set(self.snap["ultra_beast"]))

    def test_paradox(self):
        self.assertEqual(set(PARADOX_IDS), set(self.snap["paradox"]))

    def test_fossil(self):
        self.assertEqual(set(FOSSIL_IDS), set(self.snap["fossil"]))

    def test_trade_evo(self):
        self.assertEqual(set(TRADE_EVO_IDS), set(self.snap["trade_evo"]))

    def test_stone_evo_groups(self):
        expected = {k: set(v) for k, v in self.snap["stone_evo"].items()}
        actual = {k: set(v) for k, v in STONE_EVO_GROUPS.items()}
        self.assertEqual(actual, expected)

    def test_legendary_tiers_disjoint(self):
        # A Pokemon must sit in exactly one badge tier, or badge_req would be ambiguous.
        self.assertEqual(set(LEGENDARY_SUB_IDS) & set(LEGENDARY_BOX_IDS), set())
        self.assertEqual(set(LEGENDARY_SUB_IDS) & set(LEGENDARY_MYTHIC_IDS), set())
        self.assertEqual(set(LEGENDARY_BOX_IDS) & set(LEGENDARY_MYTHIC_IDS), set())


if __name__ == "__main__":
    unittest.main()
