"""
roles.py - The boardroom: model registry, role assignments, and resilient calls.

The system is organized hierarchically, in the spirit of a real engineering org:

    CEO              periodic top-level review (separate workflow)
       │
       ▼
    VP Engineering   the watchdog (separate workflow, 15-min ticks)
       │
       ▼
    Chief Architect  PLAN stage = 3-way conference + judge
       │
       ▼
    Engineers        IMPLEMENT stage, file-by-file
       │
       ▼
    Code Reviewers   CRITIQUE stage = 2-way parallel review + merge
       │
       ▼
    Fixer/Polisher   iterative repair + final polish
       │
       ▼
    QA (Playwright)  mechanical browser verification

Each role is bound to a primary model, with an explicit fallback chain that's
walked automatically when a primary is rate-limited or unavailable. The roles
deliberately spread across multiple model families so per-model rate limits
on the free tier never become a bottleneck.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from openai import OpenAI

log = logging.getLogger("brain.roles")


# ─────────────────────── Model registry ─────────────────────────────────
# Names are GitHub-Models / Azure-endpoint compatible. Tier is informational.

MODELS: dict[str, tuple[str, str]] = {
    "gpt-4o":          ("gpt-4o",                          "premium"),
    "gpt-4o-mini":     ("gpt-4o-mini",                     "fast"),
    "mistral-large":   ("Mistral-Large-2411",              "premium"),
    "llama-70b":       ("Meta-Llama-3.1-70B-Instruct",     "balanced"),
    "phi-medium":      ("Phi-3.5-MoE-instruct",            "fast"),
}


# ─────────────────────── Role → primary model ───────────────────────────

ROLE_PRIMARY: dict[str, str] = {
    "ceo":                   "gpt-4o",
    "architect_judge":       "gpt-4o",
    "architect_candidate_a": "mistral-large",
    "architect_candidate_b": "llama-70b",
    "engineer":              "gpt-4o",
    "reviewer_a":            "mistral-large",
    "reviewer_b":            "llama-70b",
    "fixer":                 "gpt-4o-mini",  # saves premium budget for plan/implement
    "polisher":              "gpt-4o-mini",
}

# Fallbacks tried in order when the primary errors. The fallback chains are
# different per role so that rate-limit pressure on one model doesn't cascade
# everyone onto the same backup.
ROLE_FALLBACK: dict[str, list[str]] = {
    "ceo":                   ["mistral-large", "gpt-4o-mini"],
    "architect_judge":       ["mistral-large", "gpt-4o-mini"],
    "architect_candidate_a": ["llama-70b", "gpt-4o-mini"],
    "architect_candidate_b": ["mistral-large", "gpt-4o-mini"],
    "engineer":              ["gpt-4o-mini", "mistral-large", "llama-70b"],
    "reviewer_a":            ["llama-70b", "gpt-4o-mini"],
    "reviewer_b":            ["mistral-large", "gpt-4o-mini"],
    "fixer":                 ["gpt-4o", "mistral-large", "llama-70b"],
    "polisher":              ["gpt-4o", "mistral-large", "llama-70b"],
}


def model_for(role: str) -> str:
    """Primary model id for a role."""
    key = ROLE_PRIMARY.get(role)
    if key is None:
        raise ValueError(f"Unknown role: {role}")
    return MODELS[key][0]


def chain_for(role: str) -> list[str]:
    """Primary + fallbacks, in order, for a role."""
    primary = ROLE_PRIMARY[role]
    fb = ROLE_FALLBACK.get(role, [])
    return [MODELS[k][0] for k in [primary, *fb]]


# ─────────────────────── Resilient call ─────────────────────────────────

class AllModelsFailed(RuntimeError):
    """Raised when every model in a role's chain fails."""


def call_with_fallback(
    client: OpenAI,
    role: str,
    *,
    system: str,
    user: str,
    max_tokens: int,
    temperature: float = 0.85,
    json_mode: bool = True,
    transient_attempts: int = 2,
) -> tuple[str, dict[str, Any]]:
    """
    Try every model in the role's chain until one succeeds.

    For each model: up to `transient_attempts` retries on transient errors
    (network, 5xx) before giving up on that model and falling back. Hard
    failures (bad request, 4xx other than 429) are treated as transient
    too — sometimes a specific model rejects a prompt format another
    accepts, and the fallback handles that.

    Returns:
        (text, meta) where meta carries {model, attempt, prompt_tokens,
        completion_tokens, role}.
    """
    chain = chain_for(role)
    last_err: Exception | None = None

    for model in chain:
        for attempt in range(1, transient_attempts + 1):
            try:
                kwargs: dict[str, Any] = dict(
                    model=model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}
                resp = client.chat.completions.create(**kwargs)
                text = resp.choices[0].message.content or ""
                meta: dict[str, Any] = {
                    "role": role,
                    "model": model,
                    "attempt": attempt,
                }
                if resp.usage:
                    meta["prompt_tokens"] = resp.usage.prompt_tokens
                    meta["completion_tokens"] = resp.usage.completion_tokens
                log.info("[role=%s] model=%s attempt=%d OK (in=%d out=%d)",
                         role, model, attempt,
                         meta.get("prompt_tokens", -1),
                         meta.get("completion_tokens", -1))
                return text, meta
            except Exception as e:  # noqa: BLE001
                last_err = e
                msg = str(e)[:240]
                # Decide whether to retry the same model or fall back.
                rate_limited = "429" in msg or "rate" in msg.lower() or "quota" in msg.lower()
                if rate_limited:
                    log.warning("[role=%s] model=%s rate-limited; falling back. %s",
                                role, model, msg)
                    break  # don't retry this model, move to next
                if attempt < transient_attempts:
                    backoff = 2 ** attempt
                    log.warning("[role=%s] model=%s attempt %d failed (%s); retrying in %ds",
                                role, model, attempt, msg, backoff)
                    time.sleep(backoff)
                    continue
                log.warning("[role=%s] model=%s exhausted retries (%s); falling back",
                            role, model, msg)
                break

    raise AllModelsFailed(
        f"role={role}: every model in chain {chain} failed. Last error: {last_err}"
    ) from last_err
