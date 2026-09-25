"""Regression tests for every issue in the review doc (IDs match the register)."""
import json
import re
import tempfile
import unittest
from datetime import date
from pathlib import Path

import numpy as np

from pipeline.build import build, dedupe_articles
from pipeline.classify import judge, partners_of
from pipeline.dedupe import cluster
from pipeline.geo import get_geo
from pipeline.models import RawArticle
from pipeline.plan import Call, Ledger, month_slices, triage
from pipeline.sources import keyed

from .helpers import FakeEncoder

FX = Path(__file__).parent / "fixtures"


def art(title, kind="google_news_rss", url=None, published="2026-09-24T10:00:00+05:30", hint="", domain="", excerpt="", name="Outlet"):
    return RawArticle(source_kind=kind, title=title, url=url or f"https://news.google.com/rss/articles/{abs(hash(title))}",
                      source_name=name, source_domain=domain, published=published, excerpt=excerpt,
                      state_hint=hint, fetched_at="2026-09-25T00:00:00+00:00")


class TestBugs(unittest.TestCase):
    def test_B1_query_state_is_not_a_fallback(self):
        g = get_geo()
        self.assertIsNone(g.resolve("Govt launches AI portal for citizens", "IN-DL").state_code)
        # state-specific outlet feed may fall back
        self.assertEqual(g.resolve("Govt launches AI portal for citizens", "IN-TG", True).state_code, "IN-TG")

    def test_B2_ai_centre_is_not_union_govt(self):
        g = get_geo()
        self.assertNotEqual(g.resolve("CM inaugurates AI centre").state_code, "IN-CENTRAL")
        self.assertEqual(g.resolve("Centre to set up AI labs in all states").state_code, "IN-CENTRAL")

    def test_B3_mou_with_money_is_partnership(self):
        self.assertEqual(judge("Telangana signs Rs 5,000 crore MoU with Microsoft for AI data centre").category, "partnership")
        self.assertEqual(judge("Gujarat budget earmarks Rs 250 crore for AI").category, "budget_funding")

    def test_B4_no_chaining_beyond_window(self):
        titles = [("2026-01-01", "Telangana AI City project at Hyderabad gets land allotment"),
                  ("2026-01-06", "AI City project in Hyderabad: Telangana finalises master plan"),
                  ("2026-01-12", "Telangana AI City master plan approved by cabinet"),
                  ("2026-01-18", "AI City: Telangana cabinet approves land for data centres")]
        items = [dict(state_code="IN-TG", date=d, title=t) for d, t in titles]
        for g in cluster(items):
            ds = [date.fromisoformat(items[i]["date"]) for i in g]
            self.assertLessEqual((max(ds) - min(ds)).days, 7)


class TestDedupeAndFilter(unittest.TestCase):
    def test_D1_paraphrase_merges_by_partner_but_not_across_partners(self):
        rows = [("2026-09-20", "Karnataka signs major pact with Google for AI"),
                ("2026-09-21", "Google and state government strike artificial intelligence deal"),
                ("2026-09-21", "Karnataka signs pact with Microsoft for AI")]
        items = [dict(state_code="IN-KA", date=d, title=t, category="partnership", partners=partners_of(t)) for d, t in rows]
        groups = sorted(sorted(g) for g in cluster(items))
        self.assertIn([0, 1], groups)
        self.assertIn([2], groups)

    def test_F1_wider_government_vocabulary(self):
        self.assertTrue(judge("The state has earmarked Rs 250 crore for AI").keep)
        self.assertTrue(judge("Authorities roll out AI cameras").keep)
        self.assertFalse(judge("Startup unveils state-of-the-art AI chip").keep)


class TestFromRealTelanganaRun(unittest.TestCase):
    """Misses found by re-processing the first real Telangana fetch (25 Sep 2026)."""

    def test_leaders_and_bodies_count_as_government(self):
        for t in ["Revanth to launch Telangana AI Innovation Hub at Davos",
                  "Tech team formed in DGP's office to drive AI-based policing initiatives in Telangana",
                  "Telangana, Microsoft, Join Hands for Green Pharma AI Centre",
                  "Hyderabad to get India's first Green Skills and Applied AI Centre of Excellence"]:
            self.assertTrue(judge(t).keep, t)

    def test_future_city_is_telangana(self):
        self.assertEqual(get_geo().resolve("UPC Volt to set up AI data centre in Bharat Future City").state_code, "IN-TG")

    def test_same_rupee_figure_same_week_merges(self):
        rows = [("2026-09-05", "Telangana CM Revanth and TCS announce Rs 70,000 crore AI Data Centre in Future City"),
                ("2026-09-05", "Tata Consultancy Services' HyperVault to establish Rs 70,000 crore AI data centre in Telangana")]
        from pipeline.classify import amount_crore
        items = [dict(state_code="IN-TG", date=d, title=t, category="budget_funding",
                      partners=partners_of(t), amount=amount_crore(t)) for d, t in rows]
        self.assertEqual(len(cluster(items)), 1)

    def test_crore_alone_is_not_budget(self):
        self.assertNotEqual(judge("How AI cracked a Rs 70,000 crore tax evasion trail in Hyderabad, says Telangana govt").category,
                            "budget_funding")


