# 06 · Plan de corrección y migración

**Qué es esto:** cómo se llega del esquema de hoy al de `03-esquema.sql` sin perder historia y sin romper
el front ni la API externa. Ocho fases ordenadas de menor a mayor riesgo, cada una con su verificación y
su rollback.
**Decisiones ya cerradas por ti (2026-08-24):** `ppa.id` conserva su valor original · la consumidora
externa se adapta, no bloquea · **frontera sigue pendiente y no se toca en ninguna fase**.
**Regla que gobierna todo:** ninguna fase avanza sin que la anterior esté verificada en producción.
**Actualizado el 2026-08-26:** hay un **apéndice al final** con la Fase 0 ya ejecutada (commit
`383bf1e`, local) y la **Fase 1 detallada paso por paso**.

---

## 1 · Lo que se conserva intacto

Va primero porque es la mayor parte del sistema, y porque saber qué **no** se toca es lo que hace el plan
ejecutable. Ninguna fase de este plan modifica nada de esta lista.

| Se conserva | Por qué |
|---|---|
| **Todo el dominio comercial / CRM** (`oportunidades`, `oportunidad_ofertas`, sus puentes e historial) | Fuera de alcance, **y es el productor de la API congelada**. Que no se toque es lo que hace barato preservar el contrato |
| **Cumplimiento / MEM** (`ppa_tarifas`, `ppa_compromisos_energia`, `cumplimiento_mensual`, `asic_*`, `gescon_*`, `clasificacion_energia_mensual`, `ipp_mensual`) | Fuera de alcance. Solo cambian de FK padre en la Fase 6, sin tocar sus columnas ni su lógica |
| **Liquidaciones y panel contable** | Fuera de alcance. El acople se prepara, no se ejecuta (§6.4 de `04-mapeo.md`) |
| **`registro_conexion` y sus 7 satélites** | Es el único subdominio que ya hace bien el historial de estados. Es el patrón que se copia |
| **Los 5 catálogos `fallas_cat_*`** | Funcionan, con UNIQUE en `codigo`, y Laura ya los administra. Solo se les agrega un índice |
| **`fronteras` y todo lo que cuelga de ella** | Decisión D-06 pendiente. **Ninguna tabla nueva la referencia**, así que el plan entero corre sin ella |
| **`portafolios`, `contactos`, `proyecto_area_contacto`** | Modelan bien lo suyo, con los UNIQUE correctos |
| **Series de tiempo** (`generacion_diaria`, `precios_bolsa_*`, `reporte_energia_*`, clima) | Correctamente modeladas |
| **Arriendos (`arr_*`), O&M (`om_*`), mandatos, garantías XM, Starlink facturación** | Fuera de alcance. `arr_proyectos` y `finanzas_mandatos` quedan como deuda señalada, no intervenida |
| **Auth, `api_keys`, `audit_log`, `usuarios`** | Infraestructura. El endurecimiento de scopes de API key es una tarea de seguridad aparte |
| **Las 4 taxonomías de falla en paralelo** (`tipo_id`, `tipo_libre`, `categoria_codigo`, `subtipo_codigo`) | Unificarlas es una decisión de dominio que necesita a Laura, no un mapeo. Se conservan las cuatro |

---

## 2 · Las tres restricciones que mandan sobre el plan

No son preferencias: son propiedades del entorno, y cada una descarta una forma habitual de migrar.

### 2.1 No hay staging

Auto-deploy de `master` a Railway. **Cada fase se estrena en producción**, con un consumidor externo
enganchado por API key. De ahí dos consecuencias en todas las fases: **todo es aditivo antes de ser
destructivo**, y **cada migración es idempotente** para poder repetirla sin daño.

### 2.2 Producción no se escribe desde local

El `.env` local apunta a `localhost/operaciones` (`CLAUDE.md:31-32`). La única vía de escritura en prod es
código que corra **dentro del contenedor**. Eso fija cómo se aplica cada cosa:

| Tipo de cambio | Mecanismo | Cuándo corre |
|---|---|---|
| **Esquema** (CREATE, ALTER, índices, constraints) | revisión de **Alembic** con los helpers de `alembic_idempotencia.py` | `start.sh:7`, antes de uvicorn |
| **Datos** (backfills, migraciones de filas) | tarea **`*_seed` idempotente** en `_deferred_init` | hilo demonio, después de que la app está arriba |
| **Medición** (contar, detectar conflictos) | tarea `*_report` que **solo lee y loguea** | ídem |

Los backfills grandes **no** van en Alembic: retrasarían el arranque y su fallo es silencioso
(`start.sh` solo imprime `WARNING`). Van como `*_seed`, que es el patrón que la casa ya usa para
`_run_catalog_seed`, `_run_inversores_minigranja_seed`, `_run_ppa_responsables_seed` y 5 más.

### 2.3 ⚠️ Los tests corren en SQLite, y el modelo nuevo usa Postgres de verdad

Esto es la consecuencia incómoda de las decisiones D-08 y D-09, y hay que decirla antes de empezar.
Los tests usan `sqlite:///:memory:` en **104 de los 130 archivos** de `tests/`, con `@compiles` para traducir
`JSONB → TEXT` y `BigInteger → INTEGER`. **Cuatro piezas del modelo nuevo no tienen equivalente en SQLite:**

| Pieza | Por qué no corre en SQLite |
|---|---|
| `DATERANGE` + `EXCLUDE USING gist` | no existen; tampoco `btree_gist` |
| `CONSTRAINT TRIGGER ... DEFERRABLE` de la suma 100 % | SQLite no tiene constraint triggers diferidos |
| `GENERATED ALWAYS AS ... STORED` (`equipos.garantia_vence_el`) | soportado desde SQLite 3.31, pero con `date + integer` la semántica no coincide |
| Índices parciales con enums (`WHERE estado IN (...)`) | el enum llega como TEXT; funciona, pero no prueba nada del enum |

**Qué hago con eso, en orden de preferencia:**

1. **Duplicar el invariante en la capa de aplicación** y testear ahí lo que la BD garantiza: un validador
   Pydantic/servicio que verifique suma 100 % y no-solapamiento. Es redundante a propósito: la BD es la
   garantía, el validador es lo testeable y da un 409 legible en vez de un error de constraint.
2. **Un archivo de tests marcado `@pytest.mark.postgres`**, que se salta si no hay `DATABASE_URL` de
   Postgres, para lo que solo se puede probar contra PG real. Hoy se saltaría siempre en CI, y queda dicho.
3. ⚠️ **Lo que no voy a fingir:** con el harness actual, **el trigger de suma 100 % y el EXCLUDE de
   vigencias no quedan cubiertos por los tests automáticos.** Se verifican a mano en producción con las
   consultas de control de §7.2, en la Fase 5. Si quieres cobertura real, hace falta Postgres en CI —
   `services: postgres` en el workflow de GitHub Actions es el camino más corto, y es una tarea aparte.

---

## 3 · Las ocho fases

Riesgo creciente. Cada fila de «verificación» es una condición que se comprueba **en producción** antes de
seguir.

### Fase 0 · Poner el mecanismo de esquema en orden — riesgo BAJO

No cambia ni una tabla del modelo. Ordena cómo se aplican los cambios, porque las siete fases siguientes
dependen de que Alembic sea confiable.

