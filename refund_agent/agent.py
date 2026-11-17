"""LlmAgent definition: generation config and callback wiring."""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.planners import BuiltInPlanner
from google.genai import types

from .config import AGENT_NAME, MAX_OUTPUT_TOKENS, MODEL_NAME, TEMPERATURE
from .guardrails.agent_callbacks import after_agent_callback, before_agent_callback
from .guardrails.model_callbacks import after_model_callback, before_model_callback
from .guardrails.tool_callbacks import after_tool_callback, before_tool_callback
from .prompts import INSTRUCTION
from .tools import ALL_TOOLS

root_agent = LlmAgent(
    name=AGENT_NAME,
    model=MODEL_NAME,
    description="Autonomous e-commerce refund orchestrator: deterministic tools, human-in-the-loop gates.",
    instruction=INSTRUCTION,  # 100% static => maximizes prompt-cache hits
    tools=ALL_TOOLS,
    generate_content_config=types.GenerateContentConfig(
        temperature=TEMPERATURE,
        max_output_tokens=MAX_OUTPUT_TOKENS,
    ),
    # Thinking tokens count against max_output_tokens on Gemini 2.5; disable so the
    # 300-token cap is spent on the visible reply. (ADK requires thinking via the planner.)
    planner=BuiltInPlanner(thinking_config=types.ThinkingConfig(thinking_budget=0)),
    before_agent_callback=before_agent_callback,
    after_agent_callback=after_agent_callback,
    before_model_callback=before_model_callback,
    after_model_callback=after_model_callback,
    before_tool_callback=before_tool_callback,
    after_tool_callback=after_tool_callback,
)
