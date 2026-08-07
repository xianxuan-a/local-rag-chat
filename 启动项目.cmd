@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_local.ps1" -FromCmd %*
set "LOCAL_RAG_EXIT_CODE=%ERRORLEVEL%"
exit /b %LOCAL_RAG_EXIT_CODE%
