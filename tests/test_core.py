import unittest
from pathlib import Path

from pipeline.build import build
from pipeline.classify import amount_crore, judge
from pipeline.dates import to_ist_date
from pipeline.dedupe import canonical_url, cluster
from pipeline.geo import get_geo
from pipeline.run import load_raw

FX = Path(__file__).parent / "fixtures"


class TestGeo(unittest.TestCase):
    def setUp(self):
        self.g = get_geo()

    def test_spellings_collapse_to_one_code(self):
        for v in ["UP", "Uttar Pradesh", "Uttar-Pradesh", "uttar  pradesh"]:
            self.assertEqual(self.g.code_for(v), "IN-UP")
        for v in ["TS", "TG", "Telangana", "Hyderabad", "Cyberabad"]:
            self.assertEqual(self.g.code_for(v), "IN-TG")
        self.assertEqual(self.g.code_for("Bombay"), "IN-MH")

    def test_new_delhi_dateline_is_not_delhi(self):
        self.assertEqual(self.g.resolve("NEW DELHI: MeitY launches IndiaAI compute portal").state_code, "IN-CENTRAL")
        self.assertEqual(self.g.resolve("Delhi CM announces AI traffic system").state_code, "IN-DL")

    def test_ncr_suburbs_not_delhi(self):
        r = self.g.resolve("Noida gets AI data centre")
        self.assertEqual(r.state_code, "IN-UP")
        self.assertFalse(r.in_focus)

    def test_centre_of_excellence_is_not_union_govt(self):
        self.assertEqual(self.g.resolve("Centre of Excellence for AI opened in Chennai").state_code, "IN-TN")

    def test_metro_sets_city(self):
        r = self.g.resolve("Hyderabad police deploy AI cameras")
        self.assertEqual((r.state_code, r.city), ("IN-TG", "Hyderabad"))


class TestClassify(unittest.TestCase):
    def test_line_drawing(self):
        self.assertEqual(judge("Telangana to set up AI task force").category, "institution")
        self.assertEqual(judge("Gujarat budget earmarks Rs 250 crore for AI").category, "budget_funding")
        self.assertEqual(judge("Maharashtra issues guidelines on deepfakes").category, "regulation_ethics")
        self.assertEqual(judge("Karnataka explores voice AI for skilling").category, "governance_deployment")
        # stance / intent is kept, not rejected
        self.assertEqual(judge("Delhi CM urges AI innovation at convocation").category, "statement_intent")
        self.assertEqual(judge("Telangana CM praises Google Gemini infrastructure").category, "statement_intent")
        self.assertEqual(judge("Maharashtra floats tender for AI-based traffic system").category, "procurement")
        self.assertEqual(judge("Google to invest Rs 10,000 crore in AI data centre in Hyderabad").category, "budget_funding")
        self.assertEqual(judge("Infosys shares jump on AI deal").reason, "excluded_topic")
        self.assertEqual(judge("Air India AI-171 probe ordered by state government").reason, "excluded_topic")
        self.assertEqual(judge("Startup raises funding for AI chips").reason, "no_gov_signal")
        self.assertEqual(judge("Hyderabad Metro to run special services").reason, "not_ai")

    def test_amount(self):
        self.assertEqual(amount_crore("Rs 1.5 lakh crore"), 150000)
        self.assertEqual(amount_crore("₹2,500 crore"), 2500)


class TestKeywords(unittest.TestCase):
    def test_case_dots_and_typos(self):
        from pipeline.classify import judge
        v = judge("Gujarat goverment signs M.o.U with IIT Gandhinagar for artifical inteligence lab")
        self.assertTrue(v.keep)
        self.assertEqual(v.category, "partnership")
        self.assertIn("artificial intelligence", v.matched["ai"])
        self.assertTrue(judge("state minster reviews ai-powered crop app").keep)

    def test_fuzzy_does_not_confuse_real_words(self):
        from pipeline.keywords import Keyword, _tok_eq
        def eq(tok, kw):
            k = Keyword(kw)
            return _tok_eq(tok, k.tokens[0], k.prefix)
        for tok, kw in [("goverment", "government"), ("minster", "minister"), ("allcoation", "allocat*"),
                        ("collabration", "collaborat*"), ("surveilance", "surveillance")]:
            self.assertTrue(eq(tok, kw), (tok, kw))
        for tok, kw in [("policy", "police"), ("contrast", "contract*"), ("deplore", "deploy*"),
                        ("startup", "startuptn"), ("session", "mission")]:
            self.assertFalse(eq(tok, kw), (tok, kw))

    def test_investor_is_not_investment(self):
        from pipeline.classify import judge
        self.assertNotEqual(judge("Karnataka explores voice AI for skilling and investor assistance").category,
                            "budget_funding")


class TestDates(unittest.TestCase):
    def test_utc_evening_becomes_next_ist_day(self):
        self.assertEqual(to_ist_date("2026-09-24T18:48:01+00:00"), ("2026-09-25", "day"))

    def test_unknown_is_explicit(self):
        self.assertEqual(to_ist_date(""), ("", "unknown"))
        self.assertEqual(to_ist_date("sometime soon"), ("", "unknown"))
        self.assertEqual(to_ist_date("Mar 2026"), ("2026-03-01", "month"))


class TestDedupe(unittest.TestCase):
    def test_canonical_url(self):
        self.assertEqual(canonical_url("https://www.thehindu.com/a/b.ece/amp/?utm_source=x"),
                         canonical_url("http://thehindu.com/a/b.ece"))

    def test_event_clustering(self):
        items = [dict(state_code=s, date=d, title=t) for s, d, t in [
            ("IN-TG", "2026-09-24", "Deakin University of Australia and Telangana government sign MoU to advance AI"),
            ("IN-TG", "2026-09-25", "Telangana inks pact with Australia's Deakin University for AI"),
            ("IN-TG", "2026-09-20", "Telangana signs MoU with Google for AI skilling"),
            ("IN-TG", "2026-09-21", "Telangana signs MoU with Microsoft for AI skilling"),
            ("IN-KA", "2026-09-24", "Karnataka signs MoU with Deakin University on AI research"),
            ("IN-TG", "2026-06-01", "Telangana signs MoU with Deakin University on AI research"),
        ]]
        groups = sorted(sorted(g) for g in cluster(items))
        self.assertIn([0, 1], groups)          # same event, reworded
        self.assertIn([2], groups)             # Google != Microsoft
        self.assertIn([4], groups)             # other state
        self.assertIn([5], groups)             # months apart


class TestEndToEnd(unittest.TestCase):
    def test_fixture_run(self):
        events, articles, rejected = build(load_raw([FX / "raw_sample.jsonl"]))
        by_title = {e["title"][:30]: e for e in events}
        mou = by_title["Deakin University of Australia"]
        self.assertEqual(mou["source_count"], 2)                # AIR + The Hindu merged
        self.assertEqual(mou["primary_source_name"], "News On AIR")   # .gov.in preferred
        self.assertEqual(by_title["Karnataka explores voice AI fo"]["state_code"], "IN-KA")  # text beats feed hint
        self.assertEqual(by_title["Karnataka explores voice AI fo"]["date_precision"], "unknown")
        self.assertTrue(all(a["event_id"] in {e["event_id"] for e in events} for a in articles))
        self.assertTrue(any(r["reason"] == "not_ai" for r in rejected))


if __name__ == "__main__":
    unittest.main()
