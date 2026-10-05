@echo off
rem ==============================================================================
rem Jalankan MikroTik AI Agent di Background (Silent / Tanpa Jendela)
rem ==============================================================================
powershell -WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_background.ps1"
