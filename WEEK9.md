# Week 9 — MCP: the Standard Way Agents Reach Tools & Data

## Task Set D · Insurance claims · Bolt on the claims-system server without touching the agent

Every number below came from a real run against a real MCP server process — nothing here is
asserted without a trace, a diff, or a hash to back it. `mcp_config.json`, `agent_diff.txt`,
`config_diff.txt`, `wire.json`, `error_before_after.md`, and `risk_note.md` are the exact
artifacts the assignment asks for; this file explains what they show and why.

---

## 1. The numbers, up front

| | before (server one only) | after (server one + two) |
|---|---|---|
| Tools discovered | **1** — `search_policy` | **3** — `search_policy`, `get_claim_status`, `get_adjuster_notes` |
| Lines changed in the agent module | — | **0** (`agent_diff.txt`) |
| Lines changed in config | — | **5**, all data (`config_diff.txt`) |
| Laps to answer a not-found claim | 4 | **2** |
| Cost of that same failing call | $0.000703 | $0.000671 |
| Wall time of that same failing call | 52.7s | 36.2s |

---

## 2. Architecture: two servers, one host, zero coupling

```
src/mcp_servers/policy_search_server.py    "server one" — wraps the real search_policy
                                            retrieval tool this app has had since Week 3
src/mcp_servers/claims_system_server.py    "server two" — the claims platform team's
                                            server (see §7): claim status + adjuster notes
src/agent/mcp_client.py                    generic MCP host — reads mcp_config.json,
                                            connects to every listed server, merges their
                                            tools/list results into one flat registry
src/agent/mcp_agent.py                     the ReAct loop — builds its system prompt from
                                            whatever the registry discovered, dispatches
                                            whatever tool name the model asks for
mcp_config.json                            the only file that changes between "server one"
                                            and "server one + two"
```

Both servers run over **stdio** — each is a subprocess the client spawns and talks JSON-RPC
to over its stdin/stdout, no network port needed for a local setup like this one. Neither
server process ever imports `src/llm.py` or holds an API key; see §5 for exactly where the
one model call in this whole path happens instead.

---

## 3. Requirement 1 — a real query, provably through MCP

```
Question: "What is the compulsory deductible for a car above 1500cc?"
Lap 1: Action: search_policy   Action Input: {"query": "compulsory deductible car above 1500cc"}
Lap 2: Final Answer: The compulsory deductible for a car above 1500cc is INR 3,000.
```

`"tool": "search_policy"` sits directly in the recorded step — not inferred, not asserted.
The answer is also correct: it identifies that Endorsement 1 (effective 2026-04-01)
supersedes the base policy's INR 2,000 figure, giving INR 3,000. Cost: $0.000338, 2 laps.

A second query proves server two specifically:

```
Question: "What is the date of loss and claim amount for claim C-002?"
Lap 1: Action: get_claim_status   Action Input: {"claim_number": "C-002"}
       Observation: {"claim_id":"C-002","date_of_loss":"2026-06-01","vehicle_cc":1800,"claim_amount":15000.0}
Lap 2: Final Answer: The date of loss for claim C-002 is June 1, 2026, and the claim amount is 15,000.00.
```

---

## 4. Requirement 2 — the config-only swap, proven twice

`agent_diff.txt` shows `diff -u` returning nothing (exit code 0) for both `mcp_agent.py` and
`mcp_client.py`, before and after `mcp_config.json` gained a second server — and a SHA-256
hash match as a second, independent check that this isn't an accidental self-comparison.

`config_diff.txt` shows the other half: the five lines that *did* change, all inside
`mcp_config.json`, all data — a server name and how to start its process, no code.

