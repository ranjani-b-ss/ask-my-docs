"""The only place that knows which LLM vendor is in use.

Four providers, same interface, chosen by ``LLM_PROVIDER`` in .env:

``ollama``     local, free, offline, no key. Slower and weaker at following the citation
               format, so the citation-verification gate in generator.py earns its keep.
``openai``     hosted, costs per call, needs a key. Good at obeying "cite every sentence".
``anthropic``  hosted, costs per call, needs a key. Strongest at the supersession rule —
               noticing that an endorsement overrides a base clause and saying so.
``gemini``     hosted, costs per call, needs a key. Generous free tier, so it is the
               cheapest way to see real generated answers.

Retrieval quality is unaffected by this choice — only the wording of the final answer is.
That is worth understanding: if the app returns a wrong figure, changing provider will not
fix it, because the error happened before generation.

The key is read from the environment only. It is never logged, never written to disk by
this app, and never sent anywhere except the vendor's own endpoint.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import requests

from .config import (
    ANTHROPIC_MAX_TOKENS,
    ANTHROPIC_MODEL,
    GEMINI_BASE_URL,
    GEMINI_MODEL,
    GEMINI_TIMEOUT,
    LLM_PROVIDER,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT,
    OLLAMA_URL,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
    OPENAI_TIMEOUT,
)


@dataclass
class ProviderStatus:
    ready: bool
    detail: str


class LLMError(RuntimeError):
    pass


# ------------------------------------------------------------------------------- ollama


def ollama_status(url: str = OLLAMA_URL) -> ProviderStatus:
    try:
        response = requests.get(f"{url}/api/tags", timeout=3)
        response.raise_for_status()
    except requests.exceptions.ConnectionError:
        return ProviderStatus(False, f"Ollama is not running on {url}")
    except Exception as exc:
        return ProviderStatus(False, f"Ollama check failed: {exc}")

    models = [m.get("name", "") for m in response.json().get("models", []) if m.get("name")]
    if not models:
        return ProviderStatus(False, "Ollama is running but no models are pulled.")
    return ProviderStatus(True, ", ".join(models))


def ollama_has_model(model: str, url: str = OLLAMA_URL) -> bool:
    status = ollama_status(url)
    if not status.ready:
        return False
    installed = [m.strip() for m in status.detail.split(",")]
    base = model.split(":")[0]
    return any(m == model or m.split(":")[0] == base for m in installed)


def _ollama_payload(system: str, user: str, model: str) -> dict:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"temperature": 0.0, "num_ctx": 8192, "top_p": 0.9},
    }


def ollama_chat(system: str, user: str, model: str = OLLAMA_MODEL, url: str = OLLAMA_URL) -> str:
    try:
        response = requests.post(f"{url}/api/chat", json=_ollama_payload(system, user, model),
                                 timeout=OLLAMA_TIMEOUT)
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        # A slow response here means "still thinking on a CPU," per OLLAMA_TIMEOUT's own
        # comment, not a dead server — but a bare requests exception left uncaught crashes
        # whoever called this, one lap taking down an entire run. Raising LLMError instead
        # lets react_agent.py's existing per-lap fault isolation treat it like any other
        # provider hiccup: log it, try again next lap, still bounded by the loop's own budgets.
        raise LLMError(f"Ollama request failed: {exc}") from exc
    return response.json()["message"]["content"].strip()


def ollama_chat_with_usage(
    system: str, user: str, model: str = OLLAMA_MODEL, url: str = OLLAMA_URL
) -> tuple[str, dict]:
    try:
        response = requests.post(f"{url}/api/chat", json=_ollama_payload(system, user, model),
                                 timeout=OLLAMA_TIMEOUT)
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise LLMError(f"Ollama request failed: {exc}") from exc
    body = response.json()
    # Ollama reports these as prompt_eval_count / eval_count, and omits both entirely when a
    # response is served from its internal cache — .get(..., 0) rather than a KeyError.
    prompt = body.get("prompt_eval_count", 0)
    completion = body.get("eval_count", 0)
    usage = {"prompt_tokens": prompt, "completion_tokens": completion,
              "total_tokens": prompt + completion}
    return body["message"]["content"].strip(), usage


# ------------------------------------------------------------------------------- openai


def openai_key() -> str | None:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    return key or None


def openai_status(model: str = OPENAI_MODEL) -> ProviderStatus:
    if not openai_key():
        return ProviderStatus(
            False,
            "OPENAI_API_KEY is not set. Put it in .env (see .env.example) — the app reads "
            "it from the environment and never stores it.",
        )
    return ProviderStatus(True, f"OpenAI key detected · model {model}")


def openai_chat(system: str, user: str, model: str = OPENAI_MODEL) -> str:
    key = openai_key()
    if not key:
        raise LLMError("OPENAI_API_KEY is not set.")

    response = requests.post(
        f"{OPENAI_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.0,
        },
        timeout=OPENAI_TIMEOUT,
    )
    if response.status_code == 401:
        raise LLMError("OpenAI rejected the key (401). Check OPENAI_API_KEY.")
    if response.status_code == 429:
        raise LLMError("OpenAI rate limit or quota exceeded (429).")
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


def openai_chat_with_usage(system: str, user: str, model: str = OPENAI_MODEL) -> tuple[str, dict]:
    key = openai_key()
    if not key:
        raise LLMError("OPENAI_API_KEY is not set.")

    response = requests.post(
        f"{OPENAI_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.0,
        },
        timeout=OPENAI_TIMEOUT,
    )
    if response.status_code == 401:
        raise LLMError("OpenAI rejected the key (401). Check OPENAI_API_KEY.")
    if response.status_code == 429:
        raise LLMError("OpenAI rate limit or quota exceeded (429).")
    response.raise_for_status()
    body = response.json()
    u = body.get("usage", {})
    usage = {"prompt_tokens": u.get("prompt_tokens", 0),
              "completion_tokens": u.get("completion_tokens", 0),
              "total_tokens": u.get("total_tokens", 0)}
    return body["choices"][0]["message"]["content"].strip(), usage


# ------------------------------------------------------------------------------ claude


def anthropic_key() -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    return key or None


def anthropic_status(model: str = ANTHROPIC_MODEL) -> ProviderStatus:
    try:
        import anthropic  # noqa: F401
    except ModuleNotFoundError:
        return ProviderStatus(
            False, "The `anthropic` package is not installed. pip install anthropic"
        )
    if not anthropic_key():
        return ProviderStatus(
            False,
            "ANTHROPIC_API_KEY is not set. Put it in .env (see .env.example) — the app "
            "reads it from the environment and never stores it.",
        )
    return ProviderStatus(True, f"Anthropic key detected · model {model}")


def anthropic_chat(system: str, user: str, model: str = ANTHROPIC_MODEL) -> str:
    """Claude via the official SDK.

    Three things differ from the Ollama and OpenAI paths, and getting them wrong is a
    hard 400 rather than a silent degradation:

    1. **No `temperature`.** The parameter was removed on Claude Opus 5 — sending it at
       all is rejected. Determinism is steered by the prompt instead, which is why the
       system prompt is emphatic about quoting figures verbatim.
    2. **The system prompt is a top-level `system=` argument**, not a message with
       `role="system"` as in the OpenAI-shaped APIs.
    3. **`max_tokens` bounds thinking *and* the answer together**, and thinking is on by
       default, so a value sized only for the answer truncates mid-sentence.
    """
    import anthropic

    if not anthropic_key():
        raise LLMError("ANTHROPIC_API_KEY is not set.")

    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model=model,
            max_tokens=ANTHROPIC_MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.AuthenticationError as exc:
        raise LLMError(f"Anthropic rejected the key: {exc}") from exc
    except anthropic.RateLimitError as exc:
        raise LLMError(f"Anthropic rate limit exceeded: {exc}") from exc

    # A safety classifier can decline the request. That returns HTTP 200 with an empty or
    # partial `content`, so reading content[0] unconditionally would crash here.
    if response.stop_reason == "refusal":
        raise LLMError(
            "Claude declined to answer this request (stop_reason=refusal)."
        )

    parts = [block.text for block in response.content if block.type == "text"]
    return "\n".join(parts).strip()


def anthropic_chat_with_usage(
    system: str, user: str, model: str = ANTHROPIC_MODEL
) -> tuple[str, dict]:
    import anthropic

    if not anthropic_key():
        raise LLMError("ANTHROPIC_API_KEY is not set.")

    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model=model,
            max_tokens=ANTHROPIC_MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.AuthenticationError as exc:
        raise LLMError(f"Anthropic rejected the key: {exc}") from exc
    except anthropic.RateLimitError as exc:
        raise LLMError(f"Anthropic rate limit exceeded: {exc}") from exc

    if response.stop_reason == "refusal":
        raise LLMError("Claude declined to answer this request (stop_reason=refusal).")

    parts = [block.text for block in response.content if block.type == "text"]
    prompt = response.usage.input_tokens
    completion = response.usage.output_tokens
    usage = {"prompt_tokens": prompt, "completion_tokens": completion,
              "total_tokens": prompt + completion}
    return "\n".join(parts).strip(), usage


# ------------------------------------------------------------------------------ gemini


def gemini_key() -> str | None:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    return key or None


def gemini_status(model: str = GEMINI_MODEL) -> ProviderStatus:
    if not gemini_key():
        return ProviderStatus(
            False,
            "GEMINI_API_KEY is not set. Put it in .env (see .env.example) — the app reads "
            "it from the environment and never stores it.",
        )
    return ProviderStatus(True, f"Gemini key detected · model {model}")


# Seconds to wait before each retry of a transient 5xx.
_BACKOFF = (4.0, 12.0, 30.0)


def _gemini_retry_delay(response, default: float = 20.0) -> float:
    """Honour the API's own RetryInfo if it sends one, else back off a fixed amount."""
    try:
        for detail in response.json().get("error", {}).get("details", []):
            delay = detail.get("retryDelay")
            if isinstance(delay, str) and delay.endswith("s"):
                return min(60.0, max(1.0, float(delay[:-1])))
    except (ValueError, TypeError, AttributeError):
        pass
    return default


