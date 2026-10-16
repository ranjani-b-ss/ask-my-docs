"""Week 12 — S10/S11/S12 fixes, offline: superseded clauses are dropped from the packet,
an unresolved deductible is flagged by code, the prompt shows plain argument types."""

from src import claim_files, wording_versions as wv
from src.agent import triage_agent as ta

META = [
    {"document_id": "END-2026-01", "supersedes": "PW-MOTOR-001", "effective_date": "2026-04-01",
     "section": "Endorsement 1 > 2. Amendment to Clause 2.2 — Compulsory deductible"},
    {"document_id": "END-2026-01", "supersedes": "PW-MOTOR-001", "effective_date": "2026-04-01",
     "section": "Endorsement 1 > 7. New Clause 6A — No Claim Bonus protection"},
    {"document_id": "END-2026-01", "supersedes": "PW-MOTOR-001", "effective_date": "2026-04-01",
     "section": "Endorsement 1 > 1. Nil Depreciation cover — amendment to Clause 2.1"},
]
AM = wv.amendment_map(META)
CLAUSE = "Private Car Package Policy > 2. Basis of settlement > 2.2 Compulsory deductible"


def test_an_amended_clause_is_marked_once_the_endorsement_is_in_force():
    assert wv.superseded_by(AM, "PW-MOTOR-001", CLAUSE, "2026-04-01") == "END-2026-01"
    assert wv.superseded_by(AM, "PW-MOTOR-001", CLAUSE, "2026-07-01") == "END-2026-01"


def test_the_day_before_the_endorsement_nothing_is_superseded():
    assert wv.superseded_by(AM, "PW-MOTOR-001", CLAUSE, "2026-03-31") is None


def test_new_clauses_and_unamended_clauses_supersede_nothing():
    assert ("PW-MOTOR-001", "6A") not in AM
    assert wv.superseded_by(AM, "PW-MOTOR-001", "Section I > 3. What is not covered", "2026-07-01") is None
    assert wv.superseded_by(AM, "PW-HEALTH-002", CLAUSE, "2026-07-01") is None


def test_the_heading_form_nil_depreciation_amends_clause_2_1():
    assert ("PW-MOTOR-001", "2.1") in AM


def _state():
    s = ta.RunState(trace_id="cap_t", claim=claim_files.get("CLM-2026-00602"))
    s.called += ["lookup_policy", "check_in_force"]
    s.policy_number, s.loss_date, s.product = "MOT-1", "2026-04-01", "motor"
    s.in_force = True
    return s


def test_a_cited_superseded_clause_is_dropped_and_recorded():
    s = _state()
    s.retrieved["A"] = {"chunk_id": "A", "document_id": "PW-MOTOR-001", "version": "5.1",
                        "effective_date": "2025-04-01", "clause": CLAUSE, "text": "t",
                        "superseded_by": "END-2026-01"}
    s.retrieved["B"] = {"chunk_id": "B", "document_id": "END-2026-01", "version": "1.0",
                        "effective_date": "2026-04-01", "clause": "2. Amendment to Clause 2.2",
                        "text": "t", "superseded_by": None}
    pk = ta.build_packet(s, {"wording_relevant": [{"chunk_id": "A"}, {"chunk_id": "B"}]}, [])
    assert [w["chunk_id"] for w in pk["wording"]] == ["B"]
    assert pk["superseded_dropped"] == [{"chunk_id": "A", "clause": CLAUSE, "amended_by": "END-2026-01"}]


def test_unresolved_deductible_gets_a_flag_the_model_cannot_remove():
    s = _state()
    s.limits = {"deductible": {"applies": True, "amount": None, "needs": "vehicle_cc"}}
    out = ta.guard_tool_args(s, "refer_to_adjuster", {"reason": "Adjuster to review.", "flags": []})
    assert any(f.startswith("unresolved:deductible") for f in out["flags"])


def test_a_resolved_deductible_adds_no_flag():
    s = _state()
    s.limits = {"deductible": {"applies": True, "amount": 1500}}
    out = ta.guard_tool_args(s, "refer_to_adjuster", {"reason": "Adjuster to review.", "flags": []})
    assert out["flags"] == []


def test_the_prompt_shows_plain_types_not_schema_fragments():
    class T:
        description = "d"
        input_schema = {"properties": {"query": {"title": "Query", "type": "string"},
                                       "top_k": {"type": "integer", "default": 3},
                                       "trace_id": {"type": "string"}},
                        "required": ["query"]}
    block = ta._tool_block({"search_wording": T()})
    assert "search_wording(query: string, top_k: integer (optional))" in block
    assert '"title"' not in block and "trace_id" not in block
