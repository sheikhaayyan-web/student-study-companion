import sqlite3
import json
import os
import secrets
from datetime import datetime, timedelta, timezone

DB_PATH = os.getenv("TALIB_DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "talib_ai.db"))

def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        email TEXT UNIQUE NOT NULL COLLATE NOCASE,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS oauth_identities (
        provider TEXT NOT NULL,
        provider_subject TEXT NOT NULL,
        user_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (provider, provider_subject),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS auth_sessions (
        token_hash TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS password_resets (
        token_hash TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        used_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS auth_rate_limits (
        rate_key TEXT PRIMARY KEY,
        attempts INTEGER NOT NULL,
        window_started_at TEXT NOT NULL
    )
    ''')

    # 1. Students Table (Multi-tenant by unique user_id)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        education_level TEXT NOT NULL,
        institution TEXT,
        degree_major TEXT,
        current_semester INTEGER DEFAULT 1,
        preferred_language TEXT DEFAULT 'en',
        streak_days INTEGER DEFAULT 1,
        study_hours REAL DEFAULT 0.0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # 2. Courses Table (Separated per student)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS courses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        code TEXT,
        total_topics INTEGER DEFAULT 0,
        completed_topics INTEGER DEFAULT 0,
        exam_date TEXT,
        FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
    )
    ''')

    # 3. Topics Table (Separated per student & course)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS topics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        course_id INTEGER NOT NULL,
        module_name TEXT,
        title TEXT NOT NULL,
        scheduled_date TEXT,
        time_slot TEXT,
        is_completed INTEGER DEFAULT 0,
        quiz_passed INTEGER DEFAULT 0,
        quiz_score REAL DEFAULT 0.0,
        difficulty TEXT DEFAULT 'medium',
        FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
        FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE
    )
    ''')

    # 4. Quiz Results (Individual student submissions)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS quiz_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        topic_id INTEGER,
        topic_title TEXT,
        score REAL,
        passed INTEGER,
        attempted_at TEXT,
        details TEXT,
        FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS activity_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        kind TEXT NOT NULL,
        duration_seconds INTEGER NOT NULL DEFAULT 0,
        occurred_at TEXT NOT NULL,
        FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS focus_sessions (
        id TEXT PRIMARY KEY,
        student_id INTEGER NOT NULL,
        duration_seconds INTEGER NOT NULL,
        started_at TEXT NOT NULL,
        completed_at TEXT,
        FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        pages_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS quiz_sessions (
        id TEXT PRIMARY KEY,
        student_id INTEGER NOT NULL,
        topic_id INTEGER,
        topic_title TEXT NOT NULL,
        questions_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        submitted_at TEXT,
        FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
        FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE CASCADE
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tutor_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS generated_exports (
        filename TEXT PRIMARY KEY,
        student_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS studio_drafts (
        student_id INTEGER PRIMARY KEY,
        topic TEXT NOT NULL DEFAULT '',
        content TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL,
        FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
    )
    ''')

    conn.commit()
    conn.close()

def get_or_create_student(user_id: str, name: str = "Student", level: str = "bachelors", institution: str = "", major: str = "", semester: int | None = None):
    """
    Finds existing student or initializes a completely fresh, isolated student environment.
    """
    if not user_id:
        raise ValueError("An authenticated user ID is required")

    conn = get_connection()
    cursor = conn.cursor()

    # Check if student exists
    row = cursor.execute('SELECT * FROM students WHERE user_id = ?', (user_id,)).fetchone()
    if row:
        student = dict(row)
        conn.close()
        return student

    cursor.execute('''
    INSERT INTO students (user_id, name, education_level, institution, degree_major, current_semester, preferred_language, streak_days, study_hours)
    VALUES (?, ?, ?, ?, ?, ?, 'en', 0, 0.0)
    ''', (user_id, name, level, institution or None, major or None, semester))
    student_id = cursor.lastrowid

    conn.commit()
    new_student = dict(cursor.execute('SELECT * FROM students WHERE id = ?', (student_id,)).fetchone())
    conn.close()
    return new_student

def update_student_profile(user_id: str, level: str | None = None, lang: str | None = None, name: str | None = None, institution: str | None = None, degree_major: str | None = None, current_semester: int | None = None):
    conn = get_connection()
    cursor = conn.cursor()

    # Ensure student exists
    row = cursor.execute('SELECT id FROM students WHERE user_id = ?', (user_id,)).fetchone()
    if not row:
        conn.close()
        return get_or_create_student(user_id, name or "Student", level or "bachelors", institution or "", degree_major or "", current_semester)

    if level:
        cursor.execute('UPDATE students SET education_level = ? WHERE user_id = ?', (level, user_id))
    if lang:
        cursor.execute('UPDATE students SET preferred_language = ? WHERE user_id = ?', (lang, user_id))
    if name:
        cursor.execute('UPDATE students SET name = ? WHERE user_id = ?', (name, user_id))
    if institution:
        cursor.execute('UPDATE students SET institution = ? WHERE user_id = ?', (institution, user_id))
    if degree_major:
        cursor.execute('UPDATE students SET degree_major = ? WHERE user_id = ?', (degree_major, user_id))
    if current_semester is not None:
        cursor.execute('UPDATE students SET current_semester = ? WHERE user_id = ?', (current_semester, user_id))

    conn.commit()
    updated = dict(cursor.execute('SELECT * FROM students WHERE user_id = ?', (user_id,)).fetchone())
    conn.close()
    return updated

def get_dashboard_data(user_id: str):
    """
    Returns completely isolated progress and courses strictly belonging to user_id.
    """
    conn = get_connection()
    cursor = conn.cursor()

    student_row = cursor.execute('SELECT * FROM students WHERE user_id = ?', (user_id,)).fetchone()
    if not student_row:
        conn.close()
        student = get_or_create_student(user_id)
        return get_dashboard_data(student["user_id"])

    student = dict(student_row)
    student_id = student["id"]

    courses = [dict(c) for c in cursor.execute('SELECT * FROM courses WHERE student_id = ? ORDER BY id ASC', (student_id,)).fetchall()]
    topics = [dict(t) for t in cursor.execute('SELECT * FROM topics WHERE student_id = ? ORDER BY id ASC', (student_id,)).fetchall()]
    conn.close()

    total_topics = sum(c['total_topics'] for c in courses) if courses else 0
    completed_topics = sum(c['completed_topics'] for c in courses) if courses else 0
    syllabus_pct = round((completed_topics / total_topics) * 100) if total_topics > 0 else 0

    conn = get_connection()
    quiz_stats = conn.execute('''
        SELECT COUNT(*) AS attempts,
               COALESCE(SUM(passed), 0) AS passed,
               COALESCE(AVG(score), 0) AS average
        FROM quiz_results WHERE student_id = ?
    ''', (student_id,)).fetchone()
    activity = conn.execute(
        'SELECT duration_seconds, occurred_at FROM activity_events WHERE student_id = ? ORDER BY occurred_at DESC',
        (student_id,)
    ).fetchall()
    quiz_dates = conn.execute(
        'SELECT attempted_at FROM quiz_results WHERE student_id = ? ORDER BY attempted_at DESC',
        (student_id,)
    ).fetchall()
    conn.close()

    active_dates = set()
    for row in [*activity, *quiz_dates]:
        raw_date = row['occurred_at'] if 'occurred_at' in row.keys() else row['attempted_at']
        try:
            active_dates.add(datetime.fromisoformat(raw_date).date())
        except (TypeError, ValueError):
            continue
    streak_days = 0
    today = datetime.now().date()
    check_date = today if today in active_dates else today - timedelta(days=1)
    while check_date in active_dates:
        streak_days += 1
        check_date -= timedelta(days=1)
    study_hours = round(sum(row['duration_seconds'] for row in activity) / 3600, 1)

    weak_topics = [t['title'] for t in topics if 0 < t['quiz_score'] < 70]

    return {
        "profile": student,
        "courses": courses,
        "topics": topics,
        "stats": {
            "syllabus_completion_pct": syllabus_pct,
            "quiz_mastery_pct": round(quiz_stats['average'], 1),
            "quiz_attempts_count": quiz_stats['attempts'],
            "passed_quizzes_count": quiz_stats['passed'],
            "study_hours": study_hours,
            "streak_days": streak_days,
            "weak_topics": weak_topics,
            "weak_topics_count": len(weak_topics)
        }
    }

def record_quiz_completion(user_id: str, topic_id: int, score: float, passed: bool, details: str = ""):
    """
    Updates progress ONLY for the student matching user_id.
    """
    conn = get_connection()
    cursor = conn.cursor()

    student_row = cursor.execute('SELECT id FROM students WHERE user_id = ?', (user_id,)).fetchone()
    if not student_row:
        conn.close()
        return

    student_id = student_row["id"]

    topic = cursor.execute(
        'SELECT id, course_id FROM topics WHERE id = ? AND student_id = ?',
        (topic_id, student_id)
    ).fetchone()
    if not topic:
        conn.close()
        return False

    cursor.execute('''
    UPDATE topics
    SET is_completed = CASE WHEN ? = 1 THEN 1 ELSE is_completed END,
        quiz_passed = CASE WHEN ? = 1 THEN 1 ELSE quiz_passed END,
        quiz_score = ?
    WHERE id = ? AND student_id = ?
    ''', (1 if passed else 0, 1 if passed else 0, score, topic_id, student_id))
    cursor.execute('''
    UPDATE courses SET completed_topics = (
        SELECT COUNT(*) FROM topics WHERE course_id = ? AND is_completed = 1
    ) WHERE id = ? AND student_id = ?
    ''', (topic['course_id'], topic['course_id'], student_id))

    cursor.execute('''
    INSERT INTO quiz_results (student_id, topic_id, topic_title, score, passed, attempted_at, details)
    VALUES (?, ?, (SELECT title FROM topics WHERE id = ?), ?, ?, ?, ?)
    ''', (student_id, topic_id, topic_id, score, 1 if passed else 0, datetime.now().isoformat(), json.dumps(details)))

    conn.commit()
    conn.close()
    return True


def start_focus_session(user_id: str, duration_seconds: int):
    student = get_or_create_student(user_id)
    session_id = secrets.token_urlsafe(24)
    started_at = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    conn.execute(
        'INSERT INTO focus_sessions (id, student_id, duration_seconds, started_at) VALUES (?, ?, ?, ?)',
        (session_id, student['id'], duration_seconds, started_at)
    )
    conn.commit()
    conn.close()
    return session_id


def complete_focus_session(user_id: str, session_id: str):
    student_id = get_student_id(user_id)
    if not student_id:
        return None
    now = datetime.now(timezone.utc)
    conn = get_connection()
    session = conn.execute('''
        SELECT duration_seconds, started_at FROM focus_sessions
        WHERE id = ? AND student_id = ? AND completed_at IS NULL
    ''', (session_id, student_id)).fetchone()
    if not session:
        conn.close()
        return None
    started_at = datetime.fromisoformat(session['started_at'])
    elapsed = (now - started_at).total_seconds()
    if elapsed < session['duration_seconds'] * 0.95:
        conn.close()
        return False
    duration = min(session['duration_seconds'], int(elapsed))
    conn.execute('UPDATE focus_sessions SET completed_at = ? WHERE id = ?', (now.isoformat(), session_id))
    conn.execute(
        'INSERT INTO activity_events (student_id, kind, duration_seconds, occurred_at) VALUES (?, ?, ?, ?)',
        (student_id, 'focus', duration, started_at.isoformat())
    )
    conn.commit()
    conn.close()
    return duration


def cancel_focus_session(user_id: str, session_id: str):
    student_id = get_student_id(user_id)
    if not student_id:
        return
    conn = get_connection()
    conn.execute(
        'DELETE FROM focus_sessions WHERE id = ? AND student_id = ? AND completed_at IS NULL',
        (session_id, student_id)
    )
    conn.commit()
    conn.close()


def get_student_id(user_id: str):
    conn = get_connection()
    row = conn.execute('SELECT id FROM students WHERE user_id = ?', (user_id,)).fetchone()
    conn.close()
    return row['id'] if row else None
