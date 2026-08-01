---
title: After-Work Life Planning Agent
sdk: gradio
app_file: app.py
pinned: false
license: mit
---

# After-Work Life Planning Agent

A Gradio web application built with LangChain and the Gemini API. It creates a
constraint-checked evening schedule and calculates bedtime and wake-up time.

## Hugging Face deployment

Create a new Hugging Face Space with:

- SDK: Gradio
- Hardware: CPU Basic
- Visibility: Public or Private

Upload the contents of this project to the root of the Space:

```text
app.py
planner.py
requirements.txt
README.md
```

In the Space settings, open **Variables and secrets** and add:

```text
Secret name: GOOGLE_API_KEY
Secret value: your Gemini API key
```

Optionally add this variable:

```text
Variable name: GEMINI_MODEL
Variable value: gemini-3.5-flash-lite
```

Do not upload `.env` or place the API key directly in the source code.

## Render deployment

Use this option when you want to showcase the project as an AI agent with a
real Python backend. Render runs the Gradio app, LangChain calls Gemini, and
the deterministic planner function performs the schedule calculations.

1. Push this project to a GitHub repository.
2. In Render, create a new **Web Service** from that GitHub repository.
3. Use these settings:

```text
Runtime: Python 3
Build Command: pip install -r requirements.txt
Start Command: python app.py
Instance Type: Free or Starter
```

4. Add environment variables in the Render service settings:

```text
GOOGLE_API_KEY=your Gemini API key
GEMINI_MODEL=gemini-3.5-flash-lite
```

The app reads Render's `PORT` environment variable and binds to `0.0.0.0`, so
it can receive public web traffic.

Do not commit `.env`, `.venv`, or API keys to GitHub.

## Local or Google Colab test

Install the dependencies:

```bash
pip install -r requirements.txt
```

Set the API key:

```python
import os
os.environ["GOOGLE_API_KEY"] = "your-key"
```

Run:

```bash
python app.py
```

In Google Colab, the last command starts a Gradio page and prints a public
preview link.

## Planning rules

- Dinner and a shower are mandatory every evening.
- Cooking and eating at home takes 1 hours and adds 10 minutes for dishes.
- Outside dining must be within 1 km of home.
- A quick shower takes 10 minutes; a full shower takes 30 minutes.
- Groceries take 30 minutes, exercise 1 hours, personal development
  60 minutes, cleaning 60 minutes, and loading laundry 5 minutes.
- Bedtime cannot be later than 01:30.
- Daily tasks that do not fit in the evening are moved to 06:00 when possible.
- The default work departure time is 08:00, with 20 minutes to get ready.
