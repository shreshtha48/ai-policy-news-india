import json
import unittest
from pathlib import Path

from pipeline.sources import gdelt, google_news, outlets

FX = Path(__file__).parent / "fixtures"


class TestSources(unittest.TestCase):
    def test_google_news_strips_outlet_suffix_and_keeps_source(self):
        arts = google_news.parse((FX / "google_news_sample.xml").read_text(encoding="utf-8"), "IN-TG")
        self.assertEqual(len(arts), 3)
        a = arts[0]
        self.assertEqual(a.title, "Deakin University of Australia and Telangana government sign MoU to advance artificial intelligence")
        self.assertEqual(a.source_name, "News On AIR")
        self.assertEqual(a.source_domain, "newsonair.gov.in")
        self.assertTrue(a.published.startswith("2026-09-24T18:48:01"))

    def test_thehindu_cdata_and_ist_offset(self):
        arts = outlets.parse_outlet_rss((FX / "thehindu_state.rss").read_text(encoding="utf-8"),
                                        "The Hindu", "IN-TG", "feed")
        self.assertEqual(arts[1].title, "Telangana to set up AI task force for public services, says Sridhar Babu")
        self.assertEqual(arts[1].published, "2026-09-24T20:05:00+05:30")
        self.assertIn("roadmap", arts[1].excerpt)

    def test_tt_listing_and_meta_date(self):
        html = (FX / "tt_tag_page.html").read_text(encoding="utf-8")
        arts = outlets.parse_tt_listing(html, "IN-TG", "p1")
        self.assertEqual(len(arts), 2)
        self.assertEqual(arts[0].published, "")          # listing has no date
        self.assertIn("ElevenLabs", arts[1].excerpt)
        self.assertEqual(outlets.parse_published_meta(html), "2026-09-20T10:00:00+05:30")

    def test_gdelt_english_only(self):
        arts = gdelt.parse(json.loads((FX / "gdelt_sample.json").read_text(encoding="utf-8")), "IN-TG")
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0].published, "2026-07-16T08:15:00+00:00")


if __name__ == "__main__":
    unittest.main()
