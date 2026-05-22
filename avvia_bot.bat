@echo off
title Angelo Bot - F1 25
cd /d "%~dp0"
echo =========================================
echo      Avvio Angelo Bot in corso...
echo      (Non chiudere questa finestra)
echo =========================================
call .venv\Scripts\activate.bat
python main.py
pause
