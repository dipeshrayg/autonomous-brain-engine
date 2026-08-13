"""
roles.py — Multi-provider boardroom with genuine model diversity.

PROVIDERS (as of 2026-08):
    Groq:       LPU inference, generous free tier. TPD caps apply.
    Google:     Gemini 2.5 family — current generation, high free limits.
    Cerebras:   CS-3 wafer-scale inference. 60k output tokens/min FREE.
    OpenRouter: Routes to many providers incl. Hermes 3 free tier.

DEAD MODELS (removed):
    gemini-2.0-flash, gemini-2.0-flash-lite  — retired by Google
    gemini-1.5-flash, gemini-1.5-flash-8b    — endpoint deprecated
    meta-llama/llama-4-scout-17b-16e-instruct  — 404 on Groq (paid tier)
    meta-llama/llama-4-maverick-17b-128e-instruct — 404 on Groq

QUOTA BUCKETS — critical for rate-limit resilience:
    Groq:       llama-3.3-70b-versatile | llama-3.1-8b-instant | gemma2-9b-it
    Google:     gemini-2.5-flash | gemini-2.5-pro (separate buckets)
    Cerebras:   llama-3.3-70b | llama3.1-8b (60k out tokens/min free)
    OpenRouter: nousresearch/hermes-3-llama-3.1-70b:free (free tier)

Primary roles:
    CEO              llama-3.3-70b-versatile  (Groq)
    CSO              gemini-2.5-flash         (Google)
    CTO              gemini-2.5-flash         (Google)
    Architect A      llama-3.3-70b            (Cerebras — fresh quota)
    Architect B      hermes-3-llama-3.1-70b   (OpenRouter — diverse)
    Judge            gemini-2.5-flash         (Google — NOT in candidate rounds)
    Engineer         gemini-2.5-flash         (Google — 1M context)
    Reviewer A       llama-3.3-70b-versatile  (Groq)
    Reviewer B       gemini-2.5-flash         (Google)
    QA Tester        llama-3.3-70b-versatile  (Groq)
    QA Fixer         gemini-2.5-flash         (Google)
    Fixer            llama3.1-8b              (Cerebras — fast)
    Polisher         gemma2-9b-it             (Groq — small, fast)
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
    "cerebras": {
        # CS-3 wafer-scale inference — 60k output tokens/min free
        "base_url": "https://api.cerebras.ai/v1",
        "env_var":  "CEREBRAS_API_KEY",
    },
    "openrouter": {
        # Routes to many providers; free models via :free suffix
        "base_url": "https://openrouter.ai/api/v1",
        "env_var":  "OPENROUTER_API_KEY",
    },
}

# model_id → provider key
MODEL_PROVIDER: dict[str, str] = {
    # ── Groq (LPU — fast; free tier has per-minute + per-day limits) ──────
    "llama-3.3-70b-versatile":  "groq",   # 128k ctx, 100k TPD free
    "llama-3.1-8b-instant":     "groq",   # fast small model
    "gemma2-9b-it":             "groq",   # Google Gemma 2 on Groq — separate quota

    # ── Google AI Studio — Gemini 2.5 family (current as of 2026) ─────────
    "gemini-2.5-flash":         "google", # main workhorse, very generous free tier
    "gemini-2.5-pro":           "google", # more capable; separate quota from flash

    # ── Cerebras — wafer-scale inference, extremely high throughput ────────
    "llama-3.3-70b":            "cerebras",  # Llama 3.3 70B — 60k out tokens/min free
    "llama3.1-8b":              "cerebras",  # Llama 3.1 8B — fast iterative repair

    # ── OpenRouter — free-tier routing to multiple providers ───────────────
    "nousresearch/hermes-3-llama-3.1-70b:free": "openrouter",  # Hermes 3 — great JSON
    "meta-llama/llama-3.3-70b-instruct:free":   "openrouter",  # diverse perspective
}

# Providers that support json_object response_format (OpenAI-compat, not Google)
_JSON_MODE_PROVIDERS = {"groq", "cerebras", "openrouter"}


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
# RATE-LIMIT STRATEGY: architect candidates burn through Cerebras and
# OpenRouter quota first. By the time judge + engineer run, those are
# partially recovered. Judge/engineer start with gemini-2.5-flash which
# is NOT used as primary in candidate rounds → fresh quota guaranteed.
#
# Quota buckets (distinct per-minute limits):
#   Groq:       llama-3.3-70b-versatile | llama-3.1-8b-instant | gemma2-9b-it
#   Google:     gemini-2.5-flash | gemini-2.5-pro
#   Cerebras:   llama-3.3-70b | llama3.1-8b (same account, but very high limit)
#   OpenRouter: hermes:free | llama-3.3-70b:free

ROLE_CHAIN: dict[str, list[str]] = {
    # ── Executive layer ──────────────────────────────────────────────────
    "ceo": [
        "llama-3.3-70b-versatile",      # Groq — strategic synthesis
        "llama-3.3-70b",                # Cerebras — fast fallback
        "gemini-2.5-flash",             # Google — fresh
        "llama-3.1-8b-instant",         # Groq small
    ],
    "cso": [
        "gemini-2.5-flash",             # Google — scientific novelty
        "nousresearch/hermes-3-llama-3.1-70b:free",  # OpenRouter Hermes
        "llama-3.3-70b-versatile",      # Groq fallback
        "llama-3.1-8b-instant",
    ],
    "cto": [
        "gemini-2.5-flash",             # Google — code + self-improvement
        "llama-3.3-70b",                # Cerebras
        "llama-3.3-70b-versatile",      # Groq fallback
        "gemini-2.5-pro",               # Google capable fallback
    ],
    "vp_eng": [
        "llama-3.3-70b-versatile",
        "llama-3.3-70b",                # Cerebras
        "gemini-2.5-flash",
        "llama-3.1-8b-instant",
    ],

    # ── Planning layer ────────────────────────────────────────────────────
    # Candidate A: Cerebras primary — completely fresh quota, very fast.
    # Avoids Google entirely so judge can use gemini-2.5-flash with full quota.
    "architect_candidate_a": [
        "llama-3.3-70b",                             # Cerebras — primary, 60k TPM free
        "gemini-2.5-flash",                          # Google — generous limits
        "nousresearch/hermes-3-llama-3.1-70b:free",  # OpenRouter Hermes — JSON expert
        "llama-3.3-70b-versatile",                   # Groq fallback
        "gemma2-9b-it",                              # Groq — separate quota bucket
    ],
    # Candidate B: Hermes primary — diverse perspective from A, excellent JSON.
    # Also avoids Google-flash so judge quota stays fresh.
    "architect_candidate_b": [
        "nousresearch/hermes-3-llama-3.1-70b:free",  # OpenRouter Hermes — primary
        "meta-llama/llama-3.3-70b-instruct:free",    # OpenRouter diverse fallback
        "gemini-2.5-pro",                            # Google Pro — different bucket from flash
        "llama-3.3-70b",                             # Cerebras fallback
        "llama-3.3-70b-versatile",                   # Groq fallback
        "gemma2-9b-it",                              # Groq small fallback
    ],
    # Judge: gemini-2.5-flash FIRST — NOT used in candidate rounds above
    # (candidates use Cerebras + Hermes/OpenRouter + Groq). Full quota available.
    "architect_judge": [
        "gemini-2.5-flash",             # Google — fresh quota, 1M context
        "gemini-2.5-pro",               # Google Pro — more capable
        "nousresearch/hermes-3-llama-3.1-70b:free",  # OpenRouter Hermes
        "llama-3.3-70b",                # Cerebras — fast
        "llama-3.3-70b-versatile",      # Groq final fallback
    ],

    # ── Implementation layer ──────────────────────────────────────────────
    # Engineer: gemini-2.5-flash FIRST — 1M context, NOT primary in architect rounds.
    "engineer": [
        "gemini-2.5-flash",             # Google — 1M ctx, NOT in architect primary rounds
        "gemini-2.5-pro",               # Google Pro — max quality fallback
        "llama-3.3-70b",                # Cerebras — fast code gen
        "nousresearch/hermes-3-llama-3.1-70b:free",  # OpenRouter Hermes
        "llama-3.3-70b-versatile",      # Groq
        "llama-3.1-8b-instant",         # Groq small — only for tiny file counts
    ],
    "reviewer_a": [
        "llama-3.3-70b-versatile",      # Groq — open-source perspective
        "llama-3.3-70b",                # Cerebras fallback
        "gemini-2.5-flash",             # Google
        "llama-3.1-8b-instant",
    ],
    "reviewer_b": [
        "gemini-2.5-flash",             # Google — fast review
        "nousresearch/hermes-3-llama-3.1-70b:free",  # OpenRouter Hermes
        "llama-3.3-70b",                # Cerebras
        "llama-3.3-70b-versatile",      # Groq fallback
    ],
    "fixer": [
        "llama3.1-8b",                  # Cerebras — very fast iterative repair
        "llama-3.1-8b-instant",         # Groq small
        "llama-3.3-70b",                # Cerebras stronger fallback
        "gemini-2.5-flash",             # Google fallback
    ],
    "polisher": [
        "gemma2-9b-it",                 # Groq Gemma — lightweight polish
        "llama3.1-8b",                  # Cerebras fast
        "llama-3.1-8b-instant",         # Groq fast
        "gemini-2.5-flash",             # Google fallback
    ],

    # ── QA layer ──────────────────────────────────────────────────────────
    "qa_tester": [
        "llama-3.3-70b-versatile",      # Groq — strict user-pathway simulation
        "llama-3.3-70b",                # Cerebras fast fallback
        "gemini-2.5-flash",             # Google fallback
        "llama-3.1-8b-instant",
    ],
    "qa_fixer": [
        "gemini-2.5-flash",             # Google — fast repair
        "llama-3.3-70b",                # Cerebras
        "llama-3.3-70b-versatile",      # Groq fallback
        "gemini-2.5-pro",               # Google capable fallback
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
    Each model may use a different provider (Groq, Google, Cerebras, OpenRouter).
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
                # Google's OpenAI-compat endpoint doesn't support json_object;
                # Groq, Cerebras, and OpenRouter do.
                provider_key = MODEL_PROVIDER.get(model_id, "unknown")
                if json_mode and provider_key in _JSON_MODE_PROVIDERS:
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
                    "provider": provider_key,
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
                    # Sleep 25s before next model — rolling minute windows.
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
