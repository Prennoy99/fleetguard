"""Gemini client setup with retry-with-backoff for transient failures.
google-genai==2.18.1 — imported as `from google import genai`, not the older
`google-generativeai` package. This version is required for Gemini 3's
thought_signature field in multi-turn function-calling responses; older SDK
versions don't have it and multi-turn tool-calling fails without it.

This project drives Gemini's function-calling (see tool_specs.py,
orchestrator.py), so this module's generate_content() always passes tools +
a fixed temperature=0 for reproducible eval runs and consistent diagnoses
for the same input.

The free tier's per-minute quota (15 req/min for gemini-3.1-flash-lite at the
time of writing) is easy to hit during the M4 eval harness, which drives
several Gemini calls per scenario across 18 scenarios. Gemini's 429 response
includes a RetryInfo.retryDelay telling us exactly how long the quota window
needs — that's honored when present instead of guessing with pure exponential
backoff, which was previously too short (~14s total) against a 51s quota
reset and just failed the run.
"""
import os
import time

from google import genai
from google.genai import types
from google.genai.errors import APIError

TEMPERATURE = 0
MAX_RETRIES = 5
BASE_BACKOFF_SECONDS = 2
MAX_BACKOFF_SECONDS = 65
RETRYABLE_STATUS_CODES = {429, 500, 503}


def _retry_delay_seconds(error: APIError, attempt: int) -> float:
    """Prefer the server's own RetryInfo.retryDelay (present on 429 quota
    errors) over guessing; fall back to capped exponential backoff.
    """
    try:
        for detail in error.details.get("error", {}).get("details", []):
            if detail.get("@type", "").endswith("RetryInfo"):
                raw = detail.get("retryDelay", "")
                if raw.endswith("s"):
                    return float(raw[:-1]) + 1  # small margin over the exact reset
    except (AttributeError, TypeError, ValueError):
        pass
    return min(BASE_BACKOFF_SECONDS * (2 ** attempt), MAX_BACKOFF_SECONDS)


def _client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set — copy .env.example to .env and fill it in.")
    return genai.Client(api_key=api_key)


def _model_name() -> str:
    return os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")


def generate_content(
    contents: list[types.Content],
    tools: list[types.Tool],
    system_instruction: str,
) -> types.GenerateContentResponse:
    """One Gemini call with tools declared, temperature=0, and retry-with-
    backoff on rate-limit/server errors."""
    client = _client()
    config = types.GenerateContentConfig(
        temperature=TEMPERATURE,
        tools=tools,
        system_instruction=system_instruction,
    )
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            return client.models.generate_content(
                model=_model_name(), contents=contents, config=config,
            )
        except APIError as e:
            if e.code not in RETRYABLE_STATUS_CODES or attempt == MAX_RETRIES - 1:
                raise
            last_error = e
            time.sleep(_retry_delay_seconds(e, attempt))
    raise last_error
