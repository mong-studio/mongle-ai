from sft_pipeline.crawl.extractor import extract

HTML = """
<html><head><title>합격 후기</title></head>
<body><article class="post">
<p>기출 3회독을 하면서 매일 두 시간씩 꾸준히 개념을 정리하고 문제를 풀었습니다.</p>
<p>오답 정리가 합격의 핵심이었고, 틀린 문제는 다음 날 다시 풀어 확실하게 이해했습니다.</p>
<p>시험 일주일 전부터는 모의고사를 반복하며 시간 배분 감각을 익혔습니다.</p>
</article></body></html>
"""

SHORT_HTML = "<html><head><title>짧음</title></head><body><div>짧</div></body></html>"


def test_extract_uses_domain_selector():
    """도메인별 설정 선택자(article.post)로 제목·본문을 추출하는지 확인."""
    res = extract(HTML, "https://example.com/case-1")
    assert res.title == "합격 후기"
    assert "기출 3회독" in res.text
    assert res.text_length == len(res.text)
    assert res.used_selector == "article.post"


def test_extract_fallback_when_short():
    """선택자 결과가 너무 짧으면 fallback 추출로 전환되는지 확인."""
    res = extract(SHORT_HTML, "https://unknown-domain.com/x")
    assert res.used_selector == "fallback"


def test_extract_empty_html_is_fallback():
    """빈 HTML이면 fallback으로 처리되고 본문이 빈 문자열인지 확인."""
    res = extract("", "https://example.com/x")
    assert res.used_selector == "fallback"
    assert res.text == ""
