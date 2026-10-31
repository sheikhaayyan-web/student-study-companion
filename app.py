import json
import hashlib
import os
import re
import secrets
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Any, Literal

import pdfplumber
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from authlib.integrations.starlette_client import OAuth, OAuthError
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

if __package__:
    from .services import auth_service
    from .services.auth_service import AccountConflictError, InvalidCredentialsError, OAuthLinkRequiredError
    from .services.db_service import (
        get_connection,
        get_dashboard_data,
        get_or_create_student,
        get_student_id,
        init_db,
        start_focus_session,
        complete_focus_session,
        cancel_focus_session,
        record_quiz_completion,
        update_student_profile,
    )
    from .services.lecture_finder import get_curated_lectures, get_short_courses
    from .services.quiz_engine import QuizUnavailableError, evaluate_quiz_submission, get_15_mcqs_for_topic
    from .services.studio_generator import (
        OUTPUT_DIR,
        generate_assignment_docx,
        generate_draft_text,
        generate_presentation_pptx,
    )
    from .services.syllabus_parser import parse_syllabus_text
    from .services.tutor_engine import generate_tutor_response
else:
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    from backend.services import auth_service
    from backend.services.auth_service import AccountConflictError, InvalidCredentialsError, OAuthLinkRequiredError
    from backend.services.db_service import (
        get_connection,
        get_dashboard_data,
        get_or_create_student,
        get_student_id,
        init_db,
        start_focus_session,
        complete_focus_session,
        cancel_focus_session,
        record_quiz_completion,
        update_student_profile,
    )
    from backend.services.lecture_finder import get_curated_lectures, get_short_courses
    from backend.services.quiz_engine import QuizUnavailableError, evaluate_quiz_submission, get_15_mcqs_for_topic
    from backend.services.studio_generator import (
        OUTPUT_DIR,
        generate_assignment_docx,
        generate_draft_text,
        generate_presentation_pptx,
    )
    from backend.services.syllabus_parser import parse_syllabus_text
    from backend.services.tutor_engine import generate_tutor_response

app = FastAPI(title="TalibAI - Student Study Companion API", version="3.0.0")
init_db()
SESSION_COOKIE = "talib_session"
SESSION_MAX_AGE = auth_service.SESSION_DAYS * 24 * 60 * 60
MAX_PDF_BYTES = 15 * 1024 * 1024
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
OAUTH_STATE_SECRET = os.getenv("OAUTH_STATE_SECRET")
oauth = OAuth()
oauth_clients = {}