**A real mistake caught while building this, not hidden after the fact**: my first draft of
both agent-side files' own module docstrings explained the zero-coupling design by naming the
servers this app happens to have *("this file never mentions `policy-search` or
`claims-system`...")* — which is itself a reference to those names, so a literal grep for
"claims-system" turned up a false positive inside my own explanatory comment. Fixed by
rephrasing the docstrings to describe the principle without naming any specific server, then
re-verified: `grep -c "claims-system\|get_claim_status\|get_adjuster_notes\|search_policy"`
across both files now returns 0. The zero-line diff in `agent_diff.txt` was regenerated
*after* this fix, against the corrected files — not the version that failed its own claim.

---

## 5. Requirement 3 & 4 — discovery, and the raw wire

Tool count: **1 → 3**, by name, straight from `tools/list` — not from notes:

```
before:  search_policy
after:   search_policy, get_claim_status, get_adjuster_notes
```

`wire.json` captures the actual protocol exchange with `claims-system` — `initialize` →
`notifications/initialized` → `tools/list` → `tools/call` — captured by speaking raw
JSON-RPC over the server's stdin/stdout directly, bypassing the `mcp` SDK's `ClientSession`
entirely for this one capture, so what's recorded is genuinely the wire format, not the SDK's
parsed objects re-serialized. Every top-level field is annotated inline in a sibling
`_annotations` object per exchange, never edited into the raw request/response themselves.

**Where the AI runs, stated once**: nowhere in `wire.json`'s four exchanges, nowhere in
`mcp_client.py`, and nowhere in either server process. The only model call in this entire
path is `usage.call_llm()` inside `mcp_agent.py`'s ReAct loop, one layer above all of this —
deciding *which* already-discovered tool to call and with what arguments. Every message
`wire.json` captures is the client asking "what can you do" and "here's a call, what
happened" — pure capability exchange, no reasoning, no prompt, no key.

---

## 6. Requirement 5 — a docstring rewritten as a prompt, and an error made recoverable

Full transcripts are in `error_before_after.md`; the shape of the fix:

| | Before | After |
|---|---|---|
| `get_claim_status`'s docstring | `"""Get claim status."""` | States what it returns, what it doesn't, the real `C-NNN` claim-number format, and that a not-found error isn't a reason to retry |
| Not-found error | `ValueError("Error 3")` | Names the claim number that failed, the expected format with an example, every currently-known claim number, and says explicitly not to retry |

Same failing call (`"What is the status of claim CLM-2024-88120?"`), same model, run twice:

- **Before**: 4 laps. The model retried the *identical* call once (nothing in `"Error 3"`
  gave it anything to change), then tried the other tool (same error), then gave up with
  *"the system returned an error"* — true, and useless.
- **After**: 2 laps, no retry. The error itself already answered the only real question
  ("fixable or not"), and the model said so directly: *"The claim number CLM-2024-88120 does
  not exist in this system. Claim numbers in this system follow the format C-NNN..."*

Lap count halved. Cost was roughly flat ($0.000703 → $0.000671) — the real win is the content
of the final answer, which is the entire point of a recoverable error: it should change what
the *caller* can do next, not just what the log records.

---

## 7. Requirement 6 — the risk note

`risk_note.md`, exactly five lines, on `claims-system` treated as a third-party server per
the exercise's own framing (there is no separate platform team in this training repo — both
servers are built here, deliberately kept as independent of each other as a real third party
would be, which is what makes the zero-line agent diff a meaningful test rather than a given).
Headline: **don't ship as-is** — no audit logging at all in the current build, and one
undifferentiated token can read both claim status and the full adjuster-note text for every
claim. The bonus (§9) is the concrete fix for both.

---

## 8. A bug found along the way, worth keeping

Building `mcp_client.py`, a single call hung silently for **38 minutes** with zero output and
zero traceback — not a slow model, not a network wait, genuinely stuck. Root cause, isolated
by successively simplifying the reproduction until one line was left: `tool.inputSchema`
instead of `tool.input_schema` (the Python MCP SDK exposes every field in snake_case;
`tools/list`'s raw JSON-RPC uses camelCase — see `wire.json`'s own `inputSchema` field for
proof the wire format really does say that). Accessing the wrong-case attribute on the
pydantic model doesn't raise cleanly inside this specific async/anyio context — it silently
hangs instead. A second instance of the identical class of bug (`result.isError` vs
`result.is_error`) crashed normally with a visible traceback, so the hang is not universal —
just real, and worth knowing before staring at a stuck terminal for half an hour assuming it's
a slow embedder load.

---

## 9. Bonus — one gateway, one audit line, a scoped denial that reaches the model

`src/mcp_servers/gateway_server.py` fronts both backends behind a single MCP server. The
agent's config (`mcp_config_gateway_full.json` / `mcp_config_gateway_scoped.json`) now lists
**one** entry — "gateway" — not two; the gateway is itself an MCP client to policy-search and
claims-system internally, and re-exposes their tools under its own name.

