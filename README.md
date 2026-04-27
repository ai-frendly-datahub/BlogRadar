# BlogRadar - 기술 블로그 트렌드 레이더

**🌐 Live Report**: https://ai-frendly-datahub.github.io/BlogRadar/

기술 블로그와 개발자 커뮤니티를 함께 모니터링하는 레이더입니다. 국내외 주요 엔지니어링 블로그 포스트를 매일 수집하고, release/changelog/migration 같은 adoption signal도 함께 추적해 도메인·언어·프레임워크별로 분류합니다.

## 수집 대상

- **국내 기업**: 카카오, 네이버, 토스, 배달의민족, 당근, 라인, 뱅크샐러드, 쿠팡, NHN, 하이퍼커넥트 등
- **글로벌 빅테크**: Google, Meta, Netflix, Airbnb, Uber, GitHub, Cloudflare, Stripe, Shopify, Spotify 등
- **오픈소스/운영 시그널**: Kubernetes, Go, Rust, GitHub, Vercel, HashiCorp
- **커뮤니티**: Hacker News, Dev.to, Reddit 개발 커뮤니티

## 소스 전략

- **Market**: 국내외 기술 블로그, 엔지니어링 매체, 뉴스레터
- **Community**: Reddit 개발자 커뮤니티
- **Operational**: release, changelog, migration, deprecation, platform rollout 성격이 강한 공식 블로그

현재 collector는 `rss`와 `reddit` 소스를 모두 처리합니다.

## 실행

```bash
pip install -r requirements.txt
python main.py --category techblog --recent-days 7 --keep-days 90 --generate-report
```

## 발행 자산

- 자동 생성 뉴스레터: [newsletter/README.md](newsletter/README.md)
- 수동 작성 초안: [ai-content-collection-linkedin.md](newsletter/drafts/ai-content-collection-linkedin.md)

## 스케줄

매일 06:00 UTC (한국 오후 3시) 자동 수집 후 GitHub Pages 배포.

<!-- DATAHUB-OPS-AUDIT:START -->
## DataHub Operations

- CI/CD workflows: `newsletter.yml`, `pr-checks.yml`, `radar-crawler.yml`.
- GitHub Pages visualization: `reports/index.html` (valid HTML); https://ai-frendly-datahub.github.io/BlogRadar/.
- Latest remote Pages check: HTTP 200, HTML.
- Local workspace audit: 58 Python files parsed, 0 syntax errors.
- Re-run audit from the workspace root: `python scripts/audit_ci_pages_readme.py --syntax-check --write`.
- Latest audit report: `_workspace/2026-04-14_github_ci_pages_readme_audit.md`.
- Latest Pages URL report: `_workspace/2026-04-14_github_pages_url_check.md`.
<!-- DATAHUB-OPS-AUDIT:END -->
