# BLOGRADAR

53개 기술 블로그 RSS 피드(국내+글로벌+오픈소스+커뮤니티)를 수집·분석하는 레이더. 프로그래밍 언어, 프레임워크, 도메인, 주제, 회사 기준 엔티티 태깅.

## STRUCTURE

```
BlogRadar/
├── blogradar/
│   ├── collector.py              # collect_sources() — RSS 피드 수집 (53개 소스)
│   ├── analyzer.py               # apply_entity_rules() — 기술 키워드 매칭
│   ├── reporter.py               # generate_report() — Jinja2 HTML
│   ├── storage.py                # RadarStorage — DuckDB upsert/query/retention
│   ├── models.py                 # Source, Article, EntityDefinition, CategoryConfig
│   ├── config_loader.py          # YAML 로딩
│   ├── logger.py                 # structlog 구조화 로깅
│   ├── notifier.py               # Email/Webhook 알림
│   ├── raw_logger.py             # JSONL 원시 로깅
│   ├── search_index.py           # SQLite FTS5 전문 검색
│   ├── nl_query.py               # 자연어 쿼리 파서
│   ├── resilience.py             # Circuit breaker (pybreaker)
│   ├── exceptions.py             # 커스텀 예외 계층
│   ├── common/                   # validators, quality_checks
│   └── mcp_server/               # MCP 서버 (server.py + tools.py)
├── config/
│   ├── config.yaml               # database_path, report_dir, raw_data_dir, search_db_path
│   └── categories/techblog.yaml  # 53개 RSS 소스 + 5개 엔티티 카테고리
├── data/                         # DuckDB, search_index.db, raw/ JSONL
├── reports/                      # 생성된 HTML 리포트
├── scripts/
│   └── check_quality.py          # 품질 체크 CLI
├── tests/
│   ├── unit/                     # 단위 테스트 (10개 파일)
│   └── integration/              # 통합 테스트 (6개 파일)
├── main.py                       # CLI 엔트리포인트
└── .github/workflows/radar-crawler.yml  # 매일 06:00 UTC
```

## ENTITIES

| Entity | Name | 주요 키워드 예시 |
|--------|------|----------------|
| `domain` | 도메인 | frontend, backend, devops, machine learning, kubernetes, cloud native |
| `language` | 언어 | python, golang, rust, typescript, javascript, java |
| `framework` | 프레임워크 | react, next.js, fastapi, django, pytorch, tensorflow, docker, kafka, llm, rag |
| `topic` | 주제 | performance, scalability, observability, architecture, migration, real-time |
| `company` | 회사 | kakao, naver, toss, google, meta, netflix, stripe, shopify |

## RSS 소스 구성

53개 피드:
- **국내 기술 블로그**: 카카오, 네이버, 토스, 라인, 쿠팡, 우아한형제들, 당근 등
- **글로벌 기술 블로그**: Netflix, Meta, Stripe, Shopify, Cloudflare, GitHub, Figma 등
- **오픈소스/커뮤니티**: Python.org, Rust Blog, CNCF, InfoQ 등

## DEVIATIONS FROM TEMPLATE

- **resilience.py**: Circuit breaker 패턴 (`pybreaker`) — 소스 장애 격리
- **exceptions.py**: `NetworkError`, `ParseError`, `SourceError` 계층 구조
- **mcp_server/**: Claude Desktop 연동용 MCP 서버
- **common/quality_checks.py**: 수집 데이터 품질 검증
- **scripts/check_quality.py**: 품질 체크 CLI 스크립트

## COMMANDS

```bash
python main.py --category techblog --recent-days 7 --keep-days 90 --generate-report
pytest tests/unit -m unit
pytest tests/integration -m integration
```
