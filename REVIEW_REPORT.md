# REVIEW_REPORT — Plataforma Operaciones (Backend)

**Fecha:** 2026-06-09 (sesión de revisión nocturna)
**Alcance:** `Backend Operaciones` (FastAPI). El frontend no se tocó (working tree limpio).
**Baseline de tests:** 70 passing → **80 passing** tras esta sesión (10 golden tests nuevos).
**Cambios BREAKING:** **ninguno**. No se modificaron esquemas, contratos de API ni formatos de datos.

---

## 1. Resumen ejecutivo

Se revisó línea por línea el backend priorizando **corrección de números operativos** (el bug más caro de esta plataforma). Disciplina aplicada: como esto se despliega a producción mañana, **solo se corrigieron bugs cuyo arreglo es claramente correcto y testeable**, con golden tests que lo prueban. Los hallazgos más delicados —sobre todo la **lógica financiera de liquidaciones** y los **cambios de comportamiento de alarmas**— se **documentan** aquí en vez de cambiarse a ciegas de noche, porque requieren validación de dominio (Jessica / Laura) y un fix equivocado tendría costo real.

El bug de mayor impacto operativo corregido: `generacion_solar.py` calculaba "hoy" con la fecha **UTC del servidor** (Railway) en vez de la fecha de **Bogotá (UTC-5)**, por lo que cada tarde/noche la "generación de hoy" salía casi en cero.

No hay funcionalidades de IA/LLM en el código (sin openai/anthropic/langchain), por lo que **Phase 3 (AI) no aplica**; se incluyen recomendaciones de gobernanza para el agente "Samantha".

---

## 2. Cambios aplicados (corrección)

| # | Archivo | Líneas | Severidad | Qué se hizo |
|---|---------|--------|-----------|-------------|
| 1 | `app/api/v1/generacion_solar.py` | imports + helper + ~14 usos | **CRITICAL** | Bug de zona horaria: `date.today()` (UTC del servidor) → `_hoy_col()` (Bogotá UTC-5). "Generación de hoy", claves de caché y ventanas de telemetría ahora usan el día de Colombia. |
| 2 | `app/api/v1/generacion_solar.py` | `_fetch_kwh` (medidor) | **CRITICAL** | Normalización de unidad MWh: `unit == "MWh"` exacto → `unit.strip().lower() == "mwh"`. Evita error de 1000× si la etiqueta varía de mayúsculas. |
| 3 | `app/api/v1/cumplimiento.py` | nuevo `_monthly_mwh_from_records` + `_fetch_month` | **CRITICAL** | Contador acumulado: (a) ignora lecturas `None` en vez de forzarlas a 0 (antes podía reportar 0 MWh el mes); (b) suma de deltas positivos en vez de heurística de reinicio. **Idéntico a (último−primero) en meses sanos**, solo corrige reinicios/nulos. Extraído a función pura testeable. |
| 4 | `app/api/v1/cumplimiento.py` | `_monthly_mwh_from_records` | HIGH | `ultimo_dia` se calcula normalizando el timestamp a Colombia antes de leer `.day`, evitando que ruede al mes siguiente en lecturas de fin de mes en UTC. |
| 5 | `app/api/v1/generacion_solar.py` | `data_completeness` | HIGH | `days_in_month` por `calendar.monthrange()` (antes una expresión frágil con `else 31`). |
| 6 | `app/api/v1/generacion_solar.py` | `fleet_summary`, `fleet_minifarms` | MEDIUM | Clave rígida `s["project_id"]` → `s.get("project_id") or s.get("id")` (mismo patrón defensivo del resto del módulo). Evitaba KeyError / todos los proyectos en 0. |
| 7 | `app/api/v1/generacion.py` | `resumen_por_proyecto` | MEDIUM | `if r.total_kwh_real` → `is not None`: una generación real de 0.0 ya no se muestra como `null`. |
| 8 | `app/core/config.py` | `SECRET_KEY` validator | **HIGH (seguridad)** | Fail-closed: en producción, `SECRET_KEY` vacío ahora **lanza error en el arranque** (antes solo advertía → cualquiera podía forjar JWT). No rompe un deploy ya configurado. |
| 9 | `app/api/v1/monitoreo.py` | `/auth/send-code` | MEDIUM (seguridad) | OTP de login con `secrets.choice` (RNG criptográfico) en vez de `random` (PRNG predecible). |
| 10 | `app/services/mgs/alarm_engine.py` | `evaluate` | HIGH | Debounce de PLANTA_CAIDA: `== DEBOUNCE_POLLS` → `>= DEBOUNCE_POLLS`. Con `==`, si un sondeo se saltaba, la alarma de una planta realmente caída **nunca disparaba**. El guard `not in proj_alarms` ya evita duplicados. |
| 11 | `app/api/v1/monitoreo.py` | `_solenium_inverters` | HIGH | Limpiar token cacheado también en 401 de `/inverter/` (antes un token vencido se reusaba hasta 20h y todos los sondeos seguían fallando). |
| 12 | `app/api/v1/monitoreo.py` | `_action_get_generation` | MEDIUM | `except: pass` → `logger.exception(...)` al parsear simulación P90/P50 (antes el dashboard mostraba generación sin línea base y sin señal del fallo). Se agregó logger de módulo. |
| 13 | `.gitignore` | — | HIGH (higiene) | Ignorar copias/artefactos locales (`backend/`, `frontend/` con node_modules, `main`, `fallas-unergy/`, `scripts/_tmp_*`) para no commitearlos por accidente. |
| 14 | `tests/test_metric_calculations.py` | nuevo | — | 10 golden tests: contador monótono, reinicio, lecturas nulas, borde de mes, y la conversión de zona horaria Bogotá. |

