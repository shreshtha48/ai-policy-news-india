"""Review steps 2 (read near-miss articles) and 3 (classifier trained on our labels)."""
import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from pipeline.build import build
from pipeline.enrich import candidates, extract_lead
from pipeline.models import RawArticle

from .helpers import FakeEncoder

HAS_SKLEARN = importlib.util.find_spec("sklearn") is not None


def art(title, url, excerpt=""):
    return RawArticle(source_kind="google_news_rss", title=title, url=url, source_name="Outlet",
                      source_domain="outlet.com", published="2026-09-20T10:00:00+05:30", excerpt=excerpt,
                      fetched_at="2026-09-25T00:00:00+00:00")


class TestEnrich(unittest.TestCase):
    HTML = """<html><body><nav>Home | AI | Tech</nav><article>
      <p>HYDERABAD: The Telangana Police on Friday deployed C-SIGHT, an artificial intelligence based tool that scans
      seized devices to speed up investigations into child sexual abuse material, officials said.</p>
      <p>The tool was developed with the state's IT department and will be rolled out to all district units.</p>
      </article><footer>Copyright</footer></body></html>"""

    def test_extract_lead(self):
        lead = extract_lead(self.HTML)
        self.assertIn("artificial intelligence based tool", lead)
        self.assertNotIn("Copyright", lead)

    def test_candidates_pick_state_action_headlines_only(self):
        rows = [{"reason": "not_ai", "title": "Telangana Police Deploys C-SIGHT for CSEAM Investigations", "source_url": "u1"},
                {"reason": "not_ai", "title": "Telangana Government Announces Optional Holidays for 2026", "source_url": "u2"},
                {"reason": "not_ai", "title": "India, US deepen collaboration", "source_url": "u3"},
                {"reason": "excluded_topic", "title": "Telangana signs MoU", "source_url": "u4"}]
        self.assertEqual([r["source_url"] for r in candidates(rows)], ["u1"])

    def test_article_lead_rescues_a_near_miss(self):
        a = art("Telangana Police Deploys C-SIGHT for CSEAM Investigations", "https://news.google.com/rss/articles/X")
        _, _, rej = build([a], semantic=None, bodies={})
        self.assertEqual(rej[0]["reason"], "not_ai")
        lead = extract_lead(self.HTML)
        ev, arts, _ = build([art(a.title, a.url)], semantic=None, bodies={a.url: lead})
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["state_code"], "IN-TG")
        self.assertIn("excerpt:article", arts[0]["matched_terms"])


@unittest.skipUnless(HAS_SKLEARN, "scikit-learn not installed")
class TestTrainedClassifier(unittest.TestCase):
    POS = ["Telangana government signs AI MoU with Google", "Karnataka minister unveils AI policy mission",
           "Telangana police deploy AI cameras", "State budget crore for AI mission", "CM praises AI hub plan",
           "Karnataka govt tender for AI tool", "Telangana AI task force set up by government",
           "Minister signs pact for AI schools", "Govt deploys AI tool in schools", "State AI policy guidelines deepfake"]
    NEG = ["AI smartphone launched stocks rally", "Startup funding for AI chips", "Film uses AI", "Cricket match AI stats",
           "Telangana holidays list", "Karnataka bus flyover opened", "AI shares jump on deal",
           "Startup AI funding round", "Smartphone AI cameras review", "Holidays and cricket schedule"]

    def _sheet(self, d: Path) -> Path:
        p = d / "sheet.csv"
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["label", "category", "suggested", "suggested_category", "reason", "title", "excerpt", "source", "url", "text_id"])
            for i in range(2):                           # 20 of each class
                for t in self.POS:
                    w.writerow([1, "", 1, "partnership" if "MoU" in t or "pact" in t else "policy_mission", "", f"{t} {i}", "", "", "", ""])
                for t in self.NEG:
                    w.writerow([0, "", 0, "", "", f"{t} {i}", "", "", "", ""])
        return p

    def test_train_save_load_and_use_in_build(self):
        spec = importlib.util.spec_from_file_location("train", Path("scripts/train_classifier.py"))
        train = importlib.util.module_from_spec(spec); spec.loader.exec_module(train)
        from pipeline.learned import Learned
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            meta = train.main([], embed_fn=FakeEncoder(), sheet=self._sheet(d), out=d / "model")
            self.assertGreaterEqual(meta["cv"]["f1"], 0.8)
            self.assertTrue((d / "model" / "head.joblib").exists())
            m = Learned(model_dir=d / "model", embed_fn=FakeEncoder())
            p = m.proba(["Telangana government signs AI MoU", "AI smartphone stocks rally"])
            self.assertGreater(p[0], p[1])
            ev, arts, rej = build([art("Telangana government signs AI MoU with Google", "https://a.com/1"),
                                   art("AI smartphone launched in Hyderabad, stocks rally", "https://a.com/2")],
                                  semantic=None, learned=m, bodies={})
            self.assertEqual(len(ev), 1)
            self.assertEqual(arts[0]["classifier"], "learned")
            self.assertIn(rej[0]["reason"], ("learned_low", "excluded_topic"))
            self.assertIn("baseline_current_pipeline", json.loads((d / "model" / "meta.json").read_text()))


if __name__ == "__main__":
    unittest.main()
