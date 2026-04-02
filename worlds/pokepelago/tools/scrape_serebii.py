"""
Supplementary scraper for Gen 8-9 encounter data from Serebii.net.

Fills gaps where PokeAPI has no encounter data:
- Galar (Sword/Shield): per-Pokemon location pages
- Paldea (Scarlet/Violet): spawn table files from pokearth map
- Hisui (Legends Arceus): manual curation (only 7 Pokemon)

Usage:
    python -m worlds.pokepelago.tools.scrape_serebii

Writes supplementary data to tools/serebii_encounters.json which
build_route_data.py can merge in a future pass.

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
REQUEST_DELAY = 1.0  # Be polite to Serebii
OUTPUT_FILE = Path(__file__).parent / "serebii_encounters.json"

# Pokemon names for Galar orphans (IDs 810-898) — we need their Serebii slugs
# Import from data.py
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from worlds.pokepelago.data import POKEMON_DATA


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
            print(f"    → 404")
            return None
        resp.raise_for_status()
        html = resp.text
        cache_file.write_text(html, encoding="utf-8")
        time.sleep(REQUEST_DELAY)
        return html
    except requests.RequestException as e:
        print(f"    → ERROR: {e}")
        return None


# ── Galar: Scrape per-Pokemon location pages ────────────────────────────────

def scrape_galar_encounters(orphan_ids: set[int]) -> dict[str, dict]:
    """Scrape Sword/Shield location data from Serebii for each orphan Pokemon."""
    print("\n=== Scraping Galar (Sword/Shield) encounters ===")
    encounters: dict[str, dict] = {}  # route_key → {display_name, region, pokemon: {id: min_level}}

    for mon in POKEMON_DATA:
        if mon["id"] not in orphan_ids:
            continue
        if mon["id"] < 810 or mon["id"] > 898:
            continue

        name_slug = mon["name"].lower().replace(" ", "").replace(".", "").replace("'", "").replace("-", "")
        # Serebii uses specific slug patterns
        url = f"https://www.serebii.net/pokedex-swsh/{name_slug}/locations.shtml"
        html = fetch_html(url)

        if not html:
            # Try alternate slug (some Pokemon have different URL patterns)
            print(f"    Trying alternate URL for {mon['name']}...")
            continue

        soup = BeautifulSoup(html, "html.parser")
        routes_found = _parse_swsh_locations(soup, mon["id"])

        for route_name, min_level in routes_found.items():
            route_key = f"galar-{route_name}"
            if route_key not in encounters:
                display_name = route_name.replace("-", " ").title()
                encounters[route_key] = {
                    "display_name": display_name,
                    "region": "Galar",
                    "pokemon": {},
                }
            current = encounters[route_key]["pokemon"].get(mon["id"])
            if current is None or min_level < current:
                encounters[route_key]["pokemon"][mon["id"]] = min_level

        if routes_found:
            print(f"    {mon['name']}: {len(routes_found)} routes")
        else:
            print(f"    {mon['name']}: NO routes found (gift/event?)")

    return encounters


def _parse_swsh_locations(soup: BeautifulSoup, pokemon_id: int) -> dict[str, int]:
    """Parse Serebii Sword/Shield location page to extract route → min_level."""
    routes: dict[str, int] = {}

    # Find all tables with encounter data
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 5:
                continue

            # Look for cells containing route names and level ranges
            text_cells = [cell.get_text(strip=True) for cell in cells]

            # Try to find a level pattern like "3-6" or "60-65"
            for i, text in enumerate(text_cells):
                level_match = re.search(r'(\d+)\s*-\s*(\d+)', text)
                if level_match and i > 0:
                    min_level = int(level_match.group(1))
                    # The route name is typically in an earlier cell
                    for j in range(i):
                        route_text = text_cells[j].strip()
                        if route_text and len(route_text) > 2 and not route_text.isdigit():
                            # Skip weather/method names
                            if route_text.lower() in ("all", "normal", "overcast", "raining",
                                                       "thunderstorm", "snowing", "snowstorm",
                                                       "sandstorm", "intense sun", "fog",
                                                       "overworld", "random encounter",
                                                       "fishing", "surfing", "curry"):
                                continue
                            route_slug = re.sub(r'[^a-z0-9]+', '-', route_text.lower()).strip('-')
                            if route_slug and len(route_slug) > 1:
                                if route_slug not in routes or min_level < routes[route_slug]:
                                    routes[route_slug] = min_level
                                break
                    break

    return routes


# ── Paldea: Scrape spawn table files ────────────────────────────────────────

def scrape_paldea_encounters(orphan_ids: set[int]) -> dict[str, dict]:
    """Scrape Scarlet/Violet spawn tables from Serebii pokearth map."""
    print("\n=== Scraping Paldea (Scarlet/Violet) encounters ===")
    encounters: dict[str, dict] = {}

    # Build Pokemon name → ID lookup for Paldea range
    name_to_id = {}
    for mon in POKEMON_DATA:
        name_to_id[mon["name"].lower()] = mon["id"]

    # Scan spawn table IDs (we don't know the range, so try sequentially)
    consecutive_404s = 0
    table_id = 1

    while consecutive_404s < 20 and table_id < 500:
        url = f"https://www.serebii.net/pokearth/paldea/spawntable/{table_id}.txt"
        html = fetch_html(url)

        if not html:
            consecutive_404s += 1
            table_id += 1
            continue
        consecutive_404s = 0

        # Parse the spawn table HTML
        soup = BeautifulSoup(html, "html.parser")
        pokemon_data = _parse_sv_spawn_table(soup, name_to_id)

        if pokemon_data:
            route_key = f"paldea-area-{table_id}"
            # Try to extract a location name from the page
            location_name = _extract_sv_location_name(soup, table_id)
            encounters[route_key] = {
                "display_name": location_name,
                "region": "Paldea",
                "pokemon": pokemon_data,
            }

        table_id += 1

    print(f"  Scraped {len(encounters)} Paldea areas")
    return encounters


def _parse_sv_spawn_table(soup: BeautifulSoup, name_to_id: dict[str, int]) -> dict[int, int]:
    """Parse a Serebii SV spawn table to extract pokemon_id → min_level."""
    pokemon_levels: dict[int, int] = {}

    # The spawn tables have Pokemon names as alt text on images
    # and levels in cells with "Level" header
    all_names: list[str] = []
    all_levels: list[int] = []

    for img in soup.find_all("img", class_="wildsprite"):
        alt = img.get("alt", "").strip()
        if alt:
            all_names.append(alt.lower())

    for td in soup.find_all("td", class_="type"):
        text = td.get_text(strip=True)
        level_match = re.search(r'Level\s*(\d+)\s*-\s*(\d+)', text)
        if level_match:
            all_levels.append(int(level_match.group(1)))
        else:
            level_match = re.search(r'Level\s*(\d+)', text)
            if level_match:
                all_levels.append(int(level_match.group(1)))

    # Match names to levels (they appear in the same order)
    for i, name in enumerate(all_names):
        pid = name_to_id.get(name)
        if pid and i < len(all_levels):
            min_level = all_levels[i]
            if pid not in pokemon_levels or min_level < pokemon_levels[pid]:
                pokemon_levels[pid] = min_level

    return pokemon_levels


def _extract_sv_location_name(soup: BeautifulSoup, table_id: int) -> str:
    """Try to extract a readable location name from the spawn table."""
    # Check for an "interact" class cell which usually has the game title
    # The actual location name may not be in the spawn table itself
    return f"Paldea Area {table_id}"


# ── Hisui: Manual curation ──────────────────────────────────────────────────

def get_hisui_encounters() -> dict[str, dict]:
    """Manually curated Hisui encounters for the 7 exclusive Pokemon."""
    print("\n=== Adding Hisui (Legends Arceus) encounters (manual) ===")
    # Hisui-exclusive Pokemon (899-905) and their locations in Legends Arceus
    return {
        "hisui-obsidian-fieldlands": {
            "display_name": "Obsidian Fieldlands",
            "region": "Hisui",
            "pokemon": {
                899: 40,  # Wyrdeer — evolves from Stantler
                901: 50,  # Kleavor — evolves from Scyther
            },
        },
        "hisui-crimson-mirelands": {
            "display_name": "Crimson Mirelands",
            "region": "Hisui",
            "pokemon": {
                903: 50,  # Sneasler — evolves from Sneasel
                904: 50,  # Overqwil — evolves from Qwilfish
            },
        },
        "hisui-coronet-highlands": {
            "display_name": "Coronet Highlands",
            "region": "Hisui",
            "pokemon": {
                900: 50,  # Ursaluna — evolves from Ursaring
            },
        },
        "hisui-alabaster-icelands": {
            "display_name": "Alabaster Icelands",
            "region": "Hisui",
            "pokemon": {
                902: 56,  # Basculegion — evolves from Basculin
            },
        },
        "hisui-ancient-retreat": {
            "display_name": "Ancient Retreat",
            "region": "Hisui",
            "pokemon": {
                905: 70,  # Enamorus — legendary, post-game
            },
        },
    }


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("Serebii Supplementary Scraper (Gen 8-9)")
    print("=" * 60)

    # Load orphan IDs from the generated route_data
    try:
        from worlds.pokepelago.route_data import ORPHAN_IDS
    except ImportError:
        print("ERROR: Run build_route_data.py first to generate route_data.py")
        sys.exit(1)

    galar_orphans = {pid for pid in ORPHAN_IDS if 810 <= pid <= 898}
    paldea_orphans = {pid for pid in ORPHAN_IDS if 906 <= pid <= 1025}

    print(f"Galar orphans to scrape: {len(galar_orphans)}")
    print(f"Paldea orphans to scrape: {len(paldea_orphans)}")

    all_encounters: dict[str, dict] = {}

    # Galar
    galar = scrape_galar_encounters(galar_orphans)
    all_encounters.update(galar)

    # Paldea
    paldea = scrape_paldea_encounters(paldea_orphans)
    all_encounters.update(paldea)

    # Hisui
    hisui = get_hisui_encounters()
    all_encounters.update(hisui)

    # Summary
    total_pokemon = set()
    for route in all_encounters.values():
        total_pokemon.update(route["pokemon"].keys())

    remaining_orphans = (galar_orphans | paldea_orphans | set(range(899, 906))) - total_pokemon

    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"Routes scraped: {len(all_encounters)}")
    print(f"  Galar: {len(galar)}")
    print(f"  Paldea: {len(paldea)}")
    print(f"  Hisui: {len(hisui)}")
    print(f"Pokemon found: {len(total_pokemon)}")
    print(f"Remaining orphans: {len(remaining_orphans)}")
    if remaining_orphans:
        print(f"  IDs: {sorted(remaining_orphans)}")

    # Write output
    # Convert sets to lists for JSON serialization
    json_data = {}
    for key, route in all_encounters.items():
        json_data[key] = {
            "display_name": route["display_name"],
            "region": route["region"],
            "pokemon": {str(k): v for k, v in route["pokemon"].items()},
        }

    OUTPUT_FILE.write_text(json.dumps(json_data, indent=2), encoding="utf-8")
    print(f"\nWrote {OUTPUT_FILE}")
    print("Merge this into route_data.py by re-running build_route_data.py with --merge-serebii")


if __name__ == "__main__":
    main()
