"""Regenerate every APWorld-derived data file in a PokepelagoClient checkout.

The client bundles two files generated from this world:

* ``src/data/route_data.json``  (``tools/_export_client_data.py``)
* ``src/data/pokemon_gates.ts`` (``tools/build_classification_data.py --write-gates``)

Forgetting to re-export after a data change let the client and the APWorld disagree
(BUG-12, BUG-16, BUG-17). This runs both exporters in one step::

    python worlds/pokepelago/tools/export_to_client.py --client <client checkout>

With ``--check`` nothing in the checkout is written: both files are generated into a
temporary directory and compared byte for byte with the committed ones. The exit code
is 1 on any drift. The client's CI runs this against APWorld ``main``.
"""
from __future__ import annotations

import argparse
import contextlib
import difflib
import io
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from worlds.pokepelago.tools import build_classification_data  # noqa: E402

ROUTE_DATA_FILE = "route_data.json"
GATES_FILE = "pokemon_gates.ts"
GENERATED_FILES = (ROUTE_DATA_FILE, GATES_FILE)


def export(data_dir: Path, pretty: bool = True) -> None:
    """Write both generated files into ``data_dir`` using the existing exporters."""
    # Imported lazily: the module builds its whole payload at import time.
    from worlds.pokepelago.tools import _export_client_data

    data_dir.mkdir(parents=True, exist_ok=True)
    _export_client_data.write_route_data(data_dir, pretty=pretty)
    build_classification_data.write_client_gates(str(data_dir / GATES_FILE))


def _describe_drift(name: str, fresh: bytes, committed: bytes) -> list[str]:
    if name == ROUTE_DATA_FILE:
        # route_data.json is one minified line, so a text diff is useless; name the keys.
        try:
            new, old = json.loads(fresh), json.loads(committed)
        except ValueError:
            return ["  committed file is not valid JSON"]
        keys = sorted(k for k in set(new) | set(old) if new.get(k) != old.get(k))
        return ["  differing top-level keys: " + ", ".join(keys)]
    diff = difflib.unified_diff(
        committed.decode("utf-8", "replace").splitlines(),
        fresh.decode("utf-8", "replace").splitlines(),
        "committed/" + name, "fresh/" + name, lineterm="", n=1,
    )
    return ["  " + line for line in list(diff)[:40]]


def check(data_dir: Path) -> list[str]:
    """Return drift messages for ``data_dir``; an empty list means no drift."""
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        with contextlib.redirect_stdout(io.StringIO()):
            export(Path(tmp), pretty=False)
        for name in GENERATED_FILES:
            fresh = (Path(tmp) / name).read_bytes()
            target = data_dir / name
            if not target.is_file():
                problems.append(f"{name}: missing from {data_dir}")
                continue
            committed = target.read_bytes()
            if committed != fresh:
                problems.append(f"{name}: differs from a fresh export")
                problems.extend(_describe_drift(name, fresh, committed))
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--client", required=True, type=Path, metavar="PATH",
                    help="root of a PokepelagoClient checkout (must contain src/data)")
    ap.add_argument("--check", action="store_true",
                    help="write nothing; exit 1 if the committed files differ from a fresh export")
    args = ap.parse_args(argv)

    data_dir = args.client / "src" / "data"
    if not data_dir.is_dir():
        ap.error(f"{data_dir} does not exist; --client must point at a PokepelagoClient checkout")

    if not args.check:
        export(data_dir)
        return 0

    problems = check(data_dir)
    if problems:
        print("CLIENT DATA DRIFT DETECTED:")
        for line in problems:
            print(line)
        print("\nRegenerate from the APWorld and commit the result in the client:\n"
              "  python worlds/pokepelago/tools/export_to_client.py --client <client checkout>")
        return 1
    print("client data matches a fresh APWorld export (" + ", ".join(GENERATED_FILES) + ")")
    return 0


if __name__ == "__main__":
    sys.exit(main())
