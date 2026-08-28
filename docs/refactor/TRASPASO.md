# Traspaso — 2026-08-28, antes de reiniciar el PC

Cierre operativo de la sesión de auditoría y refactor. **El detalle completo está en
`ESTADO.md`**; esto es solo lo que hace falta para retomar sin releerlo.

---

## En qué estaba

Cerrando la tanda de la noche del 27-ago: el hook `do_orm_execute`, el DDL de `documentos`, el
diseño de retención de `audit_log`, la migración del paso 1.2 y el resumen de estado. **Las cinco
terminaron.** No hay nada a medio hacer.

## Qué quedó hecho y empujado

`origin/master` está en **`140b274`**. Todo lo mío está ahí, y **ninguna migración de Alembic entró**:

```
140b274  docs(refactor): al cierre, otra sesion tenia WIP sin commitear en el arbol
55063ba  docs(refactor): ESTADO.md
22a5765  docs(refactor): diseno de la retencion de audit_log (07)
17ebebb  docs(refactor): D-22 baja al DDL -- la tabla documentos existe
615aa91  feat(audit): hook do_orm_execute
```

Antes, en la misma jornada: atribución de auditoría, diffs fantasma, el regex de `tipo_migration`,
el guardián de escrituras masivas y `registrar_borrado()`. **Suite: 2266 passed, 4 skipped.**

## Qué quedó a medias

**Nada.** No hice ningún `git stash`: no tenía código a medio escribir que guardar.

Lo único “pendiente” son dos cosas **completas y deliberadamente sin empujar**:

| Qué | Dónde | Por qué no está en master |
|---|---|---|
| Paso 1.1 · índices de las 17 FK | rama **`fase1-indices-fk`** → `1787618`, revisión 120 | Empujarla **es** ejecutar la Fase 1: `start.sh` corre `alembic upgrade head` en cada arranque |
| Paso 1.2 · 32 índices redundantes | rama **`fase1-indices-redundantes`** → `61f8df6`, revisión 121, encima de la anterior | Idem |

Las dos son locales y **no tienen upstream**. Un `git push` desde ellas las desplegaría: no se
empujan sin decisión explícita de Juan.

## Qué sigue

1. **Las dos líneas del log de Railway** que confirman el arreglo de `tipo_migration`
   (`No old tipos found — already clean` y `fallas_tipo_backfill: 0 corregidas`). Es lo primero
   porque valida el arreglo ya desplegado.
2. **Decidir si arranca la Fase 1.** Las revisiones están listas; hay que renumerarlas justo antes
   de empujar (ver la advertencia de abajo).
3. Los cuatro scripts contra producción, que necesitan el `DATABASE_URL`.
4. Los cinco puntos de decisión del §3 de `ESTADO.md`.

---

## ⚠️ Advertencias para quien retome

**1 · Hay otra sesión de Claude Code en este mismo directorio, y está activa.** Al momento de
escribir esto el working tree está en su rama, **`feat/registros-proyecto-documentos`**, con dos
commits suyos por delante de `origin/master` (su feature de expediente documental, que incluye la
revisión `120_registros_proyecto_expediente`). **Su trabajo no se toca**: tiene su propio traspaso en
`docs/registros-proyecto-traspaso.md`. Yo dejé el árbol en su rama, tal como lo encontré.

**2 · La revisión 120 la reclaman dos sitios.** La migración de esa otra sesión y mi rama
`fase1-indices-fk`. Es la cuarta colisión de numeración del día (`107 → 108 → 119 → 120`). **No
renumerar por adelantado**: el número se mueve. Se renumera justo antes de empujar, comprobando el
head real.

**3 · ~~El `stash@{0}: autostash`~~ — ✅ resuelto el 2026-08-28, no era deuda.** Juan lo revisó antes
de reiniciar: es residuo del rebase que se interrumpió cuando se le cerró la consola el 2026-08-26, y
contiene el diff de `CLAUDE.md` de la Fase 0, **ya commiteado y desplegado**. No hay nada que rescatar.
Se deja sin borrar, junto a los otros tres, que tampoco son míos:

```
stash@{0}: autostash                                    ← revisado, sin nada que rescatar
stash@{1}: On master: fase-0-refactor-nucleo-20260825
stash@{2}: On main: migration-file-004
stash@{3}: On main: cambios-locales-en-progreso-20260502
```

No toqué ninguno.

**4 · Los scripts de producción viven fuera de git.** `esquema-bd-produccion/` está en la raíz del
workspace, que no es un repositorio. Los cinco scripts —`verificar_arreglo_tipo_migration.py`,
`diagnosticar_ruido_seed.py`, `recontar_indices_redundantes.py`, `verificar_auditoria_y_ceros.py` y
`extraer_historico_tarifas.py`— no están versionados: sobreviven un reinicio porque están en disco,
pero no hay copia en ningún remoto.

**5 · Dos sesiones sobre un working tree se pisan.** Pasó dos veces: la rama cambió debajo mío y dos
de mis commits terminaron en la rama ajena (se empujaron bien con `HEAD:master` y verifiqué que no
arrastraran trabajo de nadie). Mientras haya dos sesiones, **verificar `git branch --show-current`
antes de cada commit** y stagear siempre con rutas explícitas, nunca `git add -A`.
