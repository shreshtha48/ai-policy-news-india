"""Copy the pipeline's outputs into the dashboard so it is self-contained.

  python scripts/sync_dashboard_data.py

data/processed/{events,articles}.csv + data/reference/{states,categories}.csv
  -> dashboard/public/data/   (Vite serves it in `npm run dev` and copies it
                               into site/data/ on `npm run build`)
Falls back to data/mock/ when no real output exists yet. Runs automatically
at the end of `python -m pipeline.run process`.
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "dashboard" / "public" / "data"


def sync(quiet: bool = False) -> str:
    if not (ROOT / "dashboard").exists():
        return "no dashboard/ folder"
    DEST.mkdir(parents=True, exist_ok=True)
    proc = ROOT / "data" / "processed"
    if (proc / "events.csv").exists():
        pairs, origin = [(proc / "events.csv", "events.csv"), (proc / "articles.csv", "articles.csv")], "processed"
    else:
        mock = ROOT / "data" / "mock"
        pairs, origin = [(mock / "events_mock.csv", "events.csv"), (mock / "articles_mock.csv", "articles.csv")], "MOCK"
    pairs += [(ROOT / "data" / "reference" / "states.csv", "states.csv"),
              (ROOT / "data" / "reference" / "categories.csv", "categories.csv")]
    for src, name in pairs:
        if src.exists():
            shutil.copyfile(src, DEST / name)
    msg = f"dashboard data synced from {origin} -> {DEST.relative_to(ROOT)}"
    if not quiet:
        print(msg)
    return msg


if __name__ == "__main__":
    sys.exit(0 if sync() else 1)
