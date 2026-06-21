from sft_pipeline.build.lib.rephrase import rephrase


def test_template_default_no_llm():
    """use_llm=False면 원문을 그대로 두고 출처를 'template'로 표기하는지 확인."""
    text, by = rephrase("원본 계획 텍스트", use_llm=False)
    assert text == "원본 계획 텍스트"
    assert by == "template"


class _FakeClient:
    class chat:
        class completions:
            @staticmethod
            def create(model, messages, **kwargs):
                class _M:
                    content = "재서술된 계획"

                class _C:
                    message = _M()

                class _R:
                    choices = [_C()]

                return _R()


def test_llm_path_uses_client():
    """use_llm=True면 주입된 LLM 클라이언트로 재서술하고 출처를 'llm'로 표기하는지 확인."""
    text, by = rephrase("원본", use_llm=True, client=_FakeClient(), model="x")
    assert text == "재서술된 계획"
    assert by == "llm"


class _BoomClient:
    class chat:
        class completions:
            @staticmethod
            def create(model, messages, **kwargs):
                raise RuntimeError("rate limit")


def test_llm_error_falls_back_to_template():
    """LLM 호출이 실패하면 원문(template)으로 안전 복귀하는지 확인."""
    text, by = rephrase("원본", use_llm=True, client=_BoomClient(), model="x")
    assert text == "원본"
    assert by == "template"


def test_llm_error_logs_warning(caplog):
    """폴백은 조용히 넘어가지 않고 경고 로그를 남긴다 (관측성)."""
    import logging

    with caplog.at_level(logging.WARNING):
        rephrase("원본", use_llm=True, client=_BoomClient(), model="x")
    assert any("rate limit" in r.getMessage() for r in caplog.records)
