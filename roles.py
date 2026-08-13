"""
roles.py — Multi-provider boardroom with genuine model diversity.

GitHub Models was retired 2026-07-30. All chains run on Groq + Google only.

QUOTA BUCKETS — critical for rate-limit resilience:
    Groq:   llama-3.3-70b  |  llama-4-scout  |  llama-4-maverick  |  llama-3.1-8b
    Google: gemini-2.0-flash  (one bucket)
            gemini-2.0-flash-lite  (separate bucket)
            gemini-1.5-flash  (separate bucket — key fallback for judge + engineer)
            gemini-1.5-flash-8b  (separate bucket — cheapest, most quota)

Primary roles:
    CEO              llama-3.3-70b-versatile  (Groq)
    CSO              llama-3.3-70b-versatile  (Groq)
    CTO              gemini-2.0-flash         (Google)
    Architect A      llama-4-scout            (Groq — Llama 4)
    Architect B      llama-3.3-70b + gemini-2.0-flash  (diverse)
    Judge            gemini-1.5-flash         (Google 1.5 — NOT in candidate rounds → fresh quota)
    Engineer         gemini-1.5-flash         (Google 1.5 — NOT exhausted by architect rounds)
    Reviewer A       llama-3.3-70b-versatile  (Groq)
    Reviewer B       gemini-2.0-flash-lite    (Google)
    QA Tester        llama-3.3-70b-versatile  (Groq)
    QA Fixer         gemini-2.0-flash         (Google)
    Fixer            llama-3.1-8b-instant     (Groq — fast)
    Polisher         gemini-2.0-flash-lite    (Google)
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
    "llama-3.3-70b-versatile":                        "groq",
    "llama-3.1-8b-instant":                           "groq",
    "meta-llama/llama-4-scout-17b-16e-instruct":      "groq",
    "meta-llama/llama-4-maverick-17b-128e-instruct":  "groq",
    # Google AI Studio — Gemini 2.0 family (one rate-limit bucket)
    "gemini-2.0-flash":                           "google",
    "gemini-2.0-flash-lite":                      "google",
    # Google AI Studio — Gemini 1.5 family (SEPARATE bucket from 2.0)
    # Critical: 1.5-flash is NOT exhausted by architect rounds that use 2.0-flash.
    "gemini-1.5-flash":                           "google",
    "gemini-1.5-flash-8b":                        "google",
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
#
# RATE-LIMIT STRATEGY: architect conference burns 4-8 calls on llama-3.3-70b,
# llama-4-scout, and gemini-2.0-flash. By the time judge + engineer run, all
# those are rate-limited. The fix: judge and engineer use gemini-1.5-flash
# FIRST — completely separate quota bucket from gemini-2.0-flash, untouched
# by the candidate rounds. gemini-1.5-flash-8b is the cheapest fallback with
# the most remaining quota at any point in the build.
#
# Quota buckets (distinct per-minute limits):
#   Groq:   llama-3.3-70b | llama-4-scout | llama-4-maverick | llama-3.1-8b
#   Google: gemini-2.0-flash | gemini-2.0-flash-lite | gemini-1.5-flash | gemini-1.5-flash-8b

ROLE_CHAIN: dict[str, list[str]] = {
    # ── Executive layer ──────────────────────────────────────────────────
    "ceo": [
        "llama-3.3-70b-versatile",      # Groq — strategic synthesis
        "gemini-1.5-flash",             # Google 1.5 — separate quota
        "gemini-2.0-flash",             # Google 2.0 fallback
        "llama-3.1-8b-instant",         # Groq fast fallback
    ],
    "cso": [
        "llama-3.3-70b-versatile",      # Groq — scientific novelty
        "gemini-1.5-flash",             # Google 1.5 — separate quota
        "gemini-2.0-flash",             # Google 2.0 fallback
        "llama-3.1-8b-instant",
    ],
    "cto": [
        "gemini-2.0-flash",             # Google 2.0 — code + self-improvement
        "gemini-1.5-flash",             # Google 1.5 fallback
        "llama-3.3-70b-versatile",      # Groq fallback
        "gemini-2.0-flash-lite",
    ],
    "vp_eng": [
        "llama-3.3-70b-versatile",
        "gemini-1.5-flash",
        "gemini-2.0-flash",
        "llama-3.1-8b-instant",
    ],

    # ── Planning layer ────────────────────────────────────────────────────
    # Candidate A: Llama 4 Scout primary, then 1.5-flash (separate bucket),
    # then 3.3-70b, then 2.0-flash as late fallback.
    "architect_candidate_a": [
        "meta-llama/llama-4-scout-17b-16e-instruct",  # Groq — Llama 4 Scout
        "gemini-1.5-flash",                            # Google 1.5 — separate bucket
        "llama-3.3-70b-versatile",                     # Groq — Llama 3.3
        "gemini-2.0-flash",                            # Google 2.0 fallback
        "gemini-1.5-flash-8b",                         # Google 1.5 tiny — last resort
    ],
    # Candidate B: diverse from A — starts with 3.3-70b + 2.0-flash so
    # the two candidates use DIFFERENT primary models (spread quota load).
    "architect_candidate_b": [
        "llama-3.3-70b-versatile",                        # Groq — different primary than A
        "gemini-2.0-flash",                               # Google 2.0
        "meta-llama/llama-4-maverick-17b-128e-instruct",  # Groq — different Llama 4 variant
        "gemini-1.5-flash-8b",                            # Google 1.5 tiny — fresh quota
        "gemini-1.5-flash",                               # Google 1.5 full
        "meta-llama/llama-4-scout-17b-16e-instruct",      # Groq Scout last resort
    ],
    # Judge: uses gemini-1.5-flash FIRST — this model is NOT used in
    # candidate rounds (which use gemini-2.0-flash), so it has full quota.
    # 1.5-flash-8b is the cheapest and has the most remaining headroom.
    # llama-3.1-8b-instant REMOVED: 413 on large prompts (PLAN_SYSTEM ~5700 tokens)
    "architect_judge": [
        "gemini-1.5-flash",             # Google 1.5 — separate bucket, full quota after candidates
        "gemini-1.5-flash-8b",          # Google 1.5 tiny — most quota remaining
        "gemini-2.0-flash-lite",        # Google 2.0 lite — different bucket from 2.0-flash
        "gemini-2.0-flash",             # Google 2.0 — may have partially reset
        "llama-3.3-70b-versatile",      # Groq fallback
    ],

    # ── Implementation layer ──────────────────────────────────────────────
    # Engineer: gemini-1.5-flash FIRST — 1M context window, NOT used in
    # architect rounds (which use gemini-2.0-flash). By the time engineer
    # runs, 1.5-flash quota is completely fresh. 1.5-flash-8b as cheap backup.
    # llama-3.1-8b-instant kept for 413-safe contexts only (small files).
    "engineer": [
        "gemini-1.5-flash",                           # Google 1.5 — 1M ctx, NOT in architect rounds
        "gemini-1.5-flash-8b",                        # Google 1.5 tiny — most quota remaining
        "gemini-2.0-flash",                           # Google 2.0 — may have reset
        "llama-3.3-70b-versatile",                    # Groq
        "meta-llama/llama-4-scout-17b-16e-instruct",  # Groq Llama 4
        "gemini-2.0-flash-lite",                      # Google 2.0 lite — last resort
    ],
    "reviewer_a": [
        "llama-3.3-70b-versatile",      # Groq — open-source perspective
        "gemini-1.5-flash",             # Google 1.5 — separate bucket
        "llama-3.1-8b-instant",         # Groq fast fallback
        "gemini-2.0-flash",
    ],
    "reviewer_b": [
        "gemini-2.0-flash-lite",        # Google 2.0 lite — fast review
        "gemini-1.5-flash-8b",          # Google 1.5 tiny — fresh quota
        "gemini-2.0-flash",             # Google 2.0 fallback
        "llama-3.3-70b-versatile",      # Groq fallback
    ],
    "fixer": [
        "llama-3.1-8b-instant",         # Groq — fast iterative repair
        "gemini-1.5-flash-8b",          # Google 1.5 tiny — cheap, fast
        "llama-3.3-70b-versatile",      # Groq stronger fallback
        "gemini-2.0-flash",             # Google fallback
    ],
    "polisher": [
        "gemini-2.0-flash-lite",        # Google 2.0 lite — lightweight polish
        "gemini-1.5-flash-8b",          # Google 1.5 tiny
        "llama-3.1-8b-instant",         # Groq fast
        "gemini-2.0-flash",
    ],

    # ── QA layer ──────────────────────────────────────────────────────────
    "qa_tester": [
        "llama-3.3-70b-versatile",      # Groq — strict user-pathway simulation
        "gemini-1.5-flash",             # Google 1.5 — separate quota
        "gemini-2.0-flash",             # Google 2.0 fallback
        "llama-3.1-8b-instant",
    ],
    "qa_fixer": [
        "gemini-2.0-flash",             # Google 2.0 — fast repair
        "gemini-1.5-flash",             # Google 1.5 — fresh quota
        "llama-3.3-70b-versatile",      # Groq fallback
        "gemini-2.0-flash-lite",
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
                    # Sleep 25s before next model — Groq/Google rate limits are per-minute
                    # rolling windows. 25s gives ~40% window reset for the next model.
                    log.warning("[role=%s] model=%s rate-limited; sleeping 25s then falling back",
                                role, model_id)
                    time.sleep(25)
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
