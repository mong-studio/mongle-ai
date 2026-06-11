# ADR-0003: FastAPI AI 서버 배포 플랫폼으로 EC2 선택

**Date**: 2026-06-11
**Status**: accepted
**Deciders**: 개발팀

## Context

mongle-ai FastAPI 서버를 배포할 플랫폼을 선택해야 한다. 이미 RDS(MySQL)와 S3가 AWS에서 운영 중이며, RunPod Serverless는 LLM/이미지 생성 워커로 사용 중이다. FastAPI는 GPU가 필요 없는 CPU 기반 API 서버다.

## Decision

FastAPI AI 서버를 AWS EC2 + docker-compose로 배포한다.

## Alternatives Considered

### Alternative 1: RunPod Serverless
- **Pros**: 기존 RunPod 인프라와 동일한 플랫폼
- **Cons**: GPU 과금, Serverless 콜드 스타트, DB 연동 복잡
- **Why not**: CPU 워크로드에 GPU 비용 낭비, RDS/S3와의 VPC 연동 불편

### Alternative 2: Railway / Render
- **Pros**: 코드 push만으로 배포, 관리형 DB 포함
- **Cons**: AWS 생태계 외부, RDS/S3 연동 시 네트워크 비용 및 지연
- **Why not**: 이미 AWS에 RDS + S3가 있어 EC2가 더 효율적

## Consequences

### Positive
- RDS와 VPC 내부 통신 → 낮은 레이턴시, 네트워크 비용 없음
- S3 IAM Role 연동 간단
- docker-compose로 mongle-ai 전체 스택 단일 관리

### Negative
- EC2 인스턴스 직접 관리 필요 (패치, 모니터링)
- 트래픽 급증 시 수동 스케일 업 필요

### Risks
- EC2 단일 인스턴스 장애 시 다운타임 — 베타 단계에서는 허용, 이후 ALB + Auto Scaling 고려