if OAUTH_STATE_SECRET and os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"):
    oauth_clients["google"] = oauth.register(
        name="google",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

facebook_version = os.getenv("FACEBOOK_GRAPH_VERSION", "v25.0")
if OAUTH_STATE_SECRET and os.getenv("FACEBOOK_CLIENT_ID") and os.getenv("FACEBOOK_CLIENT_SECRET"):
    oauth_clients["facebook"] = oauth.register(
        name="facebook",
        client_id=os.environ["FACEBOOK_CLIENT_ID"],
        client_secret=os.environ["FACEBOOK_CLIENT_SECRET"],
        authorize_url=f"https://www.facebook.com/{facebook_version}/dialog/oauth",
        access_token_url=f"https://graph.facebook.com/{facebook_version}/oauth/access_token",
        api_base_url=f"https://graph.facebook.com/{facebook_version}/",
        client_kwargs={"scope": "email public_profile"},
    )

app.add_middleware(
    SessionMiddleware,
    secret_key=OAUTH_STATE_SECRET or secrets.token_urlsafe(32),
    session_cookie="talib_oauth_state",
    max_age=600,
    same_site="lax",
    https_only=os.getenv("OAUTH_COOKIE_SECURE", "false").lower() == "true",
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "DENY"
    return response


def current_user(request: Request) -> dict:
    user = auth_service.get_session_user(request.cookies.get(SESSION_COOKIE))
    if not user:
        raise HTTPException(status_code=401, detail="Please log in to continue.")
    return user


def _set_session_cookie(response: Response, request: Request, token: str):
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax")


def _student(user: dict) -> dict:
    return get_or_create_student(user["id"])


def _valid_email(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", normalized):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    return normalized


def _password(value: str) -> str:
    if len(value) < 12 or len(value) > 128:
        raise HTTPException(status_code=422, detail="Password must be between 12 and 128 characters.")
    return value


def _auth_rate_key(action: str, request: Request, email: str) -> str:
    remote = request.client.host if request.client else "unknown"
    value = f"{action}:{remote}:{email.strip().lower()}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class SignupRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str
    name: str = Field(min_length=1, max_length=100)
    level: Literal["class_9_10", "class_11_12", "bachelors", "masters"] = "bachelors"


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str


class ProfileUpdateRequest(BaseModel):
    level: Literal["class_9_10", "class_11_12", "bachelors", "masters"] | None = None
    language: Literal["en", "ur"] | None = None
    name: str | None = Field(default=None, max_length=100)
    institution: str | None = Field(default=None, max_length=160)
    degree_major: str | None = Field(default=None, max_length=160)
    current_semester: int | None = Field(default=None, ge=1, le=12)


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=8000)
    level: Literal["class_9_10", "class_11_12", "bachelors", "masters"] = "bachelors"
    language: Literal["en", "ur"] = "en"
    mode: Literal["tutor", "hint"] = "tutor"
    context: str | None = Field(default=None, max_length=12000)


class StudioDraftRequest(BaseModel):
    topic: str = Field(max_length=200)
    content: str = Field(max_length=50000)


class SyllabusUploadRequest(BaseModel):
    course_name: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=10, max_length=30000)


class QuizStartRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    topic_id: int | None = Field(default=None, ge=1)


class QuizSubmitRequest(BaseModel):
    session_id: str = Field(min_length=20, max_length=100)
    answers: dict[str, int]


class FocusSessionRequest(BaseModel):
    duration_seconds: int = Field(ge=60, le=3600)


class CompleteFocusSessionRequest(BaseModel):
    session_id: str = Field(min_length=20, max_length=100)


class LibraryAskRequest(BaseModel):
    document_id: int = Field(ge=1)
    question: str = Field(min_length=1, max_length=4000)


class ExportDocxRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=50000)


class ExportPptxRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    slides: list[dict[str, Any]] = Field(min_length=1, max_length=30)


@app.post("/api/auth/signup", status_code=201)
def signup(req: SignupRequest, request: Request, response: Response):
    email = _valid_email(req.email)
    password = _password(req.password)
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Name is required.")
    try:
        user = auth_service.create_account(email, password)
    except AccountConflictError:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    get_or_create_student(user["id"], name=name, level=req.level)
    token, _ = auth_service.create_session(user["id"])
    _set_session_cookie(response, request, token)
    return {"user": user}


@app.post("/api/auth/login")
def login(req: LoginRequest, request: Request, response: Response):
    email = _valid_email(req.email)
    rate_key = _auth_rate_key("login", request, email)
    if not auth_service.consume_auth_rate_limit(rate_key):
        raise HTTPException(
            status_code=429,
            detail="Too many sign-in attempts. Try again in 15 minutes.",
            headers={"Retry-After": "900"},
        )
    try:
        user = auth_service.authenticate(email, req.password)
    except InvalidCredentialsError:
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    auth_service.clear_auth_rate_limit(rate_key)
    token, _ = auth_service.create_session(user["id"])
    _set_session_cookie(response, request, token)
    return {"user": user}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    auth_service.delete_session(request.cookies.get(SESSION_COOKIE))
    _clear_session_cookie(response)
    return {"status": "success"}


@app.get("/api/auth/me")
def auth_me(request: Request):
    return {"user": auth_service.get_session_user(request.cookies.get(SESSION_COOKIE))}


def _oauth_client(provider: str):
    client = oauth_clients.get(provider)
    if not client:
        raise HTTPException(status_code=503, detail=f"{provider.title()} sign-in is not configured.")
    return client


@app.get("/api/auth/providers")
def get_oauth_providers():
    return {"google": "google" in oauth_clients, "facebook": "facebook" in oauth_clients}


@app.get("/api/auth/oauth/{provider}")
async def start_oauth(provider: str, request: Request):
    client = _oauth_client(provider)
    request.session.pop("oauth_link_user_id", None)
    callback_url = request.url_for("oauth_callback", provider=provider)
    return await client.authorize_redirect(request, callback_url)


