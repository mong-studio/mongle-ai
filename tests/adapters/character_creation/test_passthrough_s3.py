import pytest

from adapters.character_creation.passthrough_s3 import PassthroughSourceS3


class _RecordingS3:
    def __init__(self):
        self.put_calls = []
        self.delete_calls = []

    async def put_object(self, *, key, body, content_type):
        self.put_calls.append(key)
        return f"https://real/{key}"

    async def delete_object(self, *, key):
        self.delete_calls.append(key)


@pytest.mark.asyncio
async def test_source_prefix_returns_known_url_without_upload():
    """sources/ 프리픽스는 업로드 없이 알려진 source_url을 그대로 반환한다."""
    inner = _RecordingS3()
    s3 = PassthroughSourceS3(inner=inner, source_url="https://web/src.png")
    url = await s3.put_object(key="sources/u1/abc.png", body=b"x", content_type="image/png")
    assert url == "https://web/src.png"
    assert inner.put_calls == []


@pytest.mark.asyncio
async def test_non_source_prefix_delegates_to_inner():
    """sources/ 외 프리픽스는 내부 S3로 위임해 실제 업로드한다."""
    inner = _RecordingS3()
    s3 = PassthroughSourceS3(inner=inner, source_url="https://web/src.png")
    url = await s3.put_object(key="characters/u1/gen.png", body=b"y", content_type="image/png")
    assert url == "https://real/characters/u1/gen.png"
    assert inner.put_calls == ["characters/u1/gen.png"]


@pytest.mark.asyncio
async def test_delete_source_prefix_is_noop():
    """sources/ 프리픽스 삭제는 내부 S3를 건드리지 않는 no-op이다."""
    inner = _RecordingS3()
    s3 = PassthroughSourceS3(inner=inner, source_url="https://web/src.png")
    await s3.delete_object(key="sources/u1/abc.png")
    assert inner.delete_calls == []
