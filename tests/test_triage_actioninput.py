"""Week 12 — the capstone loop accepts `ActionInput:` too (SEAMS.md S22). The parser lives in react_agent; this pins that the triage loop
inherits it, on the real logged text of CLM-2026-00567's lap 4."""

from src.agent import triage_agent

LOGGED_567_LAP_4 = ('Thought: Now that I have the policy number and loss date, I must check if the policy was in force on the '
                    'date of loss.\nAction: check_in_force\nActionInput: {"policy_number": "HLT-2025-0016", "loss_date": "2026-04-25"}')


def test_the_triage_loop_parses_the_logged_actioninput_lap():
    parsed = triage_agent._parse_lap(LOGGED_567_LAP_4)
    assert parsed["kind"] == "action" and parsed["tool"] == "check_in_force"
    assert parsed["args"] == {"policy_number": "HLT-2025-0016", "loss_date": "2026-04-25"}