| Paso | Qué | Detalle |
|---|---|---|
| 0.1 | **Medir producción** | `python comparar_con_prod.py "<DATABASE_URL>"`. Responde las dos preguntas abiertas: ¿existe una tabla `equipos` (colisión de nombre)? ¿siguen vivas las 14 tablas del hallazgo F3? **Nada más arranca hasta tener esta salida** |
| 0.2 | Quitar de `_PENDING_DDLS` los `CREATE TABLE` de las **16 tablas que ya tienen modelo ORM** | Hallazgo F4: el DDL crudo declara menos columnas que el modelo. Hoy no rompe porque `create_all()` corre primero, pero es una bomba para una BD nueva |
| 0.3 | Sacar los **47 `UPDATE`/`INSERT`** de `_PENDING_DDLS` a tareas `*_seed` | Hallazgo F12: son datos corriendo en cada arranque disfrazados de DDL |
| 0.4 | Quitar el `CREATE TABLE gmail_credenciales` y después `DROP` | Hallazgo F2: tabla zombie que revive en cada deploy |
| 0.5 | Hacer **visible** el fallo de Alembic | `start.sh:7` se lo traga con un `WARNING`. Que siga sin abortar el arranque, pero que el fallo quede en un log que alguien mire |
| 0.6 | Actualizar `CLAUDE.md:28` y `backend.md:70` | Los dos dicen que Alembic no se usa. **Es falso** y es la razón por la que casi diseñé la Fase 0 al revés |

**Verificación:** deploy verde; en los logs de Railway aparece `alembic upgrade head` sin error;
`python -m pytest -q` en verde; el conteo de tablas de prod no cambió salvo `gmail_credenciales`.
**Rollback:** revertir el commit. Ningún paso escribe datos de negocio.

### Fase 1 · Higiene de integridad — riesgo BAJO / MEDIO

Aditivo sobre el esquema actual. Mejora lo que hay sin moverlo, y baja el ruido antes de agregar tablas.

| Paso | Qué |
|---|---|
| 1.1 | **Índice en las 18 FK que no lo tienen** (lista completa en `00-inventario-actual.md` §11.H) |
| 1.2 | Borrar **uno de cada uno de los 46 pares de índices redundantes** |
| 1.3 | FK faltantes donde la relación es real: `alarma_estado.proyecto_id → proyectos`, `panel_soporte.created_by_id → usuarios`. `audit_log.registro_id` es polimórfica a propósito: **no lleva FK** |
| 1.4 | ⚠️ **`ON DELETE` en las 80 FK que no lo declaran.** Regla: `CASCADE` cuando el hijo no tiene vida propia (líneas de detalle, seguimientos), `SET NULL` cuando sí (documentos, contactos), `RESTRICT` cuando el borrado debe fallar a propósito |
| 1.5 | Capturar `IntegrityError` en la API y responder **409 con detalle** en vez de 500 |

⚠️ **1.4 es el único paso de esta fase con riesgo real:** cambia el comportamiento del borrado. Un
`CASCADE` mal puesto convierte un error de integridad —molesto pero seguro— en un borrado silencioso en
cascada. Se hace **FK por FK, con la decisión escrita en el commit**, no con un script masivo.

**Verificación:** `EXPLAIN` de las consultas de Cumplimiento antes y después (1.1 debería mejorarlas);
un `DELETE` de prueba en una fila desechable de cada tabla con `CASCADE` nuevo, dentro de una transacción
con `ROLLBACK`; tests verdes.
**Rollback:** los índices se recrean; los `ON DELETE` se revierten con otro `ALTER`. Reversible al 100 %.

### Fase 2 · Crear las tablas nuevas, vacías — riesgo MUY BAJO

19 tablas nuevas más la extensión, el trigger y las 4 vistas. **Nadie las lee ni las escribe todavía**, así
que el riesgo es casi solo el de arranque.

Orden dentro de la revisión de Alembic —y la extensión va **en esta misma revisión**, no en una previa:
`CREATE EXTENSION btree_gist` → catálogos (`fabricantes`,
`equipo_tipos`) → red (`red_circuitos`, `red_puntos_conexion`) → satélites de proyecto → equipos →
propiedad → contratos → satélites de falla → función y trigger → índices → vistas → seeds de catálogo
(13 `equipo_tipos`, 4 `fallas_cat_estados` con `ON CONFLICT DO NOTHING`).

⚠️ **Dos condiciones de entrada:**
- Si 0.1 encontró una tabla `equipos` en producción: **decidir antes** entre borrarla (si está en 0 filas)
  o renombrar la del modelo. **No se ejecuta un `CREATE TABLE equipos` a ciegas.**
- ✅ **`CREATE EXTENSION btree_gist` ya está probado, dos veces** (2026-08-26/27, ver D-24). Contra
  **producción**: el rol de Railway **sí tiene permiso**, verificado dentro de una transacción con
  `ROLLBACK`. Y contra la base local: el `EXCLUDE` con un enum acepta periodos consecutivos y rechaza
  los solapados. **Deja de ser una condición de entrada.** El `CREATE EXTENSION` va **dentro de la misma
  revisión que crea las tablas con `EXCLUDE`**, antes de la primera de ellas — no en una revisión aparte,
  que era la precaución de cuando no se sabía si el permiso existía.

**Verificación:** las 19 tablas existen y están en 0 filas; `app.main` importa; la app arranca; las 4
vistas responden `SELECT ... LIMIT 1`; el trigger existe (`\dft` / `pg_trigger`); tests verdes; **el
endpoint `/comercial/proyectos-operando` devuelve exactamente lo mismo que antes** (golden test de §7).
**Rollback:** `DROP` de las 19 tablas. Están vacías y nada las referencia: es limpio.

### Fase 3 · Migrar datos hacia las tablas nuevas, con doble escritura — riesgo MEDIO

Las tablas viejas **siguen siendo la fuente de verdad**. Las nuevas se llenan y se mantienen al día, pero
nadie las lee. Es la fase que compra la reversibilidad de todo lo que viene después.

Cada migración es una tarea `*_seed` idempotente que loguea `procesadas / creadas / omitidas / conflictos`.

| Script | Origen → destino | Filas | Nota |
|---|---|---|---|
| `_run_simulacion_seed` | `proyectos.p50/p90/p99_mensual_kwh` → `proyecto_simulacion` | 39 plantas × hasta 36 | Usa `serie_mensual_kwh()` (`app/utils/series_mensuales.py`), que ya maneja el caso «JSONB que llegó como texto» |
| `_run_gen_promedio_seed` | 6 columnas `gen_promedio_*` → `proyecto_generacion_promedio` | 48 | Copia directa 1:1 |
| `_run_ident_externa_seed` | 7 columnas de id → `proyecto_identificacion_externa` | ~194 × 1-7 | Una fila por columna no nula. Un choque en `UNIQUE (sistema, clave)` **es un hallazgo, no un error**: significa dos plantas con la misma clave externa. Se loguea y se omite |
| `_run_equipos_inversores_seed` | `proyecto_inversores` → `equipos` tipo `inversor` | 715 | `potencia_nominal_kw` y `tipo` van a `especificaciones`. `activo=false` → `dado_de_baja`. `marca/modelo/numero_serie` están al 0 %: nada que copiar |
| `_run_equipos_ficha_seed` | `proyecto_info_tecnica` (marcas y cantidades) → `equipos` + `fabricantes` | 110 | Crea fabricantes por nombre normalizado. **`equipo_modelo_id` queda NULL**: el modelo concreto no está en los datos. El texto original se preserva en `especificaciones.origen_texto` |
| `_run_falla_proyectos_seed` | `fallas.proyecto_id` → `falla_proyectos` | 6 478 | Una fila por falla. Mecánico, sin pérdida |
| `_run_falla_adjuntos_seed` | `fallas.fotos_urls` → `falla_adjuntos` | ~5 324 | Reusa `Falla.fotos_lista` (`app/models/fallas.py:198-218`), que ya maneja los 3 formatos legados incluida la doble codificación |
| `_run_falla_historial_seed` | `fallas_seguimientos` → `falla_estado_historial` | 1 134 | `estado_anterior_id` queda **NULL** en las filas históricas: nunca se guardó. Se documenta, no se infiere |
| `_run_proyecto_estado_seed` | `proyectos.estado` → `proyecto_estado_historial` | 194 | Una fila por planta, vigencia desde `created_at`, sin fin, `motivo='migracion: estado inicial'`. **No se inventa el pasado** |

