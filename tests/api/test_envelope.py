from pydantic import BaseModel

from api.envelope import Envelope, ErrorBody, done


class _Sample(BaseModel):
    value: int


def test_done_wraps_result_with_status_done():
    """done()은 결과를 status="done" 봉투로 감싸고 error는 None이다."""
    env = done(_Sample(value=7))
    assert env.status == "done"
    assert env.result == _Sample(value=7)
    assert env.error is None


def test_envelope_serializes_to_status_result_shape():
    """봉투는 {status, result, error} JSON 형태로 직렬화된다."""
    env = done(_Sample(value=7))
    dumped = env.model_dump(mode="json")
    assert dumped == {"status": "done", "result": {"value": 7}, "error": None}


def test_error_envelope_shape():
    """error 봉투는 status="error"·error 본문을 담고 result는 None이다."""
    env = Envelope[_Sample](status="error", error=ErrorBody(code="boom", message="bad"))
    dumped = env.model_dump(mode="json")
    assert dumped["status"] == "error"
    assert dumped["error"] == {"code": "boom", "message": "bad"}
    assert dumped["result"] is None
