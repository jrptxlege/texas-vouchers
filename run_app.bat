@echo off
REM Double-click to launch the TEFA data explorer in your browser.
cd /d "%~dp0"
python -m pip install -q -r requirements.txt
python -m streamlit run Home.py
