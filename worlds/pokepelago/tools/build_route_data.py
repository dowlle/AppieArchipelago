"""
Pull encounter, species, and evolution data from PokeAPI GraphQL and generate route_data.py.

Uses 3 bulk GraphQL queries instead of thousands of REST calls:
1. All encounters for Pokemon 1-1025 (~60k records)
2. All species data (is_baby, is_legendary, is_mythical, evolution_chain_id)
3. All evolution records (triggers, items)

Usage:
    python -m worlds.pokepelago.tools.build_route_data
    # Or: .venv/Scripts/python.exe worlds/pokepelago/tools/build_route_data.py

Requires: requests (pip install requests)
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests")
    sys.exit(1)

GRAPHQL_URL = "https://beta.pokeapi.co/graphql/v1beta"
MAX_POKEMON_ID = 1025

# Region dex ranges (mirrors data.py)
REGION_RANGES: dict[str, tuple[int, int]] = {
    "Kanto": (1, 151), "Johto": (152, 251), "Hoenn": (252, 386),
    "Sinnoh": (387, 493), "Unova": (494, 649), "Kalos": (650, 721),
    "Alola": (722, 809), "Galar": (810, 898), "Hisui": (899, 905),
    "Paldea": (906, 1025),
}

# Stone item name mapping (PokeAPI name → our short name)
STONE_MAP: dict[str, str] = {
    "fire-stone": "fire", "water-stone": "water", "thunder-stone": "thunder",
    "leaf-stone": "leaf", "moon-stone": "moon", "sun-stone": "sun",
    "shiny-stone": "shiny", "dusk-stone": "dusk", "dawn-stone": "dawn",
    "ice-stone": "ice",
}

# Cache dir for raw GraphQL responses
CACHE_DIR = Path(__file__).parent / ".api_cache"


def get_pokemon_region(mon_id: int) -> str:
    for region_name, (lo, hi) in REGION_RANGES.items():
        if lo <= mon_id <= hi:
            return region_name
    return "Unknown"


# ── GraphQL queries ──────────────────────────────────────────────────────────

def gql_query(query: str, cache_key: str) -> dict:
    """Execute a GraphQL query with file-based caching."""
    CACHE_DIR.mkdir(exist_ok=True)
    cache_file = CACHE_DIR / f"gql_{cache_key}.json"

    if cache_file.exists():
        print(f"  Using cached {cache_key}")
        return json.loads(cache_file.read_text(encoding="utf-8"))

    print(f"  Fetching {cache_key} from GraphQL API...")
    resp = requests.post(GRAPHQL_URL, json={"query": query}, timeout=120)
    resp.raise_for_status()
    data = resp.json()

    if "errors" in data:
        print(f"  GraphQL errors: {data['errors']}")
        sys.exit(1)

    cache_file.write_text(json.dumps(data), encoding="utf-8")
    return data


def fetch_all_encounters() -> list[dict]:
    """Fetch all encounter records for Pokemon 1-1025."""
    query = """
    {
        pokemon_v2_encounter(where: {pokemon_id: {_lte: 1025}}) {
            pokemon_id
            min_level
            pokemon_v2_locationarea {
                name
                pokemon_v2_location {
                    name
                    pokemon_v2_region { name }
                }
            }
            pokemon_v2_version { name }
        }
    }
    """
    data = gql_query(query, "encounters")
    return data["data"]["pokemon_v2_encounter"]


def fetch_all_species() -> list[dict]:
    """Fetch species data for Pokemon 1-1025."""
    query = """
    {
        pokemon_v2_pokemonspecies(where: {id: {_lte: 1025}}, order_by: {id: asc}) {
            id
            name
            is_baby
            is_legendary
            is_mythical
            evolution_chain_id
        }
    }
    """
    data = gql_query(query, "species")
    return data["data"]["pokemon_v2_pokemonspecies"]


def fetch_all_evolutions() -> list[dict]:
    """Fetch all evolution records with triggers and items."""
    query = """
    {
        pokemon_v2_pokemonevolution {
            evolved_species_id
            min_level
            pokemon_v2_evolutiontrigger { name }
            pokemon_v2_item { name }
        }
    }
    """
    data = gql_query(query, "evolutions")
    return data["data"]["pokemon_v2_pokemonevolution"]


# ── Data processing ──────────────────────────────────────────────────────────

def collapse_location_name(area_name: str) -> str:
    """Collapse sub-area names into parent location names."""
    suffixes = [
        "-area", "-1f", "-2f", "-3f", "-4f", "-5f",
        "-b1f", "-b2f", "-b3f", "-b4f", "-b5f",
        "-entrance", "-inside", "-outside",
    ]
    result = area_name
    for suffix in suffixes:
        if result.endswith(suffix):
            result = result[: -len(suffix)]
            break
    return result


def process_encounters(raw_encounters: list[dict]) -> tuple[
    dict[str, dict],           # routes: route_key → {display_name, region, pokemon: {id: min_level}}
    dict[int, list[str]],      # pokemon_routes: pokemon_id → [route_keys]
]:
    """Process raw encounter data into route structures."""
    routes: dict[str, dict] = {}
    pokemon_routes: dict[int, list[str]] = defaultdict(list)

    for enc in raw_encounters:
        pokemon_id = enc["pokemon_id"]
        min_level = enc["min_level"]
        area = enc["pokemon_v2_locationarea"]
        location = area["pokemon_v2_location"]
        region_data = location["pokemon_v2_region"]

        # Collapse sub-areas into parent location
        route_key = collapse_location_name(area["name"])

        # Determine region from the location's region field
        region_name = region_data["name"].title() if region_data else get_pokemon_region(pokemon_id)

        if route_key not in routes:
            display_name = route_key.replace("-", " ").title()
            routes[route_key] = {
                "display_name": display_name,
                "region": region_name,
                "pokemon": {},
            }

        # Keep lowest encounter level per Pokemon per route
        current = routes[route_key]["pokemon"].get(pokemon_id)
        if current is None or min_level < current:
            routes[route_key]["pokemon"][pokemon_id] = min_level

        if route_key not in pokemon_routes[pokemon_id]:
            pokemon_routes[pokemon_id].append(route_key)

    return routes, dict(pokemon_routes)


def process_species(raw_species: list[dict]) -> tuple[
    set[int],                  # baby_ids
    set[int],                  # legendary_ids
    set[int],                  # mythical_ids
    dict[int, int],            # species_to_chain: species_id → evolution_chain_id
]:
    """Extract species flags and chain mappings."""
    baby_ids: set[int] = set()
    legendary_ids: set[int] = set()
    mythical_ids: set[int] = set()
    species_to_chain: dict[int, int] = {}

    for sp in raw_species:
        sid = sp["id"]
        if sp["is_baby"]:
            baby_ids.add(sid)
        if sp["is_legendary"]:
            legendary_ids.add(sid)
        if sp["is_mythical"]:
            mythical_ids.add(sid)
        if sp["evolution_chain_id"]:
            species_to_chain[sid] = sp["evolution_chain_id"]

    return baby_ids, legendary_ids, mythical_ids, species_to_chain


def process_evolutions(
    raw_evolutions: list[dict],
    species_to_chain: dict[int, int],
) -> tuple[
    dict[int, frozenset[int]],  # families: base_id → all IDs
    dict[int, int],             # family_base: any_id → base_id
    set[int],                   # trade_evo_ids
    dict[str, set[int]],        # stone_evo_groups
]:
    """Build evolution families, identify trade evos and stone evos."""
    # Group species by chain_id to build families
    chain_members: dict[int, set[int]] = defaultdict(set)
    for species_id, chain_id in species_to_chain.items():
        if species_id <= MAX_POKEMON_ID:
            chain_members[chain_id].add(species_id)

    # Base form is the lowest ID in each chain
    families: dict[int, frozenset[int]] = {}
    family_base: dict[int, int] = {}
    for chain_id, members in chain_members.items():
        base_id = min(members)
        families[base_id] = frozenset(members)
        for pid in members:
            family_base[pid] = base_id

    # Extract trade evos and stone evos from evolution triggers
    trade_evo_ids: set[int] = set()
    stone_evo_groups: dict[str, set[int]] = defaultdict(set)

    for evo in raw_evolutions:
        evolved_id = evo["evolved_species_id"]
        if evolved_id > MAX_POKEMON_ID:
            continue

        trigger = evo.get("pokemon_v2_evolutiontrigger", {})
        trigger_name = trigger.get("name", "") if trigger else ""

        item = evo.get("pokemon_v2_item", {})
        item_name = item.get("name", "") if item else ""

        if trigger_name == "trade":
            trade_evo_ids.add(evolved_id)

        if trigger_name == "use-item" and item_name in STONE_MAP:
            stone_evo_groups[STONE_MAP[item_name]].add(evolved_id)

    return families, family_base, trade_evo_ids, dict(stone_evo_groups)


# ── Output writers ───────────────────────────────────────────────────────────

def write_route_data(
    routes: dict[str, dict],
    pokemon_routes: dict[int, list[str]],
    families: dict[int, frozenset[int]],
    family_base: dict[int, int],
    trade_evo_ids: set[int],
    stone_evo_groups: dict[str, set[int]],
    baby_ids: set[int],
    legendary_ids: set[int],
    mythical_ids: set[int],
    orphans_by_region: dict[str, set[int]],
) -> None:
    """Write the generated route_data.py file."""
    output_path = Path(__file__).parent.parent / "route_data.py"
    lines: list[str] = []

    lines += [
        '"""',
        "Auto-generated by tools/build_route_data.py from PokeAPI GraphQL.",
        "Do not edit manually — re-run the build script to update.",
        "",
        "Run: python -m worlds.pokepelago.tools.build_route_data",
        '"""',
        "",
        "# Default badge -> max level thresholds (0 badges = up to lv10, 8 badges = all)",
        "BADGE_LEVEL_THRESHOLDS: list[int] = [10, 20, 30, 40, 50, 60, 70, 100]",
        "",
    ]

    # Route data
    lines += ["", "# Route encounters: route_key -> {display_name, region, pokemon: {id: min_level}}"]
    lines += [f"ROUTE_DATA: dict[str, dict] = {{"]
    for route_key in sorted(routes.keys()):
        route = routes[route_key]
        pokemon_str = ", ".join(f"{pid}: {lvl}" for pid, lvl in sorted(route["pokemon"].items()))
        lines += [
            f'    "{route_key}": {{',
            f'        "display_name": "{route["display_name"]}",',
            f'        "region": "{route["region"]}",',
            f'        "pokemon": {{{pokemon_str}}},',
            f"    }},",
        ]
    lines += ["}", ""]

    # Pokemon → routes
    lines += ["", "# Pokemon ID -> list of route keys where it can be encountered"]
    lines += ["POKEMON_ROUTES: dict[int, list[str]] = {"]
    for pid in sorted(pokemon_routes.keys()):
        r_list = ", ".join(f'"{r}"' for r in sorted(pokemon_routes[pid]))
        lines += [f"    {pid}: [{r_list}],"]
    lines += ["}", ""]

    # Evolution families
    lines += ["", "# Evolution families: base_pokemon_id -> frozenset of all IDs in the family"]
    lines += ["EVOLUTION_FAMILIES: dict[int, frozenset[int]] = {"]
    for base_id in sorted(families.keys()):
        ids_str = ", ".join(str(i) for i in sorted(families[base_id]))
        lines += [f"    {base_id}: frozenset([{ids_str}]),"]
    lines += ["}", ""]

    # Family base reverse lookup
    lines += ["", "# Any Pokemon ID -> base form ID of its evolution family"]
    lines += ["FAMILY_BASE: dict[int, int] = {"]
    for pid in sorted(family_base.keys()):
        lines += [f"    {pid}: {family_base[pid]},"]
    lines += ["}", ""]

    # API-derived categorization sets
    lines += ["", "# ── API-derived categorization sets ──"]
    lines += ["# Auto-generated from PokeAPI. Compare with hand-maintained sets in data.py.", ""]
    _write_frozenset(lines, "API_BABY_IDS", baby_ids)
    _write_frozenset(lines, "API_LEGENDARY_IDS", legendary_ids)
    _write_frozenset(lines, "API_MYTHICAL_IDS", mythical_ids)
    _write_frozenset(lines, "API_TRADE_EVO_IDS", trade_evo_ids)
    lines += [""]
    lines += ["API_STONE_EVO_GROUPS: dict[str, frozenset[int]] = {"]
    for stone in sorted(stone_evo_groups.keys()):
        ids_str = ", ".join(str(i) for i in sorted(stone_evo_groups[stone]))
        lines += [f'    "{stone}": frozenset([{ids_str}]),']
    lines += ["}", ""]

    # Orphans
    lines += ["", "# ── Orphan Pokemon (no encounter data, need virtual routes) ──"]
    all_orphans: set[int] = set()
    for region_name, orphans in sorted(orphans_by_region.items()):
        if orphans:
            all_orphans.update(orphans)
            ids_str = ", ".join(str(i) for i in sorted(orphans))
            lines += [f"# {region_name} ({len(orphans)} orphans): [{ids_str}]"]
    lines += [f"# Total orphans: {len(all_orphans)}", ""]
    _write_frozenset(lines, "ORPHAN_IDS", all_orphans)
    lines += [""]

    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {output_path} ({len(lines)} lines)")


