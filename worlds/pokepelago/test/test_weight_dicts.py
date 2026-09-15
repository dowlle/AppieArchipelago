"""BUG-23 (issue #18): partial trap/filler weight dicts.

Stef ruling 2026-09-15: keep the merge. Keys left out of the YAML keep their default
weight; only an explicit 0 disables an entry. The docstrings now say so.
"""
import unittest

from worlds.pokepelago.Options import FillerWeights, TrapWeights


class TestTrapWeightsMerge(unittest.TestCase):
    def test_omitted_keys_keep_defaults(self):
        w = TrapWeights.from_any({"release": 0})
        self.assertEqual(w.value["release"], 0)
        for key in ("small_shuffle", "big_shuffle", "derpy_mon"):
            self.assertEqual(w.value[key], TrapWeights.default[key])

    def test_explicit_zero_disables(self):
        w = TrapWeights.from_any(dict.fromkeys(TrapWeights.valid_keys, 0))
        self.assertTrue(all(v == 0 for v in w.value.values()))

    def test_unknown_keys_dropped(self):
        w = TrapWeights.from_any({"not_a_trap": 99})
        self.assertNotIn("not_a_trap", w.value)

    def test_docstring_states_omitted_semantics(self):
        self.assertIn("leave out", TrapWeights.__doc__)


class TestFillerWeightsMerge(unittest.TestCase):
    def test_omitted_keys_keep_defaults(self):
        w = FillerWeights.from_any({"splash": 0})
        self.assertEqual(w.value["splash"], 0)
        self.assertEqual(w.value["master_ball"], FillerWeights.default["master_ball"])
        self.assertEqual(w.value["key_items"], FillerWeights.default["key_items"])

    def test_docstring_states_omitted_semantics(self):
        self.assertIn("leave out", FillerWeights.__doc__)
