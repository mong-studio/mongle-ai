from llm_evaluation.langsmith.compare import render_comparison_html


def test_render_shows_delta_and_regression():
    before = {"structure_valid": 1.0, "routing_correct": 0.8, "date_sanity": 1.0}
    after = {"structure_valid": 1.0, "routing_correct": 0.6, "korean_only": 0.9}
    html = render_comparison_html(before, after, before_name="A", after_name="B")
    assert "<table" in html and "</html>" in html  # 완전한 self-contained 문서
    assert "routing_correct" in html
    assert "-0.20" in html          # 0.8 → 0.6 회귀 delta 표기
    assert "korean_only" in html    # after 에만 있는 평가자도 행에 포함
    assert "structure_valid" in html


def test_render_handles_missing_keys_as_na():
    html = render_comparison_html({"a": 1.0}, {}, before_name="A", after_name="B")
    assert "n/a" in html  # after 에 없는 지표는 n/a
