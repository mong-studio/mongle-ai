from agents.feed_generation.state import FeedGraphState


def print_state(state: FeedGraphState) -> None:
    print(f"  image_prompt : {(state.get('image_prompt') or '')[:80]}")
    print(f"  raw_image    : {len(state.get('raw_image') or b'')} bytes")
    print(f"  image_url    : {state.get('image_url')}")
    print(f"  caption_ctx  : {(state.get('caption_ctx') or '')[:80]}")
    print(f"  raw_caption  : {state.get('raw_caption')}")
    print(f"  result       : {state.get('result')}")
