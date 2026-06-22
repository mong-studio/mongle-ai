from agents.feed_generation.state import FeedGraphState


def print_state(state: FeedGraphState) -> None:
    feed_prompt = state.get("feed_prompt")
    print(f"  feed_prompt.character : {(getattr(feed_prompt, 'character', '') or '')[:80]}")
    print(f"  feed_prompt.scene     : {(getattr(feed_prompt, 'scene', '') or '')[:80]}")
    print(f"  raw_image     : {len(state.get('raw_image') or b'')} bytes")
    print(f"  image_url     : {state.get('image_url')}")
    print(f"  caption_prompt: {(state.get('caption_prompt') or '')[:80]}")
    print(f"  raw_caption   : {state.get('raw_caption')}")
    print(f"  result        : {state.get('result')}")