@app.get("/api/auth/link/{provider}")
async def start_oauth_link(provider: str, request: Request, user: dict = Depends(current_user)):
    client = _oauth_client(provider)
    request.session["oauth_link_user_id"] = user["id"]
    callback_url = request.url_for("oauth_callback", provider=provider)
    return await client.authorize_redirect(request, callback_url)


@app.get("/api/auth/oauth/{provider}/callback", name="oauth_callback")
async def oauth_callback(provider: str, request: Request):
    client = oauth_clients.get(provider)
    if not client:
        return RedirectResponse("/?oauth=error", status_code=303)

    link_user_id = request.session.pop("oauth_link_user_id", None)
    try:
        token = await client.authorize_access_token(request)
        if provider == "google":
            profile = token.get("userinfo")
            if not profile:
                profile = await client.userinfo(token=token)
            subject = profile.get("sub")
            email = profile.get("email")
            email_verified = profile.get("email_verified") is True
            name = profile.get("name") or ""
        else:
            profile_response = await client.get(
                "me", token=token, params={"fields": "id,name,email"}
            )
            profile = profile_response.json()
            subject = profile.get("id")
            email = profile.get("email")
            email_verified = bool(email)
            name = profile.get("name") or ""

        if not subject or not email or not email_verified:
            return RedirectResponse("/?oauth=email_unverified", status_code=303)

        email = _valid_email(email)
        if link_user_id:
            session_user = auth_service.get_session_user(request.cookies.get(SESSION_COOKIE))
            if not session_user or session_user["id"] != link_user_id:
                return RedirectResponse("/?oauth=error", status_code=303)

        user = auth_service.resolve_oauth_account(
            provider=provider,
            provider_subject=str(subject),
            email=email,
            name=name,
            link_user_id=link_user_id,
        )
        if link_user_id:
            return RedirectResponse("/?oauth=linked", status_code=303)

        session_token, _ = auth_service.create_session(user["id"])
        response = RedirectResponse("/", status_code=303)
        _set_session_cookie(response, request, session_token)
        return response
    except OAuthLinkRequiredError:
        return RedirectResponse("/?oauth=link_required", status_code=303)
    except AccountConflictError:
        return RedirectResponse("/?oauth=identity_conflict", status_code=303)
    except OAuthError:
        return RedirectResponse("/?oauth=error", status_code=303)


@app.post("/api/auth/forgot-password")
def forgot_password(req: ForgotPasswordRequest):
    if not auth_service.email_is_configured():
        raise HTTPException(status_code=503, detail="Password reset email is not configured on this server.")
    try:
        auth_service.request_password_reset(_valid_email(req.email))
    except Exception:
        raise HTTPException(status_code=503, detail="Unable to send a password reset email right now.")
    return {"message": "If an account exists for that email, a reset token has been sent."}


@app.post("/api/auth/reset-password")
def reset_password(req: ResetPasswordRequest):
    if not auth_service.reset_password(req.token, _password(req.password)):
        raise HTTPException(status_code=400, detail="This password reset token is invalid or expired.")
    return {"status": "success", "message": "Password reset. Please log in with your new password."}


@app.get("/api/dashboard")
def dashboard(user: dict = Depends(current_user)):
    return get_dashboard_data(user["id"])


@app.post("/api/profile")
def update_profile(req: ProfileUpdateRequest, user: dict = Depends(current_user)):
    profile = update_student_profile(
        user_id=user["id"],
        level=req.level,
        lang=req.language,
        name=req.name.strip() if req.name is not None else None,
        institution=req.institution.strip() if req.institution is not None else None,
        degree_major=req.degree_major.strip() if req.degree_major is not None else None,
        current_semester=req.current_semester,
    )
    return {"profile": profile}


