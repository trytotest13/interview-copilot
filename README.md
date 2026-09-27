# Interview Copilot

Practice interviews out loud. Upload your resume, paste a job description, and the app generates the 8 questions a phone screen would probably include (5 technical aimed at where the JD overlaps your resume, 2 behavioral, 1 project deep dive). You answer by speaking, the browser turns speech into text, and each answer is graded with a score, strengths, improvements and a model answer. At the end you get an average and the recurring themes to work on.

I built it to prepare for my own interviews, which also made it a good test case: I was the first user.

## Why browser speech recognition

The Web Speech API costs nothing, needs no GPU, and works in Chrome and Edge with a permission prompt. The transcript is editable before grading, which matters because recognition errors should not cost you points. Swapping in faster-whisper later would add privacy and browser independence, at the cost of running a model locally.

## Grading

Each answer is scored 0 to 10 against a fixed rubric (see `evals/rubric.md`):

- Correctness, 40%
- Evidence grounded in your actual resume, 25%
- Structure (STAR for behavioral, claim-example-result for technical), 20%
- Communication, 15%

The grader sees the resume and the job description, so "use specifics from your projects" is something it can actually check rather than generic advice. The same weights live in the prompt and in the rubric file.

## Running it

```
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
cp .env.example .env    # set OPENAI_API_KEY
.venv/Scripts/python -m uvicorn app.main:app --reload
```

Open http://localhost:8000 in Chrome or Edge and allow microphone access. Any OpenAI-compatible provider works via `OPENAI_BASE_URL` and `LLM_MODEL`.

Sessions are held in memory for now, so a restart clears them. Adding a database is the obvious next step, along with answer history so you can see whether your scores actually improve across sessions.
