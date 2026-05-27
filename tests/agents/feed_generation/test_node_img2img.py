import pytest
from agents.feed_generation.exceptions import ImageGenerationError
from agents.feed_generation.nodes.img2img import img2img_node
from tests.agents.feed_generation.fakes import (
    FakeImageGenerator,
    FailingImageGenerator,
    make_ports,
    make_state,
)


async def test_img2img_node_sets_raw_image_and_routes_to_s3_upload():
    fake_gen = FakeImageGenerator(image_bytes=b"img_data")
    ports = make_ports(image_generator=fake_gen)
    state = make_state(image_prompt="분홍 머리, anime style")
    config = {"configurable": {"ports": ports}}

    cmd = await img2img_node(state, config)

    assert cmd.goto == "s3_upload"
    assert cmd.update["raw_image"] == b"img_data"


async def test_img2img_node_passes_reference_url_and_prompt():
    fake_gen = FakeImageGenerator()
    ports = make_ports(image_generator=fake_gen)
    state = make_state(image_prompt="분홍 머리, anime style")
    config = {"configurable": {"ports": ports}}

    await img2img_node(state, config)

    assert fake_gen.calls[0][0] == state["input"].character.image_url
    assert fake_gen.calls[0][1] == "분홍 머리, anime style"


async def test_img2img_node_wraps_port_error_as_image_generation_error():
    ports = make_ports(image_generator=FailingImageGenerator())
    state = make_state(image_prompt="prompt")
    config = {"configurable": {"ports": ports}}

    with pytest.raises(ImageGenerationError):
        await img2img_node(state, config)
