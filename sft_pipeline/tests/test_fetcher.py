from sft_pipeline.crawl.fetcher import FetchResult, fetch


class _Resp:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text


class _OkSession:
    def get(self, url, timeout, headers):
        return _Resp(200, "<html><title>ok</title></html>")


class _BoomSession:
    def get(self, url, timeout, headers):
        raise RuntimeError("connection refused")


def test_fetch_success():
    """정상 응답 시 상태코드·HTML을 담은 FetchResult를 반환하고 error가 없는지 확인."""
    res = fetch("https://example.com/a", session=_OkSession(), timeout=5, user_agent="bot")
    assert isinstance(res, FetchResult)
    assert res.status_code == 200
    assert "ok" in res.html
    assert res.error is None


def test_fetch_records_error():
    """요청 중 예외가 나면 크래시하지 않고 error 필드에 기록해 반환하는지 확인."""
    res = fetch("https://example.com/a", session=_BoomSession(), timeout=5, user_agent="bot")
    assert res.html is None
    assert res.status_code is None
    assert "connection refused" in res.error
