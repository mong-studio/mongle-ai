"""합성 산출물(daily.jsonl)을 S3에 업로드한다(RunPod 본생성 후).

sft_pipeline 은 FastAPI 앱과 독립적으로 돌기 때문에, 앱의 비동기 S3Storage
(character_creation 결합) 대신 여기서 boto3 를 직접 쓰는 작은 동기 업로더를 둔다.
자격증명/리전은 표준 AWS 환경변수(AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY/AWS_REGION)를
따른다 — 코드에 시크릿을 두지 않는다.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

_CONTENT_TYPE = "application/x-ndjson"


def build_key(prefix: str, filename: str) -> str:
    """prefix 와 파일명을 '/'로 합친다. 앞뒤 슬래시는 정리한다."""
    prefix = prefix.strip("/")
    return f"{prefix}/{filename}" if prefix else filename


def upload_file(local_path: Path, *, bucket: str, key: str, client=None) -> str:
    """로컬 파일을 s3://{bucket}/{key} 로 올리고 s3 URI 를 반환한다.

    client 미지정 시 boto3 기본 S3 클라이언트를 만든다(자격증명은 환경변수).
    테스트에서는 put_object 를 가진 가짜 client 를 주입한다.
    """
    if not bucket:
        raise ValueError("S3 bucket이 비어 있습니다 (S3_BUCKET 환경변수 또는 --bucket 필요).")
    local_path = Path(local_path)
    body = local_path.read_bytes()
    if client is None:
        import boto3

        client = boto3.client("s3", region_name=os.environ.get("AWS_REGION"))
    client.put_object(Bucket=bucket, Key=key, Body=body, ContentType=_CONTENT_TYPE)
    return f"s3://{bucket}/{key}"


def main() -> None:
    parser = argparse.ArgumentParser(description="daily.jsonl → S3 업로드")
    parser.add_argument("--in", dest="in_path", required=True, type=Path)
    parser.add_argument("--bucket", default=os.environ.get("S3_BUCKET"))
    parser.add_argument("--prefix", default=os.environ.get("S3_PREFIX", "sft/daily"))
    parser.add_argument("--key", default=None, help="명시 시 prefix/파일명 대신 이 key 를 그대로 사용")
    args = parser.parse_args()

    key = args.key or build_key(args.prefix, args.in_path.name)
    uri = upload_file(args.in_path, bucket=args.bucket or "", key=key)
    print(f"[upload] {args.in_path} -> {uri}")


if __name__ == "__main__":
    main()