def _gemini_request(system: str, user: str, model: str, attempt: int) -> dict:
    """POST to Gemini, handle status codes and retries, return the raw response JSON.

    Split out of ``gemini_chat`` so that a usage-tracking caller (``gemini_chat_with_usage``,
    needed for Week 7's cost/token budgets) shares this exact retry ladder instead of a second
    copy of it drifting out of sync. Nothing about the request or the retry behaviour changed
    in this split — only the point where text gets extracted moved to the callers.
    """
    key = gemini_key()
    if not key:
        raise LLMError("GEMINI_API_KEY is not set.")

    try:
        response = requests.post(
            f"{GEMINI_BASE_URL}/models/{model}:generateContent",
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            json={
                "system_instruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"temperature": 0.0},
            },
            timeout=GEMINI_TIMEOUT,
        )
    except requests.exceptions.RequestException as exc:
        # Everything above (400/403/404/429/5xx) is a response Gemini sent back — this
        # branch is for the request never getting a response at all: a dropped SSL
        # handshake, a DNS failure, a timeout with no bytes read. `requests.post` raises
        # these BEFORE a `response` object exists, so they were falling straight through
        # this function uncaught until a genuine one turned up mid-development (an
        # `SSLEOFError` unrelated to anything in the request). Retried on the same ladder as
        # a transient 5xx, because from the caller's side "the connection died" and "the
        # server returned 503" are the same kind of problem: not the request's fault, worth
        # one more try.
        if attempt < len(_BACKOFF):
            time.sleep(_BACKOFF[attempt])
            return _gemini_request(system, user, model, attempt=attempt + 1)
        raise LLMError(
            f"Gemini connection failed on {len(_BACKOFF) + 1} attempts: {exc}"
        ) from exc

    if response.status_code in (400, 403):
        raise LLMError(
            f"Gemini rejected the request ({response.status_code}). Check GEMINI_API_KEY "
            f"and that your key has access to '{model}'. Body: {response.text[:200]}"
        )
    if response.status_code == 404:
        # A 404 here usually does NOT mean the model is absent — Google gates older
        # versions to existing users, so the model appears in ListModels and still 404s
        # for a newer key. The API's own message says which; surface it verbatim.
        detail = response.json().get("error", {}).get("message", response.text[:200])
        raise LLMError(
            f"Gemini refused model '{model}': {detail}\n"
            "Set GEMINI_MODEL in .env to a model your key can use "
            "(`gemini-flash-latest` is the safe choice)."
        )
    if response.status_code in (500, 502, 503, 504):
        # Transient server-side failure. One retry is not enough: measured over a 22-request
        # batch, a single 5s retry still left 64% of calls failing, because the free tier
        # returns 503 in bursts rather than as isolated blips. Three attempts with
        # increasing backoff clears almost all of them.
        #
        # This matters beyond convenience. When the call fails the app degrades to quoting a
        # passage, so an under-retried provider does not look like an outage in the logs —
        # it looks like the app changed its answer style, and a whole batch of traces gets
        # attributed to the wrong cause.
        if attempt < len(_BACKOFF):
            time.sleep(_BACKOFF[attempt])
            return _gemini_request(system, user, model, attempt=attempt + 1)
        raise LLMError(
            f"Gemini returned {response.status_code} (server-side, transient) on "
            f"{len(_BACKOFF) + 1} attempts. Not a problem with your key or quota — "
            "the endpoint is having a bad day."
        )

    if response.status_code == 429:
        # Two separate free-tier quotas: requests-per-minute and TOKENS-per-minute. A RAG
        # prompt carries five passages, so it trips the token quota long before the request
        # quota — a one-word probe can succeed while real questions 429. Both reset on a
        # rolling minute, so one backoff usually clears it.
        # Shares the attempt counter with the 5xx branch above, so a call that already
        # burned retries on 503 does not then wait out three more quota backoffs.
        retry_after = _gemini_retry_delay(response)
        if attempt < 2:
            time.sleep(retry_after)
            return _gemini_request(system, user, model, attempt=attempt + 1)
        raise LLMError(
            "Gemini quota exceeded (429) twice. This is usually the free tier's "
            "tokens-per-minute limit rather than requests-per-minute, because each question "
            "sends five passages. Wait a minute, lower top-k to send fewer passages, or set "
            "GEMINI_MODEL to a lite variant with a larger allowance."
        )
    response.raise_for_status()
    return response.json()


