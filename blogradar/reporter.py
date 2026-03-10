from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, cast

from jinja2 import Template

from .models import Article, CategoryConfig


class _TemplateRenderer(Protocol):
    def render(self, **context: object) -> str: ...


def generate_report(
    *,
    category: CategoryConfig,
    articles: Iterable[Article],
    output_path: Path,
    stats: dict[str, int],
    errors: list[str] | None = None,
) -> Path:
    """Render a simple HTML report for the collected articles."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    articles_list = list(articles)
    entity_counts = _count_entities(articles_list)

    articles_json: list[dict[str, object]] = []
    for article in articles_list:
        article_data: dict[str, object] = {
            "title": article.title,
            "link": article.link,
            "source": article.source,
            "published": article.published.isoformat() if article.published else None,
            "published_at": article.published.isoformat() if article.published else None,
            "summary": article.summary,
            "matched_entities": article.matched_entities or {},
            "collected_at": article.collected_at.isoformat()
            if hasattr(article, "collected_at") and article.collected_at
            else None,
        }
        articles_json.append(article_data)

    template = cast(_TemplateRenderer, Template(_REPORT_TEMPLATE))
    rendered = template.render(
        category=category,
        articles=articles_list,
        articles_json=articles_json,
        generated_at=datetime.now(timezone.utc),
        stats=stats,
        entity_counts=entity_counts,
        errors=errors or [],
    )
    _ = output_path.write_text(rendered, encoding="utf-8")
    return output_path


def _count_entities(articles: Iterable[Article]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for article in articles:
        for entity_name, keywords in (article.matched_entities or {}).items():
            counter[entity_name] += len(keywords)
    return counter


def generate_index_html(report_dir: Path) -> Path:
    """Generate an index.html that lists all available report files."""
    report_dir.mkdir(parents=True, exist_ok=True)

    html_files = sorted(
        [f for f in report_dir.glob("*.html") if f.name != "index.html"],
        key=lambda p: p.name,
    )

    reports = []
    for html_file in html_files:
        name = html_file.stem
        display_name = name.replace("_report", "").replace("_", " ").title()
        reports.append({"filename": html_file.name, "display_name": display_name})

    template = cast(_TemplateRenderer, Template(_INDEX_TEMPLATE))
    rendered = template.render(
        reports=reports,
        generated_at=datetime.now(timezone.utc),
    )

    index_path = report_dir / "index.html"
    _ = index_path.write_text(rendered, encoding="utf-8")
    return index_path


_REPORT_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{{ category.display_name }} - Radar Report</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; padding: 24px; background: #f6f8fb; color: #0f172a; }
    h1 { margin: 0 0 8px 0; }
    h2 { margin: 24px 0 12px 0; }
    .summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 12px 0 24px 0; }
    .card { background: white; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px; box-shadow: 0 1px 2px rgba(0,0,0,0.04); }
    .muted { color: #475569; font-size: 13px; }
    .pill { display: inline-block; padding: 2px 8px; border-radius: 999px; background: #e0f2fe; color: #0369a1; font-size: 12px; margin-right: 6px; }
    .chip { display: inline-block; padding: 4px 8px; border-radius: 8px; background: #0ea5e9; color: white; font-size: 12px; margin: 4px 4px 0 0; }
    .articles { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 12px; }
    a { color: #0f172a; text-decoration: none; }
    a:hover { text-decoration: underline; }
    footer { margin-top: 32px; color: #475569; font-size: 13px; }
    .errors { background: #fef2f2; border: 1px solid #fecaca; color: #b91c1c; padding: 12px; border-radius: 10px; margin-top: 16px; }
    .charts-section { margin-top: 24px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 12px; }
    .chart-wrap { position: relative; height: 280px; margin-top: 8px; }
  </style>
</head>
<body>
  <h1>{{ category.display_name }}</h1>
  <div class="muted">Generated at {{ generated_at.isoformat() }} (UTC)</div>

  <div class="summary">
    <div class="card"><div class="muted">Sources</div><strong>{{ stats.sources }}</strong></div>
    <div class="card"><div class="muted">Collected</div><strong>{{ stats.collected }}</strong></div>
    <div class="card"><div class="muted">With entity hits</div><strong>{{ stats.matched }}</strong></div>
    <div class="card"><div class="muted">Recent window (days)</div><strong>{{ stats.window_days }}</strong></div>
  </div>

  {% if errors %}
    <div class="errors">
      <strong>Collection errors</strong><br>
      {% for error in errors %}• {{ error }}<br>{% endfor %}
    </div>
  {% endif %}

  <div class="charts-section">
    <h2>Visualizations</h2>
    <div class="grid">
      <div class="card">
        <div class="muted">Entity Distribution</div>
        <div class="chart-wrap">
          <canvas id="chartEntities"></canvas>
        </div>
      </div>
      <div class="card">
        <div class="muted">Article Timeline</div>
        <div class="chart-wrap">
          <canvas id="chartTimeline"></canvas>
        </div>
      </div>
    </div>
    <div class="grid" style="margin-top:12px">
      <div class="card">
        <div class="muted">Source Distribution</div>
        <div class="chart-wrap">
          <canvas id="chartSources"></canvas>
        </div>
      </div>
      <div class="card">
        <div class="muted">Chart Notes</div>
        <p class="muted" style="margin:8px 0 0 0; line-height:1.5; font-size:12px">
          Entity chart shows keyword frequency. Timeline displays articles per day. 
          Source chart shows article distribution by source.
        </p>
      </div>
    </div>

    <div class="grid" style="margin-top:12px">
      <div class="card">
        <div class="muted">Data Freshness (collection lag)</div>
        <div class="chart-wrap"><canvas id="chartFreshness"></canvas></div>
      </div>
      <div class="card">
        <div class="muted">Entity Extraction Rate</div>
        <div class="chart-wrap"><canvas id="chartEntityRate"></canvas></div>
      </div>
    </div>
    <div class="grid" style="margin-top:12px">
      <div class="card">
        <div class="muted">Source Health</div>
        <div class="chart-wrap"><canvas id="chartSourceHealth"></canvas></div>
      </div>
    </div>
  </div>

  {% if entity_counts %}
  <h2>Entity hit counts</h2>
  <div class="card">
    {% for entity, count in entity_counts.most_common() %}
      <span class="pill">{{ entity }} · {{ count }}</span>
    {% endfor %}
  </div>
  {% endif %}

  <h2>Recent articles</h2>
  <div class="articles">
    {% for article in articles %}
    <div class="card">
      <a href="{{ article.link }}" target="_blank" rel="noopener noreferrer"><strong>{{ article.title }}</strong></a>
      <div class="muted">{{ article.source }}{% if article.published %} · {{ article.published.date().isoformat() }}{% endif %}</div>
      <div class="muted">{{ article.summary[:220] }}{% if article.summary|length > 220 %}...{% endif %}</div>
      {% if article.matched_entities %}
        <div style="margin-top:8px;">
          {% for entity, keywords in article.matched_entities.items() %}
            <span class="chip">{{ entity }}: {{ keywords | join(", ") }}</span>
          {% endfor %}
        </div>
      {% endif %}
    </div>
    {% endfor %}
    {% if articles|length == 0 %}
      <div class="card">No articles in the recent window.</div>
    {% endif %}
  </div>

  <footer>
    This is a lightweight template — extend collectors/analyzers as needed.
  </footer>

  <script id="articles-data" type="application/json">{{ articles_json|tojson }}</script>
  <script id="entities-data" type="application/json">{{ entity_counts|tojson if entity_counts else '{}' }}</script>

  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
  <script>
    (function () {
      function readJson(id, fallback) {
        const el = document.getElementById(id);
        if (!el) return fallback;
        const txt = (el.textContent || "").trim();
        if (!txt) return fallback;
        try { return JSON.parse(txt); } catch (e) { return fallback; }
      }

      const articles = readJson("articles-data", []);
      const entityCountsRaw = readJson("entities-data", {});

      function normalizeEntityPairs(raw) {
        if (!raw) return [];
        if (Array.isArray(raw)) {
          if (raw.length && Array.isArray(raw[0]) && raw[0].length >= 2) {
            return raw.map(p => [String(p[0]), Number(p[1]) || 0]);
          }
          if (raw.length && typeof raw[0] === "object") {
            return raw.map(o => [String(o.name || o.entity || ""), Number(o.count || o.value || 0) || 0]).filter(p => p[0]);
          }
          return [];
        }
        if (typeof raw === "object") {
          return Object.entries(raw).map(([k, v]) => [String(k), Number(v) || 0]);
        }
        return [];
      }

      function getArticleDate(a) {
        const v = a && (a.published_at || a.published || a.date || a.datetime || a.publishedAt);
        if (!v) return null;
        const s = String(v);
        const direct = new Date(s);
        if (!isNaN(direct.getTime())) return direct;
        const m = s.match(/^(\\d{4})-(\\d{2})-(\\d{2})/);
        if (m) {
          const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
          if (!isNaN(d.getTime())) return d;
        }
        return null;
      }

      function toDayKey(d) {
        const y = d.getFullYear();
        const m = String(d.getMonth() + 1).padStart(2, "0");
        const day = String(d.getDate()).padStart(2, "0");
        return y + "-" + m + "-" + day;
      }

      function buildTimeline(items) {
        const map = new Map();
        for (const a of items) {
          const d = getArticleDate(a);
          if (!d) continue;
          const k = toDayKey(d);
          map.set(k, (map.get(k) || 0) + 1);
        }
        const keys = Array.from(map.keys()).sort();
        return { labels: keys, values: keys.map(k => map.get(k) || 0) };
      }

      function buildSources(items) {
        const map = new Map();
        for (const a of items) {
          const s = (a && a.source) ? String(a.source) : "unknown";
          const key = s.trim() || "unknown";
          map.set(key, (map.get(key) || 0) + 1);
        }
        const pairs = Array.from(map.entries()).sort((a, b) => b[1] - a[1]);
        const top = pairs.slice(0, 10);
        const rest = pairs.slice(10).reduce((acc, p) => acc + p[1], 0);
        const labels = top.map(p => p[0]);
        const values = top.map(p => p[1]);
        if (rest > 0) { labels.push("other"); values.push(rest); }
        return { labels, values };
      }

      function palette(n) {
        const base = [
          "rgba(51,214,197,.86)",
          "rgba(25,167,195,.78)",
          "rgba(246,200,76,.86)",
          "rgba(120,162,255,.78)",
          "rgba(255,91,110,.74)",
          "rgba(160,118,255,.70)",
          "rgba(95,222,132,.70)",
          "rgba(255,154,74,.70)"
        ];
        const out = [];
        for (let i = 0; i < n; i++) out.push(base[i % base.length]);
        return out;
      }

      if (!window.Chart) return;

      const entityPairs = normalizeEntityPairs(entityCountsRaw)
        .filter(p => p[0] && Number.isFinite(p[1]))
        .sort((a, b) => b[1] - a[1])
        .slice(0, 12);

      const timeline = buildTimeline(articles);
      const sources = buildSources(articles);

      const entityCanvas = document.getElementById("chartEntities");
      if (entityCanvas && entityPairs.length) {
        const labels = entityPairs.map(p => p[0]);
        const values = entityPairs.map(p => p[1]);
        new Chart(entityCanvas.getContext("2d"), {
          type: "bar",
          data: {
            labels,
            datasets: [{
              label: "count",
              data: values,
              backgroundColor: "rgba(51,214,197,.35)",
              borderColor: "rgba(51,214,197,.72)",
              borderWidth: 1.2,
              borderRadius: 8
            }]
          },
          options: {
            plugins: {
              legend: { display: false }
            },
            scales: {
              y: { beginAtZero: true }
            }
          }
        });
      }

      const timelineCanvas = document.getElementById("chartTimeline");
      if (timelineCanvas && timeline.labels.length) {
        new Chart(timelineCanvas.getContext("2d"), {
          type: "line",
          data: {
            labels: timeline.labels,
            datasets: [{
              label: "articles/day",
              data: timeline.values,
              tension: 0.3,
              fill: true,
              borderColor: "rgba(246,200,76,.84)",
              backgroundColor: "rgba(246,200,76,.15)",
              pointRadius: 3,
              pointBackgroundColor: "rgba(246,200,76,.84)"
            }]
          },
          options: {
            plugins: {
              legend: { display: false }
            },
            scales: {
              y: { beginAtZero: true }
            }
          }
        });
      }

       const sourcesCanvas = document.getElementById("chartSources");
       if (sourcesCanvas && sources.labels.length) {
         const colors = palette(sources.labels.length);
         new Chart(sourcesCanvas.getContext("2d"), {
           type: "doughnut",
           data: {
             labels: sources.labels,
             datasets: [{
               label: "articles",
               data: sources.values,
               backgroundColor: colors.map(c => c.replace(")", ", .35)").replace("rgba", "rgba")),
               borderColor: colors.map(c => c.replace(")", ", .80)").replace("rgba", "rgba")),
               borderWidth: 1.2
             }]
           },
           options: {
             cutout: "62%",
             plugins: {
               legend: {
                 position: "bottom"
               }
             }
           }
         });
       }

       // Chart 1: Data Freshness (collection lag in hours)
       function buildFreshness(items) {
         const lagBuckets = { "0-1h": 0, "1-6h": 0, "6-24h": 0, "1-3d": 0, "3-7d": 0, "7d+": 0 };
         const now = new Date();
         for (const a of items) {
           const pubStr = a && (a.published_at || a.published);
           const collStr = a && a.collected_at;
           if (!pubStr || !collStr) continue;
           const pubDate = new Date(String(pubStr));
           const collDate = new Date(String(collStr));
           if (isNaN(pubDate.getTime()) || isNaN(collDate.getTime())) continue;
           const lagMs = collDate.getTime() - pubDate.getTime();
           const lagHours = lagMs / (1000 * 60 * 60);
           if (lagHours < 1) lagBuckets["0-1h"]++;
           else if (lagHours < 6) lagBuckets["1-6h"]++;
           else if (lagHours < 24) lagBuckets["6-24h"]++;
           else if (lagHours < 72) lagBuckets["1-3d"]++;
           else if (lagHours < 168) lagBuckets["3-7d"]++;
           else lagBuckets["7d+"]++;
         }
         return { labels: Object.keys(lagBuckets), values: Object.values(lagBuckets) };
       }

       const freshnessData = buildFreshness(articles);
       const freshnessCanvas = document.getElementById("chartFreshness");
       if (freshnessCanvas && freshnessData.labels.length) {
         new Chart(freshnessCanvas.getContext("2d"), {
           type: "bar",
           data: {
             labels: freshnessData.labels,
             datasets: [{
               label: "articles",
               data: freshnessData.values,
               backgroundColor: "rgba(120,162,255,.35)",
               borderColor: "rgba(120,162,255,.72)",
               borderWidth: 1.2,
               borderRadius: 8
             }]
           },
           options: {
             plugins: { legend: { display: false } },
             scales: { y: { beginAtZero: true } }
           }
         });
       }

       // Chart 2: Entity Extraction Rate (doughnut with center text)
       function buildEntityRate(items) {
         let withEntities = 0, withoutEntities = 0;
         for (const a of items) {
           const ents = a && a.matched_entities;
           if (ents && Object.keys(ents).length > 0) withEntities++;
           else withoutEntities++;
         }
         return { with: withEntities, without: withoutEntities };
       }

       const entityRateData = buildEntityRate(articles);
        const entityRateCanvas = document.getElementById("chartEntityRate");
        if (entityRateCanvas) {
          const total = entityRateData.with + entityRateData.without;
          const pct = total > 0 ? Math.round((entityRateData.with / total) * 100) : 0;
          const plugin = {
            id: "textCenter",
            beforeDatasetsDraw(c) {
              const { width, height } = c.chartArea;
              const x = c.chartArea.left + width / 2;
              const y = c.chartArea.top + height / 2;
              c.ctx.save();
              c.ctx.font = "bold 24px sans-serif";
              c.ctx.fillStyle = "rgba(15,23,42,.8)";
              c.ctx.textAlign = "center";
              c.ctx.textBaseline = "middle";
              c.ctx.fillText(pct + "%", x, y);
              c.ctx.restore();
            }
          };
          new Chart(entityRateCanvas.getContext("2d"), {
            type: "doughnut",
            data: {
              labels: ["With entities", "Without entities"],
              datasets: [{
                data: [entityRateData.with, entityRateData.without],
                backgroundColor: ["rgba(95,222,132,.35)", "rgba(255,91,110,.35)"],
                borderColor: ["rgba(95,222,132,.80)", "rgba(255,91,110,.80)"],
                borderWidth: 1.2
              }]
            },
            options: {
              cutout: "62%",
              plugins: {
                legend: { position: "bottom" },
                tooltip: { enabled: true }
              }
            },
            plugins: [plugin]
          });
        }

       // Chart 3: Source Health (horizontal bar, sorted descending)
       function buildSourceHealth(items) {
         const map = new Map();
         for (const a of items) {
           const s = (a && a.source) ? String(a.source) : "unknown";
           const key = s.trim() || "unknown";
           map.set(key, (map.get(key) || 0) + 1);
         }
         const pairs = Array.from(map.entries()).sort((a, b) => b[1] - a[1]);
         return { labels: pairs.map(p => p[0]), values: pairs.map(p => p[1]) };
       }

       const sourceHealthData = buildSourceHealth(articles);
       const sourceHealthCanvas = document.getElementById("chartSourceHealth");
       if (sourceHealthCanvas && sourceHealthData.labels.length) {
         const colors = palette(sourceHealthData.labels.length);
         new Chart(sourceHealthCanvas.getContext("2d"), {
           type: "bar",
           data: {
             labels: sourceHealthData.labels,
             datasets: [{
               label: "articles",
               data: sourceHealthData.values,
               backgroundColor: colors.map(c => c.replace(")", ", .35)").replace("rgba", "rgba")),
               borderColor: colors.map(c => c.replace(")", ", .80)").replace("rgba", "rgba")),
               borderWidth: 1.2,
               borderRadius: 8
             }]
           },
           options: {
             indexAxis: "y",
             plugins: { legend: { display: false } },
             scales: { x: { beginAtZero: true } }
           }
         });
       }
     })();
   </script>
</body>
</html>
"""


_INDEX_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Radar Reports</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; padding: 24px; background: #f6f8fb; color: #0f172a; }
    h1 { margin: 0 0 8px 0; }
    .muted { color: #475569; font-size: 13px; margin-bottom: 24px; }
    .reports { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; }
    .card { background: white; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px; box-shadow: 0 1px 2px rgba(0,0,0,0.04); transition: box-shadow 0.2s; }
    .card:hover { box-shadow: 0 4px 6px rgba(0,0,0,0.08); }
    a { color: #0f172a; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .empty { text-align: center; color: #64748b; padding: 48px; }
  </style>
</head>
<body>
  <h1>Radar Reports</h1>
  <div class="muted">Generated at {{ generated_at.isoformat() }} (UTC)</div>

  {% if reports %}
  <div class="reports">
    {% for report in reports %}
    <div class="card">
      <a href="{{ report.filename }}"><strong>{{ report.display_name }}</strong></a>
    </div>
    {% endfor %}
  </div>
  {% else %}
  <div class="empty">No reports available yet.</div>
  {% endif %}
</body>
</html>
"""
