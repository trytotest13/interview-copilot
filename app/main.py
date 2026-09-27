"""Interview Copilot: resume + JD -> questions -> spoken answers -> rubric grading -> report.

Sessions live in memory (v1). Roadmap: Postgres-backed sessions + auth.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from . import llm

app = FastAPI(title="Interview Copilot", version="0.1.0")

STATIC_DIR = Path(__file__).resolve().parent / "static"

SESSIONS: dict[str, dict] = {}

MAX_RESUME_CHARS = 50_000
MAX_JD_CHARS = 20_000
MAX_ANSWER_CHARS = 8_000

# Optional shared-secret guard for /api endpoints (API_TOKEN in .env; the UI
# prompts once and stores the value in localStorage).
API_TOKEN = os.getenv("API_TOKEN", "")


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    def with_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("Permissions-Policy", "microphone=(self)")
        return resp

    protected = request.url.path.startswith("/api")
    if API_TOKEN and protected and request.headers.get("X-API-Token") != API_TOKEN:
        return with_headers(JSONResponse({"detail": "unauthorized"}, status_code=401))
    return with_headers(await call_next(request))


def _extract_resume(file: UploadFile | None, resume_text: str) -> str:
    if file and file.filename:
        data = file.file.read()
        if len(data) > 5 * 1024 * 1024:
            raise HTTPException(400, "Resume file too large (max 5 MB)")
        if file.filename.lower().endswith(".pdf"):
            import pymupdf

            doc = pymupdf.open(stream=data, filetype="pdf")
            text = "\n".join(page.get_text("text") for page in doc)
            doc.close()
            return text.strip()
        return data.decode("utf-8", errors="replace").strip()
    return resume_text.strip()


@app.get("/health")
def health() -> dict:
    return {"ok": True, "llm_configured": bool(llm.API_KEY), "sessions": len(SESSIONS)}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/setup")
async def setup(
    jd_text: str = Form(...),
    resume_text: str = Form(""),
    resume_file: UploadFile | None = File(None),
) -> dict:
    resume = _extract_resume(resume_file, resume_text)
    jd = jd_text.strip()
    if len(resume) > MAX_RESUME_CHARS:
        resume = resume[:MAX_RESUME_CHARS]
    if len(jd) > MAX_JD_CHARS:
        jd = jd[:MAX_JD_CHARS]
    if len(resume) < 100:
        raise HTTPException(400, "Resume is too short: upload a PDF or paste at least 100 characters")
    if len(jd) < 80:
        raise HTTPException(400, "Paste the full job description (at least 80 characters)")

    try:
        questions = llm.generate_questions(resume, jd)
    except llm.LlmNotConfigured as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"LLM provider error: {e}")

    session_id = uuid.uuid4().hex[:12]
    SESSIONS[session_id] = {"resume": resume, "jd": jd, "questions": questions, "grades": {}}
    return {"session_id": session_id, "questions": questions}


class GradeIn(BaseModel):
    session_id: str = Field(max_length=64)
    question_id: int
    answer: str = Field(max_length=MAX_ANSWER_CHARS)


@app.post("/api/grade")
def grade(body: GradeIn) -> dict:
    session = SESSIONS.get(body.session_id)
    if not session:
        raise HTTPException(404, "Session not found: set up the interview again")
    question = next((q for q in session["questions"] if q["id"] == body.question_id), None)
    if not question:
        raise HTTPException(404, "Unknown question id")
    if len(body.answer.strip()) < 20:
        raise HTTPException(400, "Answer is too short to grade (min 20 characters)")

    try:
        feedback = llm.grade_answer(question["question"], body.answer, session["resume"], session["jd"])
    except llm.LlmNotConfigured as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"LLM provider error: {e}")

    session["grades"][str(body.question_id)] = feedback
    scores = [g["score"] for g in session["grades"].values()]
    return {**feedback, "graded_count": len(scores), "average": round(sum(scores) / len(scores), 1)}


@app.get("/api/report/{session_id}")
def report(session_id: str) -> dict:
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    grades = session["grades"]
    if not grades:
        raise HTTPException(400, "Grade at least one answer first")
    scores = [g["score"] for g in grades.values()]
    themes: dict[str, int] = {}
    for g in grades.values():
        for imp in g["improvements"]:
            key = imp[:60]
            themes[key] = themes.get(key, 0) + 1
    top_themes = sorted(themes, key=themes.get, reverse=True)[:3]
    return {
        "questions_total": len(session["questions"]),
        "questions_graded": len(grades),
        "average": round(sum(scores) / len(scores), 1),
        "per_question": [
            {"id": int(qid), "score": g["score"], "verdict": g["verdict"]}
            for qid, g in sorted(grades.items(), key=lambda kv: int(kv[0]))
        ],
        "top_improvement_themes": top_themes,
    }
