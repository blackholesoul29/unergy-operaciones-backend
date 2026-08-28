# 07 · Retención de `audit_log` — diseño

**Estado: diseño, sin implementar.** Escrito el 2026-08-27. Nada de esto corre todavía.

Es la primera de las cuatro tareas que salieron de la investigación de la auditoría, y va antes que
agregar tablas a `_AUDITED_TABLES`: no tiene sentido dimensionar el volumen de algo que todavía no
registra bien.

---

## 1 · El dato que cambia el marco: nadie la lee

Grep sobre `app/` y sobre el frontend: **no hay un solo endpoint, vista ni reporte que consuma
`audit_log`**. Es una tabla de solo escritura que se consulta a mano cuando algo se investiga —como
esta semana, con el bug de `tipo_migration`.

Eso significa que **no hay contrato con nadie que romper**. La retención no se negocia con un
consumidor: se decide contestando una sola pregunta, *¿hasta qué punto atrás querés poder
investigar?*

Y también significa que el riesgo de equivocarse es asimétrico. Guardar de más cuesta espacio y
consultas lentas. Guardar de menos cuesta una investigación que no se puede hacer, y eso no se
recupera.

## 2 · Cuánto se guarda: tres clases, no un TTL único

Un TTL global obliga a elegir entre guardar basura 18 meses o tirar historia real. Los datos de esta
semana muestran tres poblaciones con valor muy distinto:

| Clase | Predicado | Retención | Por qué |
|---|---|---|---|
| **Financiera / regulatoria** | `tabla IN ('liquidaciones','ppa_contratos','contratos_servicio','reporte_energia_generacion','reporte_energia_consumo')` | **24 meses** | Cubre un ciclo fiscal completo más la ventana de corrección. Es la clase que contesta «quién cambió esta tarifa», que es el caso de uso real que originó todo esto (D-24 §c) |
| **Operativa** | `fallas`, `proyectos`, `clientes`, `fronteras`, `generacion_diaria` | **12 meses** | Sirve para reconstruir un incidente. A los doce meses nadie vuelve sobre una falla |
| **Ruido de arranque** | `usuario_nombre LIKE 'sistema (startup:%'` | **30 días** | Es diagnóstico, no historia. Su valor es «¿qué tarea escribió de más en el último deploy?», y eso caduca en días |

⚠️ **La tercera fila es la que justifica separar clases.** Sin ella, un bug como el de
`tipo_migration` deja 50.860 filas ocupando espacio y ensuciando toda consulta durante año y medio. Con
ella, se limpian solas un mes después.

**Regla de precedencia:** el ruido de arranque se evalúa primero. Una fila de `fallas` firmada por
`sistema (startup: ...)` cae en la clase de 30 días, no en la operativa de 12 meses.

## 3 · Cómo se purga

### Ahora: un job en el scheduler que ya existe

`_deferred_init` ya levanta un `BackgroundScheduler` con doce jobs cron. Uno más, a las 03:00 hora
Colombia:

- Un `DELETE` por clase, con su intervalo, **en lotes** (10.000 filas por vuelta, con tope por
  corrida) para no abrir una transacción larga sobre una tabla que la API está escribiendo.
- Se apoya en `ix_audit_log_created` (`created_at DESC`), que ya existe.
- Loguea cuántas borró por clase. Idempotente por naturaleza.
- ⚠️ **No va en `_PENDING_DDLS` ni en `_deferred_init`**: es recurrente, no de arranque. Va en el
  scheduler, según la convención de `CLAUDE.md`.

### Después: partición por rango mensual, sólo si el volumen lo pide

Purgar pasa a ser `DROP TABLE audit_log_2026_03`: instantáneo y sin bloat. El costo es real —hay que
migrar la tabla existente, y la PK tiene que incluir la clave de partición, o sea pasar de `id` a
`(id, created_at)`.

**Umbral para justificarlo:** cuando `audit_log` pase de ~10 M filas, o cuando el `DELETE` mensual
tarde más de unos segundos. Hoy va por ~64.000: falta mucho.

### Lo que hay que medir antes de decidir, y nadie midió

```sql
SELECT pg_size_pretty(pg_total_relation_size('audit_log')) AS total,
       pg_size_pretty(pg_relation_size('audit_log'))       AS solo_tabla,
       count(*)                                            AS filas
  FROM audit_log;
```

El tamaño en disco no se conoce. La estimación por filas puede errar por mucho: el peso real lo pone
`cambios`, y una fila del hook de escrituras masivas —que guarda la sentencia— pesa distinto que una
de un `UPDATE` de un campo.

## 4 · Las 50.860 filas de ruido que ya están

**Se borran, pero no todavía y no sin resumen.**

**No son historia.** Registran un cambio que el sistema hizo y deshizo, 23 veces. El estado final de
esas fallas es el mismo con o sin ellas.

**Pero sí son evidencia**, y la evidencia tiene su lugar: ya está escrita en `00-inventario-actual.md`
(antipatrón K). Lo que falta antes de borrar son dos pasos, en este orden:

1. **Verificar primero que el arreglo funcionó** (`esquema-bd-produccion/verificar_arreglo_tipo_migration.py`).
   Si se borra la línea base y resulta que la pelea sigue, se pierde el punto de comparación.
2. **Guardar el resumen**: correr `diagnosticar_ruido_seed.py` y dejar su salida en
   `esquema-bd-produccion/`, con el desglose de las 23 ráfagas.

Después, el predicado es exacto y no necesita fecha:

```sql
DELETE FROM audit_log WHERE usuario_nombre = 'sistema (seed de arranque)';
```

El rótulo `'sistema (seed de arranque)'` **ya no lo escribe nadie** —el código de hoy firma
`'sistema (startup: <tarea>)'`—, así que ese predicado selecciona exactamente el conjunto histórico y
nunca va a alcanzar una fila nueva.

⚠️ **Un matiz para decidir:** la **primera** de las 23 ráfagas fue la corrección legítima, la primera
vez que el backfill sí tenía trabajo. Se podría conservar por fecha. La recomendación es borrarla
igual: su resultado ya está en el estado actual de los datos, y el resumen guarda el hecho.

## 5 · Orden de ejecución

```
1. Medir el tamaño real de audit_log                        ← nadie lo hizo
2. Verificar el arreglo de tipo_migration                   ← script listo
3. Guardar el resumen del ruido                             ← script listo
4. Purgar las 50.860 filas                                  ← una sentencia
5. Implementar el job de retención de las tres clases       ← esto es el trabajo
6. Recién entonces, agregar arr_* y oportunidad* a la auditoría
```

Los pasos 1 a 4 son de una tarde. El 5 es el único que es código.

## 6 · Lo que este diseño NO decide

- **Si la retención tiene que ser configurable.** Están escritas como constantes. Si algún día
  Contabilidad pide 36 meses para la clase financiera, se cambia una constante y se despliega — no
  hay UI ni tabla de configuración, y meterlas ahora sería construir para un requisito que nadie pidió.
- **Qué pasa con una fila de una tabla que salga de `_AUDITED_TABLES`.** Sus filas viejas quedan sin
  clase y hoy caerían en «ninguna», o sea que no se borrarían nunca. Hace falta una clase
  «cualquier otra cosa» con su propio TTL, y no está decidido cuál.
- **Si hace falta archivar antes de borrar.** Para la clase financiera, 24 meses puede no alcanzarle
  a una auditoría externa. Volcar a un archivo antes del `DELETE` es barato, pero nadie pidió el
  requisito y no se va a construir por las dudas.
