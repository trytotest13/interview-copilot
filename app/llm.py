"""LLM calls: question generation + rubric grading (strict JSON, defensive parsing)."""
from __future__ import annotations

import json
import os
import re

from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
API_KEY = os.getenv("OPENAI_API_KEY", "")
MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")


class LlmNotConfigured(RuntimeError):
    pass


def _client():
    if not API_KEY:
        raise LlmNotConfigured("Set OPENAI_API_KEY (and optionally OPENAI_BASE_URL / LLM_MODEL) in .env")
    from openai import OpenAI

    return OpenAI(api_key=API_KEY, base_url=BASE_URL)


def _extract_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValueError(f"no JSON in LLM reply: {text[:200]!r}")
    return json.loads(match.group(0))


def generate_questions(resume_text: str, jd_text: str) -> list[dict]:
    client = _client()
    res = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": (
                "You are a senior interviewer preparing a phone screen. "
                "Respond with STRICT JSON only: "
                '{"questions": [{"id": 1, "question": "...", "focus": "short skill tag"}]}'
            )},
            {"role": "user", "content": (
                f"Resume:\n{resume_text[:6000]}\n\nJob description:\n{jd_text[:4000]}\n\n"
                "Generate exactly 8 questions: 5 technical (focused on the overlap of the JD's "
                "requirements with the candidate's stated stack), 2 behavioral (STAR), and 1 "
                "project deep-dive ('walk me through' one of their projects, incl. trade-offs). "
                "Order: technical 1-5, behavioral 6-7, deep-dive 8."
            )},
        ],
        temperature=0.3,
        max_tokens=900,
    )
    data = _extract_json(res.choices[0].message.content or "")
    questions = data.get("questions")
    if not isinstance(questions, list) or len(questions) < 6:
        raise ValueError("LLM returned too few questions")
    return [
        {"id": i + 1, "question": str(q.get("question", ""))[:500], "focus": str(q.get("focus", "general"))[:60]}
        for i, q in enumerate(questions[:8])
    ]


def grade_answer(question: str, answer: str, resume_text: str, jd_text: str) -> dict:
    client = _client()
    res = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": (
                "You are a fair but rigorous interviewer grading a spoken answer (transcribed, so "
                "ignore punctuation/stutters). Rubric: correctness 40%, resume-specific evidence 25%, "
                "structure 20%, communication 15%. Respond with STRICT JSON only: "
                '{"score": 0-10, "verdict": "strong|ok|weak", "strengths": ["..."], '
                '"improvements": ["..."], "sample_answer": "3-4 sentences"}'
            )},
            {"role": "user", "content": (
                f"Job description:\n{jd_text[:2500]}\n\nResume:\n{resume_text[:4000]}\n\n"
                f"Question: {question}\n\nCandidate answer:\n{answer[:4000]}"
            )},
        ],
        temperature=0.2,
        max_tokens=600,
    )
    data = _extract_json(res.choices[0].message.content or "")
    score = max(0, min(10, int(data.get("score", 0))))
    verdict = data.get("verdict") if data.get("verdict") in ("strong", "ok", "weak") else ("strong" if score >= 8 else "ok" if score >= 5 else "weak")
    return {
        "score": score,
        "verdict": verdict,
        "strengths": [str(s) for s in (data.get("strengths") or [])][:4],
        "improvements": [str(s) for s in (data.get("improvements") or [])][:4],
        "sample_answer": str(data.get("sample_answer", ""))[:1200],
    }
