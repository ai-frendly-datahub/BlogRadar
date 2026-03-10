"""Quality check script for BlogRadar."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    from blogradar.config_loader import load_category_config, load_settings
    from blogradar.storage import RadarStorage

    settings = load_settings()
    category_cfg = load_category_config("techblog")

    storage = RadarStorage(settings.database_path)
    articles = storage.recent_articles("techblog", days=7)
    storage.close()

    print(f"Sources configured: {len(category_cfg.sources)}")
    print(f"Entities configured: {len(category_cfg.entities)}")
    print(f"Articles (last 7d): {len(articles)}")

    matched = sum(1 for a in articles if a.matched_entities)
    if articles:
        match_rate = matched / len(articles) * 100
        print(f"Entity match rate: {match_rate:.1f}%")

    issues: list[str] = []
    for source in category_cfg.sources:
        if not source.url:
            issues.append(f"Source '{source.name}' has no URL")
        if not source.url.startswith("http"):
            issues.append(f"Source '{source.name}' URL looks invalid: {source.url}")

    if issues:
        print(f"\nIssues found ({len(issues)}):")
        for issue in issues:
            print(f"  - {issue}")
        sys.exit(1)
    else:
        print("\n✅ Quality checks passed")


if __name__ == "__main__":
    main()
