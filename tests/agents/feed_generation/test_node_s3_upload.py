import pytest
from agents.feed_generation.exceptions import S3UploadError
from agents.feed_generation.nodes.s3_upload import s3_upload_node
from tests.agents.feed_generation.fakes import (
    FakeS3,
    FailingS3,
    make_ports,
    make_state,
)


async def test_s3_upload_node_sets_image_url_and_routes_to_assemble_caption_ctx():
    fake_s3 = FakeS3(url="https://s3.example.com/feeds/out.png")
    ports = make_ports(s3=fake_s3)
    state = make_state(raw_image=b"img_data")
    config = {"configurable": {"ports": ports}}

    cmd = await s3_upload_node(state, config)

    assert cmd.goto == "assemble_caption_ctx"
    assert cmd.update["image_url"] == "https://s3.example.com/feeds/out.png"


async def test_s3_upload_node_uses_character_and_quest_ids_in_key():
    fake_s3 = FakeS3()
    ports = make_ports(s3=fake_s3)
    state = make_state(raw_image=b"img_data")
    config = {"configurable": {"ports": ports}}

    await s3_upload_node(state, config)

    key = fake_s3.calls[0][0]
    assert str(state["input"].character.character_id) in key
    assert str(state["input"].quest.quest_id) in key


async def test_s3_upload_node_wraps_port_error_as_s3_upload_error():
    ports = make_ports(s3=FailingS3())
    state = make_state(raw_image=b"img_data")
    config = {"configurable": {"ports": ports}}

    with pytest.raises(S3UploadError):
        await s3_upload_node(state, config)