**Verificación:** `python -m pytest -q` → **80 passed**. Todos los módulos tocados importan sin error.

---

## 3. Hallazgos documentados (NO cambiados — requieren decisión de dominio)

> Regla aplicada: *act if reversible, ask if not*. Estos tocan dinero o comportamiento de alertas en producción; el fix correcto depende de reglas de negocio que no puedo validar solo de noche.

### 3.1 FINANCIERO — `liquidaciones.py` (máxima prioridad de revisión humana)
Estos cálculos producen cifras de dinero por inversionista. **No tocar sin Jessica.**

- **`vista_por_inversionista` calcula facturas por resta y la clampa:** `total_facturas_cop = max(0.0, ingreso_bruto - valor_neto)` (~L876). Si `valor_neto > ingreso_bruto` (créditos/ajustes), la deducción real se oculta y se reporta 0. **Recomendación:** sumar las filas reales de `LiquidacionFactura` (como hace `vista_por_proyecto`), sin clamp.
- **`ingreso_bruto` con allow-list incompleta** (~L866): solo cuenta `ingreso_bruto/despacho/ventas_en_bolsa`, omite `otro_ingreso` y `redistribucion_ingresos` que el loader sí genera → subreporta ingresos y alimenta la resta anterior.
- **Posible doble-conteo cross-investor** (~L858): cuando no hay mandato "Total", cae a sumar mandatos de *todos* los inversionistas y atribuye el total del proyecto a *cada* fila de inversionista.
- **`auto_populate_xm_datos` puede persistir `tarifa = 0`** (~L1112): si no hay precio de bolsa/PPA para el periodo, registra `ingresos_energia_cop = 0` y avanza el estado. Un mes con generación real queda con ingreso 0. **Recomendación:** si `tarifa == 0`, no persistir y devolver advertencia.
- **Acumulación de moneda en `float`** en las vistas de agregación (debería ser `Decimal`, como ya hace `om_calculator._redondear`).
- **`auto_populate_xm_datos`: lookup de tarifa PPA sin `ORDER BY`** (~L1091) → tarifa no determinista para plantas en múltiples contratos (caso "duplicado").

