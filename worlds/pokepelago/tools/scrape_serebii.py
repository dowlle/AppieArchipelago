"""
Serebii scraper for Gen 8-9 encounter data.

Fills gaps where PokeAPI has no encounter data:
- Galar (Sword/Shield): per-area pages on pokearth
- Hisui (Legends Arceus): spawn tables via area page JavaScript
- Paldea (Scarlet/Violet): spawn tables via area page JavaScript

Scrapes ALL encounters (not just orphans) for cross-region route support.

Usage:
    python -m worlds.pokepelago.tools.scrape_serebii

Writes to tools/serebii_encounters.json for merging into route_data.py.

Requires: requests, beautifulsoup4
    pip install requests beautifulsoup4
"""
import json
import re
import sys
import time
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: Install dependencies: pip install requests beautifulsoup4")
    sys.exit(1)

CACHE_DIR = Path(__file__).parent / ".serebii_cache"
REQUEST_DELAY = 1.0
OUTPUT_FILE = Path(__file__).parent / "serebii_encounters.json"

# Build Pokemon name → national dex ID lookup
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from worlds.pokepelago.data import POKEMON_DATA

_NAME_TO_ID: dict[str, int] = {}
_BASE_NAME_TO_ID: dict[str, int] = {}  # First word of multi-word names → ID
for _mon in POKEMON_DATA:
    _lower = _mon["name"].lower()
    _NAME_TO_ID[_lower] = _mon["id"]
    # For form-names like "Eiscue Ice", also index by base name "eiscue"
    _parts = _lower.split()
    if len(_parts) > 1:
        _BASE_NAME_TO_ID.setdefault(_parts[0], _mon["id"])

# Additional name mappings for Serebii variants
_NAME_ALIASES: dict[str, str] = {
    "nidoran♀": "nidoran-f", "nidoran♂": "nidoran-m",
    "mr. mime": "mr. mime", "mr.mime": "mr. mime",
    "mime jr.": "mime jr.", "mimejr.": "mime jr.",
    "farfetch'd": "farfetch'd", "farfetchd": "farfetch'd",
    "sirfetch'd": "sirfetch'd", "sirfetchd": "sirfetch'd",
    "type: null": "type: null", "type:null": "type: null",
    "flabébé": "flabebe",
}

# Regional form prefixes to strip (map to base species)
_FORM_PREFIXES = [
    "hisuian ", "galarian ", "alolan ", "paldean ",
    "attack ", "defense ", "speed ",  # Deoxys
    "heat ", "wash ", "frost ", "fan ", "mow ",  # Rotom
    "origin ", "altered ",  # Giratina
    "therian ", "incarnate ",  # Forces of Nature
    "black ", "white ",  # Kyurem
    "10% ", "50% ", "complete ",  # Zygarde
    "dusk mane ", "dawn wings ", "ultra ",  # Necrozma
    "ice rider ", "shadow rider ",  # Calyrex
    "crowned ",  # Zacian/Zamazenta
    "single strike ", "rapid strike ",  # Urshifu
    "bloodmoon ",  # Ursaluna
]


def normalize_name(raw: str) -> int | None:
    """Resolve a Serebii Pokemon name to a national dex ID."""
    name = raw.strip().lower()
    if not name:
        return None

    # Direct match
    pid = _NAME_TO_ID.get(name)
    if pid:
        return pid

    # Alias match
    alias = _NAME_ALIASES.get(name)
    if alias:
        pid = _NAME_TO_ID.get(alias)
        if pid:
            return pid

    # Strip regional/form prefixes
    for prefix in _FORM_PREFIXES:
        if name.startswith(prefix):
            base = name[len(prefix):]
            pid = _NAME_TO_ID.get(base)
            if pid:
                return pid

    # Strip parenthetical form info: "Wormadam (Plant Cloak)" -> "wormadam"
    paren = name.split("(")[0].strip()
    if paren != name:
        pid = _NAME_TO_ID.get(paren)
        if pid:
            return pid

    # Base name fallback: "eiscue" matches "eiscue ice" (875)
    # Handles Serebii using short names for form-Pokemon in POKEMON_DATA
    pid = _BASE_NAME_TO_ID.get(name)
    if pid:
        return pid

    return None