**Disclosed simplification**: the gateway hand-defines one proxy tool per capability the two
backends currently have, rather than dynamically mirroring whatever `tools/list` happens to
return. A production gateway should do the latter; three hand-written proxies were the
reliable choice for this exercise's scope, not a claim that this is a fully generic reverse
proxy.

### 9.1 A real bug, not a design choice, cost the first attempt

The first version opened backend connections **lazily, inside the first tool call**. It
worked once, then crashed the whole gateway process on the very next call:

```
RuntimeError: Attempted to exit a cancel scope that isn't the current task's current
cancel scope
```

`anyio` (which both `fastmcp` and the `mcp` SDK use) ties a cancel scope to the exact task
that opened it. Each incoming `tools/call` runs as its own task — a connection opened inside
request-task-1 is invalid to reuse from request-task-2, `run_in_thread=False` notwithstanding
(that fixed a *different*, thread-related half of the same class of bug, not this one).
Fixed by moving the backend connections into FastMCP's `lifespan` hook — the one place a
resource is guaranteed to outlive every individual request that uses it, entered once when
the gateway process starts and never torn down mid-session.

### 9.2 Live proof, both halves

**Fan-out, full-access token** — all three tools, one front door, in sequence, no crash after
the fix:

```
get_claim_status(C-001)   -> real data, routed to claims-system
get_adjuster_notes(C-001) -> real data, routed to claims-system
search_policy(...)        -> real data, routed to policy-search
```

**Scoped denial reaching a real model**, not just a raw client — asked *"What do the
adjuster's notes say about claim C-003, and what is its current status?"* against the
`claim-status-only` token:

```
Lap 1: get_claim_status(C-003) -> real data
Lap 4: get_adjuster_notes(C-003) -> ERROR: access denied: this token ('claim-status-only')
       is not scoped to call 'get_adjuster_notes'. Tools this token CAN call:
       ['get_claim_status', 'search_policy']. get_claim_status is still available for this
       claim's status/amount.
Lap 5: Final Answer: For claim C-003, the current status details available are: Date of
       Loss: 2026-05-01, Vehicle CC: 1400, and Claim Amount: $6,400.0. Regarding the
       adjuster's notes, the system returned an access denied error [...] so those notes
       could not be retrieved.
```

The model didn't just fail — it explained *why* to the user and still delivered every piece
of information it genuinely had access to. That is what "reaches the model as a recoverable
message" is supposed to produce, demonstrated, not asserted.

**A second real bug surfaced in this same run**, unrelated to the gateway: laps 2–3 hit
`Gemini returned no usable content ... MALFORMED_RESPONSE` — and `mcp_agent.py`'s loop, unlike
`react_agent.py`'s, had no per-lap fault isolation for that yet, so the entire run crashed the
first time. Fixed by adding the exact same `try/except llm.LLMError` pattern `react_agent.py`
already uses — one lap's provider hiccup now costs a retry, not the whole run. This edit
happened after §4's zero-line diff was already captured and is unrelated to that claim: it is
a separate fix, to a different failure, found during bonus work.

### 9.3 The audit log

One line per `tools/call`, denials included — this is the entire fix for two of
`risk_note.md`'s five lines (no logging, one undifferentiated token):

```json
{"ts": "2026-09-22T15:11:56+0530", "caller": "claim-status-only", "tool": "get_claim_status", "claim_number": "C-003", "allowed": true, "detail": ""}
{"ts": "2026-09-22T15:12:18+0530", "caller": "claim-status-only", "tool": "get_adjuster_notes", "claim_number": "C-003", "allowed": false, "detail": "denied for token 'claim-status-only'"}
```

A compromised or misbehaving instance now leaves a trail — the exact gap `risk_note.md`
named as a reason not to ship.

---

## 10. Verdict

Every core requirement is backed by a real artifact, not a claim: a live trace naming the
tool it called, a byte-for-byte identical agent module either side of a five-line config
change, a hand-annotated raw wire capture, and a measured before/after (4 laps → 2, no wasted
retry) on the exact error-handling mistake the brief warns about. The bonus closes two of
`risk_note.md`'s five lines for real — an audit log with denials in it, and a token scope that
reaches the model as something it can act on rather than a crash — after a genuine anyio
cancel-scope bug forced the backend connections into the right lifecycle instead of the
convenient one. What's left open, honestly: `risk_note.md` line 2 (no visibility into
whatever a real backing claims database would be) and line 5's broader caution — a gateway
with an audit log and two token scopes is a demonstration of the pattern, not a production
access-control system.