### 3.2 CUMPLIMIENTO — proyección y agregación (revisión de negocio)
- **Denominador de proyección usa `today.day`** en vez de los días con datos (`dia_max_datos`). Si la API está atrasada (último dato día 5, hoy día 9) la proyección **subestima ~40%**. Es una *estimación*, por eso se documenta en vez de cambiarla; el denominador correcto depende de la intención (por planta vs agregado).
- **Baseline de inicio de mes:** `_fetch_month` toma como primer valor la primera lectura *dentro* del mes, no el cierre del mes anterior → puede subcontar el primer día. Corregirlo implica consultar el mes previo (cambio de query) — pendiente de decisión.
- **`_fetch_recent_avg` usa `max−min` por día** (~L188): erróneo si el contador se reinicia intradía; los días parciales de borde sesgan el promedio. Mismo patrón de "suma de deltas positivos" lo resolvería.

### 3.3 ALARMAS / TELEMETRÍA — `desconexion.py`, `monitoreo.py` (riesgo de spam/silencio)
Las alarmas van a WhatsApp/email; cambiar la lógica de detección de noche podría generar spam o silenciar. Documentado para revisión con Laura:
- **Sin chequeo de frescura:** `_latest_meter_kw` devuelve el último valor no-nulo aunque tenga horas. Una planta cuyo medidor murió muestra el valor viejo como "actual". **Recomendación:** exigir que el último punto esté dentro de una ventana (p.ej. ≤30 min).
- **`abs()` en lectura de medidor** puede enmascarar consumo parásito como "generando".
- **Reset de `previous_states` fuera de ventana solar** puede disparar RECUPERACION espuria en la mañana.
- **Riesgo de wedge del scheduler:** si un cliente externo (Quoia/Solenium/Gaia) no tiene timeout, `_poll_running` queda en `True` para siempre y **no se evalúan más alarmas, en silencio**. Verificar timeouts en los clientes MGS y considerar un watchdog.

### 3.4 GENERACIÓN — `generacion_solar.py` (documentado)
- **null-vs-zero en `_fetch_kwh` (inversor):** un error/timeout del inversor deja `kwh = 0.0` y se cae al medidor mal etiquetado; un 0 real (planta caída) se sustituye por el medidor. **Recomendación:** rastrear presencia (`None` vs `0.0`) y emitir `fuente="sin_dato"` cuando ninguna fuente tiene dato, en vez de 0.
- **Heurística de unidad W/kW por magnitud** (`>500 ⇒ W`) en `_extract_ac_metrics`: mal-etiqueta inversores grandes/pequeños. La unidad debería venir del campo de la API, no de un umbral.
- **Excepciones tragadas → 0** en `resumen_dia`/`_fetch_detail`: una llamada que falla cae al fondo del ranking como "0", indistinguible de una planta ociosa.

---

## 4. Seguridad (resumen separado)

**Estado general: sólido.** Contraseñas con bcrypt+salt, SQL siempre parametrizado (sin inyección), JWT fijado a HS256 con expiración, API keys hasheadas SHA-256, sin secretos hardcodeados en archivos versionados, `.env` correctamente gitignoreado.

| Hallazgo | Severidad | Estado |
|----------|-----------|--------|
| `SECRET_KEY` vacío solo advertía | HIGH | **CORREGIDO** (fail-closed en prod) |
| OTP con `random` (PRNG) | MEDIUM | **CORREGIDO** (`secrets`) |
| OTP sin rate-limit / cap de intentos | MEDIUM | **Documentado** — código 6 dígitos brute-forceable; agregar cap de ~5 intentos + rate-limit por email/IP |
| CORS `allow_origin_regex=r"https://.*"` con credenciales | HIGH | **Documentado, NO cambiado** — restringir a allow-list rompería un origen del frontend que no puedo verificar de noche; mitigado en parte porque el auth es JWT-en-header. Revisar y cambiar a `https://.*\.unergy\.io$` + Vercel. |
| `/docs` y `/redoc` siempre activos | MEDIUM | **Documentado** — gate por `ENVIRONMENT` en prod |
| `int(payload.get("sub"))` sin guard → 500 | LOW | **Documentado** — envolver en try/except → 401 |
| Tokens móviles de 30 días sin revocación | LOW | **Documentado** — aceptable; considerar jti/blacklist para robo de dispositivo |