def fetch_html(url: str) -> str | None:
    """Fetch HTML with file-based caching."""
    CACHE_DIR.mkdir(exist_ok=True)
    cache_key = re.sub(r'[^\w]', '_', url.replace("https://www.serebii.net/", ""))
    cache_file = CACHE_DIR / f"{cache_key}.html"

    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8", errors="replace")

    print(f"  GET {url}")
    try:
        resp = requests.get(url, timeout=30, headers={
            "User-Agent": "PokePelago-DataBuilder/1.0 (Archipelago multiworld game; non-commercial)"
        })
        if resp.status_code == 404:
            print(f"    -> 404")
            return None
        resp.raise_for_status()
        html = resp.text
        cache_file.write_text(html, encoding="utf-8")
        time.sleep(REQUEST_DELAY)
        return html
    except requests.RequestException as e:
        print(f"    -> ERROR: {e}")
        return None


def parse_level_range(text: str) -> int | None:
    """Extract the minimum level from a level range string like '3 - 6' or '60'."""
    m = re.search(r'(\d+)\s*-\s*(\d+)', text)
    if m:
        return int(m.group(1))
    m = re.search(r'(\d+)', text)
    if m:
        return int(m.group(1))
    return None


# ── Galar: Scrape per-area pokearth pages ──────────────────────────────────

# Area slug → display name for all Galar areas
GALAR_AREAS: dict[str, str] = {
    # Main routes
    "route1": "Route 1", "route2": "Route 2", "route3": "Route 3",
    "route4": "Route 4", "route5": "Route 5", "route6": "Route 6",
    "route7": "Route 7", "route8": "Route 8", "route9": "Route 9",
    "route10": "Route 10",
    # Towns with encounters
    "slumberingweald": "Slumbering Weald",
    "galarmine": "Galar Mine", "galarmine2": "Galar Mine No. 2",
    "motostokeoutskirts": "Motostoke Outskirts",
    "glimwoodtangle": "Glimwood Tangle",
    "route9tunnel": "Route 9 Tunnel",
    # Wild Area South
    "meetupspot": "Meetup Spot", "rollingfields": "Rolling Fields",
    "dappledgrove": "Dappled Grove", "watchtowerruins": "Watchtower Ruins",
    "eastlakeaxewell": "East Lake Axewell", "westlakeaxewell": "West Lake Axewell",
    "axewseye": "Axew's Eye", "southlakemiloch": "South Lake Miloch",
    "giantsseat": "Giant's Seat",
    # Wild Area North
    "northlakemiloch": "North Lake Miloch",
    "motostokeriverbank": "Motostoke Riverbank",
    "bridgefield": "Bridge Field", "stonywilderness": "Stony Wilderness",
    "dustybowl": "Dusty Bowl", "giantsmirror": "Giant's Mirror",
    "hammerlockhills": "Hammerlocke Hills", "giantscap": "Giant's Cap",
    "lakeofoutrage": "Lake of Outrage",
    # Isle of Armor
    "fieldsofhonor": "Fields of Honor", "soothingwetlands": "Soothing Wetlands",
    "forestoffocus": "Forest of Focus", "challengebeach": "Challenge Beach",
    "challengeroad": "Challenge Road", "courageouscavern": "Courageous Cavern",
    "brawlerscave": "Brawlers' Cave", "looplagoon": "Loop Lagoon",
    "traininglowlands": "Training Lowlands", "warmuptunnel": "Warm-Up Tunnel",
    "potbottomdesert": "Potbottom Desert",
    "honeycalmisland": "Honeycalm Island", "honeycalmsea": "Honeycalm Sea",
    "insularsea": "Insular Sea", "steppingstonesea": "Stepping-Stone Sea",
    "workoutsea": "Workout Sea",
    # Crown Tundra
    "slipperyslope": "Slippery Slope", "frostpointfield": "Frostpoint Field",
    "giantsbed": "Giant's Bed", "oldcemetery": "Old Cemetery",
    "snowslideslope": "Snowslide Slope", "tunneltothetop": "Tunnel to the Top",
    "pathtothepeak": "Path to the Peak", "crownshrine": "Crown Shrine",
    "giantsfoot": "Giant's Foot", "roaringseacaves": "Roaring-Sea Caves",
    "frigidsea": "Frigid Sea", "threepointpass": "Three-Point Pass",
    "ballimlake": "Ballimere Lake", "lakesidecave": "Lakeside Cave",
    "dynatreehill": "Dyna Tree Hill",
}


