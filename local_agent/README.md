# Agente local — Descarga de XM

El FTP de XM (`xmftps.xm.com.co:210`) solo acepta conexiones desde IPs
conocidas — Railway no puede llegar ahí directo. Por eso la conexión real
la hace este agente, corriendo en el computador de quien lo use (que sí
tiene acceso). **Cualquiera del equipo con usuario/clave del FTP de XM
puede usarlo**, no solo Jessica.

## Uso

1. Doble clic en `iniciar_descarga_xm.bat`. La primera vez instala unas
   dependencias (tarda unos segundos); luego arranca casi al instante.
2. Deja la ventana abierta.
3. Abre la pestaña "Descarga de XM" en la plataforma, desde el mismo
   computador, y úsala normal — el navegador habla directo con este
   agente en `http://127.0.0.1:8420`. Ahí pides usuario/clave del FTP de
   XM (nunca se guardan en el servidor ni en este repo).
4. Cuando termines, cierra la ventana del agente.

Si la pestaña muestra "No se pudo conectar con el agente local", revisa
que la ventana del `.bat` siga abierta y sin errores.

## Requisitos

Python 3.10+.

## Carpeta de caché (opcional)

Los archivos que se descargan de XM se guardan en disco para no volver a
pedirlos si repites un rango — por defecto, en una carpeta bajo tu
usuario de Windows (`Documentos\Xm\Archivos_Filezilla`, o la carpeta
específica de Jessica si tu usuario de Windows es `jessi`). Para elegir
otra carpeta, copia `.env.example` a `.env` en esta misma carpeta y
edita `XM_CACHE_DIR`.
