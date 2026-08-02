"""The LifeOps agent: a LangChain tool-calling agent backed by Gemini.

The model reads the user's message, decides which tools to call and writes the
narrative. Everything numeric — schedules, bedtime, sleep, scores — comes back
from the deterministic planner through the tools in `tools.py`.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import agent_trace
import planner
import tools

DEFAULT_MODEL = "gemini-3.5-flash-lite"
RECURSION_LIMIT = 24

SYSTEM_PROMPT = """\
You are LifeOps Agent, an evening planner for people in France and the rest of
Europe. You plan tonight around tomorrow. Always answer in English.

Follow this workflow:
1. Call parse_user_context once with everything you can extract from the
   message. Guess sensible defaults rather than asking questions.
2. Call load_saved_places when the user has saved places or mentions travel.
3. Call check_tomorrow_pressure to learn the required wake-up time.
4. Call get_weather_context when a location is known. If it is unavailable,
   carry on without weather.
5. Call estimate_travel_time only when the evening involves going somewhere.
   Feed the result into create_evening_plan as extra_travel_minutes.
6. Call estimate_task_priority when the evening looks too full.
7. Call create_evening_plan exactly once. It owns every exact time.
8. Call compare_alternative_plans once to get real numbers for the trade-offs.

Hard rules:
- Never invent or adjust a clock time, sleep duration or readiness score.
  Only use values returned by the tools, copied exactly.
- If the plan has warnings or violations, say so plainly. Do not hide that the
  user asked for more than the evening can hold.
- Keep the tone calm, concrete and practical. No emoji, no marketing language.

Finish your reply with a single fenced JSON block, and nothing after it:

