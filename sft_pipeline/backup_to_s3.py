"""SFT 데이터셋·시드·평가 결과를 S3에 백업한다.

사용법:
    uv run python sft_pipeline/backup_to_s3.py           # 실제 업로드
    uv run python sft_pipeline/backup_to_s3.py --dry-run # 파일 목록 확인만

환경변수 (.env):
    AWS_S3_BUCKET  — 대상 버킷
    AWS_REGION     — 리전 (예: ap-northeast-2)
    AWS_S3_PREFIX  — 버킷 내 공통 prefix (예: mongle-village)
    AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY — boto3 기본 credential chain

S3 키 구조:
    {AWS_S3_PREFIX}/sft/seeds/         — gold 시드 (손으로 큐레이션, 복원 불가)
    {AWS_S3_PREFIX}/sft/datasets/v4/   — 최종 학습·검증 JSONL
    {AWS_S3_PREFIX}/sft/evaluation/    — LLM judge 점수·실패 케이스
    {AWS_S3_PREFIX}/sft/reports/       — postcheck·coherence JSON 보고서
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import os

import boto3
from botocore.exceptions import BotoCoreError, ClientError


# ── 백업 대상 정의 ─────────────────────────────────────────────────────────────
# (local_rel, s3_subkey, 설명)
#   local_rel: ROOT 기준 상대 경로 (파일 또는 디렉토리)
#   s3_subkey: {AWS_S3_PREFIX}/sft/{s3_subkey}/ 로 업로드
BACKUP_TARGETS: list[tuple[str, str, str]] = [
    # 최우선: 손으로 큐레이션한 gold 시드 (복원 불가)
    ("sft_pipeline/data/seeds", "seeds", "Gold seed JSONL (hand-curated)"),
    # 최우선: 최신 v4 학습·검증셋 (14B LLM 재호출 비용 발생)
    ("sft_pipeline/data/generated/ipe_hardened_v4_dryrun_train.jsonl", "datasets/v4", "v4 train split"),
    ("sft_pipeline/data/generated/ipe_hardened_v4_dryrun_valid.jsonl", "datasets/v4", "v4 valid split"),
    ("sft_pipeline/data/generated/ipe_hardened_v4_mix_sft.jsonl", "datasets/v4", "v4 full mix"),
    ("sft_pipeline/data/generated/ipe_hardened_v4_valid_plan_only.jsonl", "datasets/v4", "v4 plan-only valid"),
    ("sft_pipeline/data/generated/ipe_hardened_v4_valid_followup_only.jsonl", "datasets/v4", "v4 followup-only valid"),
    # 중간: LLM evaluation 결과 (재평가 비용)
    ("llm_evaluation/data/combined", "evaluation/combined", "LLM judge scores & failure cases"),
    ("llm_evaluation/data/generated", "evaluation/generated", "LLM eval generated samples"),
    # 중간: SFT 보고서 (JSON 측정치)
    ("sft_pipeline/reports", "reports", "Postcheck & coherence JSON reports"),
]


def _build_client():
    bucket = os.getenv("AWS_S3_BUCKET")
    region = os.getenv("AWS_REGION")
    if not bucket:
        raise SystemExit("AWS_S3_BUCKET 환경변수가 없습니다. .env 파일을 확인하세요.")
    endpoint_url = f"https://s3.{region}.amazonaws.com" if region else None
    client = boto3.client("s3", region_name=region, endpoint_url=endpoint_url)
    return client, bucket


def _s3_key(prefix: str, subkey: str, filename: str) -> str:
    parts = [p for p in [prefix, subkey, filename] if p]
    return "/".join(parts)


def _collect_files(local: Path) -> list[Path]:
    if local.is_file():
        return [local]
    if local.is_dir():
        return sorted(f for f in local.rglob("*") if f.is_file() and not f.name.startswith("."))
    return []


def run(dry_run: bool, s3_prefix: str) -> None:
    prefix = s3_prefix.strip().strip("/")
    bucket_name = os.getenv("AWS_S3_BUCKET", "<AWS_S3_BUCKET 미설정>")

    if not dry_run:
        client, bucket = _build_client()

    uploaded = 0
    skipped = 0
    total_bytes = 0

    print(f"\n{'[DRY RUN] ' if dry_run else ''}S3 백업 시작")
    print(f"  버킷  : {bucket_name}")
    print(f"  prefix: {prefix}/\n")

    for rel_str, subkey, desc in BACKUP_TARGETS:
        local = ROOT / rel_str
        files = _collect_files(local)

        if not files:
            print(f"  [SKIP] {rel_str}  (파일 없음)\n")
            skipped += 1
            continue

        print(f"  [{desc}]")
        for f in files:
            base_path = ROOT / rel_str
            relative = str(f.relative_to(base_path)) if base_path.is_dir() else f.name
            key = _s3_key(prefix, subkey, relative)
            size_kb = f.stat().st_size // 1024

            if dry_run:
                print(f"    → s3://{bucket_name}/{key}  ({size_kb} KB)")
            else:
                try:
                    client.upload_file(str(f), bucket, key)
                    print(f"    ✓ {key}  ({size_kb} KB)")
                    total_bytes += f.stat().st_size
                    uploaded += 1
                except (BotoCoreError, ClientError) as e:
                    print(f"    ✗ {key}  오류: {e}", file=sys.stderr)

        print()

    print("─" * 60)
    if dry_run:
        print("Dry-run 완료. 실제 업로드하려면 --dry-run 없이 실행하세요.")
    else:
        print(f"완료: {uploaded}개 파일, {total_bytes / 1024 / 1024:.1f} MB 업로드")


def main() -> None:
    parser = argparse.ArgumentParser(description="SFT 데이터를 S3에 백업")
    parser.add_argument("--dry-run", action="store_true", help="실제 업로드 없이 대상 파일 목록만 출력")
    parser.add_argument(
        "--s3-prefix",
        default="sft",
        help="버킷 내 prefix (기본값: sft). 예: --s3-prefix mongle-village/sft",
    )
    args = parser.parse_args()
    run(dry_run=args.dry_run, s3_prefix=args.s3_prefix)


if __name__ == "__main__":
    main()