**Doble escritura:** mientras dure la fase, los endpoints que escriben en las tablas viejas escriben
también en la nueva. Se implementa en el servicio, no en la vista, y se marca con un flag de configuración
para poder apagarla.

**Verificación por script:** conteo origen vs. destino; para `falla_proyectos`, `COUNT(*) = 6478` exacto;
re-ejecutar la tarea y comprobar que `creadas = 0` (idempotencia); y una consulta de reconciliación por
script que compare el valor viejo con el nuevo en 10 filas al azar.
**Rollback:** `TRUNCATE` de la tabla nueva y apagar la doble escritura. Las viejas nunca se tocaron.

### Fase 4 · Cambiar la lectura, con la salida congelada — riesgo MEDIO / ALTO

Aquí se juega el contrato. La API empieza a leer de las tablas nuevas y **debe devolver exactamente lo
mismo**, byte a byte.

| Paso | Qué |
|---|---|
| 4.1 | **Vistas de compatibilidad** para las columnas que se movieron: una vista o propiedad que exponga `sub_project`, `p50_mensual_kwh`, `gen_mensual_promedio_mwh`, `url_ubicacion` desde su nuevo origen |
| 4.2 | `app/services/comercial.py` lee de las tablas nuevas. **No se reescribe el servicio**: solo cambian las fuentes de `_gen_promedio()`, `_simulacion()`, `api_id_unergy()` y `_nodo_proyecto()` |
| 4.3 | Mapeo de nombre en la capa de salida: la columna es `potencia_dc_kwp`, el campo sigue siendo `potencia_instalada_kwp` |
| 4.4 | Apagar la doble escritura: las tablas nuevas pasan a ser la fuente de verdad |

⚠️ **Tres invariantes que los golden tests tienen que probar, y que están en `05` §4:**
`operador_red_id = null` sigue siendo **señal** de «no está en el catálogo» y no se rellena ·
los arrays de simulación conservan su longitud real y `p50_anual_kwh` sigue siendo `null` si no hay 12
meses · `energia_promedio_detalle` sigue saliendo con los 4 campos en `null` cuando el origen es
`estimado` o `declarado`.

**Verificación:** el golden test de §7 pasa contra la respuesta capturada antes de la Fase 3;
`GET /comercial/proyectos-operando` en producción devuelve el mismo hash de respuesta; las 15 vistas del
front que tocan proyectos se abren y muestran datos.
**Rollback:** revertir el commit del servicio. Los datos viejos siguen ahí y la doble escritura los mantuvo
al día, así que volver atrás es un deploy, no una restauración.

### Fase 5 · Las tres migraciones que necesitan una decisión humana — riesgo ALTO por los datos

No por el código: por lo que la medición va a encontrar. Cada una arranca con una tarea `*_report` que
**solo lee y loguea**, y se detiene ahí hasta que decidas.

#### 5.1 `falla_inversores` → `falla_equipos` (4 213 filas, FK al 0,3 %)

**Medir primero:** cuántas de las 4 213 filas cruzan por `(proyecto_id, nombre)` contra un `equipos` de
tipo inversor. Las 11 que tienen `proyecto_inversor_id` son mapeo directo.
**Lo que no cruce no se puede migrar a una FK.** Va a `falla_equipos.detalle` con el texto original
preservado, o se queda sin fila y el texto vive en la falla. **Decisión tuya cuando veas el número.**

#### 5.2 `proyecto_inversionistas` → `proyecto_composiciones` (115 filas)

Tres problemas, y el trigger de suma 100 % **rechazará la carga** si no se resuelven antes:

| Problema | Medición | Qué hace falta |
|---|---|---|
| 73 de 115 filas sin `fecha_inicio` (36,5 %) | listar cuáles | elegir un inicio. La única opción defendible es `proyectos.created_at`, marcada con `motivo='migracion: inicio desconocido'`. **Es una suposición, no un dato** |
| Proyectos cuyas participaciones **no suman 100** | `SELECT proyecto_id, SUM(porcentaje_participacion) FROM proyecto_inversionistas GROUP BY 1 HAVING SUM(...) <> 100` | decidir uno por uno. **No se automatiza** |
| Agrupar filas en composiciones | — | con vigencias incompletas, lo único posible es **una composición por proyecto**, vigente desde el inicio elegido y sin fin |

**Los proyectos que no cumplan quedan en cuarentena**: no se migran, se listan en el log, y
`proyecto_inversionistas` sigue siendo su fuente hasta que se corrijan. Nada se borra.

#### 5.3 `operador_red` — backfill antes de cualquier borrado

`proyectos.operador_red` (texto, 32,5 %) es el 4.º escalón de la cascada del campo crítico
(`05` §2.2). El catálogo `operadores_red` tiene **7 filas**, así que no hay garantía de que los nombres
del texto crucen.

**Condición dura:** la columna **no se elimina** hasta que un backfill medido demuestre que toda planta
con texto y sin `operador_red_id` quedó resuelta contra el catálogo, y que los nombres que no cruzaron se
**agregaron como operadores nuevos**, no que se descartaron. Mientras no se demuestre, la columna se queda
y la cascada sigue teniendo sus 4 escalones.

**Verificación de la fase:** el informe de cada `*_report` revisado por ti; después de migrar,
`SELECT proyecto_id, SUM(porcentaje) FROM ... GROUP BY 1 HAVING SUM(...) <> 100` devuelve **0 filas**; y
la consulta «dueños a fecha Y» sobre un proyecto conocido da el mismo resultado que
`proyecto_inversionistas` para hoy.
**Rollback:** `TRUNCATE proyecto_composicion_lineas, proyecto_composiciones` y `falla_equipos`. Los
originales están intactos.

### Fase 6 · La fusión de contratos — riesgo MÁXIMO

`contratos_servicio` (177) + `ppa_contratos` (34) → `contratos` + `contrato_partes` + `contrato_proyectos`.
Es la de mayor riesgo porque **Cumplimiento y Liquidaciones cuelgan de `ppa_contratos`** y están fuera de
alcance: se les cambia el padre sin tocarles nada más.

