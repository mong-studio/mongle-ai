from pathlib import Path

import pytest

from sft_pipeline.latte.upload import build_key, upload_file


class _FakeS3:
    """boto3 S3 client 의 put_object 만 흉내내며 호출 인자를 기록한다."""

    def __init__(self):
        self.calls: list[dict] = []

    def put_object(self, **kwargs):
        self.calls.append(kwargs)


def test_upload_file_puts_object_and_returns_uri(tmp_path):
    f = tmp_path / "daily.jsonl"
    f.write_text('{"a":1}\n', encoding="utf-8")
    s3 = _FakeS3()

    uri = upload_file(f, bucket="my-bucket", key="sft/daily/daily.jsonl", client=s3)

    assert uri == "s3://my-bucket/sft/daily/daily.jsonl"
    assert len(s3.calls) == 1
    call = s3.calls[0]
    assert call["Bucket"] == "my-bucket"
    assert call["Key"] == "sft/daily/daily.jsonl"
    assert call["Body"] == b'{"a":1}\n'


def test_upload_file_requires_bucket(tmp_path):
    f = tmp_path / "daily.jsonl"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        upload_file(f, bucket="", key="k", client=_FakeS3())


def test_build_key_joins_prefix_and_strips_slashes():
    assert build_key("sft/daily", "daily.jsonl") == "sft/daily/daily.jsonl"
    assert build_key("/sft/daily/", "x.jsonl") == "sft/daily/x.jsonl"
    assert build_key("", "x.jsonl") == "x.jsonl"
