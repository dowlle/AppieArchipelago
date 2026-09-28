"""
rule_builder interns every resolved rule in a process-global dict and never clears
it, so a long-lived process generating many Pokepelago seeds (a fuzzer worker) grew
by a few MB per seed until it ran out of memory. purge_orphaned_resolved_rules drops
the entries of finished generations at the start of each generation.
"""
import gc
import unittest

from rule_builder.rules import CustomRuleRegister, Rule
from test.general import setup_solo_multiworld

from .. import PokepelagoWorld
from ..rules import CanAccessNPokemon, purge_orphaned_resolved_rules

_STEPS = ("generate_early", "create_regions", "create_items", "set_rules")


def _pokepelago_rule_count() -> int:
    return sum(isinstance(r, CanAccessNPokemon.Resolved)
               for r in CustomRuleRegister.resolved_rules.values())


class TestResolvedRuleCachePurge(unittest.TestCase):
    def test_live_rules_are_kept(self):
        multiworld = setup_solo_multiworld(PokepelagoWorld, _STEPS)
        purge_orphaned_resolved_rules()
        cache = CustomRuleRegister.resolved_rules
        checked = 0
        for location in multiworld.get_locations():
            rule = location.access_rule
            if isinstance(rule, Rule.Resolved):
                self.assertIs(cache.get(hash(rule)), rule, location.name)
                checked += 1
        self.assertGreater(checked, 0)

    def test_finished_generation_rules_are_dropped(self):
        multiworld = setup_solo_multiworld(PokepelagoWorld, _STEPS)
        with_live_world = _pokepelago_rule_count()
        self.assertGreater(with_live_world, 0)
        del multiworld
        gc.collect()
        purge_orphaned_resolved_rules()
        self.assertLess(_pokepelago_rule_count(), with_live_world)
