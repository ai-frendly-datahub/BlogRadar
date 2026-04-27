# Data Quality Plan

- 생성 시각: `2026-04-11T16:05:37.910248+00:00`
- 우선순위: `P2`
- 데이터 품질 점수: `93`
- 가장 약한 축: `권위성`
- Governance: `low`
- Primary Motion: `intelligence`

## 현재 이슈

- 현재 설정상 즉시 차단 이슈 없음. 운영 지표와 freshness SLA만 명시하면 됨

## 필수 신호

- GitHub release·star·issue activity
- package registry download와 dependency adoption
- 기술 채용공고와 skill demand

## 품질 게이트

- 블로그 언급량과 실제 채택 신호를 별도 점수로 유지
- repository/package 이름 충돌을 canonical key로 정리
- 릴리스일·게시일·수집일을 분리

## 다음 구현 순서

- GitHub release/star와 package download source를 운영 레이어로 연결
- 기술명 alias map과 package/repository canonical key를 추가
- 채용공고 skill demand를 후행 adoption 검증 신호로 붙임

## 운영 규칙

- 원문 URL, 수집일, 이벤트 발생일은 별도 필드로 유지한다.
- 공식 source와 커뮤니티/시장 source를 같은 신뢰 등급으로 병합하지 않는다.
- collector가 인증키나 네트워크 제한으로 skip되면 실패를 숨기지 말고 skip 사유를 기록한다.
- 이 문서는 `scripts/build_data_quality_review.py --write-repo-plans`로 재생성한다.