def scrape_galar_area(slug: str) -> dict[int, int]:
    """Scrape a single Galar area page for Pokemon encounters.

    Returns {pokemon_id: min_level}.
    Galar area pages use the same class="name"/class="level" pattern as spawn tables.
    """
    url = f"https://www.serebii.net/pokearth/galar/{slug}.shtml"
    html = fetch_html(url)
    if not html:
        return {}

    soup = BeautifulSoup(html, "html.parser")
    pokemon_levels: dict[int, int] = {}

    name_cells = soup.find_all("td", class_="name")
    level_cells = soup.find_all("td", class_="level")

    for i, name_cell in enumerate(name_cells):
        raw_name = name_cell.get_text(strip=True)
        pid = normalize_name(raw_name)
        if not pid:
            continue

        level = None
        if i < len(level_cells):
            level = parse_level_range(level_cells[i].get_text(strip=True))
        if level is None:
            level = 5

        if pid not in pokemon_levels or level < pokemon_levels[pid]:
            pokemon_levels[pid] = level

    return pokemon_levels


def scrape_all_galar() -> dict[str, dict]:
    """Scrape all Galar area pages for encounter data."""
    print("\n=== Scraping Galar (Sword/Shield) encounters ===")
    encounters: dict[str, dict] = {}

    for slug, display_name in GALAR_AREAS.items():
        pokemon = scrape_galar_area(slug)
        if pokemon:
            route_key = f"galar-{slug}"
            encounters[route_key] = {
                "display_name": display_name,
                "region": "Galar",
                "pokemon": pokemon,
            }
            print(f"    {display_name}: {len(pokemon)} Pokemon")
        else:
            print(f"    {display_name}: no data")

    print(f"  Total: {len(encounters)} Galar routes")
    return encounters


# ── Hisui: Scrape spawn tables via area page JavaScript ────────────────────

HISUI_AREAS: dict[str, str] = {
    "obsidianfieldlands": "Obsidian Fieldlands",
    "crimsonmirelands": "Crimson Mirelands",
    "cobaltcoastlands": "Cobalt Coastlands",
    "coronethighlands": "Coronet Highlands",
    "alabastericelands": "Alabaster Icelands",
}


def extract_spawn_table_ids(html: str) -> list[int]:
    """Extract standard Pokemon spawn table IDs from pokearth area page JavaScript.

    Looks for pmarkers entries with pokeballIcon or alphaIcon layers.
    """
    table_ids: list[int] = []

    # Match tableID values from pmarkers JavaScript array
    # Pattern: {... tableID: 42, layer: layPokeball} or {... tableID: 82, layer: layAlpha}
    for m in re.finditer(r'tableID:\s*(\d+)\s*,\s*layer:\s*(lay\w+)', html):
        table_id = int(m.group(1))
        layer = m.group(2)
        if layer in ("layPokeball", "layAlpha"):
            table_ids.append(table_id)

    return sorted(set(table_ids))


