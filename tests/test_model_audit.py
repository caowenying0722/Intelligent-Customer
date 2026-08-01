from model.audit import request_fingerprint, start_trace
from model.contracts import ModelRequest


def test_request_fingerprint_is_deterministic_but_not_prompt():
    request = ModelRequest(
        tenant_id="tenant-a",
        provider="fake",
        model="m",
        prompt="secret prompt",
        request_id="r1",
    )
    assert request_fingerprint(request) == request_fingerprint(request)
    assert "secret prompt" not in request_fingerprint(request)
    trace = start_trace(request)
    assert trace.request_id == "r1"
    assert trace.provider == "fake"
    assert trace.model == "m"


def test_fingerprint_changes_for_tenant_and_prompt_version():
    base = {"tenant_id": "a", "provider": "fake", "model": "m", "prompt": "same"}
    first = request_fingerprint(ModelRequest(**base, prompt_version="v1"))
    tenant = request_fingerprint(ModelRequest(**{**base, "tenant_id": "b"}))
    version = request_fingerprint(ModelRequest(**{**base, "prompt_version": "v2"}))
    assert len({first, tenant, version}) == 3
