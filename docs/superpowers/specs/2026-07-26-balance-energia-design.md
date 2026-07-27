# Balance de energía — pestaña de /mem/cumplimiento

Fecha: 2026-07-26 · Autor: Juan José + Claude · Estado: aprobado, en implementación

## Problema

Juan lleva a mano un Google Sheet con el recuento de cada planta y sus contratos
(una fila por frontera: "Registrado en Terpel 1", "Libre en UNGG", "En bolsa con
UNGC", "Cubriendo Terpel 8 · Compra/venta", "Uso del recurso"). Ese recuento ya
existe implícito en la plataforma como las piscinas a–g, pero:

1. No hay ninguna vista que responda **"este mes, ¿cuánto compro o compraré en
   bolsa?"** — que es la pregunta que gobierna garantías y cargos regulatorios.
2. El Excel no tiene fechas ni porcentajes, así que no puede responderla.
3. Los dos cálculos de bolsa que hay hoy en el módulo **no coinciden**:
   - `plantas-contratos` (pestaña Proyectos) reparte la bolsa **por días**: una
     planta con contrato vigente todo el mes aporta 0 a bolsa, sin importar su
     % de despacho.
   - `energia-transada` reparte **por porcentaje**: `bolsa = gen − Σ(gen × %)`.
   Un balance construido sobre el primero subestima la bolsa cuando hay
   despacho parcial.

## Reglas de negocio (confirmadas con Juan, 2026-07-26)

- **Venta en bolsa UNGG (e)** — energía que entra a bolsa directamente como
  generador. Acarrea **cargos regulatorios altos**. Es lo que hay que minimizar.
- **Venta en bolsa UNGC (f)** — UNGG le vende a UNGC y UNGC inyecta a bolsa.
  No acarrea cargos; acarrea **cartera**.
- **Compra en bolsa directa (c, duplicados)** — la energía no existe: Unergy la
  compra en la bolsa para cubrir un contrato duplicado (ej. Klik al 80% de
  Uruaco). Genera **garantías**.
- **Compra en bolsa no directa (uso del recurso)** — la energía sí existe y se
  entrega al contrato, pero se le paga al dueño de la planta a precio de bolsa.
  Es una compra en bolsa **no directa**: va dentro del bloque de compras, pero
  **no genera garantías**.
- **Neteo**: la venta en bolsa UNGG y las compras en bolsa se contrarrestan
  dentro del **mismo agente**. (f) es de UNGC y **no** se netea contra (c).
- **Despacho parcial**: si una planta está bajo contrato al Σ% < 100, el resto
  **se vende a la bolsa por UNGG**. Un tramo sin contrato es el caso Σ% = 0, y
  ahí sí se clasifica UNGC/UNGG según tenga registro SIC vigente con comprador
  UNGC.
- **Alcance**: solo energía (MWh). La valorización en COP queda para una
  iteración posterior.
- **Mes en curso**: real hasta la fecha de corte + proyección al cierre, en
  columnas separadas.

## Libro mayor

```
UNGG   Venta en bolsa (e)                    +X MWh   ⚠ cargos regulatorios
       Compras en bolsa
          · Directas — duplicados (c)        −Z MWh   ⚠ garantías
          · No directas — uso del recurso    −W MWh   (sin garantía)
          Total compras en bolsa             −(Z+W)
       ─────────────────────────────────────────────
       NETO UNGG                             ±N MWh

UNGC   Venta en bolsa (f)                    +Y MWh   ⚠ solo cartera
```

Cada capa lleva un tooltip en hover que explica qué es, de dónde sale y qué
riesgo implica.

## Arquitectura

Enfoque elegido: **componer sobre lo que ya existe**, no reimplementar GESCON.
Descartados: (a) extender `plantas-contratos` con MWh — lo consumen la pestaña
Proyectos y el snapshot a–f, y hoy no hace ni una llamada a la API de
generación; (b) servicio independiente que resuelva GESCON por su cuenta —
sería el tercer sitio que interpreta contratos y vigencias, y los tres se
desincronizan (justo el bug que motiva esta feature).

### Backend

**`app/services/balance_energia.py`** (nuevo)

- `construir_tramos(data, first_day, last_day) -> dict[int, list[Tramo]]`
  **Función pura, sin BD ni red.** Toma el payload de `get_plantas_contratos` y
  devuelve, por planta, los tramos elementales del mes. Corta el mes en los
  breakpoints de todas las asignaciones y segmentos de bolsa; para cada tramo
  calcula:
  - `pct_ppa`   = Σ % de asignaciones NO duplicadas vigentes (incluye uso del
                  recurso: esa energía sí se entrega al contrato)
  - `pct_dup`   = Σ % de asignaciones duplicadas → compra directa
  - `pct_uso`   = Σ % de asignaciones uso del recurso → compra no directa
  - `pct_venta_bolsa` = max(0, 1 − min(1, pct_ppa))
  - `piscina_venta`   = `ungc` si un segmento de bolsa `comercializador` cubre
                        el tramo; si no, `ungg`
  Los % vienen 0–1. Se clampan a [0,1] por registro y el Σ a [0,1]; los que se
  pasan se reportan en `advertencias.pct_anomalos` (hay filas corruptas en prod,
  ver [porcentaje_despacho escala]).

- `calcular_balance(db, year, month, excluir_compra_externa=False) -> dict`
  Orquesta: llama en proceso a `get_plantas_contratos`, construye los tramos,
  trae la generación y agrega el libro mayor + la tabla plana.

**Energía por tramo.** Reutiliza los helpers de `energia-transada`
(`_fetch_month`, `_fetch_range`, `_mon_id`) con el mismo `ThreadPoolExecutor(12)`:
- Real: generación de `tramo ∩ [primer día, corte]`. Si el tramo cubre toda la
  ventana real → `_fetch_month` (ya es la generación real de esos días, porque
  para el mes en curso la API solo tiene datos hasta hoy). Si es parcial →
  `_fetch_range` (suma de deltas día a día, nunca regla de tres).
- Proyectado: `promedio_diario_real × días de tramo ∩ [corte+1, último día]`,
  donde `promedio_diario_real = gen_mes_real / días transcurridos`. Usa el
  propio mes en curso en vez de `_fetch_recent_avg` (60 días × 55 plantas de
  llamadas extra) porque es la misma estación y clima.
- Sin `sub_project` o sin datos → la planta no suma y aparece en
  `advertencias.sin_datos`.

**Mes futuro** → payload vacío con `es_mes_futuro: true`, igual que
`/energia-transada`.

**Endpoint** `GET /cumplimiento/balance-energia?year&month&excluir_compra_externa`
Aditivo. No se modifica ningún endpoint existente.

Respuesta:
```jsonc
{
  "periodo": { "year", "month", "fecha_corte", "dias_mes", "dia_corte",
               "es_mes_actual", "es_mes_futuro" },
  "balance": {
    "ungg": {
      "venta_bolsa":            { "real", "proyectado", "total", "n_plantas" },
      "compra_bolsa_directa":   { ... },
      "compra_bolsa_no_directa":{ ... },
      "compra_bolsa_total":     { ... },
      "neto":                   { ... }
    },
    "ungc": { "venta_bolsa": { ... } }
  },
  "inventario": [ {
      "proyecto_id", "planta", "frontera", "categoria",   // e|f|c|uso|a|g
      "estado",        // "Terpel 1" | "Libre en UNGG" | "En bolsa con UNGC"
      "metodo",        // Registrado | Duplicado | Uso del recurso | Compra externa
      "contrato", "contrato_id", "codigo_sic", "pct",
      "desde", "hasta", "dias",
      "mwh_real", "mwh_proyectado", "mwh_total"
  } ],
  "advertencias": {
     "sin_datos": [...], "pct_anomalos": [...], "compra_externa_en_bolsa": [...]
  },
  "warning": "…"   // solo si falla la auth contra la API de generación
}
```

**Frontera**: se resuelve por `fronteras.proyecto_id`, prefiriendo
`tipo_frontera` de generación y `estado='activa'`; si no hay, cae al
`nombre_comercial`. Una sola query para todas las plantas.

**Plantas de compra externa (g).** Punto abierto: si Agustín 1/2/3, Bayunca,
Biosolar, Astrolumen y La Catedral están representadas por Unergy y no tienen
registro GESCON propio, hoy el residuo las mete en bolsa libre (e) como si
vendieran en bolsa por UNGG, cuando su energía está comprada por PPA y cubre un
contrato. Serían ~7 plantas infladas en la línea más sensible. **No se excluyen
en silencio**: se cuentan, se listan en `advertencias.compra_externa_en_bolsa`
con sus MWh, y el parámetro `excluir_compra_externa` deja ver el otro número al
instante. La decisión de negocio es de Juan.

### Frontend

Sexta pestaña `'Balance de energía'` en `CumplimientoV2View.vue`, misma
estructura que las demás (selectores año/mes, `cachedGet`, spinner, `Message`
de error).

- **Libro mayor**: dos tarjetas (UNGG / UNGC) con columnas Real · Proyectado ·
  Total. Cada línea es clicable y lleva `title` + popover en hover con la
  explicación de la capa. Colores existentes del módulo: morado `#915BD8` para
  contrato, `#2C2039` para bolsa, rojo `#D64455` para lo que preocupa,
  turquesa `#14B8A6` para lo favorable (misma semántica que Cumplimiento).
- **Inventario**: tabla plana, una fila por tramo, con buscador por frontera,
  filtro por categoría y export a Excel con el mismo estilo de marca que
  `exportarResumenPlantasContratos` (`xlsx-js-style`).
- **Filtro cruzado**: click en una línea del libro mayor filtra el inventario a
  esas filas; segundo click limpia.
- **Toggle** "excluir plantas de compra externa" que recarga con el parámetro.

## Errores

- Auth contra la API de generación falla → `warning` en el payload y banner en
  la vista; el inventario y los tramos igual se muestran (sin MWh).
- Planta sin `sub_project`/sin lecturas → fila con `—` y entrada en
  `advertencias.sin_datos`; no contamina los totales.
- Mes futuro → estado vacío explicado, sin llamadas a la API.

## Pruebas

`tests/test_balance_energia.py`, sobre la función pura `construir_tramos` (sin
BD ni red):
- Planta al 100% todo el mes → sin venta en bolsa.
- Planta al 70% todo el mes → 30% a venta bolsa **UNGG** (regla nueva).
- Esmeralda/Vallenata 50%+50% en dos contratos → Σ=100, sin bolsa.
- Planta que sale de contrato el 23 → tramo contratado + tramo libre, y el
  tramo libre clasificado por su piscina.
- Uruaco: Terpel 1 + duplicado Klik 80% → `pct_dup=0.8` sin tocar `pct_ppa`.
- Uso del recurso → cuenta en `pct_ppa` **y** en `pct_uso` (doble, a+c).
- Segmento de bolsa `comercializador` → `piscina_venta='ungc'`.
- % corrupto > 1 → clampado y reportado.
- Agregación real vs. proyectado con una fecha de corte fija.

## Fuera de alcance (iteraciones futuras)

- Valorización en COP y margen de uso del recurso (tarifa vs. precio bolsa).
- Cargos regulatorios y garantías cuantificados — hoy no existe el dato
  ($/MWh) en la plataforma; meter un parámetro inventado haría que el balance
  parezca más exacto de lo que es.
- Enlazar la piscina (g) al contrato que cubre ("Cubriendo Terpel 8"), que el
  Excel sí registra y el modelo no.
- Corregir los registros de Terpel 8 (Yuan / San Pelayo / Marimonda marcados
  `es_duplicado` cuando según el Excel están libres o en UNGC) — decisión de
  negocio pendiente de Juan.
