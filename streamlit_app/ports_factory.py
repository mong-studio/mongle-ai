from __future__ import annotations

import os
from dataclasses import dataclass

import boto3
from openai import OpenAI

from adapters.character_creation.memory_repo import InMemoryRepo
from adapters.character_creation.openai_image import OpenAIImageGenerator
from adapters.character_creation.openai_llm import OpenAILLM
from adapters.character_creation.openai_vlm import OpenAIVLM
from adapters.character_creation.s3_storage import S3Storage
from agents.character_creation.pipeline import Ports


class MissingEnvError(RuntimeError):
    pass


def _split_s3_uri(value: str) -> tuple[str, str]:
    """Accept either a bare bucket name or an ``s3://bucket/prefix/...`` URI.

    Returns ``(bucket, prefix)`` where ``prefix`` is "" if none was embedded.
    """
    if value.startswith("s3://"):
        value = value[len("s3://") :]
    bucket, _, prefix = value.partition("/")
    return bucket.strip("/"), prefix.strip("/")


@dataclass
class AppConfig:
    openai_api_key: str
    aws_region: str
    aws_s3_bucket: str
    aws_s3_prefix: str

    @classmethod
    def from_env(cls) -> AppConfig:
        missing: list[str] = []

        def need(key: str) -> str:
            val = os.environ.get(key, "").strip()
            if not val:
                missing.append(key)
            return val

        raw_bucket = need("AWS_S3_BUCKET")
        bucket, embedded_prefix = _split_s3_uri(raw_bucket)
        env_prefix = os.environ.get("AWS_S3_PREFIX", "").strip().strip("/")
        prefix = env_prefix or embedded_prefix or "mongle-village"

        cfg = cls(
            openai_api_key=need("OPENAI_API_KEY"),
            aws_region=need("AWS_REGION"),
            aws_s3_bucket=bucket,
            aws_s3_prefix=prefix,
        )
        if missing:
            raise MissingEnvError(
                "다음 환경변수가 필요합니다: " + ", ".join(missing)
            )
        return cfg


def build_ports(repo: InMemoryRepo, cfg: AppConfig) -> Ports:
    openai_client = OpenAI(api_key=cfg.openai_api_key)
    s3_client = boto3.client("s3", region_name=cfg.aws_region)

    return Ports(
        llm=OpenAILLM(client=openai_client, model="gpt-4o"),
        vlm=OpenAIVLM(client=openai_client, model="gpt-4o"),
        s3=S3Storage(
            client=s3_client,
            bucket=cfg.aws_s3_bucket,
            prefix=cfg.aws_s3_prefix,
        ),
        image_generator=OpenAIImageGenerator(
            client=openai_client, model="gpt-image-1", size="1024x1024"
        ),
        counter=repo,
        repository=repo,
    )
