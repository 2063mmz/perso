import os

import gradio as gr
from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI

from planner import create_evening_plan


SYSTEM_PROMPT = """
You are an after-work life planning agent.

The user may describe their arrival time, overtime, dinner preference,
shower preference, and activities in English or Chinese.

You must call create_evening_plan exactly once. Let the tool perform all time
calculations and never calculate schedule times yourself.

Defaults:
- Dinner at home
- Quick shower
- Preferred bedtime: 23:30
- Work departure time: 08:00

Outside dining must be within 1 km of home. One hour of overtime means
overtime_minutes=60. For activities outside the predefined list, use
custom_tasks in the exact format name|minutes|mandatory/daily/enjoyment.

Always present the final result in concise English. Include the evening
schedule, bedtime, wake-up time, sleep duration, morning schedule, and
warnings. Never alter calculated times or hide a constraint violation.
"""


def plan_evening(request: str) -> str:
    if not request.strip():
        return "Please describe your arrival time and evening activities."

    if not os.getenv("GOOGLE_API_KEY"):
        return "Configuration error: GOOGLE_API_KEY is missing."

    try:
        model = ChatGoogleGenerativeAI(
            model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"),
        )
        agent = create_agent(
            model=model,
            tools=[create_evening_plan],
            system_prompt=SYSTEM_PROMPT,
        )
        result = agent.invoke(
            {"messages": [{"role": "user", "content": request}]}
        )
        final_message = result["messages"][-1]
        return getattr(final_message, "text", None) or str(final_message.content)
    except Exception as error:
        return f"Planning failed: {type(error).__name__}: {error}"


demo = gr.Interface(
    fn=plan_evening,
    inputs=gr.Textbox(
        lines=6,
        label="Your evening requirements",
        placeholder=(
            "Example: I arrive home at 7 PM. I want to cook dinner, "
            "exercise for one hour, study, and take a quick shower."
        ),
    ),
    outputs=gr.Markdown(label="Generated plan"),
    title="After-Work Life Planning Agent",
    description=(
        "Describe your evening requirements. The agent will organize your "
        "activities and calculate your bedtime and wake-up time."
    ),
    examples=[
        [
            "I arrive home at 7 PM. I want to cook dinner, exercise for one "
            "hour, study for one hour, and take a quick shower."
        ],
        [
            "I arrive home at 8 PM because of overtime. I want to eat outside "
            "within 1 km of home, watch a TV series, and take a full shower."
        ],
        [
            "I arrive home at 6:30 PM. I need to buy groceries, cook dinner, "
            "do the laundry, and take a quick shower."
        ],
    ],
    flagging_mode="never",
)


if __name__ == "__main__":
    launch_kwargs = {}
    if os.getenv("RENDER"):
        launch_kwargs["server_name"] = "0.0.0.0"
    elif os.getenv("GRADIO_SERVER_NAME"):
        launch_kwargs["server_name"] = os.environ["GRADIO_SERVER_NAME"]

    port = os.getenv("PORT") or os.getenv("GRADIO_SERVER_PORT")
    if port:
        launch_kwargs["server_port"] = int(port)

    demo.launch(**launch_kwargs)