| Paso | Qué | Detalle |
|---|---|---|
| 6.1 | **Preservar el id de los PPA** — *tu decisión del 2026-08-24* | Los 34 PPA entran a `contratos` **con su `id` original**. La secuencia arranca por encima del máximo. `ppa.id` de la API no cambia de valor: el contrato queda intacto, no solo en forma sino en contenido |
| 6.2 | Los 177 contratos de servicio se remapean | Se guarda la tabla de correspondencia `viejo_id → nuevo_id` **como tabla, no como script**, porque hay que auditarla después |
| 6.3 | `contrato_partes` desde los nombres | ⚠️ `contratante_id`/`prestador_id` están al **0 %**: hay que resolver `contratante_nombre` (55,4 %) contra `clientes`. Lo que no cruce se loguea y **no se inventa** |
| 6.4 | `contrato_proyectos` | Desde `contratos_servicio.proyecto_id` (92,1 %) y desde `ppa_contrato_proyectos` (42 filas) |
| 6.5 | Re-apuntar las FK de los satélites a `contratos.id` | `ppa_tarifas`, `ppa_compromisos_energia`, `cumplimiento_mensual`, `clasificacion_energia_mensual`, `pagos_servicio`, `oportunidad_ofertas.ppa_contrato_id` (0 %), `oportunidad_ofertas.contrato_servicio_id` (0 %). **Gracias a 6.1, las de los PPA no necesitan remapeo** |
| 6.6 | El bloque internet/Starlink (13 columnas) → `equipos.especificaciones` | No es contrato, es equipo (`04-mapeo.md` §5.3) |
| 6.7 | Las tarifas escalares y los JSONB `indexacion_*` → **`contrato_tarifas`** | Decisión D-24. El orden de los 3 pasos está en `04-mapeo.md` §F. Dos reglas duras, abajo |

#### ⚠️ Las dos reglas duras del paso 6.7

Las dos salen de haber corrido la consulta de `audit_log` contra producción el 2026-08-27
(`01-decisiones.md` D-24 §e, salida en `esquema-bd-produccion/historico_tarifas.txt`).

**Regla 1 · Todas las filas nacen con `origen = 'migracion'`.** No hay ninguna con
`origen = 'renegociacion'`, porque no hay ninguna renegociación recuperable: la ventana de auditoría
existe desde el 2026-05-19 y **está vacía** de cambios de valor. Cualquier script que intente
reconstruir historia desde `audit_log` está trabajando sobre nada.

**Regla 2 · Un `0.0` no se migra: se omite la fila.** En estos datos un cero no es «tarifa cero», es
«todavía no lo lleno» — quedó demostrado con el contrato 108, cuyos `tarifa_cgm` y
`tarifa_representacion` pasaron de `0.0` a `5.0` tres minutos después de cargarse. Una fila de
`contrato_tarifas` que afirme «vale 0» es **peor que la ausencia de fila**, porque una liquidación la
consume sin dudar y no tiene forma de saber que era un relleno.

- Se omite la fila y **el escalar se deja como está** hasta que alguien ponga el valor real.
- El script loguea `omitidas_por_cero` con el `contrato_id` y el concepto. **Es un informe, no un
  error**: es la lista de tarifas que falta cargar.
- ⚠️ **Antes de correrlo hay que medir cuántas son**, con
  `esquema-bd-produccion/verificar_auditoria_y_ceros.py`. Si el número es alto, la decisión de qué hacer
  con esos contratos es previa a la migración, no posterior.
- **`NULL` y `0.0` se tratan igual**: ninguno produce fila. La diferencia es que el `NULL` ya era
  explícito y el `0.0` engañaba.

**Medido en producción el 2026-08-27** (`esquema-bd-produccion/verificacion_auditoria_ceros.txt`): son
**7 contratos**, todos de `servicio_aplica = 'representacion'` y todos `vigente`, contra **68 vigentes
con `NULL`** en cgm y otros 68 en representación. O sea: el cero es la excepción, no la norma. Y se
parten en dos grupos que **no son el mismo caso**:

| Grupo | Contratos | Forma | Lectura |
|---|---|---|---|
| **a · relleno probable** | 54, 115, 197, 209, 210 | `cgm = 0` **y** `repr = 0`, con `admin = 0.0380` | Las dos tarifas en cero a la vez y la de administración puesta: es el patrón del contrato 108 antes de corregirse. **Se omiten** |
| **b · ⚠️ cero que convive con un valor real** | **62, 69** | `cgm = 0` pero `repr = 6.0`, con `admin = NULL` | Acá el cero **puede ser intencional**: alguien puso la representación y dejó el CGM en cero a propósito. No es la misma evidencia que el grupo a |

🛑 **El grupo b está en espera de una respuesta de negocio, no de una decisión técnica.** Juan le va a
preguntar a Jessica si un contrato de representación puede tener **CGM cero legítimo**. Hasta que
responda:

- **La regla 2 se aplica igual a los dos grupos** —ningún `0.0` produce fila— porque omitir es la opción
  reversible: agregar la fila después es un `INSERT`, quitarla después es corregir liquidaciones ya
  emitidas.
- Pero el log tiene que **separarlos**: `omitidas_por_cero` marca el grupo b con
  `motivo='cero_conviviendo_con_valor'`, para que la respuesta de Jessica se pueda aplicar sobre una
  lista de dos contratos y no sobre las siete.
- Si Jessica confirma que el cero es legítimo, esos dos **entran como fila con `valor = 0`** y su
  `nota` dice que es un cero confirmado por negocio, no un relleno. Es el único caso en que la regla 2
  admite excepción, y exige la confirmación escrita.

**Verificación:** `COUNT(*) = 211` en `contratos`; los 34 ids de PPA son idénticos a los de
`ppa_contratos`; **la pestaña Cumplimiento da los mismos números que antes de la fase** (es la prueba de
que 6.5 salió bien, y hay que compararla contra una captura previa); `/liquidaciones` abre;
`GET /comercial/proyectos-operando` devuelve el mismo `ppa.id` para los mismos contratos.
Y para el 6.7, las dos reglas se comprueban con dos consultas:
`SELECT count(*) FROM contrato_tarifas WHERE valor = 0` → **0 filas**, y
`SELECT count(*) FROM contrato_tarifas WHERE origen = 'renegociacion'` → **0 filas**.
**Rollback:** las tablas viejas siguen existiendo con sus datos y sus FK originales hasta la Fase 7. Se
revierte el commit de lectura y se vuelve a apuntar. **Es la razón por la que la Fase 7 va aparte.**

### Fase 7 · Limpieza — riesgo IRREVERSIBLE, va al final

Solo después de un **periodo de observación de al menos dos semanas** con las fases 4-6 estables.

| Paso | Qué se borra |
|---|---|
| 7.1 | Las **41 columnas al 0 % de llenado** del núcleo (`04-mapeo.md` §7) |
| 7.2 | Las **7 tablas en 0 filas**: `mantenimientos`, `mantenimiento_impacto`, `polizas`, `servicio_operacion`, `servicio_representacion`, `alarmas_monitoreo`, `fronteras_lecturas` |
| 7.3 | `proyecto_inicio_operacion` (2 filas) — **exportar a archivo antes** |
| 7.4 | Las columnas ya migradas: los 3 JSONB de simulación, las 6 de `gen_promedio_*`, las 7 de id externa, `fallas.fotos_urls`, `fallas.proyecto_id`, `fallas.sla_cumplido` |
| 7.5 | Las tablas fusionadas: `proyecto_inversores`, `proyecto_info_tecnica`, `contratos_servicio`, `ppa_contratos`, `falla_inversores`, `fallas_seguimientos`, `proyecto_inversionistas` |
| 7.6 | ⚠️ `proyectos.operador_red` — **solo si la Fase 5.3 lo demostró** |
| 7.7 | ⚠️ `contratos_servicio.nombre_proyecto_ref` — **tiene índice dedicado**, o sea que algo lo usa para cruzar. Hay que encontrar qué antes de borrarla |

