"""LLM review hook with a mocked OpenAI-compatible endpoint (no network)."""
import json

import httpx
import pytest

from backend.auditor_agent import DeliverableAuditorAgent, LLMReviewer
from tests.conftest import BAD_DELIVERABLE, GOOD_DELIVERABLE

CRITERIA = ["Provide FastAPI endpoint for PayPal authorization capture and invoice creation",
            "Include automated unit tests for escrow state transitions"]


@pytest.fixture(autouse=True)
def _clean_llm_env(monkeypatch):
    for k in ("AUDITOR_LLM_API_KEY", "GEMINI_API_KEY", "AUDITOR_LLM_MODEL", "AUDITOR_LLM_BASE_URL"):
        monkeypatch.delenv(k, raising=False)


def _verdict(met=(True, True), rec="AUTO_CAPTURE_APPROVED", flags=(), conf=92):
    return {"criteria": [{"criterion": c, "met": m, "reason": "r", "evidence": "e"} for c, m in zip(CRITERIA, met)],
            "risk_flags": list(flags), "recommended_decision": rec, "confidence": conf, "summary": "s"}


def _reviewer(monkeypatch, handler, models="test-model", gemini_only=False):
    if gemini_only:
        monkeypatch.setenv("GEMINI_API_KEY", "gem-key")
    else:
        monkeypatch.setenv("AUDITOR_LLM_API_KEY", "test-key")
        monkeypatch.setenv("AUDITOR_LLM_BASE_URL", "https://llm.example/v1")
    if models:
        monkeypatch.setenv("AUDITOR_LLM_MODEL", models)
    return LLMReviewer(transport=httpx.MockTransport(handler))


def _chat(verdict, seen=None):
    def handler(request):
        body = json.loads(request.content)
        if seen is not None:
            seen.append((str(request.url), request.headers["authorization"], body["model"]))
        return httpx.Response(200, json={"model": body["model"], "choices": [{"message": {"content": json.dumps(verdict)}}]})
    return handler


def _audit(r, content=GOOD_DELIVERABLE, rate=0.98):
    return DeliverableAuditorAgent(r).evaluate_deliverable("M", CRITERIA, "python_code", content, rate)


def test_not_configured_by_default():
    rep = _audit(LLMReviewer())
    assert rep.llm_review["status"] == "NOT_CONFIGURED"
    assert rep.decision == "AUTO_CAPTURE_APPROVED"


def test_gemini_key_fallback_and_default_base_url(monkeypatch):
    seen = []
    r = _reviewer(monkeypatch, _chat(_verdict(), seen), models=None, gemini_only=True)
    assert r.key_source == "GEMINI_API_KEY" and r.models[0] == "gemini-2.5-flash"
    rep = _audit(r)
    assert seen[0][0] == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert seen[0][1] == "Bearer gem-key"
    assert rep.llm_review["status"] == "OK"


def test_model_fallback_on_404_records_actual_model(monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        if body["model"] == "gone-model":
            return httpx.Response(404, json={"error": {"message": "no longer available"}})
        return _chat(_verdict())(request)
    r = _reviewer(monkeypatch, handler, models="gone-model,good-model")
    rep = _audit(r)
    assert rep.llm_review["model"] == "good-model"
    assert rep.llm_review["fallback_attempts"][0] == {"model": "gone-model", "error": "HTTP 404"}
    assert r.active_model == "good-model"


def test_llm_pass_adds_check_and_keeps_approval(monkeypatch):
    rep = _audit(_reviewer(monkeypatch, _chat(_verdict())))
    assert any(c["criterion"].startswith("LLM Acceptance Review") for c in rep.checks)
    assert rep.decision == "AUTO_CAPTURE_APPROVED" and rep.guardrail_decision == "AUTO_CAPTURE_APPROVED"


def test_llm_unmet_criterion_blocks_even_if_model_says_approve(monkeypatch):
    rep = _audit(_reviewer(monkeypatch, _chat(_verdict(met=(True, False)))))
    assert rep.decision == "HOLD_FOR_REVISION" and rep.auto_release_eligible is False
    assert rep.llm_review["overall_pass"] is False


def test_llm_high_risk_flag_escalates(monkeypatch):
    v = _verdict(flags=[{"flag": "fake tests", "severity": "high", "detail": "assert True"}])
    rep = _audit(_reviewer(monkeypatch, _chat(v)))
    assert rep.decision == "ESCALATE_DISPUTE"


def test_llm_cannot_loosen_guardrail_dispute(monkeypatch):
    rep = _audit(_reviewer(monkeypatch, _chat(_verdict())), content=BAD_DELIVERABLE, rate=0.3)
    assert rep.guardrail_decision == "ESCALATE_DISPUTE"
    assert rep.decision == "ESCALATE_DISPUTE" and rep.auto_release_eligible is False


def test_llm_missing_criteria_counted_as_unmet(monkeypatch):
    v = _verdict(); v["criteria"] = v["criteria"][:1]
    rep = _audit(_reviewer(monkeypatch, _chat(v)))
    assert rep.auto_release_eligible is False


def test_llm_error_blocks_capture(monkeypatch):
    rep = _audit(_reviewer(monkeypatch, lambda req: httpx.Response(500, json={})))
    assert rep.llm_review["status"] == "ERROR" and rep.auto_release_eligible is False


def test_llm_garbage_output_blocks_capture(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "sure, looks great!"}}]})
    rep = _audit(_reviewer(monkeypatch, handler))
    assert rep.llm_review["status"] == "ERROR" and rep.decision == "HOLD_FOR_REVISION"


def test_reviewer_repr_hides_key(monkeypatch):
    monkeypatch.setenv("AUDITOR_LLM_API_KEY", "KEY-SHOULD-NOT-LEAK")
    assert "LEAK" not in repr(LLMReviewer()) and "LEAK" not in json.dumps(LLMReviewer().describe())
