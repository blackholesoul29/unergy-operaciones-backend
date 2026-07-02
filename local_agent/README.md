# Agente local — Descarga de XM

El FTP de XM (`xmftps.xm.com.co:210`) solo acepta conexiones desde IPs
conocidas. Railway no puede llegar ahí directo, así que la conexión real
la hace este agente, corriendo en tu computador (que sí tiene acceso,
igual que `aenc_reporte.py`).

## Uso

1. Doble clic en `iniciar_descarga_xm.bat`. La primera vez instala unas
   dependencias (tarda unos segundos); luego arranca casi al instante.
2. Deja la ventana abierta.
3. Abre la pestaña "Descarga de XM" en la plataforma, desde el mismo
   computador, y úsala normal — el navegador habla directo con este
   agente en `http://127.0.0.1:8420`.
4. Cuando termines, cierra la ventana del agente.

Si la pestaña muestra "No se pudo conectar con el agente local", revisa
que la ventana del `.bat` siga abierta y sin errores.

## Requisitos

Python 3.10+ (el mismo que ya usas para `aenc_reporte.py`).
