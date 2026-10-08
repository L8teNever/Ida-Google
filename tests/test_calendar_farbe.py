import unittest

from app.services.calendar import EVENT_FARBEN, _farbe_aufloesen, _termin_kurz


class FarbeAufloesenTest(unittest.TestCase):
    def test_leerer_string_ist_kein_fehler(self):
        self.assertEqual(_farbe_aufloesen(""), (None, None))
        self.assertEqual(_farbe_aufloesen("  "), (None, None))

    def test_color_id_eins_bis_elf(self):
        for color_id in EVENT_FARBEN:
            self.assertEqual(_farbe_aufloesen(color_id), (color_id, None))

    def test_deutsche_und_englische_namen(self):
        self.assertEqual(_farbe_aufloesen("Tomate"), ("11", None))
        self.assertEqual(_farbe_aufloesen("tomato"), ("11", None))
        self.assertEqual(_farbe_aufloesen("lavendel"), ("1", None))
        self.assertEqual(_farbe_aufloesen("Basil"), ("10", None))

    def test_ungueltig(self):
        color_id, hinweis = _farbe_aufloesen("pink")
        self.assertIsNone(color_id)
        self.assertIn("Ungueltige Farbe", hinweis)
        self.assertIn("1-11", hinweis)

    def test_id_ausserhalb_1_11(self):
        color_id, hinweis = _farbe_aufloesen("12")
        self.assertIsNone(color_id)
        self.assertIsNotNone(hinweis)


class TerminKurzTest(unittest.TestCase):
    def test_farbe_aus_color_id(self):
        kurz = _termin_kurz(
            {
                "id": "abc",
                "summary": "Arzt",
                "start": {"dateTime": "2026-10-09T10:00:00+02:00"},
                "end": {"dateTime": "2026-10-09T11:00:00+02:00"},
                "colorId": "11",
            }
        )
        self.assertEqual(kurz["farbe"], "11")
        self.assertEqual(kurz["farbe_name"], "tomate")

    def test_ohne_color_id(self):
        kurz = _termin_kurz({"id": "x", "start": {}, "end": {}})
        self.assertEqual(kurz["farbe"], "")
        self.assertEqual(kurz["farbe_name"], "")


if __name__ == "__main__":
    unittest.main()