def parse_hisui_spawn_table(html: str) -> dict[int, int]:
    """Parse a Hisui spawn table HTML for Pokemon names and levels.

    Format: class="name" cells for names, class="level" cells for levels.
    """
    soup = BeautifulSoup(html, "html.parser")
    pokemon_levels: dict[int, int] = {}

    name_cells = soup.find_all("td", class_="name")
    level_cells = soup.find_all("td", class_="level")

    for i, name_cell in enumerate(name_cells):
        raw_name = name_cell.get_text(strip=True)
        pid = normalize_name(raw_name)
        if not pid:
            continue

        level = None
        if i < len(level_cells):
            level = parse_level_range(level_cells[i].get_text(strip=True))
        if level is None:
            level = 5

        if pid not in pokemon_levels or level < pokemon_levels[pid]:
            pokemon_levels[pid] = level

    return pokemon_levels


def scrape_all_hisui() -> dict[str, dict]:
    """Scrape all Hisui areas by extracting spawn table IDs from area pages."""
    print("\n=== Scraping Hisui (Legends Arceus) encounters ===")
    encounters: dict[str, dict] = {}

    for slug, display_name in HISUI_AREAS.items():
        area_url = f"https://www.serebii.net/pokearth/hisui/{slug}.shtml"
        area_html = fetch_html(area_url)
        if not area_html:
            print(f"    {display_name}: failed to fetch area page")
            continue

        table_ids = extract_spawn_table_ids(area_html)
        print(f"    {display_name}: {len(table_ids)} spawn tables to fetch")

        area_pokemon: dict[int, int] = {}
        for tid in table_ids:
            table_url = f"https://www.serebii.net/pokearth/hisui/spawntable/{tid}.txt"
            table_html = fetch_html(table_url)
            if not table_html or len(table_html.strip()) < 10:
                continue
            pokemon = parse_hisui_spawn_table(table_html)
            for pid, level in pokemon.items():
                if pid not in area_pokemon or level < area_pokemon[pid]:
                    area_pokemon[pid] = level

        if area_pokemon:
            route_key = f"hisui-{slug}"
            encounters[route_key] = {
                "display_name": display_name,
                "region": "Hisui",
                "pokemon": area_pokemon,
            }
            print(f"    {display_name}: {len(area_pokemon)} unique Pokemon")
        else:
            print(f"    {display_name}: no Pokemon found")

    print(f"  Total: {len(encounters)} Hisui routes")
    return encounters


# ── Paldea: Scrape spawn tables via area page JavaScript ───────────────────

PALDEA_AREAS: dict[str, str] = {
    # Province areas (Serebii spells out numbers, no hyphens)
    "southprovinceareaone": "South Province (Area 1)",
    "southprovinceareatwo": "South Province (Area 2)",
    "southprovinceareathree": "South Province (Area 3)",
    "southprovinceareafour": "South Province (Area 4)",
    "southprovinceareafive": "South Province (Area 5)",
    "southprovinceareasix": "South Province (Area 6)",
    "eastprovinceareaone": "East Province (Area 1)",
    "eastprovinceareatwo": "East Province (Area 2)",
    "eastprovinceareathree": "East Province (Area 3)",
    "westprovinceareaone": "West Province (Area 1)",
    "westprovinceareatwo": "West Province (Area 2)",
    "westprovinceareathree": "West Province (Area 3)",
    "northprovinceareaone": "North Province (Area 1)",
    "northprovinceareatwo": "North Province (Area 2)",
    "northprovinceareathree": "North Province (Area 3)",
    # Named areas
    "socarrattrail": "Socarrat Trail",
    "glaseadomountain": "Glaseado Mountain",
    "dalizapapassage": "Dalizapa Passage",
    "tagtreethicket": "Tagtree Thicket",
    "casseroyalake": "Casseroya Lake",
    "asadodesert": "Asado Desert",
    "cabopoco": "Cabo Poco",
    "pocopath": "Poco Path",
    "inletgrotto": "Inlet Grotto",
    "alfornada": "Alfornada",
    "alfornadacavern": "Alfornada Cavern",
    "areazero": "Area Zero",
    "eastpaldeansea": "East Paldean Sea",
    "westpaldeansea": "West Paldean Sea",
    "northpaldeansea": "North Paldean Sea",
    "southpaldeansea": "South Paldean Sea",
}


