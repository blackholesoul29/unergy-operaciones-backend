# Estado del refactor — 2026-08-27

Qué está listo, qué está bloqueado y qué necesita una decisión de Juan. Se escribió al cierre de la
jornada del 27 de agosto; si la fecha del último commit de este archivo es vieja, desconfiá de él y
mirá `git log`.

---

## 1 · Lo que quedó desplegado

Todo esto está en `origin/master` y se desplegó solo (Railway). **Ninguna migración de Alembic entró**:
nada de esto toca el esquema.

| Qué | Commit | Por qué importa |
|---|---|---|
| Atribución de auditoría por sesión | `fe57896` (rebase de `9228f76`) | `audit_log` acumuló **13.303 filas sin autor en 9 tablas** desde mayo, y cero con autor real. El `ContextVar` moría en la copia de contexto del threadpool de FastAPI |
| Rótulo por tarea de arranque | idem | Un solo rótulo para las 22 tareas hacía imposible atribuir un pico de ruido. Ahora cada una firma con su nombre |
| Diffs fantasma | `b3954ca` | 22 de 25 filas del histórico de tarifas eran `{"antes": 0.038, "despues": 0.038}`: `Decimal('0.0380') != 0.038` en Python |
| `tipo_migration` no reconocía el catálogo estructurado | `7d2797b` | Reescribía **5.086 fallas en cada arranque**, 23 arranques en 16 horas, sirviendo el dato equivocado por la API en la ventana entre dos tareas |
| Guardián de escrituras masivas | `8f22b6b` | Inventario de las **70 escrituras que la auditoría no ve**, 15 sobre tablas auditadas. Falla si aparece una nueva sin declarar |
| `registrar_borrado()` + los dos merges | `fe57896`, `792d9ee` | **Borrar un proyecto no dejaba rastro.** Ahora guarda el snapshot completo de la fila antes del DELETE |
| Hook `do_orm_execute` | `615aa91` | Los UPDATE/DELETE masivos dejan una fila resumen con la sentencia y cuántas filas tocó |
| `starlink_parser` docstring a raw | `ac0fe25` | `\d` inválido: hoy `SyntaxWarning`, mañana `SyntaxError` |
| `cgm_seed` habla siempre | `792d9ee` | Su silencio era ambiguo entre «reparé 0» y «reventé antes» |

**Suite: 2266 passed, 4 skipped.**

## 2 · Lo que quedó escrito y no ejecutado

| Qué | Dónde | Estado |
|---|---|---|
| `documentos` (D-22) | `03-esquema.sql` BLOQUE 9 bis | DDL completo. Salen las 5 columnas `*_url` y `falla_adjuntos` |
| Retención de `audit_log` | `07-retencion-audit-log.md` | Diseño de tres clases + purga. **Sin implementar** |
| Índices de las 17 FK (paso 1.1) | rama `fase1-indices-fk`, revisión **120** | Escrita, **sin empujar** |
| Índices redundantes (paso 1.2) | rama `fase1-indices-redundantes`, revisión **121** | Escrita, **sin empujar**. 32 DROP |
| Golden de `/comercial/proyectos-operando` | `tests/test_golden_operando.py` | Herramienta lista; **falta capturar la base** |

⚠️ **Las dos ramas de Fase 1 no se empujan porque empujarlas *es* ejecutar la fase**: `start.sh` corre
`alembic upgrade head` en cada arranque. No hay forma de tenerlas en `master` sin que se apliquen.

## 3 · Lo que necesita tu decisión

1. **Arrancar la Fase 1.** Las revisiones 120 y 121 están listas y verificadas contra la cadena. Una
   palabra y se empujan, en ese orden.
2. **Los contratos 62 y 69** (`cgm = 0` con `repr = 6.0`): ¿puede un contrato de representación tener
   CGM cero legítimo? Es pregunta para Jessica. Mientras tanto se omiten, que es la opción reversible.
3. **Las 50.860 filas de ruido**: borrarlas o no, y si se conserva la primera ráfaga (la corrección
   legítima). El diseño recomienda borrarlas todas después de guardar el resumen.
4. **`documentos`: borrado lógico o físico**, y qué hacer cuando un `RESTRICT` bloquea el borrado del
   padre. El `deleted_at` está en el DDL pero la política no.
5. **Los grupos 1 y 2 de la auditoría** (`arr_*`, `oportunidad*`): son 12 líneas, pero van **después**
   de la retención.

## 4 · Bloqueado por falta de acceso

Nada de esto se puede hacer sin producción, y no tengo el `DATABASE_URL`:

| Script | Qué contesta |
|---|---|
| `verificar_arreglo_tipo_migration.py` | Si la pelea por `tipo_id` se acabó. ⚠️ Verifica **la mitad**: `tipo_migration` escribe con `.update()` masivo y nunca dejó rastro. La otra mitad son dos líneas del log de Railway |
| `diagnosticar_ruido_seed.py` | Qué tarea generó las 50.860 filas, y si se repite por deploy o fue una vez |
| `recontar_indices_redundantes.py` | Ya corrido. Su salida alimentó la revisión 121 |
| `capturar_golden_operando.py` | Necesita un JWT del navegador o la API key de `solo_lectura` |

## 5 · Deudas abiertas que salieron de esta semana

Ninguna es del refactor; todas salieron de investigarlo.

- **`tsf_sync` cuenta mal** (`00-inventario-actual.md`): `sin_cambios` declarado y nunca incrementado.
- **`panel_contable_linea` no se puede auditar todavía**: sus recálculos borran en bloque en cinco
  sitios. ⚠️ **No hay que convertirlos a ORM** — el masivo existe porque el fila-por-fila causaba
  504 en producción. El camino es que el hook registre el borrado como fila resumen.
- **16 sitios de SQL crudo con la tabla interpolada** (`UPDATE {t} SET ...`): ni el hook ni el escáner
  pueden atribuirlos. La única cobertura posible es explícita, sitio por sitio.
- **La suite se puso 3× más lenta** (1:44 → 4:35) y el salto cae con los dos commits de upstream de
  `portafolios` («matching por nombre parecido»). No lo perseguí: no es mi cambio y la suite está verde.
- **`documentos` deja `05-impacto-campos-congelados.md` §F con una dependencia dura**: el paso 1.5
  (`IntegrityError` → 409) tiene que estar antes de la Fase 2, o borrar un cliente con documentos pasa
  a ser un 500 opaco.

## 6 · Una advertencia sobre este working tree

⚠️ **Otra sesión cambió de rama mientras yo trabajaba.** El reflog muestra un
`checkout: moving from master to feat/registros-proyecto-documentos` que yo no hice, y dos de mis
commits terminaron ahí en vez de en `master` (se empujaron igual, con `HEAD:master`, y verifiqué que
la rama no traía trabajo ajeno).

Si hay dos sesiones trabajando sobre este mismo directorio, conviene que cada una use su propio
worktree. Mientras tanto: **verificar `git branch --show-current` antes de cada commit**, que es lo
que hice el resto de la noche.