```json
{
  "summary": "Two or three sentences on what tonight looks like and why.",
  "tradeoff_explanation": "What this plan gives up and what it protects, using the tool numbers.",
  "alternatives": [
    {"name": "Sleep-first plan", "summary": "One sentence with its bedtime and sleep total."},
    {"name": "Productivity plan", "summary": "One sentence with its bedtime and sleep total."}
  ],
  "coach_notes": ["Short, actionable notes. Optional."]
}
```
"""


class ConfigurationError(RuntimeError):
    """Raised when the deployment is missing the credentials the agent needs."""


def is_configured() -> bool:
    """True when the server itself holds a key, so visitors do not need one."""
    return bool(os.getenv("GOOGLE_API_KEY", "").strip())


def model_name() -> str:
    return os.getenv("GEMINI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def resolve_key(api_key: str | None) -> str:
    """Pick the key for this request: the visitor's own, else the server's.

    The visitor's key is used for this single call and never stored, logged or
    written into the agent trace.
    """
    visitor = (api_key or "").strip()
    if visitor:
        if len(visitor) < 20 or " " in visitor:
            raise ConfigurationError(
                "That does not look like a Gemini API key. Copy the whole key "
                "from https://aistudio.google.com/app/apikey."
            )
        return visitor

    server = os.getenv("GOOGLE_API_KEY", "").strip()
    if server:
        return server

    raise ConfigurationError(
        "No Gemini API key available. Paste your own free key in the API key "
        "field, or set GOOGLE_API_KEY on the server. Free keys: "
        "https://aistudio.google.com/app/apikey"
    )


def build_agent(api_key: str | None = None):
    """Create the LangChain agent. Raises ConfigurationError without a key."""
    key = resolve_key(api_key)

    from langchain.agents import create_agent
    from langchain_google_genai import ChatGoogleGenerativeAI

    model = ChatGoogleGenerativeAI(
        model=model_name(), temperature=0.3, google_api_key=key
    )
    return create_agent(model=model, tools=tools.AGENT_TOOLS, system_prompt=SYSTEM_PROMPT)


def run(
    message: str,
    energy_level: str = "medium",
    location: str | None = None,
    saved_places: dict[str, str] | None = None,
    api_key: str | None = None,
    recorder: agent_trace.TraceRecorder | None = None,
) -> dict[str, Any]:
    """Plan one evening and return the dashboard payload.

    `api_key` is the visitor's own Gemini key when they supplied one. It is
    used for this call only; the server keeps no copy.

    Never raises: configuration problems and model failures come back as a
    structured `error` in the response so the UI can show them in place.
    """
    recorder = recorder or agent_trace.TraceRecorder()
    agent_trace.start(recorder)
    recorder.remember("saved_places", saved_places or {})

    if not message or not message.strip():
        return _error_payload(
            recorder,
            "empty_request",
            "Describe your evening first — when you get home and what you need to do.",
        )

    try:
        agent = build_agent(api_key)
    except ConfigurationError as error:
        return _error_payload(recorder, "missing_api_key", str(error))

    prompt = _user_prompt(message, energy_level, location, saved_places)
    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": prompt}]},
            config={"recursion_limit": RECURSION_LIMIT},
        )
        reply = _final_text(result)
    except Exception as error:  # noqa: BLE001 - surfaced to the user
        return _error_payload(
            recorder, "agent_failed", _explain_failure(error, api_key)
        )

    narrative = _extract_json(reply)
    plan = recorder.data.get("plan") or _recover_plan(recorder)
    if plan is None:
        return _error_payload(
            recorder,
            "no_plan",
            "The agent replied without calling the planner tool. Try rephrasing "
            "your request with a clear arrival time.",
            assistant_text=reply,
        )

    alternatives = _alternatives(recorder, narrative)
    summary = narrative.get("summary") or _strip_json(reply) or _fallback_summary(plan)
    tradeoff = narrative.get("tradeoff_explanation") or _fallback_tradeoff(plan, alternatives)
    recorder.record("recommendation", "complete", summary)

    return {
        "status": "ok",
        "model": model_name(),
        "agent_trace": build_trace(recorder),
        "recommended_plan": _shape_plan(plan),
        "alternatives": alternatives,
        "tradeoff_explanation": tradeoff,
        "tomorrow_readiness_score": plan["tomorrow_readiness_score"],
        "summary": summary,
        "coach_notes": [str(note) for note in narrative.get("coach_notes") or []][:4],
        "context": recorder.data.get("context", {}),
        "weather": _tool_result(recorder, "get_weather_context"),
        "travel": _tool_result(recorder, "estimate_travel_time"),
    }


# --------------------------------------------------------------------------
# Prompt and reply plumbing
# --------------------------------------------------------------------------


def _user_prompt(
    message: str,
    energy_level: str,
    location: str | None,
    saved_places: dict[str, str] | None,
) -> str:
    lines = [message.strip(), "", "Form fields set in the app:"]
    lines.append(f"- energy level: {energy_level}")
    lines.append(f"- location: {location}" if location else "- location: not provided")
    if saved_places:
        places = ", ".join(f"{name}: {value}" for name, value in saved_places.items())
        lines.append(f"- saved places: {places}")
    else:
        lines.append("- saved places: none")
    return "\n".join(lines)


def _explain_failure(error: Exception, api_key: str | None) -> str:
    """Turn a provider exception into something a visitor can act on.

    The visitor's key is scrubbed in case the provider echoed it back.
    """
    detail = f"{type(error).__name__}: {error}"
    if api_key:
        detail = detail.replace(api_key.strip(), "***")

    lowered = detail.lower()
    if "api key" in lowered or "api_key" in lowered or "unauthenticated" in lowered:
        return (
            "That Gemini API key was rejected. Check you copied the whole key "
            f"from https://aistudio.google.com/app/apikey. ({detail})"
        )
    if "quota" in lowered or "429" in lowered or "resource_exhausted" in lowered:
        return (
            "The Gemini free-tier quota for this key is used up. Wait a minute "
            f"and try again, or use another key. ({detail})"
        )
    if "not found" in lowered and "model" in lowered:
        return (
            f"The model {model_name()!r} is not available for this key. Set "
            f"GEMINI_MODEL to a model your key can access. ({detail})"
        )
    return f"The agent could not finish ({detail})."


def _final_text(result: dict[str, Any]) -> str:
    messages = result.get("messages") or []
    if not messages:
        return ""
    last = messages[-1]
    text = getattr(last, "text", None)
    if callable(text):  # older LangChain exposes .text() as a method
        text = text()
    return str(text or getattr(last, "content", "") or "")


def _extract_json(reply: str) -> dict[str, Any]:
    """Pull the trailing ```json block out of the model's reply."""
    blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", reply, re.DOTALL)
    if not blocks:
        match = re.search(r"(\{[\s\S]*\})", reply)
        blocks = [match.group(1)] if match else []
    for block in reversed(blocks):
        try:
            parsed = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _strip_json(reply: str) -> str:
    """The model's prose without the trailing JSON block."""
    return re.sub(r"```(?:json)?\s*\{.*?\}\s*```", "", reply, flags=re.DOTALL).strip()


# --------------------------------------------------------------------------
# Response assembly
# --------------------------------------------------------------------------


def build_trace(recorder: agent_trace.TraceRecorder) -> list[dict[str, Any]]:
    """Show every planned step, including the ones the agent chose to skip."""
    recorded: dict[str, dict[str, Any]] = {}
    for entry in recorder.entries:
        recorded.setdefault(entry["tool"], entry)
    steps = []
    for tool_name in agent_trace.STEP_ORDER:
        entry = recorded.get(tool_name)
        if entry:
            steps.append(entry)
        else:
            steps.append(
                {
                    "step": agent_trace.STEP_LABELS[tool_name],
                    "tool": tool_name,
                    "status": "skipped",
                    "detail": "Not needed for this request.",
                    "arguments": {},
                    "result": {},
                    "elapsed_ms": 0,
                }
            )
    # Repeated calls (e.g. two travel legs) are appended after their step.
    extra = [
        entry
        for entry in recorder.entries
        if recorded.get(entry["tool"]) is not entry
    ]
    return steps + extra


def _shape_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "arrival_time": plan["arrival_time"],
        "evening_schedule": plan["evening_schedule"],
        "morning_schedule": plan["morning_schedule"],
        "bedtime": plan["bedtime"],
        "wake_time": plan["wake_time"],
        "sleep_duration": plan["sleep_duration"],
        "sleep_minutes": plan["sleep_minutes"],
        "target_sleep_minutes": plan["target_sleep_minutes"],
        "morning_carryover": plan["morning_carryover"],
        "dropped_optional": plan["dropped_optional"],
        "warnings": plan["warnings"],
        "violations": plan["violations"],
        "tomorrow": plan["tomorrow"],
        "totals": plan["totals"],
        "rules_applied": plan["rules_applied"],
        "status": plan["status"],
    }


def _alternatives(recorder: agent_trace.TraceRecorder, narrative: dict[str, Any]) -> list[dict[str, Any]]:
    """Merge the planner's computed alternatives with the model's wording."""
    computed = recorder.data.get("alternatives")
    if not computed:
        kwargs = recorder.data.get("plan_kwargs")
        computed = planner.compare_plans(kwargs) if kwargs else []

    summaries = {}
    for item in narrative.get("alternatives") or []:
        if isinstance(item, dict) and item.get("name"):
            summaries[str(item["name"]).strip().lower()] = str(item.get("summary", ""))

    merged = []
    for item in computed:
        summary = summaries.get(item["name"].lower()) or (
            f"Bed at {item['bedtime']}, up at {item['wake_time']}, "
            f"{item['sleep_duration']} of sleep, readiness {item['tomorrow_readiness_score']}/100."
        )
        merged.append({**item, "summary": summary})
    return merged


def _tool_result(recorder: agent_trace.TraceRecorder, tool_name: str) -> dict[str, Any] | None:
    for entry in recorder.entries:
        if entry["tool"] == tool_name:
            return entry["result"]
    return None


def _recover_plan(recorder: agent_trace.TraceRecorder) -> dict[str, Any] | None:
    """Safety net: build a plan from the parsed context if the model skipped the tool."""
    context = recorder.data.get("context")
    if not context:
        return None
    plan = planner.create_evening_plan(
        arrival_time=context["arrival_time"],
        mandatory_tasks=context["mandatory_tasks"],
        optional_tasks=context["optional_tasks"],
        energy_level=context["energy_level"],
        preferred_bedtime=context["preferred_bedtime"],
        target_sleep_minutes=context["target_sleep_minutes"],
        tomorrow_first_event=context["tomorrow_first_event"],
        tomorrow_event_importance=context["tomorrow_event_importance"],
        commute_minutes=context["commute_minutes"],
    )
    if plan.get("status") == "error":
        return None
    recorder.remember("plan", plan)
    recorder.record(
        "create_evening_plan",
        "complete",
        f"Planner run directly as a fallback — bed {plan['bedtime']}, "
        f"{plan['sleep_duration']} of sleep.",
        plan,
    )
    return plan


def _fallback_summary(plan: dict[str, Any]) -> str:
    return (
        f"You get home at {plan['arrival_time']}, finish the evening by {plan['bedtime']} "
        f"and wake at {plan['wake_time']} for {plan['sleep_duration']} of sleep."
    )


def _fallback_tradeoff(plan: dict[str, Any], alternatives: list[dict[str, Any]]) -> str:
    parts = [
        f"This plan protects {plan['sleep_duration']} of sleep against a target of "
        f"{planner.format_duration(plan['target_sleep_minutes'])}."
    ]
    if plan["dropped_optional"]:
        parts.append("Left out tonight: " + ", ".join(plan["dropped_optional"]) + ".")
    if plan["morning_carryover"]:
        parts.append("Moved to the morning: " + ", ".join(plan["morning_carryover"]) + ".")
    for item in alternatives:
        if item["mode"] != "balanced":
            parts.append(f"{item['name']}: bed {item['bedtime']}, {item['sleep_duration']}.")
    return " ".join(parts)


def _error_payload(
    recorder: agent_trace.TraceRecorder,
    code: str,
    message: str,
    assistant_text: str = "",
) -> dict[str, Any]:
    recorder.record("recommendation", "failed", message)
    return {
        "status": "error",
        "model": model_name(),
        "error": {"code": code, "message": message},
        "agent_trace": build_trace(recorder),
        "recommended_plan": None,
        "alternatives": [],
        "tradeoff_explanation": "",
        "tomorrow_readiness_score": None,
        "summary": assistant_text or message,
        "coach_notes": [],
        "context": recorder.data.get("context", {}),
        "weather": None,
        "travel": None,
    }
