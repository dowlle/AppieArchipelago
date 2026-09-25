"""Issue #28: one command regenerates the client data files and detects drift."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from worlds.pokepelago.tools import _export_client_data, export_to_client


def _quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return fn(*args, **kwargs)


class TestExportToClient(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.client = Path(self._tmp.name)
        self.data_dir = self.client / "src" / "data"
        self.data_dir.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_writes_both_files_in_exporter_format(self):
        self.assertEqual(_quiet(export_to_client.main, ["--client", str(self.client)]), 0)
        route = (self.data_dir / "route_data.json").read_text(encoding="utf-8")
        self.assertEqual(route, json.dumps(_export_client_data.output, separators=(",", ":")))
        gates = (self.data_dir / "pokemon_gates.ts").read_text(encoding="utf-8")
        self.assertIn("AUTO-GENERATED from worlds/pokepelago/data.py", gates)
        self.assertIn("export const STONE_NAMES_ORDERED", gates)

    def test_check_passes_on_fresh_export(self):
        _quiet(export_to_client.main, ["--client", str(self.client)])
        self.assertEqual(_quiet(export_to_client.check, self.data_dir), [])
        self.assertEqual(_quiet(export_to_client.main, ["--client", str(self.client), "--check"]), 0)

    def test_check_writes_nothing(self):
        _quiet(export_to_client.main, ["--client", str(self.client), "--check"])
        self.assertEqual(list(self.data_dir.iterdir()), [])

    def test_check_flags_edited_gates(self):
        _quiet(export_to_client.main, ["--client", str(self.client)])
        gates = self.data_dir / "pokemon_gates.ts"
        gates.write_text(gates.read_text(encoding="utf-8") + "// hand edit\n", encoding="utf-8")
        problems = _quiet(export_to_client.check, self.data_dir)
        self.assertTrue(problems[0].startswith("pokemon_gates.ts: differs"))
        self.assertEqual(_quiet(export_to_client.main, ["--client", str(self.client), "--check"]), 1)

    def test_check_names_drifted_route_data_keys(self):
        _quiet(export_to_client.main, ["--client", str(self.client)])
        stale = dict(_export_client_data.output, badgeRequirements={})
        (self.data_dir / "route_data.json").write_text(
            json.dumps(stale, separators=(",", ":")), encoding="utf-8")
        problems = _quiet(export_to_client.check, self.data_dir)
        self.assertEqual(problems, ["route_data.json: differs from a fresh export",
                                    "  differing top-level keys: badgeRequirements"])

    def test_check_flags_missing_file(self):
        self.assertIn(f"route_data.json: missing from {self.data_dir}",
                      _quiet(export_to_client.check, self.data_dir))

    def test_rejects_path_without_client_data_dir(self):
        with self.assertRaises(SystemExit):
            _quiet(export_to_client.main, ["--client", str(self.client / "nope")])
