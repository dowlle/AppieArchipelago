"""BUG-22 (issue #17): `starting_location_count` under two or more lock options.

The floor is load-bearing (4/20 FillErrors at 0 with six locks, 2026-09-15 repro), so it
stays. The bump is no longer silent: every raise logs a warning naming the reason.
"""
from test.bases import WorldTestBase
from worlds.pokepelago.Locations import starting_locations

HEAVY_LOCKS = {
    "regions": ["Kanto", "Johto"],
    "random_region_count": 0,
    "type_locks": 1,
    "region_locks": 1,
    "route_locks_enabled": 1,
    "line_locks": 1,
    "badge_level_gating": 1,
    "dexsanity": 1,
}


def _gate_count(o) -> int:
    return sum(bool(v.value) for v in [
        o.type_locks, o.region_locks, o.route_locks_enabled, o.line_locks,
        o.badge_level_gating, o.legendary_locks, o.trade_locks, o.baby_locks,
        o.fossil_locks, o.ultra_beast_locks, o.paradox_locks, o.stone_locks,
    ])


class TestZeroRaisedToFloor(WorldTestBase):
    game = "Pokepelago"
    options = {**HEAVY_LOCKS, "starting_location_count": 0}

    def test_zero_is_raised(self):
        o = self.world.options
        self.assertGreaterEqual(_gate_count(o), 2)
        self.assertEqual(o.starting_location_count.value, min(_gate_count(o), 8))

    def test_starting_locations_created(self):
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        self.assertEqual(len(names & set(starting_locations)),
                         self.world.options.starting_location_count.value)


class TestLowValueRaisedToFloor(WorldTestBase):
    game = "Pokepelago"
    options = {**HEAVY_LOCKS, "starting_location_count": 1}

    def test_raised_to_gate_count_floor(self):
        o = self.world.options
        self.assertEqual(o.starting_location_count.value, min(_gate_count(o), 8))


class TestHighValueUntouched(WorldTestBase):
    game = "Pokepelago"
    options = {**HEAVY_LOCKS, "starting_location_count": 8}

    def test_not_lowered(self):
        self.assertEqual(self.world.options.starting_location_count.value, 8)


class TestZeroWithSingleLockUnchanged(WorldTestBase):
    game = "Pokepelago"
    options = {
        "regions": ["Kanto"], "random_region_count": 0, "starting_location_count": 0,
        "type_locks": 1, "region_locks": 0, "route_locks_enabled": 0, "line_locks": 0,
        "badge_level_gating": 0, "legendary_locks": 0, "trade_locks": 0, "baby_locks": 0,
        "fossil_locks": 0, "ultra_beast_locks": 0, "paradox_locks": 0, "stone_locks": 0,
    }

    def test_single_lock_never_bumps(self):
        self.assertEqual(self.world.options.starting_location_count.value, 0)