class _GeminiRetryableContent(LLMError):
    """A 200 OK carrying no usable content, for a reason worth trying again rather than
    surfacing — never raised past ``gemini_chat``/``gemini_chat_with_usage``."""


def _gemini_extract(payload: dict) -> tuple[str, dict]:
    """Text and usage counters from a successful Gemini payload.

    ``usageMetadata`` is what makes the Week 7 cost budget real rather than estimated: Gemini
    reports the exact prompt and completion token counts it billed for, so
    ``gemini_chat_with_usage`` never has to fall back to a chars/4 guess.
    """
    # A safety filter can block the prompt outright — no candidates come back at all.
    blocked = payload.get("promptFeedback", {}).get("blockReason")
    if blocked:
        raise LLMError(f"Gemini blocked the prompt (reason: {blocked}).")

    candidates = payload.get("candidates") or []
    if not candidates:
        raise LLMError("Gemini returned no candidates.")

    finish = candidates[0].get("finishReason")
    if finish in {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT"}:
        raise LLMError(f"Gemini stopped early (finishReason: {finish}).")
    if finish == "MALFORMED_RESPONSE":
        # An intermittent decoding failure on Google's side — HTTP 200, empty content, no
        # fault in the request. Observed on gemini-flash-lite-latest under a long system
        # prompt (Week 7's tool-heavy agent prompt); a same-request retry clears it.
        raise _GeminiRetryableContent(f"finishReason: {finish}")

    parts = candidates[0].get("content", {}).get("parts", [])
    text = "\n".join(p["text"] for p in parts if "text" in p).strip()
    if not text:
        raise _GeminiRetryableContent(f"empty answer, finishReason: {finish}")

    meta = payload.get("usageMetadata", {})
    usage = {
        "prompt_tokens": meta.get("promptTokenCount", 0),
        "completion_tokens": meta.get("candidatesTokenCount", 0),
        "total_tokens": meta.get("totalTokenCount", 0),
    }
    return text, usage


def _gemini_call(system: str, user: str, model: str, content_attempt: int = 0) -> tuple[str, dict]:
    """``_gemini_request`` + ``_gemini_extract``, with one retry ladder of its own for a
    200 OK that carried nothing usable — a different failure class from the 5xx/429 ladder
    inside ``_gemini_request``, so it needs its own attempt counter rather than sharing one.
    """
    try:
        return _gemini_extract(_gemini_request(system, user, model, attempt=0))
    except _GeminiRetryableContent as exc:
        # 4 attempts, not 3: measured on Week 7's agent prompt (~4000 chars, three tool
        # descriptions plus the ReAct protocol), MALFORMED_RESPONSE from
        # gemini-flash-lite-latest showed up in bursts of 3 straight failures on the same
        # call — a fixed prompt this size on this model needs more headroom than a short
        # single-turn prompt does, not because the request is malformed but because longer
        # prompts appear to raise this model's chance of a bad decode.
        if content_attempt < 3:
            time.sleep(2.0)
            return _gemini_call(system, user, model, content_attempt=content_attempt + 1)
        raise LLMError(f"Gemini returned no usable content on 4 attempts ({exc}).") from exc


def gemini_chat(system: str, user: str, model: str = GEMINI_MODEL, attempt: int = 0) -> str:
    """Gemini via the REST API.

    Shape differs from the OpenAI-style APIs in three ways worth noting:
    the system prompt is its own ``system_instruction`` object rather than a message with
    ``role="system"``; user turns wrap text in a ``parts`` list; and sampling settings live
    under ``generationConfig`` instead of at the top level.

    The key goes in a header, not the query string — a key in a URL ends up in server
    logs, proxy logs, and browser history.
    """
    text, _usage = _gemini_call(system, user, model)
    return text


def gemini_chat_with_usage(
    system: str, user: str, model: str = GEMINI_MODEL, attempt: int = 0
) -> tuple[str, dict]:
    """Same call as ``gemini_chat``, plus the token counts Gemini billed for.

    Needed wherever a caller has to enforce a token or cost budget rather than just display
    an answer — the Week 7 agent loop resends the whole growing transcript every lap, so its
    token spend cannot be inferred from the final call alone; it has to be summed lap by lap
    from real usage, not estimated.
    """
    return _gemini_call(system, user, model)


# ------------------------------------------------------------------------------ dispatch

PROVIDERS = ("ollama", "openai", "anthropic", "gemini")


def provider_name() -> str:
    return os.environ.get("LLM_PROVIDER", LLM_PROVIDER).strip().lower()


def status(provider: str | None = None) -> ProviderStatus:
    name = provider or provider_name()
    if name == "openai":
        return openai_status()
    if name == "anthropic":
        return anthropic_status()
    if name == "gemini":
        return gemini_status()
    return ollama_status()


def is_ready(provider: str | None = None) -> bool:
    name = provider or provider_name()
    if name == "openai":
        return openai_status().ready
    if name == "anthropic":
        return anthropic_status().ready
    if name == "gemini":
        return gemini_status().ready
    return ollama_has_model(OLLAMA_MODEL)


def default_model(provider: str | None = None) -> str:
    name = provider or provider_name()
    return {
        "openai": OPENAI_MODEL,
        "anthropic": ANTHROPIC_MODEL,
        "gemini": GEMINI_MODEL,
    }.get(name, OLLAMA_MODEL)


def call_params(provider: str | None = None) -> dict:
    """The decoding parameters this provider is actually called with.

    Recorded in every trace. Naming the provider is not enough to replay a call: two runs
    at different temperatures are two different experiments, and Anthropic is deliberately
    called with no temperature at all (the parameter was removed on Opus 5), which is a
    difference a reader would otherwise have to go read the source to discover.
    """
    name = provider or provider_name()
    if name == "openai":
        return {"temperature": 0.0}
    if name == "anthropic":
        # No temperature by design — see anthropic_chat.
        return {"max_tokens": ANTHROPIC_MAX_TOKENS, "thinking": "default"}
    if name == "gemini":
        return {"temperature": 0.0}
    return {"temperature": 0.0, "num_ctx": 8192, "top_p": 0.9}


def chat(system: str, user: str, provider: str | None = None, model: str | None = None) -> str:
    name = provider or provider_name()
    if name == "openai":
        return openai_chat(system, user, model or OPENAI_MODEL)
    if name == "anthropic":
        return anthropic_chat(system, user, model or ANTHROPIC_MODEL)
    if name == "gemini":
        return gemini_chat(system, user, model or GEMINI_MODEL)
    if name == "ollama":
        return ollama_chat(system, user, model or OLLAMA_MODEL)
    raise LLMError(
        f"Unknown LLM_PROVIDER '{name}'. Use one of: {', '.join(PROVIDERS)}."
    )


def chat_with_usage(
    system: str, user: str, provider: str | None = None, model: str | None = None
) -> tuple[str, dict]:
    """Same contract as ``chat``, plus a ``{prompt_tokens, completion_tokens, total_tokens}``
    dict from the provider's own response — never estimated from character counts.

    Week 7's agent loop needs this because it resends the whole transcript every lap: the
    final call's token count says almost nothing about what the task actually cost, so the
    budget enforcement in ``src/agent/react_agent.py`` sums this dict across every lap rather
    than reading it once at the end.
    """
    name = provider or provider_name()
    if name == "openai":
        return openai_chat_with_usage(system, user, model or OPENAI_MODEL)
    if name == "anthropic":
        return anthropic_chat_with_usage(system, user, model or ANTHROPIC_MODEL)
    if name == "gemini":
        return gemini_chat_with_usage(system, user, model or GEMINI_MODEL)
    if name == "ollama":
        return ollama_chat_with_usage(system, user, model or OLLAMA_MODEL)
    raise LLMError(
        f"Unknown LLM_PROVIDER '{name}'. Use one of: {', '.join(PROVIDERS)}."
    )
