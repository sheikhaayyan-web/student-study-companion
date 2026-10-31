@echo off
title TalibAI - Student Study Companion
cd /d "%~dp0"
echo =====================================================================
echo           TALIB-AI: ALL-IN-ONE STUDENT STUDY COMPANION
echo =====================================================================
echo   [1] Initializing SQLite Academic Database...
echo   [2] Starting Adaptive AI Socratic Tutor Engine...
echo   [3] Activating 15-MCQ Learning Verification Gatekeeper...
echo   [4] Launching Spotify-Dark Liquid Glass Web Workspace...
echo =====================================================================
echo   Server is running at: http://127.0.0.1:8000
echo   Opening in your default browser...
echo =====================================================================
start http://127.0.0.1:8000
python run.py
pause
