# TalibAI

TalibAI is a single-origin FastAPI web app for student profiles, course outlines, quizzes, study activity, tutoring, and document exports. User-owned records are stored in SQLite and are available again after login.

## Run Locally

```powershell
cd talib_ai
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python run.py
```

Open `http://127.0.0.1:8000`. Signup requires an email address and a password of at least 12 characters. Passwords are stored as scrypt hashes; login uses an opaque, HTTP-only server-side session cookie.

The app starts with an empty student profile. Add a course by uploading a text syllabus or PDF. The included offline quiz bank only covers database normalization topics. Topic-specific quiz generation, AI tutoring, syllabus extraction beyond local text parsing, document Q&A, and studio draft generation require `GEMINI_API_KEY`; `GEMINI_MODEL` defaults to `gemini-3.8-flash` and can be overridden for your account or region.

Password reset requires an SMTP service. Configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM`, `SMTP_USERNAME`, and `SMTP_PASSWORD`; reset tokens expire after 30 minutes and are single-use. Without SMTP configuration, reset requests return an explicit service error.

## Persistence

By default, the database is `backend/services/talib_ai.db` and generated documents are stored in `backend/generated_files`. Set `TALIB_DB_PATH` and `TALIB_GENERATED_DIR` to durable storage paths in deployed environments. Back up the database and generated files together.

The Dockerfile stores these paths under `/var/lib/talib-ai`; mount a persistent volume there. `render.yaml` provisions a persistent disk at `/var/data` and uses the paid `starter` plan because Render's free web service does not provide durable disks.

Existing anonymous records in a prior `talib_ai.db` are not automatically assigned to new accounts. Keep a backup before changing storage paths or migrating data.

## Tests

From this directory, run:

```powershell
python -m unittest discover -s tests -v
```

The tests use a temporary SQLite database and cover account creation, login/logout, password reset, profile and quiz persistence, per-user isolation, and focus-session validation.

## Integrations

- Gemini AI: configure `GEMINI_API_KEY` for live generation. AI features return an error when the service is unavailable instead of presenting canned output as generated content.
- Password resets: configure SMTP as above.
- YouTube learning links are search links, not embedded players or completion tracking.
- PDF library documents are extracted and stored per account. Document Q&A requires Gemini and searches extracted page text before asking the model for an answer.

## Social Sign-In

Google and Facebook OAuth are optional. Set `OAUTH_STATE_SECRET` to a stable, private random value and configure the provider client ID and secret. Set `OAUTH_COOKIE_SECURE=true` when serving over HTTPS. The social buttons appear only for providers with complete configuration.

Register these exact callback URLs in the provider consoles:

- Google: `https://YOUR_DOMAIN/api/auth/oauth/google/callback`
- Facebook: `https://YOUR_DOMAIN/api/auth/oauth/facebook/callback`

Enable the Google OpenID Connect scopes `openid`, `email`, and `profile`. Enable Facebook Login permissions `email` and `public_profile`, and set `FACEBOOK_GRAPH_VERSION` to a version supported by your app. Both providers must return an email address; Google email must be verified.

The login and signup screens show Google and Facebook options; they become clickable after the matching provider credentials are configured. First-time social sign-in creates a new TalibAI account. If the returned email already belongs to a password account, sign in with that account first, then use **Link Google** or **Link Facebook** in Account settings. Linking requires the provider to return the same email address. Provider credentials and callback URLs must be configured before those actions become available.
