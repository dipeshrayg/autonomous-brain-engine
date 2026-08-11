"""
roles.py — Multi-provider boardroom with genuine model diversity.

GitHub Models was retired 2026-07-30. All chains now run on Groq + Google only.

    CEO              llama-3.3-70b-versatile  (Groq — strategic synthesis)
    CSO              llama-3.3-70b-versatile  (Groq — scientific novelty)
    CTO              gemini-2.0-flash         (Google — code + self-improvement)
    Architect A      llama-4-scout            (Groq — Llama 4, newest generation)
    Architect B      llama-3.3-70b-versatile  (Groq — Llama 3.3, different generation from A)
    Judge            gemini-2.0-flash         (Google — independent from Groq candidates)
    Engineer         gemini-2.0-flash         (Google — large context, good at code)
    Reviewer A       llama-3.3-70b-versatile  (Groq — open-source perspective)
    Reviewer B       gemini-2.0-flash-lite    (Google — lighter, fast review)
    QA Tester        llama-3.3-70b-versatile  (Groq — strict user-pathway sim)
    QA Fixer         gemini-2.0-flash         (Google — fast repair)
    Fixer            llama-3.1-8b-instant     (Groq — fast iterative repair)
    Polisher         gemini-2.0-flash-lite    (Google — lightweight UX polish)

Providers used (all zero-cost):
    groq   — Groq cloud (GROQ_API_KEY secret, free tier, very fast LPU inference)
    google — Google AI Studio (GOOGLE_AI_KEY secret, Gemini free tier)

If a provider's API key is missing, that model is silently skipped and the
chain falls through to the next available model.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from openai import OpenAI

log = logging.getLogger("brain.roles")


# ─────────────────────── Provider registry ──────────────────────────────

PROVIDERS: dict[str, dict[str, str]] = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "env_var":  "GROQ_API_KEY",
    },
    "google": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "env_var":  "GOOGLE_AI_KEY",
    },
}

# model_id → provider key
MODEL_PROVIDER: dict[str, str] = {
    # Groq — Meta Llama family (free tier, high-speed LPU)
    "llama-3.3-70b-versatile":                    "groq",
    "llama-3.1-8b-instant":                       "groq",
    "meta-llama/llama-4-scout-17b-16e-instruct":  "groq",
    # Google AI Studio — Gemini family (free tier)
    "gemini-2.0-flash":                           "google",
    "gemini-2.0-flash-lite":                      "google",
}


def _get_client(model_id: str) -> OpenAI | None:
    """Build an OpenAI-compatible client for the model's provider.
    Returns None if the required API key is not set."""
    provider_key = MODEL_PROVIDER.get(model_id)
    if provider_key is None:
        log.warning("Unknown model %r — not in MODEL_PROVIDER, skipping", model_id)
        return None
    provider = PROVIDERS[provider_key]
    api_key = os.environ.get(provider["env_var"])
    if not api_key:
        log.debug("Provider %s: env var %s not set — skipping model %s",
                  provider_key, provider["env_var"], model_id)
        return None
    return OpenAI(base_url=provider["base_url"], api_key=api_key)


# ─────────────────────── Role → model chain ─────────────────────────────
# Each entry: [primary, fallback1, fallback2, ...]
# GitHub Models retired 2026-07-30 — all chains use Groq + Google only.
# Groq: llama-3.3-70b-versatile, llama-4-scout, llama-3.1-8b-instant
# Google: gemini-2.0-flash, gemini-2.0-flash-lite
# llama-3.1-8b-instant is the last-resort fallback — different quota bucket
# from llama-3.3-70b, so it stays available when the larger model is rate-limited.

ROLE_CHAIN: dict[str, list[str]] = {
    # ── Executive layer ──────────────────────────────────────────────────
    "ceo": [
        "llama-3.3-70b-versatile",      # Groq — strategic synthesis
        "gemini-2.0-flash",             # Google fallback
        "llama-3.1-8b-instant",         # Groq fast fallback (fresh quota when 70b rate-limited)
    ],
    "cso": [
        "llama-3.3-70b-versatile",      # Groq — scientific novelty
        "gemini-2.0-flash",             # Google fallback
        "llama-3.1-8b-instant",
    ],
    "cto": [
        "gemini-2.0-flash",             # Google — code + self-improvement
        "llama-3.3-70b-versatile",      # Groq fallback
        "gemini-2.0-flash-lite",        # Google lighter fallback
    ],
    "vp_eng": [
        "llama-3.3-70b-versatile",      # Groq — pragmatic engineering
        "llama-3.1-8b-instant",         # Groq fast fallback
        "gemini-2.0-flash",
    ],

    # ── Planning layer ────────────────────────────────────────────────────
    "architect_candidate_a": [
        "meta-llama/llama-4-scout-17b-16e-instruct",  # Groq — Llama 4, newest generation
        "llama-3.3-70b-versatile",                    # Groq Llama 3.3 fallback
        "gemini-2.0-flash",                           # Google fallback
        "gemini-2.0-flash-lite",                      # Google lite — last resort (separate quota)
    ],
    "architect_candidate_b": [
        "llama-3.3-70b-versatile",      # Groq — Llama 3.3 (different generation from Llama 4 candidate A)
        "gemini-2.0-flash",             # Google fallback
        "gemini-2.0-flash-lite",        # Google lite — separate quota from flash
    ],
    "architect_judge": [
        "gemini-2.0-flash",             # Google — independent from Groq candidates
        "gemini-2.0-flash-lite",        # Google lite — separate quota; NOT used in candidate rounds
        "llama-3.3-70b-versatile",      # Groq fallback
        # llama-3.1-8b-instant removed: 413 on large prompts (PLAN_SYSTEM ~5700 tokens alone)
    ],

    # ── Implementation layer ──────────────────────────────────────────────
    "engineer": [
        "gemini-2.0-flash",                           # Google — large context, strong at code
        "llama-3.3-70b-versatile",                    # Groq fallback
        "meta-llama/llama-4-scout-17b-16e-instruct",  # Groq Llama 4 fallback
        "llama-3.1-8b-instant",                       # Groq final fallback
    ],
    "reviewer_a": [
        "llama-3.3-70b-versatile",      # Groq — open-source perspective
        "llama-3.1-8b-instant",         # Groq fast fallback
    ],
    "reviewer_b": [
        "gemini-2.0-flash-lite",        # Google — fast, lightweight review
        "gemini-2.0-flash",             # Google primary fallback
        "llama-3.3-70b-versatile",      # Groq fallback
    ],
    "fixer": [
        "llama-3.1-8b-instant",         # Groq — fast iterative repair
        "llama-3.3-70b-versatile",      # Groq stronger fallback
        "gemini-2.0-flash",             # Google fallback
    ],
    "polisher": [
        "gemini-2.0-flash-lite",        # Google — lightweight UX polish
        "llama-3.1-8b-instant",         # Groq fast fallback
        "gemini-2.0-flash",
    ],

    # ── QA layer ──────────────────────────────────────────────────────────
    "qa_tester": [
        "llama-3.3-70b-versatile",      # Groq — strict user-pathway simulation
        "gemini-2.0-flash",             # Google fallback
        "llama-3.1-8b-instant",         # Groq fast fallback
    ],
    "qa_fixer": [
        "gemini-2.0-flash",             # Google — fast, capable repair
        "llama-3.3-70b-versatile",      # Groq fallback
        "gemini-2.0-flash-lite",        # Google lighter fallback
    ],
}


# ─────────────────────── Resilient multi-provider call ──────────────────

class AllModelsFailed(RuntimeError):
    pass


def call_with_fallback(
    client: OpenAI,          # kept for API compat — ignored (we build per-model clients)
    role: str,
    *,
    system: str,
    user: str,
    max_tokens: int,
    temperature: float = 0.85,
    json_mode: bool = True,
    transient_attempts: int = 2,
    validator: "callable | None" = None,
) -> tuple[str, dict[str, Any]]:
    """
    Walk the role's model chain across multiple providers until one succeeds.
    Each model may use a different provider (GitHub, Groq, Google).
    Missing API keys are silently skipped.
    """
    chain = ROLE_CHAIN.get(role)
    if not chain:
        raise ValueError(f"Unknown role: {role!r}")

    last_err: Exception | None = None

    for model_id in chain:
        provider_client = _get_client(model_id)
        if provider_client is None:
            continue  # API key not configured — skip silently

        for attempt in range(1, transient_attempts + 1):
            try:
                kwargs: dict[str, Any] = dict(
                    model=model_id,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user",   "content": user},
                    ],
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                # Gemini doesn't support json_object response_format — Groq does
                provider_key = MODEL_PROVIDER.get(model_id, "unknown")
                if json_mode and provider_key == "groq":
                    kwargs["response_format"] = {"type": "json_object"}

                resp = provider_client.chat.completions.create(**kwargs)
                text = resp.choices[0].message.content or ""

                if validator is not None:
                    try:
                        validator(text)
                    except Exception as ve:
                        last_err = ve
                        finish_reason = (
                            resp.choices[0].finish_reason if resp.choices else "?"
                        )
                        log.warning(
                            "[role=%s] model=%s attempt %d validator rejected "
                            "(finish=%s, len=%d): %s",
                            role, model_id, attempt, finish_reason, len(text), ve,
                        )
                        if finish_reason == "length":
                            break
                        if attempt < transient_attempts:
                            time.sleep(1)
                            continue
                        break

                meta: dict[str, Any] = {
                    "role": role, "model": model_id,
                    "provider": MODEL_PROVIDER.get(model_id, "unknown"),
                    "attempt": attempt,
                }
                if resp.usage:
                    meta["prompt_tokens"]     = resp.usage.prompt_tokens
                    meta["completion_tokens"] = resp.usage.completion_tokens
                log.info("[role=%s] model=%s attempt=%d OK (in=%s out=%s)",
                         role, model_id, attempt,
                         meta.get("prompt_tokens", "?"),
                         meta.get("completion_tokens", "?"))
                return text, meta

            except Exception as e:
                last_err = e
                msg = str(e)[:280]
                rate_limited = (
                    "429" in msg or "rate" in msg.lower()
                    or "quota" in msg.lower() or "tokens_limit" in msg.lower()
                )
                too_large = "413" in msg or "tokens_limit_reached" in msg
                # 404/401 are permanent errors (model gone, auth issue) — don't retry
                permanent = "404" in msg or "401" in msg
                if too_large or permanent:
                    log.warning("[role=%s] model=%s attempt %d failed (%s); falling back",
                                role, model_id, attempt, msg[:120])
                    break  # permanent / size errors don't recover with sleep
                if rate_limited:
                    # Sleep briefly before trying the next model — gives the rate-limit
                    # window time to partially reset so the fallback model isn't also
                    # immediately rejected (all models share minute-level quota windows).
                    log.warning("[role=%s] model=%s rate-limited; sleeping 8s then falling back",
                                role, model_id)
                    time.sleep(8)
                    break
                if attempt < transient_attempts:
                    backoff = 2 ** attempt
                    log.warning("[role=%s] model=%s attempt %d failed (%s); retrying in %ds",
                                role, model_id, attempt, msg[:120], backoff)
                    time.sleep(backoff)
                    continue
                log.warning("[role=%s] model=%s exhausted retries (%s); falling back",
                            role, model_id, msg[:120])
                break

    raise AllModelsFailed(
        f"role={role}: every model in chain {chain} failed. Last error: {last_err}"
    ) from last_err
