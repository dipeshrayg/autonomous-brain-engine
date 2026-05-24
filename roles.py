"""
roles.py — Project Evolution boardroom.

Personas (each opinionated, each free to disagree):

    CEO              visionary, high-risk; pushes new domains; rejects derivative
    CSO              Chief Science Officer; experimental edge-cases, novel algorithms,
                     physics simulations, deep-tech research
    VP Engineering   pragmatic anchor; ensures wild ideas are technically feasible
                     but never stifles the domain shift
    Judge            single metric: "is this predictable?" If yes, reject.
                     Synthesizes architect candidates after applying that test.
    Architect cands  multi-model conference proposing project plans in parallel
    Engineer         per-file implementation
    Reviewer A/B     parallel critique conference
    QA Tester        VISUAL + STATE-SYNC tester. Click nodes, verify
                     coordinate-math matches render, simulate user pathways.
    QA Fixer         repairs dead controls + state-sync bugs
    Fixer/Polisher   iterative repair + final UX polish

Note: the Security Officer role has been REMOVED in Project Evolution. The
system trades pre-publish security review for build-friction reduction and
domain expansion. Generated projects must still comply with platform TOS,
but enforcement now lives in the system prompts, not a dedicated gate.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from openai import OpenAI

log = logging.getLogger("brain.roles")


# ─────────────────────── Model registry ─────────────────────────────────

MODELS: dict[str, tuple[str, str]] = {
    "gpt-4o":      ("gpt-4o",      "premium"),
    "gpt-4o-mini": ("gpt-4o-mini", "fast"),
}


# ─────────────────────── Role → primary model ───────────────────────────

ROLE_PRIMARY: dict[str, str] = {
    # Executive layer
    "ceo":                   "gpt-4o",
    "cso":                   "gpt-4o",   # Chief Science Officer (experimental)
    "cto":                   "gpt-4o",   # Chief Technology Officer (self-improvement)
    "vp_eng":                "gpt-4o",   # pragmatic feasibility check

    # Plan stage
    "architect_judge":       "gpt-4o",   # the Judge — predictability filter
    "architect_candidate_a": "gpt-4o-mini",
    "architect_candidate_b": "gpt-4o-mini",

    # Build stages
    "engineer":              "gpt-4o",
    "reviewer_a":            "gpt-4o-mini",
    "reviewer_b":            "gpt-4o-mini",

    # QA — now visual + state-sync, not just console-watching
    "qa_tester":             "gpt-4o",
    "qa_fixer":              "gpt-4o",

    # Iteration helpers
    "fixer":                 "gpt-4o-mini",
    "polisher":              "gpt-4o-mini",
}


ROLE_FALLBACK: dict[str, list[str]] = {
    "ceo":                   ["gpt-4o-mini"],
    "cso":                   ["gpt-4o-mini"],
    "cto":                   ["gpt-4o-mini"],
    "vp_eng":                ["gpt-4o-mini"],
    "architect_judge":       ["gpt-4o-mini"],
    "architect_candidate_a": ["gpt-4o"],
    "architect_candidate_b": ["gpt-4o"],
    "engineer":              ["gpt-4o-mini"],
    "reviewer_a":            ["gpt-4o"],
    "reviewer_b":            ["gpt-4o"],
    "qa_tester":             ["gpt-4o-mini"],
    "qa_fixer":              ["gpt-4o-mini"],
    "fixer":                 ["gpt-4o"],
    "polisher":              ["gpt-4o"],
}


def model_for(role: str) -> str:
    key = ROLE_PRIMARY.get(role)
    if key is None:
        raise ValueError(f"Unknown role: {role}")
    return MODELS[key][0]


def chain_for(role: str) -> list[str]:
    primary = ROLE_PRIMARY[role]
    fb = ROLE_FALLBACK.get(role, [])
    return [MODELS[k][0] for k in [primary, *fb]]


# ─────────────────────── Resilient call ─────────────────────────────────

class AllModelsFailed(RuntimeError):
    pass


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
    validator: "callable | None" = None,
) -> tuple[str, dict[str, Any]]:
    """Walk the role's model chain until one returns a valid response."""
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
                            role, model, attempt, finish_reason, len(text), ve,
                        )
                        if finish_reason == "length":
                            break
                        if attempt < transient_attempts:
                            time.sleep(1)
                            continue
                        break

                meta: dict[str, Any] = {
                    "role": role, "model": model, "attempt": attempt,
                }
                if resp.usage:
                    meta["prompt_tokens"] = resp.usage.prompt_tokens
                    meta["completion_tokens"] = resp.usage.completion_tokens
                log.info("[role=%s] model=%s attempt=%d OK (in=%d out=%d)",
                         role, model, attempt,
                         meta.get("prompt_tokens", -1),
                         meta.get("completion_tokens", -1))
                return text, meta
            except Exception as e:
                last_err = e
                msg = str(e)[:240]
                rate_limited = "429" in msg or "rate" in msg.lower() or "quota" in msg.lower()
                if rate_limited:
                    log.warning("[role=%s] model=%s rate-limited; falling back. %s",
                                role, model, msg)
                    break
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
