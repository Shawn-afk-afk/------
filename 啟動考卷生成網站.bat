@echo off
chcp 65001 >nul
title ExamCrafter AI - 多科目智慧教材出卷系統

echo =======================================================
echo   ExamCrafter AI 智慧教材出卷與評量系統正在啟動...
echo   本系統支援五大科目：國文、英文、地理、歷史、公民
echo =======================================================
echo.

cd /d "%~dp0"

echo 正在檢查後端環境與本機 Ollama 狀態...
start http://localhost:8000
python app.py

pause