**Antes de cada `DROP`:** `pg_dump` de la tabla a un archivo, guardado fuera de la BD.
**Verificación:** tests verdes; la app arranca; ningún log de `column does not exist` durante 48 h.
**Rollback:** restaurar del dump. Es el único punto del plan donde el rollback no es un deploy, y por eso
va último y con dos semanas de espera.

---

## 4 · Rutas de API

48 routers, 494 rutas. **La inmensa mayoría no cambia de contrato**: cambia de dónde leen. Lo que sigue es
solo lo que se mueve.

### 4.1 Se actualizan por dentro, contrato intacto

| Router | Qué cambia | Fase |
|---|---|---|
| `comercial.py` + `services/comercial.py` | `_gen_promedio()`, `_simulacion()`, `api_id_unergy()`, `_nodo_proyecto()` leen de las tablas nuevas. **La forma de la respuesta no cambia** — es el contrato congelado | 4 |
| `proyectos.py` | `PUT /{id}/info-tecnica` pasa a escribir equipos; `GET` sigue devolviendo la misma ficha, armada desde `equipos` | 4 |
| `proyectos.py` | CRUD `/{id}/inversores` pasa a operar sobre `equipos` filtrando por tipo `inversor` | 4 |
| `proyectos.py` | CRUD `/{id}/inversionistas` pasa a `proyecto_composiciones`. ⚠️ **Aquí sí cambia el comportamiento**: un PATCH ya no sobrescribe, crea una composición nueva. La respuesta se mantiene | 5 |
| `fallas.py` | `proyecto_id` se lee de `falla_proyectos`; adjuntos de `falla_adjuntos`; historial de `falla_estado_historial` | 4 |
| `contratos_servicio.py`, `ppa.py`, `representacion.py` | leen de `contratos` con `tipo` filtrado | 6 |
| `cumplimiento.py`, `liquidaciones.py`, `panel_contable.py`, `facturacion.py`, `asic.py` | **cero cambios de código**: sus satélites cambian de FK padre, no de columnas | 6 |
| `mantenimiento_impacto.py` | pasa a `falla_impactos`. Tabla en 0 filas y **sin ningún consumidor en el front** | 3 |

### 4.2 Rutas nuevas

| Ruta | Para qué | Fase |
|---|---|---|
| `GET/POST /equipos`, `GET/PATCH/DELETE /equipos/{id}` | el inventario de equipos, que hoy no tiene dónde vivir | 3 |
| `GET /equipos/tipos`, `POST /equipos/tipos` | catálogo extensible por el usuario | 3 |
| `GET /equipos/garantias-por-vencer` | sobre `v_equipo_garantia_por_vencer` | 3 |
| `GET /equipos/mantenimiento-pendiente` | sobre `v_equipo_mantenimiento_pendiente` | 3 |
| `GET/POST /equipos/{id}/mantenimientos` | bitácora por equipo | 3 |
| `GET/POST /red/circuitos`, `/red/puntos-conexion` | la topología, hoy inexistente | 3 |
| `GET /proyectos/{id}/composiciones`, `POST /proyectos/{id}/composiciones` | propiedad con vigencia; el POST crea una composición completa | 5 |
| `GET /proyectos/{id}/propiedad?fecha=YYYY-MM-DD` | **la consulta que hoy es imposible**: dueños a una fecha | 5 |
| `GET /fallas/{id}/proyectos`, `POST /fallas/{id}/proyectos` | sumar plantas a un incidente de red | 4 |

### 4.3 Se deprecan

Ninguna se borra en este plan. Se marcan como deprecadas en el OpenAPI y se retiran en una fase posterior,
fuera de este documento.

| Ruta | Motivo | Reemplazo |
|---|---|---|
| `POST /proyectos/inversores/backfill-minigranja` | sembraba las casillas de inversor; el modelo nuevo no las necesita | `POST /equipos` |
| `GET/PUT /inicio-operacion/{proyecto_id}` | el checklist JSONB (2 filas). Su único consumidor es `EvidenciaUploader.vue` | `/equipos` + `/proyectos/{id}/composiciones` |
| `PUT /proyectos/{id}/info-tecnica` | tabla disuelta. **Se conserva funcionando** como fachada sobre `equipos`, porque lo llaman 4 vistas | `/equipos` |

⚠️ **`fila_operando()` y `proyectos_operando()` en `app/services/comercial.py:567-620` son código muerto**
(solo los referencian los tests) y contienen la versión vieja de la API con `estado_pipeline` y
`oferta_vigente`. **Se borran en la Fase 0**, junto con sus tests, para que nadie los confunda con el
contrato vivo. Es lo que me hizo perder tiempo reconstruyendo qué campos existen de verdad.

---

## 5 · Estrategia para no romper el front

El front es la parte frágil, por una razón concreta: **no tiene capa de servicios.** Las 177 vistas `.vue`
llaman `api.get()` directo (`src/api/client.js`), así que un cambio de forma en una respuesta se busca en
177 archivos, no en un módulo.

De ahí la estrategia, en cuatro capas:

### 5.1 El contrato de salida no cambia — el front no se toca en las fases 0-4

Es la decisión de fondo de todo el refactor: **el almacenamiento se reorganiza, la salida queda igual.**
Si la Fase 4 está bien hecha, el front no requiere **ni un cambio** hasta la Fase 5. Eso se verifica con
los golden tests de §7, no con confianza.

### 5.2 Vistas de compatibilidad para las columnas que se mudan

Cuatro columnas se mueven de tabla y las lee mucho código: `sub_project`, los 3 JSONB de simulación,
`gen_mensual_promedio_mwh` y `url_ubicacion`. En vez de buscar todos los usos, se expone cada una desde su
nuevo origen —vista SQL o `@property` del modelo— con el mismo nombre y tipo. El código viejo sigue
funcionando sin saber que la columna se movió.

⚠️ `sub_project` es el caso caro: tiene UNIQUE y lo lee medio backend. La decisión D-13 tiene una
**variante de menor riesgo**: dejar `sub_project` y `topic_slug` en `proyectos` y mover solo las otras 5
claves. Si en la Fase 3 el informe muestra más usos de los esperados, esa variante sigue disponible y no
obliga a rehacer nada.

### 5.3 Doble escritura durante la Fase 3

Mientras las tablas nuevas se llenan, los endpoints escriben en las dos. Con un flag de configuración para
apagarla. Es lo que permite que el rollback de las fases 3-6 sea un deploy y no una restauración de backup.

### 5.4 Lo único que el front sí tiene que cambiar

| Vista | Cambio | Fase |
|---|---|---|
| `ProyectoDetailView.vue` — panel de inversionistas | El PATCH ya no sobrescribe un porcentaje: abre una composición nueva con vigencia. **Es un cambio de UX, no solo de API**: hay que pedir la fecha desde la que aplica | 5 |
| `ProyectoDetailView.vue` — ficha técnica | Las marcas dejan de ser 15 campos de texto y pasan a ser una lista de equipos | 3-4 |
| `ProyectosListView.vue` | Quitar el botón de backfill de minigranja | 3 |
| `EvidenciaUploader.vue` | Único consumidor de `/inicio-operacion` | 7 |
| **Vistas nuevas** | Inventario de equipos, garantías por vencer, mantenimiento pendiente, topología de red | 3+ |