class TestOps(unittest.TestCase):
    def test_O1_ledger_skips_repeats_and_enforces_budget(self):
        with tempfile.TemporaryDirectory() as d:
            led = Ledger(Path(d) / "l.json")
            mk = lambda k, api="gnews", perm=False: Call(api=api, state="IN-TG", key=k, run=lambda: [], permanent=perm, keyed=api != "google_news")
            led.record(mk("gnews|a"), 3)
            led.record(mk("google_news|jan", "google_news", True), 5)
            run, skipped = triage([mk("gnews|a"), mk("gnews|b"), mk("gnews|c"),
                                   mk("google_news|jan", "google_news", True)], led, {"gnews": 2})
            self.assertEqual([c.key for c in run], ["gnews|b"])            # a done, c over budget (1 used + 1 planned)
            reasons = {c.key: r for c, r in skipped}
            self.assertIn("already", reasons["gnews|a"])
            self.assertIn("budget", reasons["gnews|c"])
            self.assertIn("closed month", reasons["google_news|jan"])
            # survives reload
            self.assertTrue(Ledger(Path(d) / "l.json").done(mk("google_news|jan", "google_news", True)))

    def test_month_slices_2026(self):
        s = month_slices("2026-01-01", date(2026, 9, 25))
        self.assertEqual(len(s), 9)
        self.assertTrue(s[7][2])        # August is closed
        self.assertFalse(s[8][2])       # September is open

    def test_O2_keyed_parsers(self):
        na = keyed.parse_newsapi(json.loads((FX / "newsapi_sample.json").read_text()), "IN-TG")
        self.assertEqual(len(na), 1)                                     # [Removed] dropped
        self.assertEqual(na[0].source_domain, "thehindu.com")
        nd = keyed.parse_newsdata(json.loads((FX / "newsdata_sample.json").read_text()), "IN-GJ")
        self.assertEqual(nd[0].published, "2026-09-24T20:00:00+00:00")   # UTC made explicit
        with self.assertRaises(RuntimeError):
            keyed.parse_newsapi({"status": "error", "code": "rateLimited", "message": "x"})

    def test_O2_missing_key_is_a_skip_not_a_call(self):
        import os
        os.environ.pop("NEWS_API_KEY", None)
        cfg = json.loads(Path("config/sources.json").read_text())["newsapi"]
        c = keyed.plan_newsapi("IN-TG", "Telangana", cfg, "2026-01-01")[0]
        self.assertIn("not set", c.skip_reason)

    def test_O4_unknown_first_reported_is_empty(self):
        ev, _, _ = build([art("Telangana to set up AI task force", kind="outlet_scrape", published="",
                              url="https://telanganatoday.com/x", domain="telanganatoday.com")], semantic=None)
        self.assertEqual(ev[0]["first_reported_date"], "")
        self.assertEqual(ev[0]["date_precision"], "unknown")

    def test_S3_real_url_borrowed_from_api_copy(self):
        g = art("Telangana signs MoU with Deakin University on AI research", domain="thehindu.com", name="The Hindu")
        n = art("Telangana signs MoU with Deakin University on AI research", kind="newsapi", domain="thehindu.com",
                url="https://www.thehindu.com/news/x/article1.ece", name="The Hindu")
        merged = dedupe_articles([g, n])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].url, "https://www.thehindu.com/news/x/article1.ece")
        ev, arts, _ = build([g, n], semantic=None)
        self.assertEqual(ev[0]["url_resolved"], "true")


class TestSemantic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from pipeline.semantic import Semantic
        cls.sem = Semantic(encoder=FakeEncoder())

    def test_scores_policy_above_gadget(self):
        a, b = self.sem.score(["State government signs MoU for AI mission", "New AI smartphone launched, stocks rally"])
        self.assertGreater(a.margin, b.margin)

    def test_build_uses_semantic_and_records_classifier(self):
        ev, arts, rej = build([art("Telangana government signs AI MoU with Google", domain="thehindu.com"),
                               art("AI smartphone launched in Hyderabad, stocks rally", domain="x.com")],
                              semantic=self.sem)
        self.assertEqual(len(ev), 1)
        self.assertTrue(arts[0]["classifier"].startswith("rules") or arts[0]["classifier"] == "semantic")
        self.assertNotEqual(arts[0]["relevance_score"], "")


if __name__ == "__main__":
    unittest.main()
