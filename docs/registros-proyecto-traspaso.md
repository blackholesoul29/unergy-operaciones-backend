# Traspaso — sección Registros (expediente documental)

**Escrito:** 2026-08-28, antes de un reinicio del PC.
**Estado corto:** trabajo terminado y commiteado. **No hay nada a medias, no hay stashes míos.**

---

## 1. Dónde está todo

| Repo | Rama | Commit |
|---|---|---|
| `Backend Operaciones` | `feat/registros-proyecto-documentos` | `170e6c9` |
| `unergy-operaciones-frontend` | `feat/registros-proyecto-documentos` | `b1ab43d` |

**Sobre la cadena Alembic:** el repo tiene **tres heads** (`019`, `036` y la nueva) más un
`down_revision` huérfano (`5650ccf73b5c`). Los tres preexisten en `origin/master`: esta rama
agrega **una sola** revisión. Detalle y forma de medirlo en §10 de
`docs/registros-proyecto-decisiones.md`.

**Nada fue empujado a ningún remoto.** El commit del backend contiene la migración
Alembic `120_registros_proyecto_expediente.py`, así que no debe empujarse sin revisión
explícita.

`master` en el backend quedó exactamente en `origin/master` (`140b274`), sin tocar.

---

## 2. En qué estaba

Modelar el expediente documental de un proyecto: los 28 ítems del proceso SIC/ASIC y los
10 del proceso CND, con los datos que se repiten entre documentos extraídos una sola vez.

El razonamiento completo está en **`docs/registros-proyecto-decisiones.md`** (15 decisiones
con su evidencia). Este archivo es solo el traspaso operativo.

---

## 3. Qué quedó hecho

Todo el alcance pedido, verificado:

- **Backend** — 3 tablas (`documentos_proyecto`, `documentos_proyecto_archivo`,
  `parametros_proyecto`), migración 120, 11 endpoints CRUD bajo
  `/api/v1/registros-proyecto`, catálogos de ítems y parámetros, y el mapa de
  deduplicación documento→parámetro.
- **Frontend** — `/registros` (índice con avance por proceso) y `/registros/:proyectoId`
  (selector de proceso + línea de tiempo + formularios), más la entrada en el sidebar.
- **Deduplicación** — 526 campos del formato oficial → 182 parámetros únicos, más 61 del
  CND. 171 transcripciones que el usuario deja de hacer.

**Verificación al momento de escribir esto:**

| | |
|---|---|
| Tests nuevos | 62 pasan (eran 60; la cifra original de 63 estaba mal contada) |
| Tests de registros en total | 92 pasan (incluye `registros_cnd`) |
| Suite completa del backend | 2302 pasan, 4 saltados |
| Cadena Alembic | la rama agrega **una** revisión; el repo tiene 3 heads, ver abajo |
| Build del frontend | `npm run build` OK |

---

## 4. Qué quedó a medias

**Nada.** No hay código a medio escribir ni stashes míos.

Lo que queda son **decisiones de negocio pendientes**, no código incompleto. Ninguna
bloquea el merge; todas están marcadas explícitamente en el catálogo y cubiertas por un
test que impide inventarles contenido:

1. Ítems SIC **16–23** — carpetas vacías, no sé qué contienen. Creados sin parámetros.
2. Ítem SIC **27** (plataforma de registro de frontera) — no existe el documento.
3. Numerales CND **9.5, 9.6, 9.8** — el 9.5 y 9.6 salen del enum viejo (sin respaldo
   documental); el 9.8 no aparece en ningún lado. Hay que leer el Anexo 1 del Acuerdo
   CNO 1937.
4. **Simulación** — conectarla como fuente del ítem 24.
5. **D-13** — confirmar que "nombre de la planta" (CND) y "nombre de la frontera" (SIC)
   nunca difieren. Si difieren, se separan cambiando una línea del catálogo CND.
6. **D-10** — el enum de `registros_cnd/dominio.py` rotula mal el 9.9. No lo toqué.
7. Secciones 13–15 de la hoja de vida (bitácoras) — si se quieren, van como tabla aparte.
8. `registro_parametros_93` está incompleto frente al Anexo 4 real; los campos que le
   faltan ya existen en el catálogo nuevo.

---

## 5. Qué sigue

```bash
# Backend
cd "Backend Operaciones"
git checkout feat/registros-proyecto-documentos
python -m pytest tests/test_registros_proyecto_*.py -q       # 62 tests

# Frontend
cd ../unergy-operaciones-frontend
git checkout feat/registros-proyecto-documentos
npm run build
```

Después: revisar `docs/registros-proyecto-decisiones.md` (§1, §2 y §7), decidir sobre los
8 pendientes de arriba, y recién ahí mergear y correr la migración 120.

---

## 6. Advertencias para quien retome

**Hay otra sesión de Claude Code trabajando en este mismo directorio.** Consecuencias
concretas:

- El 2026-08-27 me movió de rama sin aviso: creé
  `feat/registros-proyecto-documentos`, y al ir a commitear el repo estaba de vuelta en
  `master`. El commit aterrizó en `master` local y tuve que reubicarlo. **Verifica
  `git branch --show-current` justo antes de cada commit**, no solo al crear la rama.
- `docs/refactor/` (00–07 y `ESTADO.md`) es de esa otra sesión, no mío. Por eso este
  traspaso está aquí y no ahí.

**Archivos sucios que NO son míos y que deliberadamente no toqué** — no los commitees ni
los guardes en un stash, son trabajo en curso ajeno:

- Backend, sin seguimiento: `Guía de inicio — Plataforma Operaciones.md`,
  `backend_structure.html`, `docs/plan-backend.md`,
  `scripts/cargar_fronteras_comerciales.py`, `scripts/create_purchase_contracts.py`,
  `scripts/pruebas_api_operando/`
- Frontend, modificado: `src/views/Servicios/ServiciosUnificadoView.vue` (+75 líneas)

Sobreviven al reinicio sin más: están en disco y un reinicio no borra el árbol de trabajo.
