# Trend Frame Reader Docs

이 디렉터리는 `trend-frame-reader` 백엔드 프로젝트 구조를 빠르게 파악하기 위한 문서 세트입니다.

## 읽는 순서

1. [System Overview](./architecture/01-system-overview.md)
2. [Backend Structure](./architecture/02-backend-structure.md)
3. [Sequence Diagrams](./architecture/03-sequence-diagrams.md)
4. [Data Model](./architecture/04-data-model.md)
5. [Operations](./architecture/05-operations.md)
6. [API Map](./architecture/06-api-map.md)

## 범위

- 대상: 현재 레포의 FastAPI 백엔드(`app/`)
- 포함: 아키텍처, 모듈 책임, 런타임 시퀀스, 데이터 모델, 운영 흐름
- 제외: 프론트엔드 상세 구현(`trend-frame-reader-web`), 스프링 포팅 레포 상세

## 빠른 요약

- API 서버: FastAPI + SQLAlchemy + PostgreSQL
- 보조 저장소: MongoDB Atlas(그래프/벡터), OpenAI(키워드/임베딩/RAG)
- 스케줄러: APScheduler(30분 ingestion, 매시 05분 feed refresh)
- 인증: Google OAuth + JWT 쿠키(`auth_token`)
