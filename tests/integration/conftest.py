from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from blogradar.models import Article, CategoryConfig, EntityDefinition, Source
from blogradar.storage import RadarStorage


@pytest.fixture
def tmp_storage(tmp_path: Path) -> RadarStorage:
    db_path = tmp_path / "test.duckdb"
    storage = RadarStorage(db_path)
    yield storage
    storage.close()


@pytest.fixture
def sample_articles() -> list[Article]:
    now = datetime.now(timezone.utc)
    return [
        Article(
            title="Python 3.13의 새로운 기능들",
            link="https://techblog.example.com/python-3-13-features",
            summary="Python 3.13에서 추가된 성능 최적화와 새로운 문법들을 소개합니다.",
            published=now,
            source="python_blog",
            category="techblog",
            matched_entities={},
        ),
        Article(
            title="React 19 서버 컴포넌트 완벽 가이드",
            link="https://techblog.example.com/react-19-server-components",
            summary="React 19의 서버 컴포넌트 기능과 next.js 통합 방법을 알아봅니다.",
            published=now,
            source="frontend_blog",
            category="techblog",
            matched_entities={},
        ),
        Article(
            title="Kubernetes 클러스터 성능 최적화 전략",
            link="https://techblog.example.com/kubernetes-performance",
            summary="대규모 kubernetes 클러스터의 성능과 확장성 개선을 위한 실전 가이드.",
            published=now,
            source="devops_blog",
            category="techblog",
            matched_entities={},
        ),
        Article(
            title="FastAPI로 구축하는 마이크로서비스 아키텍처",
            link="https://techblog.example.com/fastapi-microservices",
            summary="fastapi와 docker를 활용한 마이크로서비스 아키텍처 설계 패턴.",
            published=now,
            source="backend_blog",
            category="techblog",
            matched_entities={},
        ),
        Article(
            title="Rust로 작성한 고성능 웹 서버 구현",
            link="https://techblog.example.com/rust-web-server",
            summary="rust의 메모리 안전성과 성능을 활용한 웹 서버 구현 사례.",
            published=now,
            source="systems_blog",
            category="techblog",
            matched_entities={},
        ),
    ]


@pytest.fixture
def sample_entities() -> list[EntityDefinition]:
    return [
        EntityDefinition(
            name="language",
            display_name="프로그래밍 언어",
            keywords=["python", "rust", "golang", "typescript", "javascript"],
        ),
        EntityDefinition(
            name="framework",
            display_name="프레임워크",
            keywords=["react", "next.js", "fastapi", "django", "docker"],
        ),
        EntityDefinition(
            name="domain",
            display_name="도메인",
            keywords=["kubernetes", "마이크로서비스", "backend", "frontend", "devops"],
        ),
        EntityDefinition(
            name="topic",
            display_name="주제",
            keywords=["성능", "확장성", "아키텍처", "최적화", "observability"],
        ),
    ]


@pytest.fixture
def sample_config(tmp_path: Path, sample_entities: list[EntityDefinition]) -> CategoryConfig:
    sources = [
        Source(
            name="python_blog",
            type="rss",
            url="https://techblog.example.com/feed",
        ),
    ]
    return CategoryConfig(
        category_name="techblog",
        display_name="기술 블로그",
        sources=sources,
        entities=sample_entities,
    )
