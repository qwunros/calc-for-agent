@echo off
rem calc-for-agent launcher: resolves its own directory, so any cwd works.
setlocal
set "SKILL_DIR=%~dp0"
python "%SKILL_DIR%scripts\calc.py" %*
exit /b %ERRORLEVEL%
