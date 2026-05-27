"""
roles.py — Multi-provider boardroom with genuine model diversity.

Every role now pulls from a different AI family so the adversarial
conference actually has adversarial perspectives:

    CEO              gpt-4o              (OpenAI — strategic synthesis)
    CSO              llama-3.3-70b       (Meta via Groq — scientific novelty)
    CTO              gemini-2.0-flash    (Google — code & self-improvement)
    Architect A      Mistral-Large       (Mistral via GitHub Models)
    Architect B      Meta-Llama-3.3-70B  (Meta via GitHub Models)
    Judge            gpt-4o              (OpenAI — predictability filter)
    Engineer         gpt-4o              (OpenAI — implementation quality)
    Reviewer A       Mistral-Large       (Mistral — different lens from GPT)
    Reviewer B       gemini-2.0-flash    (Google — third perspective)
    QA Tester        gpt-4o              (OpenAI — strict user-pathway sim)
    QA Fixer         gemini-2.0-flash    (Google — fast, capable repair)
    Fixer            gpt-4o-mini         (OpenAI fast — iterative repair)
    Polisher         Phi-4               (Microsoft via GitHub Models — UX polish)

Providers used (all zero-cost):
    github   — GitHub Models API (GITHUB_TOKEN, always available in Actions)
    groq     — Groq cloud (GROQ_API_KEY secret, free tier, very fast)
    google   — Google AI Studio (GOOGLE_AI_KEY secret, Gemini free tier)

If a provider's API key is missing, that model is silently skipped and the
chain falls through to the next available model. The pipeline never crashes
due to a missing optional key.
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
    "github": {
        "base_url": "https://models.inference.ai.azure.com",
        "env_var":  "GITHUB_TOKEN",
    },
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
    # GitHub Models (OpenAI family)
    "gpt-4o":                        "github",
    "gpt-4o-mini":                   "github",
    # GitHub Models (Microsoft)
    "Phi-4":                         "github",
    "Phi-3.5-mini-instruct":         "github",
    # GitHub Models (Mistral)
    "Mistral-Large-2411":            "github",
    "Mistral-small":                 "github",
    # GitHub Models (Meta)
    "Meta-Llama-3.3-70B-Instruct":   "github",
    "Meta-Llama-3.1-8B-Instruct":    "github",
    # GitHub Models (Cohere)
    "Cohere-command-r-plus-08-2024": "github",
    # Groq (Meta Llama — ultra-fast inference)
    "llama-3.3-70b-versatile":       "groq",
    "llama-3.1-8b-instant":          "groq",
    "mixtral-8x7b-32768":            "groq",
    # Google AI Studio (Gemini)
    "gemini-2.0-flash":              "google",
    "gemini-1.5-flash":              "google",
    "gemini-1.5-pro":                "google",
}


def _get_client(model_id: str) -> OpenAI | None:
    """Build an OpenAI-compatible client for the model's provider.
    Returns None if the required API key is not set."""
    provider_key = MODEL_PROVIDER.get(model_id, "github")
    provider = PROVIDERS[provider_key]
    api_key = os.environ.get(provider["env_var"])
    if not api_key:
        log.debug("Provider %s: env var %s not set — skipping model %s",
                  provider_key, provider["env_var"], model_id)
        return None
    return OpenAI(base_url=provider["base_url"], api_key=api_key)


# ─────────────────────── Role → model chain ─────────────────────────────
# Each entry: [primary, fallback1, fallback2, ...]
# Models from different families = genuinely adversarial boardroom.
# github models are always attempted since GITHUB_TOKEN is always present.

ROLE_CHAIN: dict[str, list[str]] = {
    # ── Executive layer ──────────────────────────────────────────────────
    "ceo": [
        "gpt-4o",                       # OpenAI — strategic synthesis
        "Mistral-Large-2411",           # Mistral fallback
        "gpt-4o-mini",
    ],
    "cso": [
        "llama-3.3-70b-versatile",      # Meta via Groq — scientific novelty
        "Meta-Llama-3.3-70B-Instruct",  # Meta via GitHub fallback
        "gpt-4o",
    ],
    "cto": [
        "gemini-2.0-flash",             # Google — code + self-improvement
        "gemini-1.5-flash",             # Google fallback
        "gpt-4o",                       # OpenAI final fallback
    ],
    "vp_eng": [
        "Mistral-Large-2411",           # Mistral — pragmatic engineering
        "gpt-4o",
        "gpt-4o-mini",
    ],

    # ── Planning layer ────────────────────────────────────────────────────
    "architect_candidate_a": [
        "Mistral-Large-2411",           # Mistral — different creative axis
        "Meta-Llama-3.3-70B-Instruct",  # Meta fallback
        "gpt-4o-mini",                  # OpenAI guaranteed fallback
        "gpt-4o",
    ],
    "architect_candidate_b": [
        "Meta-Llama-3.3-70B-Instruct",  # Meta — open-source perspective
        "llama-3.3-70b-versatile",      # Meta via Groq fallback
        "gpt-4o-mini",                  # OpenAI guaranteed fallback
        "gpt-4o",
    ],
    "architect_judge": [
        "gpt-4o",                       # OpenAI — predictability filter
        "Mistral-Large-2411",
    ],

    # ── Implementation layer ──────────────────────────────────────────────
    "engineer": [
        "gpt-4o",                       # OpenAI — best implementation quality
        "gemini-2.0-flash",             # Google fallback — strong coder
        "gpt-4o-mini",
    ],
    "reviewer_a": [
        "Mistral-Large-2411",           # Mistral — genuinely different from GPT
        "Meta-Llama-3.3-70B-Instruct",
        "gpt-4o-mini",                  # guaranteed fallback
    ],
    "reviewer_b": [
        "gemini-2.0-flash",             # Google — third independent perspective
        "gemini-1.5-flash",
        "gpt-4o-mini",                  # guaranteed fallback
    ],
    "fixer": [
        "gpt-4o-mini",
        "Phi-4",                        # Microsoft — good at targeted fixes
        "gpt-4o",
    ],
    "polisher": [
        "Phi-4",                        # Microsoft Phi — good at UX refinement
        "gpt-4o-mini",
    ],

    # ── QA layer ──────────────────────────────────────────────────────────
    "qa_tester": [
        "gpt-4o",                       # OpenAI — strict user-pathway simulation
        "gemini-2.0-flash",
    ],
    "qa_fixer": [
        "gemini-2.0-flash",             # Google — fast, capable repair
        "gpt-4o",
        "gpt-4o-mini",
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
                # Gemini doesn't support json_object response_format reliably
                provider_key = MODEL_PROVIDER.get(model_id, "github")
                if json_mode and provider_key != "google":
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
                    "provider": MODEL_PROVIDER.get(model_id, "github"),
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
                if rate_limited or too_large:
                    log.warning("[role=%s] model=%s attempt %d failed (%s); falling back",
                                role, model_id, attempt, msg[:120])
                    break  # try next model immediately
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
