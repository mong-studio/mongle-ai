import base64
import json

import httpx
import pytest

from adapters.character_creation.runpod_image import RunPodImageGenerator

pytestmark = pytest.mark.asyncio


async def test_generate_feed_sends_adapter_feed_and_scene_prompt():
    captured = {}
    png = base64.b64encode(b"\x89PNG\r\n").decode()

    def handler(request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if p.endswith("/run"):
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"id": "job1"})
        if "/status/" in p:
            return httpx.Response(
                200, json={"status": "COMPLETED", "output": {"image_b64": png}}
            )
        if "/ref" in p:  # reference 이미지 다운로드
            return httpx.Response(200, content=b"refimg")
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

    assert out == b"\x89PNG\r\n"
    inp = captured["body"]["input"]
    assert inp["mode"] == "feed"
    assert inp["prompt"] == "분홍, cleaning"
    assert inp["quest_ko"] == "cozy bedroom"
    assert inp["appearance"] == appearance