def _write_frozenset(lines: list[str], name: str, ids: set[int]) -> None:
    ids_str = ", ".join(str(i) for i in sorted(ids))
    lines += [f"{name}: frozenset[int] = frozenset([{ids_str}])"]


def write_validation_report(
    trade_evo_ids: set[int],
    stone_evo_groups: dict[str, set[int]],
    baby_ids: set[int],
    legendary_ids: set[int],
    mythical_ids: set[int],
) -> None:
    """Compare API data with hand-maintained sets in data.py."""
    report_path = Path(__file__).parent / "validation_report.txt"

    try:
        sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
        from worlds.pokepelago.data import (
            BABY_IDS, TRADE_EVO_IDS, LEGENDARY_SUB_IDS, LEGENDARY_BOX_IDS,
            LEGENDARY_MYTHIC_IDS, STONE_EVO_GROUPS,
        )
    except ImportError:
        print("  WARNING: Could not import data.py for validation")
        return

    lines: list[str] = [
        "Validation Report: API data vs hand-maintained sets in data.py",
        "=" * 70, "",
    ]

    _compare(lines, "BABY_IDS", BABY_IDS, baby_ids)
    _compare(lines, "TRADE_EVO_IDS", TRADE_EVO_IDS, trade_evo_ids)
    _compare(lines, "LEGENDARY_MYTHIC_IDS", LEGENDARY_MYTHIC_IDS, mythical_ids)
    _compare(lines, "LEGENDARY_SUB+BOX_IDS", LEGENDARY_SUB_IDS | LEGENDARY_BOX_IDS, legendary_ids)

    for stone in sorted(set(list(STONE_EVO_GROUPS.keys()) + list(stone_evo_groups.keys()))):
        current = STONE_EVO_GROUPS.get(stone, frozenset())
        api = stone_evo_groups.get(stone, set())
        _compare(lines, f"STONE[{stone}]", current, api)

    lines += [
        "", "Cannot auto-detect (manual curation required):",
        "  - Ultra Beast status", "  - Paradox Pokemon status",
        "  - Fossil Pokemon status", "  - Legendary sub vs box tier",
    ]

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {report_path}")


