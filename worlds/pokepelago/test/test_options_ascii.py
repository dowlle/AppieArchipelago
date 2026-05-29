"""Guards against non-ASCII characters in option metadata (BUG-13).

The generated Pokepelago.yaml template embeds each option's docstring and display name.
Smart quotes, em dashes, arrows, etc. there make WordPad prompt about "formatting you'll
lose" on save and can break downstream YAML parsing. Keep all option-facing text ASCII.
"""
import unittest

from worlds.pokepelago.Options import PokepelagoOptions


class TestOptionMetadataAscii(unittest.TestCase):
    def test_docstrings_and_display_names_are_ascii(self):
        for field, cls in PokepelagoOptions.__annotations__.items():
            doc = getattr(cls, "__doc__", "") or ""
            self.assertTrue(
                doc.isascii(),
                f"{getattr(cls, '__name__', field)} docstring has non-ASCII characters "
                f"(these leak into the YAML template and break WordPad — BUG-13)",
            )
            display_name = getattr(cls, "display_name", "") or ""
            self.assertTrue(
                display_name.isascii(),
                f"{getattr(cls, '__name__', field)} display_name has non-ASCII characters (BUG-13)",
            )


if __name__ == "__main__":
    unittest.main()
