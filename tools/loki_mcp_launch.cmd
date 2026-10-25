@echo off
rem Start LOKI's MCP server on Windows (see tools/loki_mcp_launch.sh). Claude desktop app config:
rem   {"mcpServers": {"loki": {"command": "<this checkout>\\tools\\loki_mcp_launch.cmd"}}}
cd /d "%~dp0.."
set PY=harness_data\.venv\Scripts\python.exe
if not exist "%PY%" set PY=python
if "%LOKI_DATA%"=="" if exist "%LOCALAPPDATA%\Loki\app\engine.token" set LOKI_DATA=%LOCALAPPDATA%\Loki
"%PY%" engine\loki_mcp.py %*