def _compare(lines: list[str], name: str, current: frozenset | set, api: set) -> None:
    current_set = set(current)
    missing = current_set - api
    extra = api - current_set
    lines += [f"{name}: current={len(current_set)}, api={len(api)}"]
    if missing:
        lines += [f"  In current but NOT in API: {sorted(missing)}"]
    if extra:
        lines += [f"  In API but NOT in current: {sorted(extra)}"]
    if not missing and not extra:
        lines += [f"  MATCH"]
    lines += [""]


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("PokeAPI Route Data Builder (GraphQL)")
    print("=" * 60)

    # 3 bulk queries
    raw_encounters = fetch_all_encounters()
    print(f"  Encounters: {len(raw_encounters)} records")

    raw_species = fetch_all_species()
    print(f"  Species: {len(raw_species)} records")

    raw_evolutions = fetch_all_evolutions()
    print(f"  Evolutions: {len(raw_evolutions)} records")

    # Process
    print("\nProcessing encounters...")
    routes, pokemon_routes = process_encounters(raw_encounters)
    print(f"  {len(routes)} routes, {len(pokemon_routes)} Pokemon with encounters")

    print("Processing species...")
    baby_ids, legendary_ids, mythical_ids, species_to_chain = process_species(raw_species)

    print("Processing evolutions...")
    families, family_base, trade_evo_ids, stone_evo_groups = process_evolutions(
        raw_evolutions, species_to_chain
    )
    print(f"  {len(families)} families, {len(trade_evo_ids)} trade evos, {len(stone_evo_groups)} stone types")

    # Orphans
    orphans_by_region: dict[str, set[int]] = {}
    for region_name, (lo, hi) in REGION_RANGES.items():
        region_ids = set(range(lo, hi + 1))
        with_routes = {pid for pid in region_ids if pid in pokemon_routes}
        orphans = region_ids - with_routes
        if orphans:
            orphans_by_region[region_name] = orphans

    # Summary
    total_with_routes = len(pokemon_routes)
    total_orphans = MAX_POKEMON_ID - total_with_routes
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"Routes: {len(routes)}")
    print(f"Pokemon with encounters: {total_with_routes}/{MAX_POKEMON_ID}")
    print(f"Orphans: {total_orphans}")
    print(f"Evolution families: {len(families)}")
    print(f"Trade evos: {len(trade_evo_ids)}")
    print(f"Stone types: {len(stone_evo_groups)}")
    print(f"Babies: {len(baby_ids)}, Legendaries: {len(legendary_ids)}, Mythicals: {len(mythical_ids)}")
    print()
    for region_name, orphans in sorted(orphans_by_region.items()):
        print(f"  {region_name}: {len(orphans)} orphans")

    # Write
    write_route_data(routes, pokemon_routes, families, family_base,
                     trade_evo_ids, stone_evo_groups, baby_ids, legendary_ids,
                     mythical_ids, orphans_by_region)

    write_validation_report(trade_evo_ids, stone_evo_groups, baby_ids,
                            legendary_ids, mythical_ids)

    print("\nDone!")


if __name__ == "__main__":
    main()