def parse_paldea_spawn_table(html: str) -> dict[int, int]:
    """Parse a Paldea spawn table HTML for Pokemon names and levels.

    Format: class="name" cells for names, level in class="type" cells containing "<b>Level</b>".
    """
    soup = BeautifulSoup(html, "html.parser")
    pokemon_levels: dict[int, int] = {}

    # Find all name cells
    name_cells = soup.find_all("td", class_="name")

    # Find all level cells: class="type" containing "Level"
    level_cells = []
    for td in soup.find_all("td", class_="type"):
        text = td.get_text()
        if "Level" in text:
            level_cells.append(td)

    for i, name_cell in enumerate(name_cells):
        raw_name = name_cell.get_text(strip=True)
        pid = normalize_name(raw_name)
        if not pid:
            continue

        level = None
        if i < len(level_cells):
            level = parse_level_range(level_cells[i].get_text())
        if level is None:
            level = 5

        if pid not in pokemon_levels or level < pokemon_levels[pid]:
            pokemon_levels[pid] = level

    return pokemon_levels


def scrape_all_paldea() -> dict[str, dict]:
    """Scrape Paldea spawn tables sequentially.

    Paldea's pokearth pages include ALL spawn table IDs globally (not per-area),
    so we can't map tables to specific areas from the page JavaScript.
    Instead, we scan all spawn tables and group Pokemon by their biome field.
    """
    print("\n=== Scraping Paldea (Scarlet/Violet) encounters ===")

    # Fetch one area page to get the full set of table IDs
    area_url = f"https://www.serebii.net/pokearth/paldea/southprovinceareaone.shtml"
    area_html = fetch_html(area_url)
    if not area_html:
        print("    Failed to fetch Paldea area page for table IDs")
        return {}

    table_ids = extract_spawn_table_ids(area_html)
    print(f"    Found {len(table_ids)} spawn tables to scan")

    # Group Pokemon by biome from spawn table data
    biome_pokemon: dict[str, dict[int, int]] = {}

    for tid in table_ids:
        table_url = f"https://www.serebii.net/pokearth/paldea/spawntable/{tid}.txt"
        table_html = fetch_html(table_url)
        if not table_html or len(table_html.strip()) < 10:
            continue

        soup = BeautifulSoup(table_html, "html.parser")
        name_cells = soup.find_all("td", class_="name")

        # Extract biome and level per Pokemon entry
        type_cells = soup.find_all("td", class_="type")
        # Parse entries: each Pokemon has multiple type cells (type icon, level, biome, location, time, etc.)
        entry_biomes: list[str] = []
        entry_levels: list[int | None] = []
        for td in type_cells:
            text = td.get_text()
            if "Biomes" in text:
                biome = text.replace("Biomes", "").strip().split("\n")[0].strip()
                if not biome:
                    biome = "Unknown"
                entry_biomes.append(biome)
            elif "Level" in text:
                entry_levels.append(parse_level_range(text))

        for i, name_cell in enumerate(name_cells):
            raw_name = name_cell.get_text(strip=True)
            pid = normalize_name(raw_name)
            if not pid:
                continue

            biome = entry_biomes[i] if i < len(entry_biomes) else "Unknown"
            level = entry_levels[i] if i < len(entry_levels) else None
            if level is None:
                level = 5

            if biome not in biome_pokemon:
                biome_pokemon[biome] = {}
            if pid not in biome_pokemon[biome] or level < biome_pokemon[biome][pid]:
                biome_pokemon[biome][pid] = level

    # Collapse multi-biome strings into primary biome (first word)
    primary_pokemon: dict[str, dict[int, int]] = {}
    for biome, pokemon in biome_pokemon.items():
        primary = biome.split(",")[0].strip()
        if not primary or primary == "Unknown":
            primary = "Wilderness"
        if primary not in primary_pokemon:
            primary_pokemon[primary] = {}
        for pid, level in pokemon.items():
            if pid not in primary_pokemon[primary] or level < primary_pokemon[primary][pid]:
                primary_pokemon[primary][pid] = level

    # Convert to route entries
    encounters: dict[str, dict] = {}
    for biome, pokemon in sorted(primary_pokemon.items()):
        slug = re.sub(r'[^a-z0-9]+', '-', biome.lower()).strip('-')
        route_key = f"paldea-{slug}"
        encounters[route_key] = {
            "display_name": f"Paldea {biome}",
            "region": "Paldea",
            "pokemon": pokemon,
        }
        print(f"    Paldea {biome}: {len(pokemon)} Pokemon")

    print(f"  Total: {len(encounters)} Paldea biome routes")
    return encounters


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("Serebii Encounter Scraper (Gen 8-9)")
    print("=" * 60)
    print(f"Pokemon name lookup: {len(_NAME_TO_ID)} entries")

    all_encounters: dict[str, dict] = {}

    galar = scrape_all_galar()
    all_encounters.update(galar)

    hisui = scrape_all_hisui()
    all_encounters.update(hisui)

    paldea = scrape_all_paldea()
    all_encounters.update(paldea)

    # Summary
    total_pokemon: set[int] = set()
    for route in all_encounters.values():
        total_pokemon.update(route["pokemon"].keys())

    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    print(f"Routes scraped: {len(all_encounters)}")
    print(f"  Galar: {len(galar)} routes")
    print(f"  Hisui: {len(hisui)} routes")
    print(f"  Paldea: {len(paldea)} routes")
    print(f"Unique Pokemon found: {len(total_pokemon)}")

    # Show which Gen 8-9 Pokemon are still missing
    gen8_ids = set(range(810, 906))
    gen9_ids = set(range(906, 1026))
    gen8_found = total_pokemon & gen8_ids
    gen9_found = total_pokemon & gen9_ids
    gen8_missing = gen8_ids - total_pokemon
    gen9_missing = gen9_ids - total_pokemon
    print(f"\nGen 8 (Galar+Hisui): {len(gen8_found)}/{len(gen8_ids)} found, {len(gen8_missing)} missing")
    print(f"Gen 9 (Paldea):      {len(gen9_found)}/{len(gen9_ids)} found, {len(gen9_missing)} missing")

    if gen8_missing:
        print(f"  Missing Gen 8 IDs: {sorted(gen8_missing)[:20]}{'...' if len(gen8_missing) > 20 else ''}")
    if gen9_missing:
        print(f"  Missing Gen 9 IDs: {sorted(gen9_missing)[:20]}{'...' if len(gen9_missing) > 20 else ''}")

    # Also show cross-gen Pokemon found (Gen 1-7 Pokemon on Gen 8-9 routes)
    cross_gen = total_pokemon - gen8_ids - gen9_ids
    print(f"\nCross-gen Pokemon (Gen 1-7 on Gen 8-9 routes): {len(cross_gen)}")

    # Write output
    json_data = {}
    for key, route in sorted(all_encounters.items()):
        json_data[key] = {
            "display_name": route["display_name"],
            "region": route["region"],
            "pokemon": {str(k): v for k, v in sorted(route["pokemon"].items())},
        }

    OUTPUT_FILE.write_text(json.dumps(json_data, indent=2), encoding="utf-8")
    print(f"\nWrote {OUTPUT_FILE}")
    print("Merge into route_data.py by re-running build_route_data.py with --merge-serebii")


if __name__ == "__main__":
    main()
