"""Model-level callbacks: deterministic domain lock and anti-looping guard."""

from __future__ import annotations

import re
from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from ..config import LOOP_BREAK_MESSAGE, OFF_TOPIC_RESPONSE, REPEAT_LIMIT

# Strong, unambiguous off-topic / injection signals. Ambiguous words (e.g. "code",
# which may be a promo code) are intentionally excluded; the static prompt handles the
# semantic long tail. This is defense in depth, not the only line of defense.
_OFF_TOPIC = re.compile(
    r"\b(python|javascript|typescript|java|c\+\+|golang|rust code|sql query|regex|"
    r"write (me )?(a |some )?(code|script|program|function)|debug|"
    r"joke|riddle|poem|song lyrics|limerick|recipe|weather|forecast|horoscope|"
    r"how are you|tell me about yourself|meaning of life|"
    r"ignore (all |any |your )?(previous|prior|above) (instructions|rules)|"
    r"system prompt|jailbreak|developer mode|pretend (to be|you are))\b",
    re.IGNORECASE,
)


def _text_response(text: str) -> LlmResponse:
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))


def _latest_user_text(llm_request: LlmRequest) -> Optional[str]:
    """Return the newest human message text, or None if the last turn is a tool result."""
    for content in reversed(llm_request.contents or []):
        if content.role != "user":
            continue
        parts = content.parts or []
        if any(getattr(p, "function_response", None) for p in parts):
            return None
        return " ".join(p.text for p in parts if getattr(p, "text", None))
    return None


def before_model_callback(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> Optional[LlmResponse]:
    """Reject off-topic prompts with the exact required sentence, skipping the LLM call (saves tokens).

    Args:
        callback_context: ADK callback context.
        llm_request: The request about to be sent to the model.

    Returns:
        An LlmResponse containing the exact refusal string for off-topic input, else None.
    """
    text = _latest_user_text(llm_request)
    if text and _OFF_TOPIC.search(text):
        return _text_response(OFF_TOPIC_RESPONSE)
    return None


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", text.lower())).strip()


def after_model_callback(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> Optional[LlmResponse]:
    """Break repeated identical assistant messages with a polite troubleshooting message.

    Tracks consecutive identical text replies in session state. After REPEAT_LIMIT repeats
    (i.e. the third identical message), the reply is replaced.

    Args:
        callback_context: ADK callback context exposing session state.
        llm_response: The model's response.

    Returns:
        A replacement LlmResponse when a loop is detected, else None.
    """
    if getattr(llm_response, "partial", False) or not llm_response.content:
        return None
    parts = llm_response.content.parts or []
    if any(getattr(p, "function_call", None) for p in parts):
        return None
    norm = _normalize(" ".join(p.text for p in parts if getattr(p, "text", None)))
    if not norm:
        return None

    state = callback_context.state
    if norm == state.get("last_assistant_norm"):
        state["repeat_count"] = int(state.get("repeat_count", 0)) + 1
    else:
        state["repeat_count"] = 0
        state["last_assistant_norm"] = norm

    if state["repeat_count"] >= REPEAT_LIMIT:
        state["repeat_count"] = 0
        state["last_assistant_norm"] = _normalize(LOOP_BREAK_MESSAGE)
        return _text_response(LOOP_BREAK_MESSAGE)
    return None