**Sin versionado de endpoints.** Se evaluó `/api/v2` y no se justifica: hay un solo front y un solo
consumidor externo, la salida no cambia, y mantener dos versiones de 494 rutas cuesta más que el problema
que resuelve. Si en la Fase 5 algún contrato tuviera que cambiar de forma, ahí sí se versiona **esa ruta**,
no la API entera.

---

## 6 · Rollback por fase

| Fase | Cómo se revierte | Coste | Punto de no retorno |
|---|---|---|---|
| 0 · Mecanismo | revertir el commit | minutos | no |
| 1 · Integridad | recrear índices, revertir los `ON DELETE` | minutos | no |
| 2 · Tablas nuevas | `DROP` de las 19 tablas vacías | minutos | no |
| 3 · Migración de datos | `TRUNCATE` de las nuevas + apagar doble escritura | minutos | no |
| 4 · Cambio de lectura | revertir el commit; los datos viejos siguen al día por la doble escritura | un deploy | no |
| 5 · Datos con decisión | `TRUNCATE` composiciones y `falla_equipos`; los originales intactos | un deploy | no |
| 6 · Fusión de contratos | revertir el commit de lectura; las tablas viejas siguen con sus datos y sus FK | un deploy | no |
| 7 · Limpieza | **restaurar del `pg_dump` previo** | horas, con pérdida de lo escrito desde el dump | **sí** |

La propiedad que sostiene la tabla: **hasta la Fase 7 no se borra nada.** Las siete primeras fases son
aditivas, y por eso su rollback es siempre un deploy. La Fase 7 es la única destructiva, va al final, y
espera dos semanas de observación.

---

## 7 · Cómo se verifica cada fase

Tres instrumentos. Ninguno es «revisar a ojo».

### 7.1 El golden test del contrato congelado

Es la red de seguridad principal, y se construye **antes de la Fase 3**:

1. Capturar la respuesta completa de `GET /comercial/proyectos-operando` en producción hoy, con todos los
   estados, a un archivo JSON versionado en el repo.
2. Un test que arma la misma respuesta desde una BD de prueba y la compara **campo por campo** contra ese
   archivo, con tolerancia solo en `generado_en`.
3. El test corre en CI en cada commit desde la Fase 3 hasta la 7.

Ya existe la base para hacerlo: `tests/test_comercial_proyectos_operando.py` (1 061 líneas) y
`tests/test_comercial_ppas_pipeline.py` (1 094). Hay que reorientarlos: hoy prueban `fila_operando()`, que
es código muerto.

**Y tres aserciones específicas**, que son los invariantes de `05` §4:
`operador_red_id is None` cuando el nombre viene del texto legacy · `len(p50_mensual_kwh)` conserva la
longitud real y `p50_anual_kwh is None` si no son 12 · los 4 campos de `energia_promedio_detalle` son
`None` cuando el origen es `estimado` o `declarado`.

### 7.2 Consultas de control, contra producción

Se corren después de cada fase, y su resultado esperado es fijo:

| Qué comprueba | Consulta | Esperado |
|---|---|---|
| Ninguna falla perdió su planta | `SELECT COUNT(*) FROM falla_proyectos` | **6 478** |
| Ninguna falla quedó sin planta | `SELECT COUNT(*) FROM fallas f WHERE NOT EXISTS (SELECT 1 FROM falla_proyectos WHERE falla_id=f.id)` | **0** |
| Las composiciones suman 100 | `SELECT composicion_id, SUM(porcentaje) FROM proyecto_composicion_lineas GROUP BY 1 HAVING SUM(porcentaje) <> 100` | **0 filas** |
| No hay vigencias solapadas | el `EXCLUDE` lo impide; se confirma que el constraint existe en `pg_constraint` | presente |
| Los PPA conservaron su id | `SELECT COUNT(*) FROM contratos c JOIN ppa_contratos p ON p.id=c.id WHERE c.tipo='compraventa_energia'` | **34** |
| Los equipos vigentes cuadran | `SELECT COUNT(*) FROM equipos WHERE equipo_tipo_id=(...'inversor') AND fecha_baja IS NULL` | = inversores activos de hoy |
| Toda FK tiene índice | consulta de `pg_index` vs `pg_constraint` | **0 FK sin índice** |
| El promedio de generación no cambió | comparar `proyecto_generacion_promedio` con las 6 columnas viejas | **48 filas idénticas** |

### 7.3 Las tres puertas manuales

Hay cosas que ninguna consulta decide:

- **Cumplimiento da los mismos números.** Antes de la Fase 6, capturar la pestaña completa (o la respuesta
  de `/cumplimiento/panel-anual`) y compararla después. Es la única prueba real de que re-apuntar las FK
  de los satélites salió bien.
- **Los informes de la Fase 5**, revisados por ti: cuántos `falla_inversores` cruzan por nombre, qué
  proyectos no suman 100 %, qué nombres de operador no están en el catálogo.
- **Laura abre `/fallas` y `/operaciones/gestion-fallas`** y confirma que ve lo mismo. Son sus vistas de
  trabajo diario y el golden test no cubre el front.

---

## 8 · Orden de ejecución y puertas de aprobación

```
Fase 0 ── mecanismo de esquema ─────────── [aprobación] ──┐
Fase 1 ── higiene de integridad ────────── [aprobación] ──┤
Fase 2 ── tablas nuevas vacías ─────────── [aprobación] ──┤  aditivas
Fase 3 ── migrar datos + doble escritura ─ [aprobación] ──┤  rollback = deploy
Fase 4 ── cambiar la lectura ───────────── [aprobación] ──┤
Fase 5 ── datos con decisión humana ────── [aprobación] ──┤
Fase 6 ── fusión de contratos ──────────── [aprobación] ──┘
   ⋮ dos semanas de observación
Fase 7 ── limpieza ────────────────────────[aprobación] ─── destructiva
```

**Regla, y viene de tu propio brief:** ninguna fase arranca sin que apruebes la anterior, y cada
aprobación se pide con la verificación de §7 ya corrida y su salida a la vista.

### Lo primero que hay que hacer, y que no es código

1. **`python comparar_con_prod.py "<DATABASE_URL>"`** — es la entrada de la Fase 0. Responde si existe una
   tabla `equipos` en producción (colisión de nombre con el modelo nuevo) y si siguen vivas las 14 tablas
   del hallazgo F3. **La Fase 2 no se puede planear sin esa salida.**
2. ~~Probar `CREATE EXTENSION btree_gist` en su propia revisión de Alembic.~~ ✅ **Hecho** el
   2026-08-26/27, contra producción y contra la base local (D-24). El permiso existe y el `EXCLUDE` con
   enum funciona; la extensión se crea dentro de la revisión que crea las tablas que la necesitan.
3. **Capturar el golden de `/comercial/proyectos-operando`** hoy, antes de tocar nada. Cuanto antes, mejor:
   es la única forma de demostrar después que la salida no cambió.

### Lo que queda explícitamente fuera de este plan

| Fuera | Por qué |
|---|---|
| **Frontera** | Decisión D-06 pendiente. Ninguna fase la toca. Cuando la retomes entra como fase propia, y no depende de ninguna de las 8 |
| **Rediseño de Liquidaciones** | Fuera de alcance. La Fase 6 le deja el acople preparado (`04-mapeo.md` §5.4) |
| **Unificar las 4 taxonomías de falla** | Decisión de dominio, necesita a Laura |
| **Postgres en CI** | Habilitaría probar el trigger y el `EXCLUDE` (§2.3). Tarea de infraestructura, no de modelo |
| **Endurecer los scopes de API key** | Hoy una key `["read"]` puede escribir. Es una tarea de seguridad y es independiente |
| **Catálogo DIVIPOLA de municipios** | Decisión D-16: el contrato congelado necesita los dos strings resueltos por cascadas independientes |

