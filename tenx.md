**What breaks first at 10x claim volume: the rate limit — and it's already broken at 1x,
confirmed live twice in this project — in Week 10, and again while building this week.**
`gemini-3.6-flash` (the project's pinned model) carries a free-tier cap of **20 requests
PER DAY**, read straight off a 429 body's own
`quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier` (Week 10; this week's 429
repeated the same `limit: 20`) — not estimated. This
week's suite is 11 claims averaging **6.5 LLM calls each** (`cost_by_stage.md`) — **~72
requests for one pass of today's own eval set**, 3.6x over the daily cap before a single
real adjuster has filed anything. The pinned model's quota was exhausted *twice*: during
Week 10 (Sept 29), and again this week (Oct 1) — the second time partly by my own four
hand-run C-011 attempts on the pinned model, before the suite ran. Every suite run in this
file therefore used a substitute model (`gemini-3.5-flash-lite`) just to keep working — which
`drill.md` shows carries its own cost (a weaker model hallucinating a fictional policy
clause under retrieval pressure). Latency and token cost both matter less here: at $0.00347
and ~28 wall-seconds per claim, 10x volume is a Tuesday for cost and a queue, not an outage
— the request-rate ceiling is the one number that is already, today, lower than this app's
own test suite needs.
