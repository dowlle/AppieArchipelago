"""Source-of-truth checker / generator for Pokepelago's classification sets.

Background
----------
The gate-classification frozensets in ``data.py`` (legendaries, mythicals, babies,
Ultra Beasts, Paradox, trade evolutions, stone evolutions, fossils) were originally
hand-curated from memory. That drifts every new generation/DLC: the audit on
2026-05-29 found Type: Null, Silvally, Cosmog, Cosmoem, Ogerpon and the Loyal Three
missing from the legendary sets, Poipole/Naganadel missing from Ultra Beasts, Toxel
missing from babies, Aromatisse/Slurpuff missing from trade evolutions, and Phione
mis-tiered as a sub-legendary instead of a mythical.

This tool makes PokeAPI the source of truth so the data can't silently drift again:

* ``--check``    Query PokeAPI live, derive the expected sets, and diff against the
                 committed ``data.py``. Exits non-zero on any unexpected drift.
                 Used by the classification-audit workflow.
* ``--snapshot`` Write ``classification_snapshot.json`` next to this file. That
                 snapshot is what the offline unit test (test/test_classification.py)
                 compares ``data.py`` against, so the per-PR test needs no network.

Per-species flags (is_legendary / is_mythical / is_baby) come straight from PokeAPI
and are authoritative. The sets PokeAPI cannot express as a flag are curated here with
their source, and the evolution-derived sets carry documented exclusions for the few
cases where a national-dex number is shared with a regional form that uses a different
method (e.g. Hisuian Electrode / Alolan Ninetales) -- Pokepelago guesses by national
dex number, so those must NOT inherit the regional form's gate.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_PY = os.path.join(HERE, "..", "data.py")
SNAPSHOT = os.path.join(HERE, "classification_snapshot.json")
ENDPOINT = "https://graphql.pokeapi.co/v1beta2"

# --- Curated sets PokeAPI has no flag for (with sources) ---------------------

# Ultra Beasts: the 11 officially classified Ultra Beasts (Bulbapedia: "Ultra Beast"),
# plus Necrozma which Pokepelago gates here for its Ultra-Space origin. Necrozma is a
# deliberate project choice, not an official UB -- keep it documented.
UB_OFFICIAL = frozenset({793, 794, 795, 796, 797, 798, 799, 803, 804, 805, 806})
UB_PROJECT_EXTRA = frozenset({800})  # Necrozma -- judgment call
ULTRA_BEAST_EXPECTED = UB_OFFICIAL | UB_PROJECT_EXTRA

# Paradox Pokemon (Bulbapedia: "Paradox Pokemon"): the 18 paradox forms + the DLC four-
# pair, plus Koraidon/Miraidon which are also box legendaries (both gates apply).
PARADOX_EXPECTED = frozenset({
    984, 985, 986, 987, 988, 989,        # Scarlet ancient paradox
    990, 991, 992, 993, 994, 995,        # Violet future paradox
    1005, 1006,                          # Roaring Moon, Iron Valiant
    1007, 1008,                          # Koraidon, Miraidon
    1009, 1010,                          # Walking Wake, Iron Leaves
    1020, 1021, 1022, 1023,              # Gouging Fire, Raging Bolt, Iron Boulder, Iron Crown
})

# Fossils are a fixed historical roster (no PokeAPI flag, no Gen 7 / Gen 9 additions).
FOSSIL_EXPECTED = frozenset({
    138, 139, 140, 141, 142,             # Gen 1
    345, 346, 347, 348,                  # Gen 3
    408, 409, 410, 411,                  # Gen 4
    564, 565, 566, 567,                  # Gen 5
    696, 697, 698, 699,                  # Gen 6
    880, 881, 882, 883,                  # Gen 8
})

# --- Documented exclusions for evolution-derived sets ------------------------

# Trade-evolution species that PokeAPI records with a trade trigger but that also have a
# non-trade method, so Pokepelago does not gate them behind a Link Cable.
TRADE_EXCLUDE = frozenset({350})  # Milotic -- also evolves via high Beauty / level-up

# Stone-evolution rows where the national-dex number is shared with a regional form that
# uses a stone the base form does not. Pokepelago gates by national dex number, so the
# base form's method wins and the regional-form stone is excluded.
STONE_EXCLUDE = {
    "leaf": frozenset({101}),            # Hisuian Electrode (Kantonian Electrode = level-up)
    "ice":  frozenset({28, 38, 555}),    # Alolan Sandslash / Alolan Ninetales / Galarian Darmanitan
}

STONE_ITEM_NAMES = {
    "fire": "fire-stone", "water": "water-stone", "thunder": "thunder-stone",
    "leaf": "leaf-stone", "moon": "moon-stone", "sun": "sun-stone",
    "shiny": "shiny-stone", "dusk": "dusk-stone", "dawn": "dawn-stone", "ice": "ice-stone",
}

NATIONAL_DEX_MAX = 10000  # form/variety rows use ids above this; base species are below


def gql(query: str) -> dict:
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps({"query": query}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "pokepelago-classification-audit/1.0"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read())
    if "errors" in payload:
        raise RuntimeError(f"PokeAPI GraphQL errors: {payload['errors']}")
    return payload["data"]


def fetch_expected() -> dict:
    """Derive every classification set from PokeAPI plus the curated constants above."""
    def species_with(flag: str) -> set:
        rows = gql("{ pokemonspecies(where: {%s: {_eq: true}}, order_by: {id: asc}) { id } }" % flag)
        return {r["id"] for r in rows["pokemonspecies"]}

    legendary = species_with("is_legendary")
    mythical = species_with("is_mythical")
    baby = species_with("is_baby")

    trade_rows = gql("{ pokemonevolution(where: {evolution_trigger_id: {_eq: 2}}) { evolved_species_id } }")
    useitem_rows = gql("{ pokemonevolution(where: {evolution_trigger_id: {_eq: 3}}) { evolved_species_id evolution_item_id } }")
    items = {r["id"]: r["name"] for r in gql("{ item(where: {id: {_lt: 2000}}) { id name } }")["item"]}

    base = lambda i: i is not None and i < NATIONAL_DEX_MAX
    trade = {r["evolved_species_id"] for r in trade_rows["pokemonevolution"] if base(r["evolved_species_id"])}
    # Gen 9 sometimes records classic trade evolutions as a Linking Cord use-item trigger.
    linking = {r["evolved_species_id"] for r in useitem_rows["pokemonevolution"]
               if base(r["evolved_species_id"]) and items.get(r["evolution_item_id"]) == "linking-cord"}
    trade = (trade | linking) - TRADE_EXCLUDE

    stone = {k: set() for k in STONE_ITEM_NAMES}
    for r in useitem_rows["pokemonevolution"]:
        sid, name = r["evolved_species_id"], items.get(r["evolution_item_id"])
        if not base(sid):
            continue
        for group, item_name in STONE_ITEM_NAMES.items():
            if name == item_name:
                stone[group].add(sid)
    for group, excl in STONE_EXCLUDE.items():
        stone[group] -= excl

    return {
        "legendary": legendary,          # is_legendary union (split into SUB/BOX in data.py)
        "mythical": mythical,
        "baby": baby,
        "ultra_beast": set(ULTRA_BEAST_EXPECTED),
        "paradox": set(PARADOX_EXPECTED),
        "fossil": set(FOSSIL_EXPECTED),
        "trade_evo": trade,
        "stone_evo": {k: stone[k] for k in STONE_ITEM_NAMES},
    }


def _load_data_module():
    """Import data.py standalone (it has no AP dependencies)."""
    spec = importlib.util.spec_from_file_location("pokepelago_data", os.path.abspath(DATA_PY))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_committed() -> dict:
    """Load the frozensets currently committed in data.py (no AP env needed)."""
    mod = _load_data_module()
    return {
        "legendary": set(mod.LEGENDARY_SUB_IDS | mod.LEGENDARY_BOX_IDS),
        "mythical": set(mod.LEGENDARY_MYTHIC_IDS),
        "baby": set(mod.BABY_IDS),
        "ultra_beast": set(mod.ULTRA_BEAST_IDS),
        "paradox": set(mod.PARADOX_IDS),
        "fossil": set(mod.FOSSIL_IDS),
        "trade_evo": set(mod.TRADE_EVO_IDS),
        "stone_evo": {k: set(v) for k, v in mod.STONE_EVO_GROUPS.items()},
        "_overlap": [
            ("SUB&BOX", sorted(mod.LEGENDARY_SUB_IDS & mod.LEGENDARY_BOX_IDS)),
            ("SUB&MYTHIC", sorted(mod.LEGENDARY_SUB_IDS & mod.LEGENDARY_MYTHIC_IDS)),
            ("BOX&MYTHIC", sorted(mod.LEGENDARY_BOX_IDS & mod.LEGENDARY_MYTHIC_IDS)),
        ],
    }


def diff(expected: dict, committed: dict) -> list:
    """Return a list of human-readable discrepancy strings (empty == all good)."""
    problems = []
    flat_keys = ["legendary", "mythical", "baby", "ultra_beast", "paradox", "fossil", "trade_evo"]
    for key in flat_keys:
        miss = sorted(expected[key] - committed[key])
        extra = sorted(committed[key] - expected[key])
        if miss:
            problems.append(f"{key}: MISSING from data.py (authoritative says these belong): {miss}")
        if extra:
            problems.append(f"{key}: EXTRA in data.py (authoritative does not list these): {extra}")
    for group in STONE_ITEM_NAMES:
        exp, com = expected["stone_evo"][group], committed["stone_evo"].get(group, set())
        miss, extra = sorted(exp - com), sorted(com - exp)
        if miss:
            problems.append(f"stone_evo[{group}]: MISSING {miss}")
        if extra:
            problems.append(f"stone_evo[{group}]: EXTRA {extra}")
    for label, ids in committed.get("_overlap", []):
        if ids:
            problems.append(f"legendary tiers overlap ({label}): {ids} (a Pokemon must be in exactly one tier)")
    return problems


def write_client_gates(out_path: str) -> None:
    """Project data.py's gate sets into the client's pokemon_gates.ts.

    The client's GameContext.isPokemonGuessable() / useGateChecks enforce the same
    locks client-side, so this file must mirror data.py exactly or the client and
    APWorld will disagree about what is gated (BUG-12 / BUG-16). data.py is the single
    source of truth; this regenerates the TypeScript mirror from it.
    """
    mod = _load_data_module()

    def emit_set(name, ids):
        nums = sorted(ids)
        rows = [", ".join(str(n) for n in nums[i:i + 12]) for i in range(0, len(nums), 12)]
        body = ",\n    ".join(rows)
        return f"export const {name} = new Set<number>([\n    {body},\n]);\n"

    stone_groups = mod.STONE_EVO_GROUPS  # preserves data.py insertion order
    stone_lines = ",\n".join(
        f"    {group}: new Set([{', '.join(str(n) for n in sorted(ids))}])"
        for group, ids in stone_groups.items()
    )
    stone_order = ", ".join(f"'{g}'" for g in stone_groups)

    parts = [
        "/**",
        " * pokemon_gates.ts",
        " *",
        " * AUTO-GENERATED from worlds/pokepelago/data.py by",
        " * tools/build_classification_data.py --write-gates. DO NOT EDIT BY HAND.",
        " *",
        " * Mirror of the APWorld gate-classification sets, consumed by",
        " * GameContext.isPokemonGuessable() / useGateChecks to enforce locks client-side.",
        " * Regenerate after any data.py classification change so the client and the",
        " * APWorld never disagree about what is gated (see BUG-12 / BUG-16).",
        " */",
        "",
        "// Sub-legendaries — require 6 Gym Badges",
        emit_set("SUB_LEGENDARY_IDS", mod.LEGENDARY_SUB_IDS),
        "// Box legendaries — require 7 Gym Badges",
        emit_set("BOX_LEGENDARY_IDS", mod.LEGENDARY_BOX_IDS),
        "// Mythics — require 8 Gym Badges",
        emit_set("MYTHIC_IDS", mod.LEGENDARY_MYTHIC_IDS),
        "// Baby Pokémon — require Daycare item(s)",
        emit_set("BABY_IDS", mod.BABY_IDS),
        "// Trade-evolved Pokémon — require Link Cable",
        emit_set("TRADE_EVO_IDS", mod.TRADE_EVO_IDS),
        "// Fossil Pokémon — require Fossil Restorer",
        emit_set("FOSSIL_IDS", mod.FOSSIL_IDS),
        "// Ultra Beasts — require Ultra Wormhole (Necrozma #800 included by project choice)",
        emit_set("ULTRA_BEAST_IDS", mod.ULTRA_BEAST_IDS),
        "// Paradox Pokémon — require Time Rift",
        emit_set("PARADOX_IDS", mod.PARADOX_IDS),
        "// Stone-only evolutions — require the matching evolutionary stone item.",
        "export const STONE_EVO_IDS: Record<string, Set<number>> = {\n" + stone_lines + ",\n};\n",
        "// Ordered stone names matching APWorld item ID offsets (6010 + index)",
        f"export const STONE_NAMES_ORDERED = [\n    {stone_order},\n] as const;\n",
    ]
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(parts))
    print(f"wrote {out_path}")


def to_snapshot(expected: dict) -> dict:
    snap = {k: sorted(expected[k]) for k in
            ["legendary", "mythical", "baby", "ultra_beast", "paradox", "fossil", "trade_evo"]}
    snap["stone_evo"] = {k: sorted(expected["stone_evo"][k]) for k in STONE_ITEM_NAMES}
    return snap


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="diff committed data.py against live PokeAPI")
    ap.add_argument("--snapshot", action="store_true", help="write classification_snapshot.json from live PokeAPI")
    ap.add_argument("--write-gates", metavar="PATH",
                    help="regenerate the client's pokemon_gates.ts from data.py (no network)")
    args = ap.parse_args()
    if not (args.check or args.snapshot or args.write_gates):
        ap.error("pass --check, --snapshot, and/or --write-gates")

    # --write-gates is a pure data.py -> TS projection; it needs no network.
    if args.write_gates:
        write_client_gates(args.write_gates)
        if not (args.check or args.snapshot):
            return 0

    expected = fetch_expected()

    if args.snapshot:
        with open(SNAPSHOT, "w", encoding="utf-8") as fh:
            json.dump(to_snapshot(expected), fh, indent=2)
            fh.write("\n")
        print(f"wrote {SNAPSHOT}")

    if args.check:
        problems = diff(expected, load_committed())
        if problems:
            print("CLASSIFICATION DRIFT DETECTED:")
            for p in problems:
                print("  - " + p)
            print("\nFix data.py, or update the documented exclusions/curated sets in this tool, "
                  "then re-run with --snapshot to refresh the offline test fixture.")
            return 1
        print("classification sets match PokeAPI source of truth (no drift)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
