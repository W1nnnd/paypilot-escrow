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


def _audit(r, content=GOOD_DELIVERABLE, rate=0.98, **kwargs):
    return DeliverableAuditorAgent(r).evaluate_deliverable("M", CRITERIA, "python_code", content, rate, **kwargs)


def test_not_configured_blocks_capture_by_default():
    rep = _audit(LLMReviewer())
    assert rep.llm_review["status"] == "NOT_CONFIGURED"
    assert rep.guardrail_decision == "AUTO_CAPTURE_APPROVED"
    assert rep.decision == "HOLD_FOR_REVISION"
    assert rep.auto_release_eligible is False
    assert "not configured" in rep.summary and "blocked" in rep.summary


def test_explicit_replay_can_use_guardrails_without_llm():
    rep = _audit(LLMReviewer(), require_llm=False)
    assert rep.llm_review["status"] == "NOT_CONFIGURED"
    assert rep.decision == "AUTO_CAPTURE_APPROVED"
    assert rep.auto_release_eligible is True
    assert "Replay" in rep.summary


def test_missing_llm_does_not_downgrade_guardrail_dispute():
    rep = _audit(LLMReviewer(), content=BAD_DELIVERABLE, rate=0.3)
    assert rep.decision == "ESCALATE_DISPUTE"
    assert rep.auto_release_eligible is False


@pytest.mark.parametrize("confidence, threshold, eligible", [
    (0, 80, False), (60, 80, False), (79.9, 80, False),
    (80, 80, True), (80.1, 80, True), (94.9, 95, False), (95, 95, True),
])
def test_merged_llm_confidence_must_meet_threshold(monkeypatch, confidence, threshold, eligible):
    rep = _audit(_reviewer(monkeypatch, _chat(_verdict(conf=confidence))), threshold=threshold)
    assert rep.guardrail_decision == "AUTO_CAPTURE_APPROVED"
    assert rep.confidence_score == confidence
    assert rep.auto_release_eligible is eligible
    assert rep.decision == ("AUTO_CAPTURE_APPROVED" if eligible else "HOLD_FOR_REVISION")
    if not eligible:
        assert "Eligible for" not in rep.summary


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


@pytest.mark.parametrize("status", ["ERROR", "UNEXPECTED"])
@pytest.mark.parametrize("require_llm", [True, False])
def test_failed_reviewer_blocks_capture_even_in_replay(monkeypatch, status, require_llm):
    reviewer = LLMReviewer()
    monkeypatch.setattr(reviewer, "review", lambda *args: {"status": status})
    rep = _audit(reviewer, require_llm=require_llm)
    assert rep.decision == "HOLD_FOR_REVISION"
    assert rep.auto_release_eligible is False


def test_reordered_normalised_criteria_are_matched_to_contract(monkeypatch):
    v = _verdict()
    v['criteria'].reverse()
    for c in v['criteria']:
        c['criterion'] = '  \t' + c['criterion'].upper().replace(' ', '  \n') + '  '
    rep = _audit(_reviewer(monkeypatch, _chat(v)))
    assert rep.auto_release_eligible is True
    assert [c['criterion'] for c in rep.llm_review['criteria']] == CRITERIA


def test_missing_first_criterion_is_not_replaced_by_last(monkeypatch):
    v = _verdict()
    v['criteria'] = v['criteria'][1:]
    rep = _audit(_reviewer(monkeypatch, _chat(v)))
    assert rep.llm_review['criteria'][0]['criterion'] == CRITERIA[0]
    assert rep.llm_review['criteria'][0]['met'] is False
    assert rep.llm_review['criteria'][1]['met'] is True
    assert rep.auto_release_eligible is False


@pytest.mark.parametrize('kind', ['duplicate', 'unknown', 'extra', 'case_duplicate', 'empty'])
def test_invalid_criterion_coverage_cannot_approve(monkeypatch, kind):
    v = _verdict()
    if kind in ('duplicate', 'case_duplicate'):
        v['criteria'][1]['criterion'] = CRITERIA[0]
        if kind == 'case_duplicate':
            v['criteria'][1]['criterion'] = ' ' + CRITERIA[0].upper() + '\n'
    elif kind == 'unknown':
        v['criteria'][0]['criterion'] = 'Invented acceptance criterion'
    elif kind == 'extra':
        v['criteria'].append(dict(v['criteria'][0], criterion='Extra criterion'))
    else:
        v['criteria'] = []
    rep = _audit(_reviewer(monkeypatch, _chat(v)))
    assert rep.decision == 'HOLD_FOR_REVISION'
    assert rep.auto_release_eligible is False


