import csv

from sft_pipeline.crawl import run_crawl
from sft_pipeline.crawl.run_crawl import _crawl_one, _effective_delay, read_urls, run


def test_read_urls_strips_comments_and_blanks(tmp_path):
    """전체-줄 주석·빈 줄은 제외, 인라인 주석(공백 뒤 #)은 떼고, URL 프래그먼트는 보존."""
    f = tmp_path / "urls.txt"
    f.write_text(
        "# 헤더 주석\n"
        "\n"
        "https://example.com/a              # 비전공 D-3, 70+ 합격\n"
        "https://example.com/b\n"
        "https://example.com/c#section\n",
        encoding="utf-8",
    )
    assert read_urls(f) == [
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/c#section",
    ]


class _FakeResponse:
    def __init__(self, code, text):
        self.status_code, self.text = code, text


class _FakeSession:
    """robots.txt는 /private/ 차단, case-01은 본문 반환."""

    def get(self, url, timeout, headers):
        if url.endswith("robots.txt"):
            return _FakeResponse(200, "User-agent: *\nDisallow: /private/")
        if url.endswith("/case-01"):
            return _FakeResponse(
                200,
                "<html><title>기출문제</title><body><p>기출 본문 텍스트입니다.</p></body></html>",
            )
        return _FakeResponse(404, "<html>nope</html>")


def test_effective_delay_honors_declared():
    """sleep 기본값과 robots의 Crawl-delay 중 더 큰 값을 실제 대기시간으로 쓰는지 확인."""
    assert _effective_delay(1.0, "3") == 3.0
    assert _effective_delay(2.0, "") == 2.0
    assert _effective_delay(2.0, "1") == 2.0


def test_robots_fetched_once_per_domain():
    """같은 도메인의 여러 URL을 크롤할 때 robots.txt는 캐시되어 한 번만 요청되는지 확인."""
    class _CountingSession:
        def __init__(self):
            self.robots_hits = 0

        def get(self, url, timeout, headers):
            class _R:
                def __init__(s, code, text):
                    s.status_code, s.text = code, text

            if url.endswith("robots.txt"):
                self.robots_hits += 1
                return _R(200, "User-agent: *\nDisallow:")
            return _R(200, "<html><title>t</title><body><p>hello world body text here</p></body></html>")

    sess = _CountingSession()
    cache = {}
    for path in ("/a", "/b"):
        _crawl_one(f"https://example.com{path}", user_agent="b", session=sess, timeout=5, robots_cache=cache)
    assert sess.robots_hits == 1


def test_http_error_flagged():
    """페이지 응답이 404면 error를 http_404로 기록하고 본문은 비우는지 확인."""
    class _S:
        def get(self, url, timeout, headers):
            class _R:
                def __init__(s, code, text):
                    s.status_code, s.text = code, text

            if url.endswith("robots.txt"):
                return _R(200, "")
            return _R(404, "<html>nope</html>")

    row = _crawl_one("https://example.com/x", user_agent="b", session=_S(), timeout=5, robots_cache={})
    assert row["error"] == "http_404"
    assert row["extracted_text"] == ""


def test_run_blocks_disallowed_and_writes_outputs(tmp_path, monkeypatch):
    """run() 전체 흐름: robots가 막은 URL은 robots_disallow로 건너뛰고, 허용 URL은 추출해 CSV·JSONL로 쓰는지 확인."""
    monkeypatch.setattr(run_crawl.requests, "Session", _FakeSession)
    monkeypatch.setattr(run_crawl.time, "sleep", lambda _s: None)
    urls = tmp_path / "urls.txt"
    urls.write_text(
        "https://example.com/case-01\nhttps://example.com/private/secret\n",
        encoding="utf-8",
    )
    out = tmp_path / "crawl_results.csv"
    rows = run(urls_path=urls, out_csv=out, user_agent="mybot")
    by_url = {r["source_url"]: r for r in rows}

    allowed = by_url["https://example.com/case-01"]
    assert allowed["robots_allowed"] == "True"
    assert allowed["error"] == ""
    assert "기출" in allowed["extracted_text"]
    assert int(allowed["text_length"]) > 0

    blocked = by_url["https://example.com/private/secret"]
    assert blocked["robots_allowed"] == "False"
    assert blocked["error"] == "robots_disallow"
    assert blocked["extracted_text"] == ""

    # CSV·JSONL로도 기록되는지
    with open(out, encoding="utf-8") as f:
        assert len(list(csv.DictReader(f))) == 2
    assert out.with_suffix(".jsonl").exists()
