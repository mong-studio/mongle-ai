import base64
import io
import json

import httpx
import pytest
from PIL import Image

from adapters.character_creation.runpod_image import RunPodImageGenerator

pytestmark = pytest.mark.asyncio


def _png(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


async def test_generate_feed_composites_sprite_on_worker_background():
    captured = {}
    background = _png(Image.new("RGBA", (64, 64), (200, 120, 60, 255)))
    sprite = _png(Image.new("RGBA", (20, 30), (20, 80, 200, 255)))
    bg_b64 = base64.b64encode(background).decode()

    def handler(request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if p.endswith("/run"):
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"id": "job1"})
        if "/status/" in p:
            return httpx.Response(
                200, json={"status": "COMPLETED", "output": {"image_b64": bg_b64}}
            )
        if "/ref" in p:  # 원본 캐릭터 스프라이트 다운로드
            return httpx.Response(200, content=sprite)
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gen = RunPodImageGenerator(
        endpoint_url="http://ep", api_key="k", poll_interval=0, client=client
    )
    appearance = {"character_type": "bear", "main_colors": ["pink"]}
    out = await gen.generate_feed(
        "http://ep/ref/x.png",
        "분홍, cleaning",
        "cozy bedroom",
        appearance,
    )

    # 합성 결과는 배경 크기의 유효한 PNG 여야 한다.
    result = Image.open(io.BytesIO(out))
    assert result.format == "PNG"
    assert result.size == (64, 64)

    # 워커로 보낸 입력(배경 생성용)은 그대로다.
    inp = captured["body"]["input"]
    assert inp["mode"] == "feed"
    assert inp["prompt"] == "분홍, cleaning"
    assert inp["quest_ko"] == "cozy bedroom"
    assert inp["appearance"] == appearance


async def test_generate_feed_without_reference_returns_background():
    background = _png(Image.new("RGBA", (32, 32), (10, 10, 10, 255)))
    bg_b64 = base64.b64encode(background).decode()

    def handler(request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if p.endswith("/run"):
            return httpx.Response(200, json={"id": "job1"})
        if "/status/" in p:
            return httpx.Response(
                200, json={"status": "COMPLETED", "output": {"image_b64": bg_b64}}
            )
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gen = RunPodImageGenerator(
        endpoint_url="http://ep", api_key="k", poll_interval=0, client=client
    )
    # reference_url 이 비면 합성 없이 배경 그대로 반환한다.
    out = await gen.generate_feed("", "p", "scene", {"character_type": "bear"})
    assert out == background