---
---

# Apéndice · 2026-08-26 · Fase 0 cerrada y Fase 1 en detalle

**Fase 0: hecha y commiteada** (`383bf1e`, local, sin push). Lo que se ejecutó y lo que se descubrió
al ejecutarla está en §A.
**Fase 1: detallada aquí** — 5 pasos, con su script, su orden, su verificación y su rollback. Ningún
script se ejecutó: este apéndice es el plan, no el registro de una corrida.
**Lo que cambió del plan original:** el paso 1.4 (`ON DELETE`) ya está hecho en parte por otra sesión,
y el conteo de FK sin índice subió de 18 a 20.

## A · Fase 0 · lo ejecutado y las tres sorpresas

Commit `383bf1e`. `_PENDING_DDLS` pasó de **551 a 478 sentencias** (−73), y sus `CREATE TABLE` de
**55 a 11** (−44 redundantes, incluida la zombie `gmail_credenciales`, que la revisión **100** dropea).
Los 29 backfills del mapeo FRT → `quoia_meter_id` salieron a `_BACKFILLS_REFERENCIA`. Más el borrado de
`fila_operando`/`proyectos_operando` y 51 de sus tests. Suite: **1897 pasan** contra un baseline de
**1947** en `origin/master`.

⚠️ **Errata del mensaje del commit `383bf1e`:** dice «queda en 439 sentencias». El número correcto es
**478**; el 439 era de un estado intermedio, antes de rebasar sobre los 86 commits. El resto del
mensaje es exacto. Conviene corregirlo con un `--amend` antes del push, ya que el commit todavía es
local.

Tres cosas que el plan no anticipaba, y que valen como lección para la Fase 1:

1. **No se pueden mover todos los backfills.** Hay tres parejas *backfill → constraint* donde el
   orden importa: `asic_solicitudes.porcentaje_despacho` antes de `chk_porcentaje_despacho`, y los dos
   `UPDATE` de `oportunidad_ofertas` antes de sus `SET NOT NULL`. Quedaron en `_PENDING_DDLS` con un
   comentario «No los separes». **Regla derivada para la Fase 1: antes de mover o borrar una sentencia
   del arranque, buscar qué depende de ella.**
2. **Borrar tests de código muerto puede llevarse cobertura de código vivo.** De los 67 tests del
   archivo, 15 cubrían funciones vivas — 5 de ellos `duracion_contrato()`, que produce tres campos
   congelados. Un `rm` del archivo habría quitado esa cobertura justo antes de tocar esos campos.
3. **Resolver un conflicto por «mi lado» sin leer el lado ajeno completo pierde trabajo.** Al reaplicar
   la Fase 0 sobre los 86 commits nuevos, tomé mi lado en un conflicto cuyo lado upstream traía, además
   del `CREATE TABLE` que yo quitaba, **12 `ALTER ... ADD COLUMN`** — entre ellos los que arreglaban un
   500 en producción. Lo detectó `tests/test_modelo_vs_ddl.py`, que otra sesión había agregado
   precisamente para eso. **Se rehízo la fase partiendo del archivo de `origin/master`** y verificando
   que el conteo de `ALTER` no bajara.

⚠️ **Y un aviso sobre la Fase 0:** su objetivo era que los datos no vivan en `_PENDING_DDLS`, pero
otra sesión **agregó** sentencias de datos ahí el 2026-08-25 (contratos de Cedillanos y Sabana de
Torres, clasificación heredada). Se respetaron donde están. Mientras el equipo siga usando
`_PENDING_DDLS` como vía rápida para cargar datos, la limpieza se deshace sola. Eso no se arregla con
un commit sino con la convención, y por eso se documentó en `CLAUDE.md`.

## B · Fase 1 · Higiene de integridad, en detalle

**Objetivo:** que la base imponga lo que hoy solo vive en la aplicación, sin mover ni una tabla.
**Riesgo global: BAJO**, salvo el paso 1.4, que cambia el comportamiento del borrado.
**Precondición:** la Fase 0 desplegada y estable 24 h. Nada de esta fase depende de las decisiones
abiertas (D-06 frontera, D-10 tarifas), así que se puede ejecutar mientras esas se discuten.

### Paso 1.1 · Índice en las 20 FK que no lo tienen

**Recontado el 2026-08-26** contra los modelos de hoy: son **20**, no 18. Dos son nuevas y dos casos
merecen decisión aparte.

| # | FK sin índice | Nota |
|---|---|---|
| 1 | `cliente_tasa_servicio.proyecto_id` | verificado: solo aparece como 3.ª columna de un `UniqueConstraint`, que no sirve de índice |
| 2 | `fallas_cat_tipos.categoria_id` | catálogo chico, pero se lee en cada carga de `/fallas` |
| 3 | `mantenimiento_impacto.created_by` | tabla en 0 filas |
| 4 | `oportunidades.creado_por_usuario_id` | |
| 5 | `oportunidad_estado_historial.usuario_id` | |
| 6 | `oportunidad_gestiones.usuario_id` | |
| 7 | `panel_contable.generado_por_id` | |
| 8 | **`panel_contable_linea.proyecto_inversionista_id`** | **el más importante:** es el que ata las liquidaciones a la composición accionaria (`04` §5.4) |
| 9 | `clasificacion_energia_mensual.contrato_ppa_id` | |
| 10 | `informes_guardados.enviado_por_id` | |
| 11 | `om_pagina_sin_match.contrato_id_asignado` | |
| 12 | `fronteras_quoia_ignoradas.ignorado_por_usuario_id` | |
| 13 | `proyectos_pendientes_ignorados.ignorado_por_usuario_id` | |
| 14 | `registro_hito.evidencia_documento_id` | |
| 15 | `registro_transicion.evidencia_documento_id` | |
| 16 | `reporte_energia_consumo.validado_por_id` | tabla que crece a diario |
| 17 | `reporte_energia_generacion.validado_por_id` | ídem |
| 18 | `reporte_energia_exclusiones.creado_por_id` | |
| 19 | ⚠️ `ppa_contrato_proyectos.proyecto_id` | **caso distinto:** es la 2.ª columna de una PK compuesta. Postgres indexa `(contrato_id, proyecto_id)`, así que la búsqueda «qué contratos tiene esta planta» hace scan. **Sí hace falta**, y es una consulta que Cumplimiento usa |
| 20 | ⚠️ `oportunidad_oferta_proyectos.proyecto_id` | idéntico al anterior, en la M2M del CRM |

**Script:** una revisión de Alembic, `101_indices_fk_faltantes.py`, con
`CREATE INDEX IF NOT EXISTS` uno por uno. Sin `CONCURRENTLY`: son tablas chicas y `CONCURRENTLY` no
corre dentro de la transacción de Alembic. La excepción son
`reporte_energia_generacion`/`_consumo`, que crecen a diario: para esas dos, medir el tamaño primero y
si pasan de ~100 k filas, sacarlas a una revisión aparte con `autocommit_block()`.

**Verificación:** `EXPLAIN (ANALYZE, BUFFERS)` antes y después de tres consultas concretas — el
`/cumplimiento/panel-anual`, el detalle de un cliente (`/clientes/{id}/panel`) y `GET /fallas`. Y la
consulta de control de `§7.2`: 0 FK sin índice.
**Rollback:** `DROP INDEX` de cada uno. Reversible sin pérdida.