@pytest.mark.parametrize('confidence', [float('nan'), float('inf'), -float('inf'), None,
                                       'NaN', 'Infinity', '92', True, False, [], {}, -1, 101, 10**400])
def test_invalid_confidence_fails_closed_even_with_zero_threshold(monkeypatch, confidence):
    rep = _audit(_reviewer(monkeypatch, _chat(_verdict(conf=confidence))), threshold=0)
    assert rep.llm_review['status'] == 'ERROR'
    assert rep.auto_release_eligible is False


def test_confidence_is_not_rounded_up_across_approval_threshold(monkeypatch):
    rep = _audit(_reviewer(monkeypatch, _chat(_verdict(conf=79.99))))
    assert rep.llm_review['confidence'] == 79.99
    assert rep.auto_release_eligible is False


@pytest.mark.parametrize('field,value', [
    ('criteria', None), ('criteria', {}), ('criteria', 'criteria'), ('criteria', [None]),
    ('criteria', ['criterion']), ('criteria', [1]),
    ('risk_flags', None), ('risk_flags', {}), ('risk_flags', 'high'),
    ('risk_flags', [None]), ('risk_flags', ['high']), ('risk_flags', [1]),
    ('risk_flags', [{}]), ('risk_flags', [{'flag': 'unsafe', 'severity': 'critical', 'detail': 'x'}]),
    ('risk_flags', [{'flag': 'unsafe', 'severity': ['high'], 'detail': 'x'}]),
    ('recommended_decision', None), ('recommended_decision', []), ('summary', {}),
])
def test_malformed_verdict_structures_fail_closed(monkeypatch, field, value):
    v = _verdict()
    v[field] = value
    rep = _audit(_reviewer(monkeypatch, _chat(v)))
    assert rep.llm_review['status'] == 'ERROR'
    assert rep.auto_release_eligible is False


@pytest.mark.parametrize('field,value', [('criterion', None), ('criterion', []), ('met', 'true'),
                                        ('met', 1), ('reason', {}), ('evidence', [])])
def test_malformed_criterion_fields_fail_closed(monkeypatch, field, value):
    v = _verdict()
    v['criteria'][0][field] = value
    rep = _audit(_reviewer(monkeypatch, _chat(v)))
    assert rep.llm_review['status'] == 'ERROR'
    assert rep.auto_release_eligible is False


@pytest.mark.parametrize('content', [None, [], {}, 10])
def test_non_text_response_content_fails_closed(monkeypatch, content):
    def handler(request):
        return httpx.Response(200, json={'choices': [{'message': {'content': content}}]})
    rep = _audit(_reviewer(monkeypatch, handler))
    assert rep.llm_review['status'] == 'ERROR'
    assert rep.auto_release_eligible is False