@app.post("/api/tutor/chat")
def tutor_chat(req: ChatRequest, user: dict = Depends(current_user)):
    student = _student(user)
    conn = get_connection()
    conn.execute(
        'INSERT INTO tutor_messages (student_id, role, content, created_at) VALUES (?, ?, ?, ?)',
        (student["id"], "user", req.query, datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()
    result = generate_tutor_response(
        query=req.query,
        level=req.level,
        language=req.language,
        mode=req.mode,
        context=req.context,
    )
    if result.get("source") != "live_gemini":
        raise HTTPException(status_code=503, detail="AI tutoring requires a configured Gemini API key.")
    conn = get_connection()
    conn.execute(
        'INSERT INTO tutor_messages (student_id, role, content, created_at) VALUES (?, ?, ?, ?)',
        (student["id"], "assistant", result["response"], datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()
    return result


@app.get("/api/tutor/history")
def tutor_history(user: dict = Depends(current_user)):
    student = _student(user)
    conn = get_connection()
    rows = conn.execute('''
        SELECT role, content FROM tutor_messages WHERE student_id = ? ORDER BY id DESC LIMIT 100
    ''', (student["id"],)).fetchall()
    conn.close()
    return list(reversed([dict(row) for row in rows]))


@app.post("/api/quiz/session")
def start_quiz(req: QuizStartRequest, user: dict = Depends(current_user)):
    student = _student(user)
    if req.topic_id is not None:
        conn = get_connection()
        topic = conn.execute(
            'SELECT title FROM topics WHERE id = ? AND student_id = ?', (req.topic_id, student["id"])
        ).fetchone()
        conn.close()
        if not topic:
            raise HTTPException(status_code=404, detail="Topic not found in your account.")
    try:
        quiz = get_15_mcqs_for_topic(req.topic)
    except QuizUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error))
    session_id = secrets.token_urlsafe(24)
    conn = get_connection()
    conn.execute('''
        INSERT INTO quiz_sessions (id, student_id, topic_id, topic_title, questions_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        session_id, student["id"], req.topic_id, req.topic,
        json.dumps(quiz["questions"]), datetime.now(timezone.utc).isoformat()
    ))
    conn.commit()
    conn.close()
    public_questions = [
        {key: value for key, value in question.items() if key not in ("correct_index", "explanation")}
        for question in quiz["questions"]
    ]
    return {
        "session_id": session_id,
        "topic": req.topic,
        "total_questions": len(public_questions),
        "passing_threshold_pct": quiz["passing_threshold_pct"],
        "min_correct_to_pass": quiz["min_correct_to_pass"],
        "questions": public_questions,
    }


@app.post("/api/quiz/submit")
def submit_quiz(req: QuizSubmitRequest, user: dict = Depends(current_user)):
    student = _student(user)
    conn = get_connection()
    session = conn.execute('''
        SELECT * FROM quiz_sessions WHERE id = ? AND student_id = ? AND submitted_at IS NULL
    ''', (req.session_id, student["id"])).fetchone()
    if not session:
        conn.close()
        raise HTTPException(status_code=404, detail="Quiz session not found or already submitted.")
    questions = json.loads(session["questions_json"])
    valid_ids = {str(question["id"]) for question in questions}
    if set(req.answers) - valid_ids or any(answer < 0 or answer > 3 for answer in req.answers.values()):
        conn.close()
        raise HTTPException(status_code=422, detail="Quiz answers contain an invalid question or option.")
    result = evaluate_quiz_submission(req.answers, session["topic_title"], questions=questions)
    conn.close()
    if session["topic_id"] is not None:
        saved = record_quiz_completion(
            user["id"], session["topic_id"], result["score_pct"], result["passed"], result["feedback"]
        )
        if not saved:
            raise HTTPException(status_code=404, detail="Topic not found in your account.")
    else:
        conn = get_connection()
        conn.execute('''
            INSERT INTO quiz_results (student_id, topic_id, topic_title, score, passed, attempted_at, details)
            VALUES (?, NULL, ?, ?, ?, ?, ?)
        ''', (
            student["id"], session["topic_title"], result["score_pct"], int(result["passed"]),
            datetime.now(timezone.utc).isoformat(), json.dumps(result["feedback"])
        ))
        conn.commit()
        conn.close()
    conn = get_connection()
    conn.execute('UPDATE quiz_sessions SET submitted_at = ? WHERE id = ? AND student_id = ?',
                 (datetime.now(timezone.utc).isoformat(), req.session_id, student["id"]))
    conn.commit()
    conn.close()
    return result


@app.get("/api/lectures")
def lectures(topic: str = "normalization", user: dict = Depends(current_user)):
    return get_curated_lectures(topic)


@app.get("/api/short-courses")
def short_courses(user: dict = Depends(current_user)):
    return get_short_courses()


@app.post("/api/syllabus/upload")
def upload_syllabus_text(req: SyllabusUploadRequest, user: dict = Depends(current_user)):
    try:
        return parse_syllabus_text(req.content, req.course_name, user_id=user["id"])
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.post("/api/syllabus/upload-pdf")
async def upload_syllabus_pdf(
    file: UploadFile = File(...),
    course_name: str = Form("Uploaded Course Outline"),
    user: dict = Depends(current_user),
):
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=415, detail="Please upload a PDF file.")
    contents = await file.read(MAX_PDF_BYTES + 1)
    if len(contents) > MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="PDF files must be 15 MB or smaller.")
    if __package__:
        from .services.syllabus_parser import extract_text_from_pdf_bytes
    else:
        from backend.services.syllabus_parser import extract_text_from_pdf_bytes
    extracted_text = extract_text_from_pdf_bytes(contents)
    if not extracted_text.strip():
        raise HTTPException(status_code=400, detail="Could not extract readable text from PDF.")
    name = course_name.strip() or os.path.splitext(file.filename or "Course outline")[0]
    try:
        return parse_syllabus_text(extracted_text, name, user_id=user["id"])
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.post("/api/activity/focus/start")
def begin_focus_session(req: FocusSessionRequest, user: dict = Depends(current_user)):
    return {"session_id": start_focus_session(user["id"], req.duration_seconds)}


@app.post("/api/activity/focus/complete")
def finish_focus_session(req: CompleteFocusSessionRequest, user: dict = Depends(current_user)):
    result = complete_focus_session(user["id"], req.session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Focus session not found.")
    if result is False:
        raise HTTPException(status_code=409, detail="The focus session has not reached its planned duration.")
    return {"status": "success", "duration_seconds": result}


@app.delete("/api/activity/focus/{session_id}")
def stop_focus_session(session_id: str, user: dict = Depends(current_user)):
    cancel_focus_session(user["id"], session_id)
    return {"status": "cancelled"}


@app.get("/api/library/documents")
def list_documents(user: dict = Depends(current_user)):
    student = _student(user)
    conn = get_connection()
    rows = conn.execute('''
        SELECT id, title, created_at FROM user_documents WHERE student_id = ? ORDER BY id DESC
    ''', (student["id"],)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.post("/api/library/documents", status_code=201)
async def upload_library_pdf(file: UploadFile = File(...), user: dict = Depends(current_user)):
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=415, detail="Please upload a PDF file.")
    contents = await file.read(MAX_PDF_BYTES + 1)
    if len(contents) > MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="PDF files must be 15 MB or smaller.")
    try:
        with pdfplumber.open(__import__("io").BytesIO(contents)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
    except Exception:
        raise HTTPException(status_code=400, detail="This PDF could not be read.")
    if not any(page.strip() for page in pages):
        raise HTTPException(status_code=400, detail="No readable text was found in this PDF.")
    student = _student(user)
    title = os.path.basename(file.filename or "Uploaded textbook.pdf")[:200]
    conn = get_connection()
    cursor = conn.execute(
        'INSERT INTO user_documents (student_id, title, pages_json, created_at) VALUES (?, ?, ?, ?)',
        (student["id"], title, json.dumps(pages), datetime.now(timezone.utc).isoformat())
    )
    document_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"id": document_id, "title": title, "page_count": len(pages)}


@app.post("/api/library/ask")
def ask_library(req: LibraryAskRequest, user: dict = Depends(current_user)):
    student = _student(user)
    conn = get_connection()
    document = conn.execute(
        'SELECT title, pages_json FROM user_documents WHERE id = ? AND student_id = ?',
        (req.document_id, student["id"])
    ).fetchone()
    conn.close()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found in your library.")
    terms = {term.lower() for term in re.findall(r"[\w'-]{3,}", req.question)}
    pages = json.loads(document["pages_json"])
    ranked = sorted(
        ((sum(page.lower().count(term) for term in terms), index, page) for index, page in enumerate(pages)),
        reverse=True,
    )
    relevant = [(index, page) for score, index, page in ranked[:3] if score > 0]
    if not relevant:
        raise HTTPException(status_code=404, detail="No matching text was found in this document for that question.")
    context = "\n\n".join(f"Page {index + 1}: {page[:4000]}" for index, page in relevant)
    result = generate_tutor_response(
        query=req.question,
        level=_student(user)["education_level"],
        language="en",
        mode="tutor",
        context=f"Answer only using this excerpt from {document['title']}. Cite page numbers.\n{context}",
    )
    if result.get("source") != "live_gemini":
        raise HTTPException(status_code=503, detail="Document Q&A requires a configured Gemini API key.")
    return {"answer": result["response"], "pages": [index + 1 for index, _ in relevant]}


@app.post("/api/studio/generate-draft")
def studio_generate_draft(req: dict[str, str], user: dict = Depends(current_user)):
    topic = (req.get("topic") or "").strip()
    if not topic or len(topic) > 200:
        raise HTTPException(status_code=422, detail="Enter a topic up to 200 characters long.")
    level = _student(user)["education_level"]
    text = generate_draft_text(topic, level)
    if not text:
        raise HTTPException(status_code=503, detail="Draft generation requires a configured Gemini API key.")
    return {"topic": topic, "content": text}


@app.get("/api/studio/draft")
def get_studio_draft(user: dict = Depends(current_user)):
    student = _student(user)
    conn = get_connection()
    row = conn.execute('SELECT topic, content FROM studio_drafts WHERE student_id = ?', (student["id"],)).fetchone()
    conn.close()
    return dict(row) if row else {"topic": "", "content": ""}


@app.put("/api/studio/draft")
def save_studio_draft(req: StudioDraftRequest, user: dict = Depends(current_user)):
    student = _student(user)
    conn = get_connection()
    conn.execute('''
        INSERT INTO studio_drafts (student_id, topic, content, updated_at) VALUES (?, ?, ?, ?)
        ON CONFLICT(student_id) DO UPDATE SET topic = excluded.topic, content = excluded.content, updated_at = excluded.updated_at
    ''', (student["id"], req.topic, req.content, datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()
    return {"status": "saved"}


def _register_export(user: dict, filename: str):
    student_id = get_student_id(user["id"])
    conn = get_connection()
    conn.execute(
        'INSERT INTO generated_exports (filename, student_id, created_at) VALUES (?, ?, ?)',
        (filename, student_id, datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()


@app.post("/api/studio/export/docx")
def export_docx(req: ExportDocxRequest, user: dict = Depends(current_user)):
    student = _student(user)
    filepath = generate_assignment_docx(req.topic, req.content, student["name"], student["education_level"])
    filename = os.path.basename(filepath)
    _register_export(user, filename)
    return {"status": "success", "filename": filename, "download_url": f"/api/download/{filename}"}


@app.post("/api/studio/export/pptx")
def export_pptx(req: ExportPptxRequest, user: dict = Depends(current_user)):
    student = _student(user)
    filepath = generate_presentation_pptx(req.topic, req.slides, student["name"])
    filename = os.path.basename(filepath)
    _register_export(user, filename)
    return {"status": "success", "filename": filename, "download_url": f"/api/download/{filename}"}


@app.get("/api/download/{filename}")
def download_file(filename: str, user: dict = Depends(current_user)):
    conn = get_connection()
    row = conn.execute('''
        SELECT generated_exports.filename FROM generated_exports
        JOIN students ON students.id = generated_exports.student_id
        WHERE generated_exports.filename = ? AND students.user_id = ?
    ''', (os.path.basename(filename), user["id"])).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="File not found.")
    safe_path = os.path.join(OUTPUT_DIR, row["filename"])
    if not os.path.isfile(safe_path):
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(safe_path, filename=row["filename"])


if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/manifest.json")
def get_manifest():
    path = os.path.join(FRONTEND_DIR, "manifest.json")
    if os.path.isfile(path):
        return FileResponse(path, media_type="application/manifest+json")
    raise HTTPException(status_code=404, detail="Manifest not found.")


@app.get("/sw.js")
def get_service_worker():
    path = os.path.join(FRONTEND_DIR, "sw.js")
    if os.path.isfile(path):
        return FileResponse(path, media_type="application/javascript")
    raise HTTPException(status_code=404, detail="Service worker not found.")


@app.get("/")
def read_root():
    index_file = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.isfile(index_file):
        return FileResponse(index_file)
    return HTMLResponse("<h1>TalibAI Backend Active</h1>")
