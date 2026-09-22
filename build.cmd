@echo off
rem Double-click friendly wrapper: bypasses PowerShell execution policy restrictions.
rem All real logic lives in build.ps1 (this file is intentionally ASCII-only to
rem avoid console codepage issues).
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1" %*
endlocal
