# LifeOps Agent

> **Plan tonight around tomorrow.**

An AI agent that turns one sentence —

> *"I get home at 20:15. I need to cook, do laundry and review tomorrow's
> presentation. I have a 9 AM client meeting so I want to sleep early."*

— into a constraint-checked evening timeline, a bedtime, a wake-up time, a
tomorrow-readiness score, and an honest list of what will **not** fit.

It is a real **LangChain tool-calling agent** running on **Google Gemini**, with
a **FastAPI** backend and a custom dashboard. The middle panel of the UI shows
every tool call the agent made, with its inputs and outputs, so you can watch
the agent work instead of taking its word for it.

---

## Table of contents

1. [The idea](#1-the-idea)
2. [How people use it](#2-how-people-use-it)
3. [Features](#3-features)
4. [Architecture](#4-architecture)
5. [Every file, explained](#5-every-file-explained)
6. [The LangChain agent](#6-the-langchain-agent)
7. [The eight tools](#7-the-eight-tools)
8. [The deterministic planner](#8-the-deterministic-planner)
9. [API reference](#9-api-reference)
10. [API keys and security](#10-api-keys-and-security)
11. [Run it locally](#11-run-it-locally)
12. [Deploy it publicly](#12-deploy-it-publicly)
13. [Tests and verification](#13-tests-and-verification)
14. [Free-service policy and limits](#14-free-service-policy-and-limits)

---

## 1. The idea

Most evening planners are calculators: you type durations into boxes and they
add them up. That fails on the part that actually hurts — **the evening is only
as free as tomorrow morning allows**. A 9 AM client meeting across town is what
decides whether tonight's episode happens, not the number of minutes left.

So LifeOps Agent plans **backwards from tomorrow**:

```
tomorrow's first event  →  minus commute  →  minus getting ready  →  wake-up time
wake-up time  →  minus the sleep you need  →  the latest bedtime that still works
that bedtime  →  the real budget for tonight
```

Then it fits tonight's tasks into that budget, drops what does not fit, moves
what can wait to the morning, and explains the trade-off.

**The division of labour is the point of the project:**

| | Who does it | Why |
| --- | --- | --- |
| Understanding messy human input | **Gemini** (LLM) | "8 PM", "sleep early", "client meeting" need language understanding |
| Deciding which tools to call | **LangChain agent** | Weather only matters sometimes; travel only when you go somewhere |
| Every exact time and number | **`planner.py`** (plain Python) | An LLM that invents "23:15" is a bug, not a feature |
| Explaining the trade-off | **Gemini** | Using only the numbers the tools returned |

The LLM never computes a schedule. It picks tools, fills in arguments, and
writes prose around results it is forbidden to alter. That is what makes the
agent trustworthy, and it is what the Agent Trace panel demonstrates.

---

## 2. How people use it

Open the public URL. That is the whole onboarding.

**Bring your own key.** The deployed site does not spend the owner's Gemini
quota on visitors. Each visitor pastes their own free Gemini API key into the
key field in the left panel:

1. Get a free key at <https://aistudio.google.com/app/apikey> (no credit card).
2. Paste it into **Gemini API key**.
3. Describe the evening, or click one of the example prompts.
4. Press **Plan my evening**.

The key is kept in that visitor's own browser (`localStorage`) and sent to the
backend only to run their own request. The server never stores it, never logs
it, and never writes it into a response. See
[API keys and security](#10-api-keys-and-security).

If the owner *does* set `GOOGLE_API_KEY` on the server, the key field becomes
optional and visitors can use the site with no setup at all — useful for a demo
day, at the cost of the owner's free quota.

---

## 3. Features

**Input**
- Free-text description of the evening — no forms to fill in.
- Four one-click example prompts for the common shapes of evening.
- Energy selector (low / medium / high) that genuinely changes the plan.
- Optional location for weather and travel (built for France / Europe).
- Saved places manager (home, work, gym…) stored in `localStorage`, no database.
- Everything the visitor types is remembered locally between visits.

**Agent**
- Real LangChain tool-calling loop with eight tools.
- Live agent trace over Server-Sent Events: each card appears the moment the
  tool actually runs.
- Every trace card expands to show the exact **tool input** and **tool output**
  JSON.
- Steps the agent chose *not* to run are shown too, marked *skipped*, so the
  full workflow is visible.
- Degrades gracefully: if weather or travel lookups fail, the plan is still
  produced without them, and the trace says so.
- If the model ever replies without calling the planner, the backend runs the
  planner itself rather than returning nothing.

**Plan**
- Evening timeline and tomorrow-morning timeline, block by block.
- Bedtime, wake-up time, sleep duration against your target.
- Tomorrow-readiness score (0–100) with a colour-banded ring.
- Morning carryover: what got pushed to tomorrow and how much earlier the alarm
  has to ring for it.
- Warnings (too much asked, sleep debt, dropped activities) and hard constraint
  violations, kept separate.
- Weather and travel context as inline notes.
- Trade-off explanation written by the model from planner numbers.
- Three alternatives — **sleep-first**, **balanced**, **productivity** — each a
  real planner run with real times, not prose.
- "Planner rules applied" disclosure so the logic is auditable.

**Interface**
- Three-panel dashboard: command → agent trace → plan. The usable app is the
  first screen; there is no marketing page in front of it.
- Responsive down to phone width; the panels stack and the plan scrolls into
  view when it is ready.
- Light and dark themes follow the OS setting.
- No build step, no framework, no external fonts or CDNs — three static files.
- Keyboard: ⌘/Ctrl + Enter submits.

---

## 4. Architecture

```
┌─ Browser ──────────────────┐        ┌─ FastAPI backend ─────────────────┐
│  frontend/index.html       │        │  app.py                           │
│  frontend/app.js           │──POST─►│    /api/plan          (JSON)      │
│  frontend/style.css        │  SSE   │    /api/plan/stream   (SSE)       │
│                            │◄───────│    /api/health                    │
│  localStorage:             │        │            │                      │
│   · saved places           │        │            ▼                      │
│   · visitor's API key      │        │  agent.py    LangChain + Gemini   │
│   · last prompt & prefs    │        │      │                            │
└────────────────────────────┘        │      ├─► tools.py   8 tools       │
                                      │      │      ├─► planner.py        │
                                      │      │      └─► Open-Meteo (free) │
                                      │      └─► agent_trace.py  recorder │
                                      └───────────────────────────────────┘
```

**Lifecycle of one request**

1. `app.js` POSTs `{message, energy_level, location, saved_places, api_key}` to
   `/api/plan/stream`.
2. `app.py` creates a `TraceRecorder` and runs `agent.run(...)` in a worker
   thread so the event loop can stream while the agent thinks.
3. `agent.py` builds the LangChain agent with the resolved key and invokes it.
4. Gemini calls tools. Every tool in `tools.py` pushes a trace entry onto the
   recorder's queue the moment it finishes.
5. `app.py` drains that queue and emits each entry as an SSE `trace` event, so
   cards light up live in the browser.
6. When the agent finishes, `agent.py` assembles the payload: **times come from
   the recorded planner result**, prose comes from the model's JSON block.
7. `app.py` emits `result` then `done`; `app.js` renders the dashboard.

If SSE is unavailable (proxy, old browser), `app.js` silently retries against
the plain `/api/plan` endpoint and renders the same payload.

---

## 5. Every file, explained

```
app.py            FastAPI application — endpoints, SSE plumbing, static files
agent.py          The LangChain agent: prompt, key resolution, response assembly
tools.py          The eight agent tools + Open-Meteo integrations
planner.py        Deterministic scheduler — the only source of exact times
agent_trace.py    Per-request recorder that makes the agent's work visible
frontend/
  index.html      Dashboard markup + inline SVG icon sprite
  app.js          State, localStorage, SSE client, all rendering
  style.css       Design system: palette, panels, timeline, dark mode
tests/
  test_planner.py Scheduling, pressure, after-midnight, carryover, scoring
  test_tools.py   Tool behaviour, weather/travel stubs, trace recording
  test_api.py     Endpoints, streaming, BYO key, every error path
render.yaml       Render blueprint — deploys with no manual configuration
Procfile          Start command for Railway / Fly.io / Heroku
requirements.txt  Five dependencies
env.example       Template for local .env
```

### `app.py` — the web layer

Defines `PlanRequest` (the request body), three endpoints, and mounts
`frontend/` as static files so one process serves both API and UI.

The streaming endpoint is the interesting part. The LangChain agent is
synchronous, so it runs in a thread while the async generator drains the
recorder's thread-safe queue:

```python
task = asyncio.create_task(asyncio.to_thread(agent.run, ..., recorder=recorder))
while True:
    for event in _drain(recorder.events):
        yield _sse(event)          # a tool call, the instant it happened
    if task.done():
        break
    await asyncio.sleep(POLL_SECONDS)
yield _sse({"type": "result", "payload": task.result()})
```

`api_key` is declared with `exclude=True` so the visitor's key can never be
serialised back out of the model by accident.

### `agent.py` — the agent layer

Holds the system prompt, builds the LangChain agent, and assembles the response.
Key responsibilities:

- `resolve_key(api_key)` — visitor's key first, server's key second, otherwise a
  clear `ConfigurationError`.
- `build_agent(api_key)` — creates `ChatGoogleGenerativeAI` + `create_agent`.
- `run(...)` — never raises. Every failure becomes a structured `error` object
  so the dashboard can render it in place.
- `_extract_json(reply)` — pulls the model's trailing ```json block; if the model
  forgets it, deterministic fallbacks generate the summary and trade-off text
  from planner numbers.
- `_recover_plan(recorder)` — if the model somehow skipped `create_evening_plan`,
  the planner is run directly from the parsed context.
- `_explain_failure(error, api_key)` — turns provider errors into advice
  ("that key was rejected", "free-tier quota used up"), scrubbing the key from
  the message first.
- `build_trace(recorder)` — merges the recorded calls with placeholders for the
  steps the agent skipped, so the UI always shows the full nine-step workflow.

### `tools.py` — the tool layer

Eight `@tool`-decorated functions. Each one is ordinary deterministic Python,
records its call into the trace, and returns JSON-serialisable data. Also
contains the free geo/weather helpers: `geocode()`, `haversine_km()`,
`travel_minutes()`, and the WMO weather-code table.

### `planner.py` — the deterministic core

No LLM, no network, no state. Pure functions:

| Function | Purpose |
| --- | --- |
| `parse_time` | `"8 PM"`, `"20h15"`, `"8:30pm"`, `"20:15"` → minutes |
| `format_time` / `format_duration` | minutes → `"23:15"` / `"7h 45min"` |
| `normalize_tasks` | `["cook dinner", "laundry\|10"]` → structured tasks with durations |
| `estimate_task_minutes` | keyword library: dinner 45, shower 15, laundry 10… |
| `assess_tomorrow_pressure` | wake-up time, latest healthy bedtime, pressure level |
| `estimate_task_priority` | scores tasks so the agent knows what to drop first |
| `create_evening_plan` | **the scheduler** — every exact time in the product |
| `compare_plans` | runs the scheduler in all three modes for the alternatives |

### `agent_trace.py` — visibility

A `TraceRecorder` per request, held in a `ContextVar` so tools can reach it
without threading it through every signature. It keeps an ordered list of
entries (for the final response) *and* a `queue.Queue` (for live streaming),
plus a small `data` dict the tools use to hand results to each other — that is
how `compare_alternative_plans` reuses the exact arguments the planner ran with.

---

## 6. The LangChain agent

The agent is created with LangChain's `create_agent`, which builds a
tool-calling loop: the model receives the tool schemas, emits tool calls,
LangChain executes them, feeds the results back, and repeats until the model
answers in prose.

```python
# agent.py
from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI

model = ChatGoogleGenerativeAI(model=model_name(), temperature=0.3, google_api_key=key)
return create_agent(model=model, tools=tools.AGENT_TOOLS, system_prompt=SYSTEM_PROMPT)
```

Tools are declared with the `@tool` decorator and `parse_docstring=True`, so the
Google-style docstring becomes the JSON schema Gemini sees — the description,
every argument and its meaning:

```python
# tools.py
@tool(parse_docstring=True)
def check_tomorrow_pressure(
    first_event_time: str | None = None,
    event_importance: str = "medium",
    commute_minutes: int = 30,
    morning_prep_minutes: int = 45,
    target_sleep_hours: float = 8.0,
) -> dict[str, Any]:
    """Compute how hard tomorrow morning constrains tonight.

    Returns the required wake-up time, the latest bedtime that still delivers
    the sleep target, and a pressure level. Use these numbers when you explain
    the trade-offs; do not compute them yourself.

    Args:
        first_event_time: Tomorrow's first fixed commitment, e.g. "09:00".
        event_importance: "low", "medium" or "high".
        ...
    """
```

The system prompt fixes the workflow and the hard rules:

```
1. Call parse_user_context once …
3. Call check_tomorrow_pressure to learn the required wake-up time.
7. Call create_evening_plan exactly once. It owns every exact time.
8. Call compare_alternative_plans once to get real numbers for the trade-offs.

Hard rules:
- Never invent or adjust a clock time, sleep duration or readiness score.
  Only use values returned by the tools, copied exactly.
- If the plan has warnings or violations, say so plainly.
```

The model ends its reply with a JSON block containing `summary`,
`tradeoff_explanation`, `alternatives[].summary` and `coach_notes`. The backend
merges that prose onto planner-computed numbers — the model's wording is used,
the model's arithmetic is not.

---

## 7. The eight tools

| # | Tool | What it does | Backed by |
| --- | --- | --- | --- |
| 1 | `parse_user_context` | Normalises `"8 PM"` → `20:00`, assigns durations to tasks, applies defaults, flags anything it had to guess | `planner.py` |
| 2 | `load_saved_places` | Reads the visitor's saved places (home / work / gym) sent with the request | request body |
| 3 | `check_tomorrow_pressure` | Required wake-up time, departure time, latest healthy bedtime, pressure level (low/medium/high) | `planner.py` |
| 4 | `estimate_task_priority` | Scores every task 0–100 with reasons, and names the two to drop first | `planner.py` |
| 5 | `get_weather_context` | This evening's and tomorrow morning's temperature, rain probability and conditions, plus plain-language advice | Open-Meteo, no key |
| 6 | `estimate_travel_time` | Door-to-door estimate from geocoded coordinates, great-circle distance × route factor ÷ average speed per mode | Open-Meteo geocoding |
| 7 | `create_evening_plan` | **Owns every exact time**: both timelines, bedtime, wake time, sleep, warnings, violations, readiness score | `planner.py` |
| 8 | `compare_alternative_plans` | Re-runs the planner in sleep-first and productivity modes so trade-offs quote real times | `planner.py` |

**Failure behaviour.** Tools 5 and 6 are the only ones that touch the network.
If geocoding finds nothing, or Open-Meteo times out, they return
`{"available": false, ...}` or a low-confidence default instead of raising. The
trace card turns amber and says why, and the plan is still produced. This is
covered by tests.

**Travel model.** Straight-line distance × 1.3 (route factor) ÷ average
door-to-door city speed, plus fixed overhead: walk 4.8 km/h, bike 15 km/h +3 min,
transit 24 km/h +6 min, drive 22 km/h +6 min. It is labelled an estimate in the
UI, with `low` or `medium` confidence. No paid routing API, no billing account.

---

## 8. The deterministic planner

### Inputs

`arrival_time`, `mandatory_tasks`, `optional_tasks`, `energy_level`,
`preferred_bedtime`, `target_sleep_minutes`, `tomorrow_first_event`,
`tomorrow_event_importance`, `commute_minutes`, `morning_prep_minutes`,
`wind_down_minutes`, `extra_travel_minutes`, `latest_bedtime`, `mode`.

Tasks are strings — `"cook dinner"` or `"cook dinner|45"`. Without an explicit
duration, a keyword library supplies one.

### Rules

- Tomorrow's first event fixes the wake-up time; the evening is planned
  backwards from it.
- Mandatory tasks are scheduled first, ordered so unattended chores start early
  (laundry) and wind-down tasks end late (shower). They may push bedtime later,
  but never past the hard limit.
- Optional activities are kept only while they fit both the bedtime target and
  the energy budget (low 30 min, medium 90 min, high 150 min).
- Low energy also adds a 20-minute decompression block on arrival and 30 minutes
  to the sleep target. High energy removes the decompression block.
- Tasks that do not fit tonight move to tomorrow morning — the alarm moves
  earlier to pay for them — but only while sleep stays above 5 hours and the
  alarm stays after 05:30. Anything left over becomes a **violation**, not a
  silent omission.
- Bedtime never passes 01:30. Arrivals after midnight are planned on the next
  day's clock rather than wrapping around.
- If the evening ends early, free time fills the gap up to the normal bedtime —
  except in sleep-first mode, which goes to bed immediately.

### Modes

| Mode | Behaviour | Use |
| --- | --- | --- |
| `balanced` | Default. Respects the energy budget and the healthy bedtime. | The recommendation |
| `sleep_first` | Drops every optional activity, goes to bed as soon as the must-dos are done. | Alternative |
| `productivity` | Keeps everything, uses the night up to the hard limit. | Alternative |

All three are scored against the **same** sleep target, so the readiness numbers
are comparable.

### Readiness score

```
start at 100
− up to 45   for sleep debt against the target (a 2-hour deficit costs the full 45)
− 12         per constraint violation (max 30)
− 5          per warning (max 15)
− 10         if tomorrow is high-pressure and sleep is short
+ 5          if there are no warnings and the sleep target is met
clamped to 0–100
```

### Output

`status`, both schedules, `bedtime`, `wake_time`, `sleep_duration`,
`sleep_minutes`, `target_sleep_minutes`, `tomorrow` (the pressure block),
`morning_carryover`, `dropped_optional`, `unscheduled`, `warnings`,
`violations`, `tomorrow_readiness_score`, `totals`, `rules_applied`.

---

## 9. API reference

### `POST /api/plan`

```json
{
  "message": "I arrive home at 20:15. I need to cook, do laundry, review tomorrow's presentation, and sleep early because I have a 9 AM client meeting.",
  "energy_level": "low",
  "location": "Paris, France",
  "saved_places": { "home": "Paris 11e", "work": "La Defense", "gym": "Near Republique" },
  "api_key": "AIza…"
}
```

`energy_level`, `location`, `saved_places` and `api_key` are all optional.

Response (abridged):

```json
{
  "status": "ok",
  "model": "gemini-3.5-flash-lite",
  "agent_trace": [
    {
      "step": "Understanding request",
      "tool": "parse_user_context",
      "status": "complete",
      "detail": "Home at 20:15, 4 must-do and 2 optional items, low energy.",
      "arguments": { "…": "…" },
      "result": { "…": "…" },
      "elapsed_ms": 812
    }
  ],
  "recommended_plan": {
    "arrival_time": "20:15",
    "evening_schedule": [
      { "start": "20:15", "end": "20:35", "task": "Decompress after work", "type": "buffer", "minutes": 20 }
    ],
    "morning_schedule": [
      { "start": "07:40", "end": "08:25", "task": "Get ready and leave", "type": "routine", "minutes": 45 }
    ],
    "bedtime": "23:00",
    "wake_time": "07:40",
    "sleep_duration": "8h 40min",
    "morning_carryover": [],
    "dropped_optional": ["watch one episode"],
    "warnings": ["Held back to protect a low-energy evening: watch one episode."],
    "violations": [],
    "tomorrow": { "pressure_level": "medium", "required_wake_time": "07:40", "latest_healthy_bedtime": "23:40" },
    "rules_applied": ["…"]
  },
  "alternatives": [
    { "name": "Sleep-first plan", "mode": "sleep_first", "bedtime": "22:50", "sleep_duration": "8h 50min", "tomorrow_readiness_score": 95, "summary": "…" },
    { "name": "Balanced plan", "mode": "balanced", "bedtime": "23:00", "…": "…" },
    { "name": "Productivity plan", "mode": "productivity", "bedtime": "23:50", "…": "…" }
  ],
  "tradeoff_explanation": "…",
  "tomorrow_readiness_score": 90,
  "summary": "…",
  "coach_notes": ["Start the laundry before you cook so it finishes while you eat."],
  "weather": { "available": true, "…": "…" },
  "travel": { "minutes": 42, "mode": "transit", "confidence": "medium" }
}
```

`agent_trace` always contains all nine steps. Steps the agent chose not to run
come back with `"status": "skipped"`. Tool statuses are `complete`, `skipped`,
`unavailable` or `failed`.

### `POST /api/plan/stream`

Same body, `text/event-stream` response:

```
data: {"type": "start"}
data: {"type": "trace",  "entry": { … }}      ← one per tool call, live
data: {"type": "result", "payload": { … }}    ← the full /api/plan payload
data: {"type": "done"}
```

### `GET /api/health`

```json
{ "status": "ok", "llm_configured": false, "byo_key_required": true, "model": "gemini-3.5-flash-lite" }
```

The dashboard uses `byo_key_required` to decide whether the key field is
required or optional.

### Errors

Errors return **HTTP 200** with a structured body, so the dashboard renders them
in place instead of showing a blank failure:

```json
{
  "status": "error",
  "error": { "code": "missing_api_key", "message": "No Gemini API key available. Paste your own free key…" },
  "recommended_plan": null,
  "alternatives": [],
  "agent_trace": [ … ]
}
```

| Code | Meaning |
| --- | --- |
| `missing_api_key` | No visitor key and no server key, or the key is malformed |
| `empty_request` | The message was blank |
| `agent_failed` | The model call failed — rejected key, quota, unknown model, network |
| `no_plan` | The model answered without a usable plan and recovery failed |

---

## 10. API keys and security

**Where a key can come from**, in priority order:

1. `api_key` in the request body — the visitor's own key, used for that one
   request.
2. `GOOGLE_API_KEY` in the server environment — the owner's key, used when a
   visitor supplies none.
3. Neither → `missing_api_key`, with instructions.

**What the server does with a visitor's key**

- Uses it to construct `ChatGoogleGenerativeAI` for that request, then drops it.
- Never writes it to disk, a database, or a log.
- Never puts it in the agent trace (only tool arguments are recorded, and the
  key is not a tool argument).
- Excludes it from the response model (`exclude=True`).
- Scrubs it from provider error messages before they reach the browser, in case
  the provider echoed it back.

**What the browser does**

- Stores the key in `localStorage` under `lifeops.apikey` so visitors do not
  retype it. The field is `type="password"` and there is a one-click **forget**
  button.
- Sends it in the POST body over HTTPS — never in a URL or query string, where
  it would land in server logs and browser history.

**What you must never do**

- Do not commit a real key. `.gitignore` already excludes `.env`.
- Do not put the key in `frontend/app.js` or any file served to the browser.
- Set `GOOGLE_API_KEY` through your host's environment-variable UI only.

Anyone self-hosting should treat a server-side key as a spending decision:
every visitor then shares that quota.

---

## 11. Run it locally

```bash
pip install -r requirements.txt
```

```bash
python app.py
```

Open <http://localhost:8000> and paste a Gemini key into the key field.

To let the server hold the key instead, so the field is optional:

```bash
GOOGLE_API_KEY="your-key" python app.py
```

Or put it in a `.env` file next to `app.py` — the app reads it on startup, and
`.gitignore` keeps it out of git:

```bash
cp env.example .env
```

Then edit `.env` and set your key. Real environment variables always override
the file, so hosted deployments are unaffected.

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `GOOGLE_API_KEY` | no | — | Server-side key. Without it, visitors supply their own. |
| `GEMINI_MODEL` | no | `gemini-3.5-flash-lite` | Any Gemini model the key can access |
| `PORT` | no | `8000` | Set automatically by most hosts |
| `HOST` | no | `0.0.0.0` | Bind address |
| `ALLOWED_ORIGINS` | no | `*` | Comma-separated origins allowed to call `/api/*` |
| `DEV_RELOAD` | no | — | Any value enables uvicorn auto-reload |

---

## 12. Deploy it publicly

### Step 1 — push to GitHub

```bash
git init
```

```bash
git add . && git commit -m "LifeOps Agent"
```

```bash
git branch -M main
```

```bash
git remote add origin https://github.com/<your-username>/lifeops-agent.git
```

```bash
git push -u origin main
```

Check that `.env` is **not** in the commit — `.gitignore` covers it, but verify
with `git status` before pushing.

### Step 2 — deploy on Render (recommended)

The repository ships `render.yaml`, so Render configures itself.

1. Sign in at <https://render.com> with GitHub.
2. **New → Web Service**, pick the repository.
3. Render reads `render.yaml`. To configure manually instead:
   - Runtime **Python 3**
   - Build command `pip install -r requirements.txt`
   - Start command `uvicorn app:app --host 0.0.0.0 --port $PORT`
   - Health check path `/api/health`
4. **Optional** — if you want visitors to skip the key field, add
   `GOOGLE_API_KEY` under **Environment**. Leave it out for bring-your-own-key.
5. **Create Web Service.** First build takes a few minutes.

Your public URL is `https://<service-name>.onrender.com`. Share that link.

> The free instance sleeps after 15 minutes idle, so the first request after a
> pause takes ~30 seconds to wake. Everything after that is fast.

### Step 3 — check it

```bash
curl -s https://<your-app>.onrender.com/api/health
```

Expect `{"status":"ok","llm_configured":false,"byo_key_required":true,...}`.
Then open the URL, paste a key, and plan an evening.

### Railway, Fly.io, Heroku

The included `Procfile` is all they need:

```
web: uvicorn app:app --host 0.0.0.0 --port $PORT
```

Connect the repository, add `GOOGLE_API_KEY` if you want one, deploy.

### A note on Vercel

Vercel can run FastAPI via `@vercel/python`, but this project is a poor fit:
LangChain + Gemini sits close to the 250 MB serverless bundle limit, and
`/api/plan/stream` needs a long-lived process. Use Render or Railway. If you
must use Vercel, host `frontend/` there as a static site and point it at a
backend elsewhere using `ALLOWED_ORIGINS`.

---

## 13. Tests and verification

62 tests. No network access, no API key, no LLM call — the model is replaced by
a stand-in that drives the real tools, so the whole request path is exercised.

```bash
python -m unittest discover
```

| File | Covers |
| --- | --- |
| `tests/test_planner.py` | Time parsing, task ordering, energy profiles, bedtime limits, **tomorrow schedule pressure**, **after-midnight planning**, morning carryover, impossible nights, readiness scoring, the three modes |
| `tests/test_tools.py` | Context normalisation, saved places, weather parsing and graceful degradation, travel estimates and fallbacks, trace recording and truncation |
| `tests/test_api.py` | Response shape, trace completeness, SSE streaming, **bring-your-own-key**, key redaction, and every error path including **a missing `GOOGLE_API_KEY`** |

### Manual verification

```bash
python -m unittest discover
```

```bash
curl -s localhost:8000/api/health
```

```bash
curl -s -X POST localhost:8000/api/plan -H 'Content-Type: application/json' -d '{"message":"Home at 20:15, need to cook and review a presentation, 9 AM meeting tomorrow","energy_level":"low","location":"Paris, France"}'
```

With no key anywhere, the last command returns
`{"status":"error","error":{"code":"missing_api_key",…}}` at HTTP 200 — that is
the expected configuration error, not a crash. Add `"api_key":"AIza…"` to the
JSON body to get a real plan.

In the browser, confirm: the trace cards fill in one by one while the request
runs; each card expands to show tool input and output; the plan panel shows both
timelines, the readiness ring, warnings and three alternatives.

---

## 14. Free-service policy and limits

| Service | Cost | Key needed |
| --- | --- | --- |
| Google Gemini | Free tier | Yes — visitor's own, or the server's |
| Open-Meteo geocoding | Free | No |
| Open-Meteo forecast | Free | No |
| Travel estimates | Free — computed locally | No |
| Saved places | Free — browser `localStorage` | No database |
| Render hosting | Free tier | — |

**Known limits, stated honestly**

- Travel is a distance-and-speed estimate, not a routed itinerary. It does not
  know about RER schedules, strikes or traffic. The UI labels its confidence.
- Weather comes from the city centroid, not a street address.
- Gemini's free tier is rate-limited. On a burst you will see the quota message;
  waiting a minute fixes it.
- Saved places live in one browser. Clearing site data clears them.
- The free Render instance cold-starts after idling.

---

Built with FastAPI, LangChain, Google Gemini and Open-Meteo. MIT licensed.
