from sft_pipeline.crawl.robots import evaluate, robots_url_for

ROBOTS = """
User-agent: *
Disallow: /private/
Crawl-delay: 3
"""


def test_robots_url_for():
    """임의 URL에서 해당 도메인의 robots.txt 주소를 만들어내는지 확인."""
    assert robots_url_for("https://blog.example.com/post/1") == "https://blog.example.com/robots.txt"


def test_allowed_path():
    """허용된 경로는 allowed=True이고 Crawl-delay 값을 파싱하는지 확인."""
    info = evaluate("https://blog.example.com/post/1", "mybot", robots_text=ROBOTS)
    assert info.allowed is True
    assert info.crawl_delay == 3.0


def test_disallowed_path():
    """Disallow에 걸리는 경로는 allowed=False인지 확인."""
    info = evaluate("https://blog.example.com/private/x", "mybot", robots_text=ROBOTS)
    assert info.allowed is False


def test_empty_robots_allows_all():
    """robots.txt가 비어 있으면 모든 경로를 허용하는지 확인."""
    info = evaluate("https://blog.example.com/post/1", "mybot", robots_text="")
    assert info.allowed is True
