# Requirement 5 — docstring-as-prompt + recoverable error, before vs after

Same failing call, same model, same question, run twice against
`src/mcp_servers/claims_system_server.py` before and after rewriting `get_claim_status`'s
docstring and its not-found error. Nothing else changed between the two runs.

**Question:** `"What is the status of claim CLM-2024-88120?"` — a claim number in the wrong
format entirely (this system's real claim numbers look like `C-001`).

## The change

| | Before | After |
|---|---|---|
| Docstring | `"""Get claim status."""` | Full sentence: what it returns, what it doesn't, the real `C-NNN` format, and that a not-found error is not a reason to retry |
| Not-found error | `ValueError("Error 3")` | `ValueError` naming the claim number that failed, the expected format with an example, the full list of currently-known claim numbers, and an explicit instruction not to retry the identical call |

## The measured result

| | Before | After |
|---|---|---|
| Laps to a Final Answer | **4** | **2** |
| Wall time | 52.7s | 36.2s |
| Cost | $0.000703 | $0.000671 |
| Identical call retried | **Yes** — lap 2 resubmitted the exact same failing call | **No** |
| Final answer | *"I am unable to retrieve the status of claim CLM-2024-88120 because the system returned an error..."* — never says why, never says what the right format is | *"The claim number CLM-2024-88120 does not exist in this system. Claim numbers in this system follow the format C-NNN (e.g., C-001 to C-010)..."* |

## Before — full transcript

```
Lap 1: Action: get_claim_status  Action Input: {"claim_number": "CLM-2024-88120"}
       Observation: ERROR: Error calling tool 'get_claim_status': Error 3

Lap 2: Thought: The tool call failed with "Error 3". [...] Let's try it one more time.
       Action: get_claim_status  Action Input: {"claim_number": "CLM-2024-88120"}
       Observation: ERROR: Error calling tool 'get_claim_status': Error 3

Lap 3: Thought: [...] let me check the adjuster notes [...] to see if that works
       Action: get_adjuster_notes  Action Input: {"claim_number": "CLM-2024-88120"}
       Observation: ERROR: Error calling tool 'get_adjuster_notes': Error 3

Lap 4: Final Answer: I am unable to retrieve the status of claim CLM-2024-88120 because the
       system returned an error when attempting to access the claim status and adjuster notes.
```

`"Error 3"` gives the model nothing to act on. It can't tell a typo from a dead system —
exactly the common mistake the brief names — so it does the only two things it can: retry
the identical call once, then try the other tool, then give up with an answer that tells the
user nothing they didn't already know (something failed).

## After — full transcript

```
Lap 1: Action: get_claim_status  Action Input: {"claim_number": "CLM-2024-88120"}
       Observation: ERROR: Error calling tool 'get_claim_status': claim 'CLM-2024-88120' not
       found: claim numbers in this system look like C-NNN (a letter C, a hyphen, three
       digits — for example C-001). Known claim numbers right now: C-001, C-002, C-003,
       C-004, C-005, C-006, C-007, C-008, C-009, C-010. If the number you were given matches
       this format and still isn't found, the claim may not exist in this system at all —
       say so rather than retrying the identical call.

Lap 2: Thought: The error message indicates [...] the claim does not exist in this system.
       Final Answer: The claim number CLM-2024-88120 does not exist in this system. Claim
       numbers in this system follow the format C-NNN (e.g., C-001 to C-010), and the
       provided claim number is not recognized.
```

One rejection was enough. The model didn't need to guess, didn't retry, and didn't need the
second tool — the error itself already answered the only question left ("is this fixable or
not"), and told the model explicitly not to waste a lap finding that out the hard way.

## What actually moved, stated plainly

Not primarily the cost (roughly flat) — the **lap count** (4→2, cut in half) and, more
importantly, the **content of the final answer**. Before, the user got told something broke
with zero information to act on. After, the user got told exactly why, in terms they can fix
(the format) or escalate on (the claim genuinely doesn't exist) — which is the entire point of
a recoverable error: it should change what the *caller* can do next, not just what the log
says happened.
