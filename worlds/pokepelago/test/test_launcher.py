"""Tests for the Pokepelago Launcher slot-link connect flow.

Covers URI detection/parsing, the web and desktop handoff URLs, and that the two
connect components are registered so the Launcher's chooser appears for Pokepelago
links. No Launcher, Kivy, or network is involved.
"""
import unittest

from worlds.pokepelago import launcher

POKEPELAGO_URI = "archipelago://Ash:None@archipelago.gg:38281?game=Pokepelago&room=12345"


class TestPokepelagoUri(unittest.TestCase):
    def test_detects_pokepelago_link(self):
        self.assertTrue(launcher.is_pokepelago_uri(POKEPELAGO_URI))

    def test_rejects_other_game(self):
        uri = "archipelago://Ash:None@archipelago.gg:38281?game=Ocarina%20of%20Time&room=1"
        self.assertFalse(launcher.is_pokepelago_uri(uri))

    def test_rejects_non_archipelago_uri(self):
        self.assertFalse(launcher.is_pokepelago_uri("https://archipelago.gg/room/12345"))

    def test_rejects_empty(self):
        self.assertFalse(launcher.is_pokepelago_uri(None))
        self.assertFalse(launcher.is_pokepelago_uri(""))

    def test_parse_connection_drops_none_password(self):
        connection = launcher.parse_connection(POKEPELAGO_URI)
        self.assertEqual(connection["host"], "archipelago.gg")
        self.assertEqual(connection["port"], "38281")
        self.assertEqual(connection["name"], "Ash")
        self.assertEqual(connection["password"], "")

    def test_parse_connection_keeps_real_password(self):
        uri = "archipelago://Ash:secret@example.com:1234?game=Pokepelago"
        self.assertEqual(launcher.parse_connection(uri)["password"], "secret")

    def test_web_url_contains_connection_params(self):
        url = launcher.build_web_url(launcher.parse_connection(POKEPELAGO_URI))
        self.assertTrue(url.startswith(launcher.WEB_CLIENT_URL))
        for fragment in ("host=archipelago.gg", "port=38281", "name=Ash"):
            self.assertIn(fragment, url)
        self.assertNotIn("password=", url)

    def test_desktop_uri_contains_connection_params(self):
        uri = launcher.build_desktop_uri(launcher.parse_connection(POKEPELAGO_URI))
        self.assertTrue(uri.startswith(launcher.DESKTOP_PROTOCOL_URI))
        for fragment in ("host=archipelago.gg", "port=38281", "name=Ash"):
            self.assertIn(fragment, uri)


class TestConnectComponents(unittest.TestCase):
    def test_both_connect_components_are_registered(self):
        by_name = {component.display_name: component
                   for component in launcher.components
                   if component.game_name == launcher.GAME_NAME}
        self.assertIn("Pokepelago Web Client", by_name)
        self.assertIn("Pokepelago Desktop Client", by_name)
        for name in ("Pokepelago Web Client", "Pokepelago Desktop Client"):
            self.assertTrue(by_name[name].supports_uri,
                            f"{name} must support URI so the chooser offers it")

    def test_connect_components_open_the_matching_mode(self):
        opened = []
        calls = []
        original_open_mode = launcher._open_mode
        original_launch = launcher.launch_textclient
        try:
            launcher._open_mode = lambda mode, connection: opened.append((mode, connection))
            launcher.launch_textclient = calls.append

            launcher._web_client(POKEPELAGO_URI)
            self.assertEqual(opened[-1][0], launcher.MODE_WEB)
            self.assertEqual(calls, [POKEPELAGO_URI])

            launcher._desktop_client(POKEPELAGO_URI)
            self.assertEqual(opened[-1][0], launcher.MODE_DESKTOP)
            self.assertEqual(calls, [POKEPELAGO_URI, POKEPELAGO_URI])
        finally:
            launcher._open_mode = original_open_mode
            launcher.launch_textclient = original_launch


if __name__ == "__main__":
    unittest.main()