---

## 5. Base de datos (Phase 4)

- **Migraciones:** existe sistema versionado (`alembic/versions/` 001–009) **y** `init_db.py` con `ALTER ... ADD COLUMN IF NOT EXISTS` idempotente. Enfoque dual ya establecido (ver memoria del equipo). Regla del equipo: columna nueva = ALTER IF NOT EXISTS; tabla nueva = modelo + create_all.
- **Inyección SQL:** no se encontró. Todos los `text(...)` usan parámetros ligados; los pocos f-strings en SQL interpolan solo enteros forzados o fragmentos estáticos del servidor.
- **Telemetría time-series:** la generación cruda vive en la API externa de Unergy (no se persiste en tabla local en los flujos revisados); `generacion_diaria` guarda agregados diarios. Conviene confirmar índices en `(proyecto_id, fecha)` para los hot-paths de dashboard.
- **Idempotencia de ingesta:** la generación de `codigo_interno` por `MAX(id)+1` / `count+1` (scheduler + monitoreo) tiene riesgo de colisión bajo concurrencia. **Recomendación:** usar secuencia DB o `RETURNING id`.

---

## 6. Gobernanza del contribuidor "Samantha" (en vez de Phase 3 AI)

No hay features de IA en runtime. Pero dado que un agente autónomo extiende este código de noche, se recomienda:
- **Rama + PR obligatorio**, nunca push directo a `master` (ya hay ramas `claude/*`, `copilot/*`, `nightwatch/*` en el remoto — buena señal).
- **Gate de tests:** CI debe correr `pytest` y bloquear merge si fallan. Los golden tests de cálculo (`tests/test_metric_calculations.py`) son la red de seguridad para los números.
- **Requiere revisión humana (no autónomo):** migraciones de esquema, `auth.py`/`security.py`, y **toda** la lógica de `liquidaciones.py` (dinero). Esto coincide con el mandato del negocio.
- **Permitido autónomo:** vistas/endpoints read-only, mejoras de logging, tests, refactors con tests verdes.

---

## 7. Top 5 mejoras estructurales (próxima iteración)

1. **Centralizar la zona horaria.** Crear `app/core/tz.py` con `COL_TZ`, `hoy_col()`, `now_col()` y usarlo en todos los módulos. Hoy `_COL_TZ` está redefinido en `fallas.py`, `cumplimiento.py`, `desconexion.py`, `generacion_solar.py` — fuente de los bugs de UTC.
2. **Extraer las matemáticas de métricas a funciones puras** (como se hizo con `_monthly_mwh_from_records`) y cubrirlas con golden tests. Hoy el cálculo está mezclado con I/O HTTP y es difícil de probar; PR/cumplimiento/generación deberían tener un módulo de cálculo puro.
3. **Modelo explícito de null-vs-zero en telemetría.** Un tipo/convención claro (`sin_dato` vs `0.0`) en todo el pipeline de generación y alarmas; nunca `or 0` sobre lecturas. Es el patrón de bug recurrente más peligroso.
4. **Reescribir `vista_por_inversionista` con `Decimal` y sumas reales** (no por resta ni allow-lists frágiles), con golden tests financieros acordados con Jessica.
5. **Robustez del scheduler:** timeouts explícitos en todos los clientes MGS + watchdog que resetee `_poll_running`, y reemplazar `MAX(id)+1` por secuencias. Una caída silenciosa del scheduler significa cero alarmas sin que nadie se entere.

---

*Generado en sesión de revisión nocturna. Cambios corregidos verificados con `pytest` (80 passed). Los ítems de §3 y §4 quedan para revisión humana antes de tocarlos.*
