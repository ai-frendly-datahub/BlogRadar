# BlogRadar Newsletter Generator

Automated weekly newsletter generation from BlogRadar's tech blog article database.

## Overview

This newsletter system:
- Reads weekly top articles from DuckDB database
- Groups articles by framework/language trends
- Generates both HTML and Markdown newsletter formats
- Runs automatically every Sunday via GitHub Actions

## Directory Structure

```
newsletter/
├── README.md           # This file
├── config.yaml         # Newsletter configuration
├── template.html       # Jinja2 HTML template
├── generator.py        # Main generation script
└── output/             # Generated newsletter files
    ├── newsletter_YYYYMMDD.html
    ├── newsletter_YYYYMMDD.md
    └── newsletter_YYYYMMDD.json
```

## Setup

### Prerequisites

- Python 3.11+
- DuckDB database with articles data
- Required Python packages:
  - `duckdb`
  - `jinja2`
  - `pyyaml`

### Local Installation

```bash
# From BlogRadar root directory
pip install duckdb jinja2 pyyaml

# Or install all requirements
pip install -r requirements.txt
pip install jinja2 pyyaml
```

## Usage

### Generate Newsletter Locally

```bash
# Basic usage (uses default paths)
python newsletter/generator.py

# Specify custom paths
python newsletter/generator.py \
  --db data/radar_data.duckdb \
  --config newsletter/config.yaml \
  --template newsletter/template.html \
  --output newsletter/output \
  --category techblog \
  --days 7

# Dry run (preview without generating files)
python newsletter/generator.py --dry-run
```

### Command Line Options

| Option | Default | Description |
|--------|---------|-------------|
| `--db` | `data/radar_data.duckdb` | Path to DuckDB database |
| `--config` | `newsletter/config.yaml` | Path to configuration file |
| `--template` | `newsletter/template.html` | Path to HTML template |
| `--output` | `newsletter/output` | Output directory |
| `--category` | `techblog` | Article category filter |
| `--days` | `7` | Number of days to include |
| `--dry-run` | `false` | Preview mode (no files) |

## Configuration

Edit `config.yaml` to customize the newsletter:

### Newsletter Settings

```yaml
newsletter:
  name: "Tech Blog Radar Weekly"
  description: "Weekly digest of trending tech blog articles"
  frequency: "weekly"

  data:
    days: 7           # Articles from past N days
    min_articles: 10  # Minimum articles to include
    max_articles: 50  # Maximum articles to include
```

### Sections

Configure which sections appear in the newsletter:

```yaml
sections:
  - id: "top_articles"
    title: "Top Articles This Week"
    max_items: 10

  - id: "by_domain"
    title: "Trends by Domain"
    max_items_per_group: 5
    groups:
      - "AI/ML"
      - "Backend"
      - "Frontend"
      - "DevOps"
      - "Security"
```

### Layout Customization

```yaml
layout:
  primary_color: "#2563eb"
  secondary_color: "#1e40af"
  background_color: "#f8fafc"
  text_color: "#1e293b"
  link_color: "#3b82f6"
```

### Entity Groupings

Define how articles are grouped by topic:

```yaml
entity_groups:
  "AI/ML":
    - "machine learning"
    - "deep learning"
    - "pytorch"
    - "tensorflow"
  "Backend":
    - "fastapi"
    - "django"
    - "postgresql"
```

## GitHub Actions

The newsletter is automatically generated every Sunday at 09:00 KST (00:00 UTC).

### Workflow: `.github/workflows/newsletter.yml`

- **Schedule**: Every Sunday at 00:00 UTC
- **Manual trigger**: Available via workflow_dispatch
- **Outputs**: Newsletter files are committed to the repository

### Manual Trigger

1. Go to Actions tab in GitHub
2. Select "Weekly Newsletter" workflow
3. Click "Run workflow"
4. Optionally enable "dry_run" for preview mode

## Output Formats

### HTML Newsletter

Full-featured HTML email with:
- Responsive design
- Styled sections with icons
- Article cards with metadata
- Tag badges for domains/languages

### Markdown Newsletter

Plain text format suitable for:
- GitHub releases
- Discord/Slack posts
- RSS feeds
- Static site generators

### JSON Data

Raw newsletter data for:
- API consumption
- Custom rendering
- Analytics

## Customization

### Modify HTML Template

Edit `template.html` to customize the newsletter appearance:

```html
<!-- Add new section -->
<div class="section">
  <div class="section-header">
    <span class="section-icon">&#x1F4CC;</span>
    <span class="section-title">{{ section_title }}</span>
  </div>
  {% for article in articles %}
  <div class="article-card">
    <!-- Article content -->
  </div>
  {% endfor %}
</div>
```

### Add New Groupings

1. Define keywords in `config.yaml`:
   ```yaml
   entity_groups:
     "NewCategory":
       - "keyword1"
       - "keyword2"
   ```

2. Update `generator.py` to include the new group in the output.

### Change Schedule

Edit `.github/workflows/newsletter.yml`:

```yaml
schedule:
  # Daily at 09:00 KST
  - cron: "0 0 * * *"

  # Every Monday and Thursday
  - cron: "0 0 * * 1,4"
```

## Troubleshooting

### No Articles Found

- Check if the database exists and contains data
- Verify the category name matches your data
- Try increasing `--days` parameter

### Template Errors

- Ensure Jinja2 is installed: `pip install jinja2`
- Check template syntax for unclosed tags

### Database Connection Issues

- Verify DuckDB is installed: `pip install duckdb`
- Check database file permissions
- Ensure database path is correct

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test locally with `--dry-run`
5. Submit a pull request

## License

MIT License - See repository LICENSE file.