### Paso 1.2 · Quitar uno de cada par de índices redundantes

Eran **46 pares** en el inventario del 23-ago. ⚠️ **Hay que recontar antes de ejecutar:** las
migraciones 077-097 crearon y borraron índices de `fronteras`, así que ese número está desactualizado y
no se puede recalcular sin leer los índices reales de la base.

**Script:** una revisión que, para cada par, dropee el índice **no** asociado a un constraint —
Postgres no deja dropear el que respalda un `UNIQUE` sin dropear el constraint.
**Precondición:** correr primero la consulta que lista los pares reales (va en el paso, no acá, porque
exige la base).
**Verificación:** el conteo de índices baja en exactamente el número de pares detectados; ninguna
consulta de control cambia de plan.
**Rollback:** recrear. Los nombres quedan en la migración.

### Paso 1.3 · Las FK que faltan

| FK a agregar | Estado hoy |
|---|---|
| `alarma_estado.proyecto_id → proyectos` | ⚠️ La tabla **no tiene modelo ORM** y `alarmas_monitoreo` tampoco. Ver la corrección del `04` §E: **están vivas**, el scheduler les escribe cada 15 min. Agregar la FK exige antes verificar que no haya filas con `proyecto_id` huérfano, y eso necesita la base |
| `panel_soporte.created_by_id → usuarios` | directa |
| `fallas.alarma_monitoreo_id → alarmas_monitoreo` | ⚠️ **Reevaluar.** El inventario la propuso, pero la columna está al **0 %** y `05` la marca sin uso. Si no se va a llenar, la decisión correcta es **borrar la columna**, no agregarle una FK |
| `audit_log.registro_id` | **NO lleva FK**: es polimórfica a propósito |

**Verificación:** por cada FK nueva, contar filas huérfanas **antes** (`LEFT JOIN ... WHERE padre.id IS
NULL`). Si hay alguna, el `ADD CONSTRAINT` falla — y eso es información, no un error a silenciar.
**Rollback:** `DROP CONSTRAINT`.

### Paso 1.4 · ⚠️ `ON DELETE` explícito — el único paso con riesgo real

Eran **80 de 148 FK** sin `ON DELETE`. **Otra sesión ya hizo una parte**: la migración 083 puso
`RESTRICT` en las 4 tablas de historial que cuelgan de `fronteras`
(`reporte_energia_generacion`, `_consumo`, `_exclusiones`, `liquidacion_xm_datos`, esta última ya
eliminada), y la 085 puso `CASCADE` en la M2M `contrato_frontera`. **Y usó exactamente el criterio que
este plan propone**, así que hay precedente citable:

> *"`RESTRICT` explícito — un intento de hard-delete falla ruidosamente en vez de cascadear datos
> regulatorios/financieros o depender de un default sin documentar"* (migración 083)
>
> *"`CASCADE` en las dos FK es correcto para esta tabla: es una tabla de vínculo puro sin datos
> propios — si se borra un Contrato o una Frontera, lo único que debe desaparecer es el enlace"* (085)

**El criterio, ya validado en producción:**

| Tipo de hijo | `ON DELETE` | Ejemplos |
|---|---|---|
| Vínculo puro, sin datos propios | `CASCADE` | `ppa_contrato_proyectos`, `oportunidad_oferta_proyectos`, `contrato_frontera` |
| Línea de detalle que no existe sin su padre | `CASCADE` | `fallas_seguimientos`, `pagos_servicio`, `ppa_tarifas` |
| Historial regulatorio o financiero | `RESTRICT` | `reporte_energia_*`, `cumplimiento_mensual`, `panel_contable_linea` |
| Referencia opcional a un catálogo o persona | `SET NULL` | `*_por_usuario_id`, `resolucion_id`, `asignado_a_id` |

**Cómo se ejecuta, y esto no es negociable:** **una revisión de Alembic por grupo, no una sola para
las 80.** Un `CASCADE` mal puesto convierte un error de integridad —molesto pero seguro— en un borrado
silencioso en cascada, y el rollback no devuelve las filas. El orden es: primero todos los `SET NULL`
(los más inocuos), después los `RESTRICT` (endurecen, no borran), y **al final** los `CASCADE`, uno por
grupo, con la decisión escrita en el mensaje del commit.

**Verificación por grupo:** para cada FK que pase a `CASCADE`, un `DELETE` de prueba sobre una fila
desechable dentro de `BEGIN … ROLLBACK`, contando qué se habría borrado. Si el conteo sorprende, no se
aplica.
**Rollback:** `ALTER ... DROP CONSTRAINT` + `ADD CONSTRAINT` sin `ON DELETE`. Reversible, pero **las
filas borradas por un CASCADE no vuelven** — de ahí el `BEGIN/ROLLBACK` previo.

### Paso 1.5 · `IntegrityError` → 409 en la API

Hoy un borrado con dependencias devuelve **500**, y está documentado como deuda en
`docs/API_FALLAS.md`.

Hay **precedente del patrón**, no un helper reusable: el commit `2793a90` creó
`_commit_o_409_codigo_duplicado()` (`app/api/v1/fronteras.py:276`), pero es específico del choque de
`codigo_frontera` duplicado, no genérico —captura `IntegrityError` y devuelve un 409 con un mensaje de
código duplicado. **Lo que se reusa es su forma**: centralizar el `try/except IntegrityError` en un
helper en vez de repetirlo en cada endpoint. Para los borrados hace falta uno distinto, que distinga
violación de FK (409 «tiene dependencias») de violación de UNIQUE (409 «ya existe»).

**Alcance:** los `DELETE` de `/proyectos`, `/clientes`, `/ppa`, `/contratos-servicio` y `/fallas`.
**Verificación:** un test por endpoint que cree padre + hijo, intente borrar el padre y espere 409 con
mensaje legible. Estos **sí** se pueden testear en SQLite (§2.3 no aplica: es comportamiento de la app).
**Rollback:** revertir el commit. No toca datos.

### Orden y puertas

```
1.1 índices FK        ── medir EXPLAIN ── [aprobación]
1.2 índices redundantes ─ recontar primero ─ [aprobación]
1.3 FK faltantes      ── contar huérfanos ── [aprobación]
1.5 IntegrityError→409 ─ tests ─────────── [aprobación]
1.4 ON DELETE         ── por grupos, el último ── [aprobación por grupo]
```

⚠️ **1.5 va antes de 1.4 a propósito**, cambiando el orden del plan original: endurecer los borrados
antes de que la API sepa reportar el conflicto convierte cada bloqueo nuevo en un 500 para el usuario.
Con el 409 ya en su lugar, el endurecimiento se ve como un mensaje claro.

## C · Lo que la Fase 1 NO incluye

- **Nada de las decisiones abiertas.** D-06 (frontera) y D-10 (las tres tarifas) no se tocan; la
  Fase 1 no depende de ninguna.
- **El golden test del contrato congelado.** Sigue sin construirse y sigue siendo precondición de la
  Fase 4, no de la 1. ⚠️ Pero conviene capturarlo **ya**: cada día que pasa, el árbol cambia y el
  golden se vuelve más difícil de atribuir.
- **`comparar_con_prod.py`.** Sigue pendiente y sigue siendo precondición de la Fase 2 (colisión del
  nombre `equipos` — Juan confirmó el 25-ago que no existe, pero las 14 tablas del hallazgo F3 siguen
  sin verificar).
