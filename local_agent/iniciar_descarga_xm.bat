@echo off
title Agente local - Descarga de XM
cd /d "%~dp0"
echo.
echo  ======================================
echo    AGENTE LOCAL - DESCARGA DE XM
echo  ======================================
echo.
echo  Instalando/actualizando dependencias (solo tarda la primera vez)...
python -m pip install -q -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo  ERROR instalando dependencias. Revisa que Python este instalado y en el PATH.
    pause
    exit /b 1
)
echo.
echo  Listo. Deja esta ventana abierta mientras usas la pestana "Descarga de XM".
echo  Para detener el agente, cierra esta ventana.
echo.
python servidor.py
pause
