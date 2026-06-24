import json

from sft_pipeline.crawl.daily_extractor import extract_daily_features


class _FakeResp:
    def __init__(self, content):
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})})]


class _FakeCompletions:
    def __init__(self, content):
        self._content = content

    def create(self, **kwargs):
        return _FakeResp(self._content)


class _FakeClient:
    def __init__(self, content):
        self.chat = type("Chat", (), {"completions": _FakeCompletions(content)})


def _payload(**over):
    base = {
        "plan_kind": "routine",
        "goal_text": "꾸준히 운동",
        "activity": "헬스",
        "domains": "운동",
        "cadence": "주 3회",
        "time_of_day": "저녁",
        "horizon": "한 달",
        "trigger": "건강검진 경고",
        "real_breakdown": "주3회 헬스|주3|저녁",
        "confidence": 0.9,
        "ad": False,
    }
    base.update(over)
    return base


def test_no_client_returns_none():
    assert extract_daily_features("본문", source_url="u", source_type="blog", client=None) is None


def test_extracts_fields_from_client():
    client = _FakeClient(json.dumps(_payload()))
    out = extract_daily_features("본문", source_url="u", source_type="blog", client=client)
    assert out["plan_kind"] == "routine"
    assert out["source_url"] == "u"
    assert out["real_breakdown"] == "주3회 헬스|주3|저녁"


def test_low_confidence_dropped():
    client = _FakeClient(json.dumps(_payload(confidence=0.2)))
    assert extract_daily_features("본문", source_url="u", source_type="blog", client=client) is None


def test_ad_flagged_dropped():
    client = _FakeClient(json.dumps(_payload(ad=True)))
    assert extract_daily_features("본문", source_url="u", source_type="blog", client=client) is None


def test_invalid_json_returns_none():
    client = _FakeClient("not json")
    assert extract_daily_features("본문", source_url="u", source_type="blog", client=client) is None
