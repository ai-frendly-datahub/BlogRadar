from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from html import escape
from pathlib import Path
from typing import Any

from radar_core.ontology import build_summary_ontology_metadata
from radar_core.report_utils import (
    generate_index_html as _core_generate_index_html,
)
from radar_core.report_utils import (
    generate_report as _core_generate_report,
)

from .models import Article, CategoryConfig


def generate_report(
    *,
    category: CategoryConfig,
    articles: Iterable[Article],
    output_path: Path,
    stats: dict[str, int],
    errors: list[str] | None = None,
    store=None,
    quality_report: Mapping[str, Any] | None = None,
) -> Path:
    """Generate HTML report (delegates to radar-core)."""
    articles_list = list(articles)
    plugin_charts = []

    # --- Universal plugins (entity heatmap + source reliability) ---
    try:
        from radar_core.plugins.entity_heatmap import get_chart_config as _heatmap_config

        _heatmap = _heatmap_config(articles=articles_list)
        if _heatmap is not None:
            plugin_charts.append(_heatmap)
    except Exception:
        pass
    try:
        from radar_core.plugins.source_reliability import get_chart_config as _reliability_config

        _reliability = _reliability_config(store=store)
        if _reliability is not None:
            plugin_charts.append(_reliability)
    except Exception:
        pass

    report_path = _core_generate_report(
        category=category,
        articles=articles_list,
        output_path=output_path,
        stats=stats,
        errors=errors,
        plugin_charts=plugin_charts if plugin_charts else None,
        ontology_metadata=build_summary_ontology_metadata(
            "BlogRadar",
            category_name=category.category_name,
            search_from=Path(__file__).resolve(),
        ),
    )
    if quality_report:
        for quality_report_path in _quality_panel_report_paths(
            report_path,
            category.category_name,
        ):
            _inject_blog_quality_panel(quality_report_path, quality_report)
    return report_path


def _quality_panel_report_paths(report_path: Path, category_name: str) -> list[Path]:
    paths = [report_path]
    pattern = re.compile(rf"^{re.escape(category_name)}_\d{{8}}\.html$")
    dated_reports = [
        path
        for path in report_path.parent.glob(f"{category_name}_*.html")
        if pattern.match(path.name)
    ]
    dated_reports.sort(key=lambda path: path.stat().st_mtime_ns, reverse=True)
    if dated_reports and dated_reports[0] not in paths:
        paths.append(dated_reports[0])
    return paths


def _inject_blog_quality_panel(
    report_path: Path,
    quality_report: Mapping[str, Any],
) -> None:
    panel = _render_blog_quality_panel(quality_report)
    html = report_path.read_text(encoding="utf-8")
    if 'id="blog-quality"' in html:
        return
    marker = '<section id="entities"'
    if marker in html:
        html = html.replace(marker, f"{panel}\n\n      {marker}", 1)
    else:
        html = html.replace("</main>", f"{panel}\n    </main>", 1)
    report_path.write_text(html, encoding="utf-8")


def _render_blog_quality_panel(quality_report: Mapping[str, Any]) -> str:
    summary = _mapping(quality_report.get("summary"))
    events = _list_of_mappings(quality_report.get("events"))[:8]
    review_items = _list_of_mappings(quality_report.get("daily_review_items"))[:8]
    chips = [
        ("events", summary.get("operational_adoption_event_count", 0)),
        ("repo keys", summary.get("repository_canonical_key_present_count", 0)),
        ("package keys", summary.get("package_canonical_key_present_count", 0)),
        ("proxy keys", summary.get("technology_proxy_key_count", 0)),
        ("field gaps", summary.get("event_required_field_gap_count", 0)),
        ("review", summary.get("daily_review_item_count", 0)),
    ]
    chip_html = "\n          ".join(
        f'<span class="chip brand"><strong>{escape(label)}</strong> {escape(str(value))}</span>'
        for label, value in chips
    )
    return f"""      <section id="blog-quality" class="section" aria-label="Blog quality">
        <div class="section-hd">
          <div>
            <p class="eyebrow">Quality</p>
            <h2>Blog Quality</h2>
          </div>
          <div class="right mono">{escape(str(quality_report.get("generated_at", "")))}</div>
        </div>
        <div class="chips">
          {chip_html}
        </div>
        <div class="grid two">
          <div class="panel">
            <p class="panel-title">Operational Adoption Events</p>
            {_render_quality_events(events)}
          </div>
          <div class="panel">
            <p class="panel-title">Daily Review</p>
            {_render_quality_review(review_items)}
          </div>
        </div>
      </section>"""


def _render_quality_events(events: list[Mapping[str, Any]]) -> str:
    if not events:
        return '<p class="muted">No operational adoption events observed.</p>'
    rows = []
    for event in events:
        rows.append(
            "<tr>"
            f"<td>{escape(str(event.get('event_model') or ''))}</td>"
            f"<td>{escape(str(event.get('source') or ''))}</td>"
            f"<td>{escape(str(event.get('canonical_key') or ''))}</td>"
            f"<td>{escape(str(event.get('signal_basis') or ''))}</td>"
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table><thead><tr>'
        "<th>Model</th><th>Source</th><th>Canonical key</th><th>Basis</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def _render_quality_review(items: list[Mapping[str, Any]]) -> str:
    if not items:
        return '<p class="muted">No review items.</p>'
    rows = []
    for item in items:
        gaps = item.get("required_field_gaps")
        if isinstance(gaps, list):
            detail = ", ".join(str(gap) for gap in gaps)
        else:
            detail = str(
                item.get("activation_gate")
                or item.get("canonical_key")
                or item.get("latest_title")
                or item.get("title")
                or ""
            )
        rows.append(
            "<tr>"
            f"<td>{escape(str(item.get('reason') or ''))}</td>"
            f"<td>{escape(str(item.get('event_model') or ''))}</td>"
            f"<td>{escape(str(item.get('source') or ''))}</td>"
            f"<td>{escape(detail)}</td>"
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table><thead><tr>'
        "<th>Reason</th><th>Model</th><th>Source</th><th>Detail</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def generate_index_html(
    report_dir: Path,
    summaries_dir: Path | None = None,
) -> Path:
    """Generate index.html (delegates to radar-core)."""
    radar_name = "Blog Radar"
    return _core_generate_index_html(report_dir, radar_name)
