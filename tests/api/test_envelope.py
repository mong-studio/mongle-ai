from pydantic import BaseModel

from api.envelope import Envelope, ErrorBody, done


class _Sample(BaseModel):
    value: int


def test_done_wraps_result_with_status_done():
    env = done(_Sample(value=7))
    assert env.status == "done"
    assert env.result == _Sample(value=7)
    assert env.error is None


def test_envelope_serializes_to_status_result_shape():
    env = done(_Sample(value=7))
    dumped = env.model_dump(mode="json")
    assert dumped == {"status": "done", "result": {"value": 7}, "error": None}


def test_error_envelope_shape():
    env = Envelope[_Sample](status="error", error=ErrorBody(code="boom", message="bad"))
    dumped = env.model_dump(mode="json")
    assert dumped["status"] == "error"
    assert dumped["error"] == {"code": "boom", "message": "bad"}
    assert dumped["result"] is None
