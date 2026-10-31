"""
Syllabus & Course Outline Parser.
Supports raw text AND actual PDF files (via pdfplumber).
Extracts course structure, modules, and schedules dynamic timetable sessions.
"""

import os
import re
import io
import json
from datetime import datetime, timedelta
import pdfplumber
from dotenv import load_dotenv
from .db_service import get_connection

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

genai_client = None
if GEMINI_API_KEY:
    try:
        from google import genai
        genai_client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"Notice: Live Gemini client not initialized in syllabus parser: {e}")

def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """Extracts all text from uploaded PDF bytes."""
    extracted_text = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    extracted_text.append(text)
    except Exception as e:
        print(f"PDF extraction error: {e}")
    return "\n".join(extracted_text)

def parse_syllabus_text(raw_text: str, course_name: str, user_id: str) -> dict:
    """
    Parses syllabus text using either Gemini AI or regex heuristics,
    then populates the SQLite timetable and course tables for the specific student.
    """
    extracted_topics = []

    # If Live Gemini client is present, use structured extraction
    if genai_client and len(raw_text.strip()) > 50:
        try:
            prompt = (
                f"You are an academic curriculum scheduler. Parse the following course syllabus for '{course_name}' "
                "into a structured learning sequence.\n"
                "Return ONLY a JSON array of objects. Each object must have:\n"
                "- 'module': string (e.g. 'Module 1: Foundations')\n"
                "- 'title': string (topic title, max 80 chars)\n"
                "- 'difficulty': 'easy' | 'medium' | 'hard'\n"
                "Extract between 5 and 15 distinct topics.\n"
                f"Syllabus Content:\n{raw_text[:4000]}"
            )
            response = genai_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[{"role": "user", "parts": [{"text": prompt}]}]
            )
            raw = response.text.strip()
            if raw.startswith("```json"):
                raw = raw[7:]
            if raw.endswith("```"):
                raw = raw[:-3]
            parsed = json.loads(raw.strip())
            if isinstance(parsed, list) and len(parsed) >= 2:
                extracted_topics = parsed
        except Exception as e:
            print(f"Live syllabus extraction fallback ({e}). Using regex parser.")

    # Fallback heuristic parser
    if not extracted_topics:
        lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
        current_module = "Module 1: Foundations"
        for line in lines:
            if any(marker in line.lower() for marker in ["module", "chapter", "unit", "week"]):
                current_module = line
                continue
            clean_line = re.sub(r'^[0-9]+[\.\-\)]\s*', '', line)
            if 5 < len(clean_line) < 120 and not clean_line.startswith("http"):
                extracted_topics.append({
                    "module": current_module,
                    "title": clean_line,
                    "difficulty": "medium"
                })

    if not extracted_topics:
        raise ValueError("No topics could be extracted from the supplied course outline.")

    # Save to SQLite under student's specific account
    conn = get_connection()
    cursor = conn.cursor()

    row = cursor.execute('SELECT id FROM students WHERE user_id = ?', (user_id,)).fetchone()
    if row:
        student_id = row["id"]
    else:
        cursor.execute('INSERT INTO students (user_id, name, education_level) VALUES (?, ?, ?)', (user_id, "Student", "bachelors"))
        student_id = cursor.lastrowid

    cursor.execute('''
    INSERT INTO courses (student_id, name, code, total_topics, completed_topics, exam_date)
    VALUES (?, ?, ?, ?, 0, NULL)
    ''', (student_id, course_name, None, len(extracted_topics)))
    course_id = cursor.lastrowid

    time_slots = ["09:00 - 10:15 AM", "11:30 - 01:00 PM", "03:00 - 04:30 PM", "05:30 - 07:00 PM"]
    saved_topics = []

    for i, t in enumerate(extracted_topics):
        day_offset = i // 2
        day_label = "Today" if day_offset == 0 else ("Tomorrow" if day_offset == 1 else f"Day +{day_offset}")
        slot = time_slots[i % len(time_slots)]

        cursor.execute('''
        INSERT INTO topics (student_id, course_id, module_name, title, scheduled_date, time_slot, is_completed, quiz_passed, quiz_score, difficulty)
        VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0.0, ?)
        ''', (student_id, course_id, t["module"], t["title"], day_label, slot, t.get("difficulty", "medium")))

        saved_topics.append({
            "id": cursor.lastrowid,
            "module": t["module"],
            "title": t["title"],
            "scheduled_date": day_label,
            "time_slot": slot,
            "difficulty": t.get("difficulty", "medium")
        })

    conn.commit()
    conn.close()

    return {
        "course_id": course_id,
        "course_name": course_name,
        "total_topics_extracted": len(saved_topics),
        "scheduled_topics": saved_topics,
        "message": f"Successfully parsed '{course_name}'! Added {len(saved_topics)} study sessions to your timetable."
    }