def test_malformed_verdict_can_fall_back_to_valid_model(monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        v = _verdict()
        if body['model'] == 'invalid-model':
            v['risk_flags'] = [None]
        return _chat(v)(request)
    r = _reviewer(monkeypatch, handler, models='invalid-model,valid-model')
    rep = _audit(r)
    assert rep.auto_release_eligible is True
    assert rep.llm_review['model'] == 'valid-model'
    assert rep.llm_review['fallback_attempts'] == [
        {'model': 'invalid-model', 'error': 'invalid verdict (ValueError)'}]


def test_subthreshold_score_is_not_rounded_up_in_report(monkeypatch):
    rep = _audit(_reviewer(monkeypatch, _chat(_verdict(conf=79.99))))
    assert rep.confidence_score == 79.99
    assert "79.99/100" in rep.summary
    assert rep.auto_release_eligible is False


@pytest.mark.parametrize("rate", [0.999, 0.99999])
def test_guardrail_mean_does_not_round_up_across_threshold(monkeypatch, rate):
    rep = _audit(_reviewer(monkeypatch, _chat(_verdict(conf=100))), rate=rate, threshold=100)
    assert rep.confidence_score < 100
    assert rep.guardrail_decision == "HOLD_FOR_REVISION"
    assert rep.auto_release_eligible is False


@pytest.mark.parametrize("decision", ["HOLD_FOR_REVISION", "ESCALATE_DISPUTE"])
def test_confident_rejection_has_no_approval_score(monkeypatch, decision):
    rep = _audit(_reviewer(monkeypatch, _chat(_verdict(rec=decision, conf=100))))
    assert rep.decision == decision and rep.auto_release_eligible is False
    assert rep.confidence_score == 99.6  # Existing numeric API and policy are unchanged.
    assert rep.risk_score == 0.4
    scores = rep.score_details
    assert scores['approval_gate_score'] is None
    assert scores['approval_gate_basis'] == 'BLOCKED'
    assert scores['model_decision_confidence'] == 100
    assert scores['model_confidence_for'] == decision
    assert scores['model_confidence_basis'] == 'MODEL_RECOMMENDED_DECISION'
    assert scores['semantics_version'] == '1.0'
    assert 'not delivery quality' in rep.summary
    assert '99.6' not in rep.summary and '0.4' not in rep.summary


@pytest.mark.parametrize("verdict", [
    _verdict(met=(True, False), conf=100),
    _verdict(met=(True,), conf=100),
    _verdict(flags=[{'flag':'unsafe','severity':'high','detail':'unsafe'}], conf=100),
])
def test_normalized_rejection_keeps_confidence_tied_to_original_recommendation(monkeypatch, verdict):
    rep = _audit(_reviewer(monkeypatch, _chat(verdict)))
    assert rep.llm_review['model_recommended_decision'] == 'AUTO_CAPTURE_APPROVED'
    assert rep.llm_review['recommended_decision'] != 'AUTO_CAPTURE_APPROVED'
    assert rep.score_details['model_confidence_for'] == 'AUTO_CAPTURE_APPROVED'
    assert rep.score_details['approval_gate_score'] is None
    assert rep.auto_release_eligible is False


@pytest.mark.parametrize("require_llm", [True, False])
def test_missing_reviewer_score_semantics_distinguish_live_and_replay(require_llm):
    rep = _audit(LLMReviewer(), require_llm=require_llm)
    scores = rep.score_details
    assert scores['model_decision_confidence'] is None
    assert scores['model_confidence_for'] is None
    assert scores['approval_gate_basis'] == ('BLOCKED' if require_llm else 'REPLAY_GUARDRAILS_ONLY')
    assert scores['approval_gate_score'] == (None if require_llm else 99.6)


def test_model_error_has_no_confidence_or_approval_score(monkeypatch):
    rep = _audit(_reviewer(monkeypatch, lambda _: httpx.Response(500)))
    assert rep.score_details['model_decision_confidence'] is None
    assert rep.score_details['approval_gate_score'] is None
    assert rep.auto_release_eligible is False


@pytest.mark.parametrize('confidence', [79.99, 80, 100])
def test_approving_model_preserves_exact_gate_and_threshold(monkeypatch, confidence):
    rep = _audit(_reviewer(monkeypatch, _chat(_verdict(conf=confidence))))
    assert rep.score_details['approval_gate_score'] == min(99.6, confidence)
    assert rep.score_details['approval_gate_threshold'] == 80
    assert rep.score_details['approval_gate_basis'] == 'RULES_AND_MODEL'
    assert rep.auto_release_eligible is (confidence >= 80)


def test_guardrail_dispute_has_no_approval_gate_despite_model_approval(monkeypatch):
    rep = _audit(_reviewer(monkeypatch, _chat(_verdict(conf=100))), content=BAD_DELIVERABLE)
    assert rep.decision == 'ESCALATE_DISPUTE'
    assert rep.score_details['approval_gate_score'] is None
    assert rep.auto_release_eligible is False


def test_model_prompt_defines_new_confidence_semantics_and_ignores_supplied_metadata(monkeypatch):
    assert 'confidence in your recommended_decision' in LLMReviewer.SYSTEM_PROMPT
    verdict = _verdict(rec='HOLD_FOR_REVISION', conf=100)
    verdict.update(confidence_basis='QUALITY', model_recommended_decision='AUTO_CAPTURE_APPROVED')
    rep = _audit(_reviewer(monkeypatch, _chat(verdict)))
    assert rep.llm_review['confidence_basis'] == 'MODEL_RECOMMENDED_DECISION'
    assert rep.llm_review['model_recommended_decision'] == 'HOLD_FOR_REVISION'
