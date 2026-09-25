"""Unit tests for the DEVEX-16 Phase 2 client item-decode fuzz hook.

The hook normally runs inside the Eijebong fuzzer, but its decoder is a faithful
port of the client's ID-to-name math. These tests import the hook module
directly (stubbing the fuzzer's ``fuzz`` module, which is not installed in the
unit-test environment) and pin the range the hook used to skip: the useful-item
trio. Issue #29 / BUG-24 lived there (the client transposed Pokedex and
Pokegear), so the negative control below proves the check would catch that
transposition instead of silently passing.
"""
import importlib.util
import sys
import types
import unittest
from pathlib import Path

_HOOK_PATH = (Path(__file__).resolve().parents[1]
              / "tools" / "fuzz" / "client_item_decode.py")


def _load_hook_module():
    """Load the fuzz hook from its path with a minimal ``fuzz`` stub installed.

    The hook does ``from fuzz import BaseHook, GenOutcome`` at import time; that
    module ships with the external fuzzer, not the APWorld test environment. A
    stub lets the unit suite exercise the real decoder/check code without the
    harness. The stub is only used to satisfy the import of ``Hook``'s base.
    """
    if "fuzz" not in sys.modules:
        stub = types.ModuleType("fuzz")

        class BaseHook:  # pragma: no cover - only satisfies the import
            def setup_worker(self, args):
                pass

        class GenOutcome:  # pragma: no cover - only satisfies the import
            Success = "success"
            Failure = "failure"
            Timeout = "timeout"
            OptionError = "option_error"

        stub.BaseHook = BaseHook
        stub.GenOutcome = GenOutcome
        sys.modules["fuzz"] = stub

    spec = importlib.util.spec_from_file_location(
        "pokepelago_fuzz_client_item_decode", _HOOK_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _StubItems:
    """Minimal stand-in for the world's Items module.

    Empty route/line maps are enough to build a decoder; these tests never touch
    those paths.
    """
    ROUTE_KEY_NAMES = {}
    LINE_UNLOCK_NAMES = {}


class TestUsefulItemDecode(unittest.TestCase):
    def setUp(self):
        self.mod = _load_hook_module()
        self.decoder = self.mod._ClientDecoder(_StubItems)

    def _id(self, offset):
        return self.mod.CLIENT_ITEM_OFFSET + offset

    def test_useful_trio_is_in_scope(self):
        for offset in (3001, 3002, 3003):
            self.assertEqual(self.decoder.category(self._id(offset)), "useful")
        # Range edges: 3000 is not a useful item, 3004 is beyond the trio.
        self.assertIsNone(self.decoder.category(self._id(3000)))
        self.assertIsNone(self.decoder.category(self._id(3004)))

    def test_decodes_in_apworld_id_order(self):
        self.assertEqual(self.decoder.decode("useful", self._id(3001)), "Master Ball")
        self.assertEqual(self.decoder.decode("useful", self._id(3002)), "Pokedex")
        self.assertEqual(self.decoder.decode("useful", self._id(3003)), "Pokegear")

    def test_check_passes_for_correctly_placed_useful_items(self):
        self.assertIsNone(self.decoder.check(self._id(3001), "Master Ball"))
        self.assertIsNone(self.decoder.check(self._id(3002), "Pokedex"))
        self.assertIsNone(self.decoder.check(self._id(3003), "Pokegear"))


class TestUsefulItemNegativeControl(unittest.TestCase):
    """BUG-24 negative control: Pokedex and Pokegear transposed.

    A decoder carrying that defect must FAIL the hook's check for those two
    items, otherwise the newly added coverage would be toothless.
    """

    def setUp(self):
        self.mod = _load_hook_module()
        # Exact BUG-24 transposition: the +2/+3 ordered entries swapped.
        swapped = ["Master Ball", "Pokegear", "Pokedex"]
        self.swapped = self.mod._ClientDecoder(_StubItems, useful_names=swapped)

    def _id(self, offset):
        return self.mod.CLIENT_ITEM_OFFSET + offset

    def test_swapped_decoder_fails_pokedex_check(self):
        mismatch = self.swapped.check(self._id(3002), "Pokedex")
        self.assertIsNotNone(mismatch)
        self.assertIn("useful", mismatch)
        self.assertIn("Pokedex", mismatch)
        self.assertIn("Pokegear", mismatch)

    def test_swapped_decoder_fails_pokegear_check(self):
        self.assertIsNotNone(self.swapped.check(self._id(3003), "Pokegear"))

    def test_swapped_decoder_still_passes_master_ball(self):
        # The transposition is isolated to the +2/+3 pair, proving the failures
        # above come from the swap and not a broken harness.
        self.assertIsNone(self.swapped.check(self._id(3001), "Master Ball"))


if __name__ == "__main__":
    unittest.main()
