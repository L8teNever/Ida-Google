import unittest

from app.google_client import GoogleApiError
from app.services.health import SCOPES, baue_schlaf_datenpunkt, _pfad, _utc_und_offset


class ZeitTest(unittest.TestCase):
    def test_mez_wird_zu_utc_mit_offset(self):
        self.assertEqual(
            _utc_und_offset("2024-10-31T01:55:00+01:00"),
            ("2024-10-31T00:55:00Z", "3600s"),
        )

    def test_z_suffix(self):
        self.assertEqual(
            _utc_und_offset("2026-06-07T22:00:00Z"), ("2026-06-07T22:00:00Z", "0s")
        )

    def test_ohne_zeitzone_ist_fehler(self):
        with self.assertRaises(GoogleApiError):
            _utc_und_offset("2024-10-31T01:55:00")

    def test_unsinn_ist_fehler(self):
        with self.assertRaises(GoogleApiError):
            _utc_und_offset("gestern")


class SchlafBodyTest(unittest.TestCase):
    def test_mit_stufen(self):
        body = baue_schlaf_datenpunkt(
            "2024-10-31T01:55:00+01:00",
            "2024-10-31T10:02:00+01:00",
            [
                {"start": "2024-10-31T01:55:00+01:00", "ende": "2024-10-31T03:00:00+01:00", "typ": "light"},
                {"start": "2024-10-31T03:00:00+01:00", "ende": "2024-10-31T10:02:00+01:00", "typ": "DEEP"},
            ],
        )
        schlaf = body["sleep"]
        self.assertEqual(schlaf["type"], "STAGES")
        self.assertEqual(schlaf["interval"]["startTime"], "2024-10-31T00:55:00Z")
        self.assertEqual(schlaf["interval"]["endUtcOffset"], "3600s")
        self.assertEqual([s["type"] for s in schlaf["stages"]], ["LIGHT", "DEEP"])

    def test_ohne_stufen(self):
        body = baue_schlaf_datenpunkt("2024-10-31T01:55:00+01:00", "2024-10-31T10:02:00+01:00", None)
        self.assertNotIn("stages", body["sleep"])
        self.assertNotIn("type", body["sleep"])

    def test_falsche_stufe(self):
        with self.assertRaises(GoogleApiError):
            baue_schlaf_datenpunkt(
                "2024-10-31T01:55:00+01:00",
                "2024-10-31T10:02:00+01:00",
                [{"start": "2024-10-31T01:55:00+01:00", "ende": "2024-10-31T02:00:00+01:00", "typ": "TRAUM"}],
            )


class MiscTest(unittest.TestCase):
    def test_pfad(self):
        self.assertEqual(
            _pfad("sleep"), "https://health.googleapis.com/v4/users/me/dataTypes/sleep/dataPoints"
        )
        with self.assertRaises(GoogleApiError):
            _pfad("sleep/../x")

    def test_scopes(self):
        self.assertEqual(len(SCOPES), 12)
        self.assertIn("https://www.googleapis.com/auth/googlehealth.sleep.writeonly", SCOPES)


class ScopedTokenTest(unittest.TestCase):
    def test_health_nutzt_eingeschraenkten_token(self):
        from app.services import health

        aufrufe = []

        class FakeClient:
            def request(self, methode, url, **kw):
                aufrufe.append(kw.get("scopes"))
                return {}

        health._anfrage(FakeClient(), "GET", "http://x")
        self.assertEqual(aufrufe, [SCOPES])


if __name__ == "__main__":
    unittest.main()
