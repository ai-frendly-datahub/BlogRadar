# BlogRadar

기술 블로그 RSS 수집 및 트렌드 분석 Radar. 국내외 주요 기술 블로그 포스트를 매일 수집하여 도메인·언어·프레임워크별로 분류하고 GitHub Pages에 배포합니다.

## 수집 대상

- **국내 기업**: 카카오, 네이버, 토스, 배달의민족, 당근, 라인, 뱅크샐러드, 쿠팡, NHN, 하이퍼커넥트 등
- **글로벌 빅테크**: Google, Meta, Netflix, Airbnb, Uber, GitHub, Cloudflare, Stripe, Shopify, Spotify 등
- **오픈소스**: Kubernetes, Go, Rust, PyTorch
- **커뮤니티**: Hacker News, Dev.to, The New Stack

## 실행

```bash
pip install -r requirements.txt
python main.py --category techblog --recent-days 7 --keep-days 90 --generate-report
```

## 스케줄

매일 06:00 UTC (한국 오후 3시) 자동 수집 후 GitHub Pages 배포.
