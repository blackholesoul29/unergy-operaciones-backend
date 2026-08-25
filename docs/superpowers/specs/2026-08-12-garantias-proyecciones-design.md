# Garantías — sub-pestaña "Proyecciones" (diseño)

Fecha: 2026-08-12
Estado: **diseño en borrador** — arquitectura aprobada a alto nivel; faltan datos reales (facturas, verificación en prod) y confirmar un par de parámetros.

## Qué es

Estimar la **garantía que XM precobra** sobre las compras y ventas de energía en bolsa
que tendremos. NO es el ajuste XM de `AjustesXM` (eso es otra cosa; el módulo
`garantias`/`garantias_ajustes` existente es solo el "hogar" donde viven las garantías,
no un cálculo). Se construye una **sub-pestaña nueva llamada "Proyecciones"** dentro de
Garantías, separada de todo lo actual.

## Fórmula (confirmada con negocio)

```
garantía = (ventas − compras) × precio_bolsa_prom_7d_conocidos
           + costos_regulatorios_del_mes_anterior
```

- **ventas** = venta en bolsa (excedente no contratado).
- **compras** = SOLO **duplicados** (`compra_bolsa_directa`, `es_duplicado=true`).
  NO incluye "uso del recurso" (compra no directa, sin garantía).
- **(ventas − compras)** = el **`neto`** que ya calcula
  `balance_energia.agregar_balance` → `ungg.neto = venta_bolsa − compra_bolsa_total`.
  ⚠️ OJO: el `neto` actual resta compra_total (directa + no directa); para la garantía
  las "compras" son SOLO directas → hay que separar el término (usar
  `venta_bolsa − compra_bolsa_directa`, no el `neto` tal cual).
- **precio_bolsa_prom_7d** = promedio de bolsa de los últimos 7 días conocidos.
  **Fuente: SIMEM (aislada, solo para garantías) — NO tocar `precios_bolsa_diario`/EVO.**
  API pública: `GET https://www.simem.co/backend-files/api/PublicData?startdate=&enddate=&datasetId=EC6945`.
  - Variable `CodigoVariable = PB_Nal` (nacional), valores horarios (PT1H), unidad COP/kWh.
  - **Versión:** por cada día tomar la **versión más alta disponible** (`Version` = TX1,
    TX2, …). Filtrar solo a una versión fija perdería los días recientes (que solo tienen
    TX1); tomar el max por día da recencia + refinamiento a la vez.
  - Promediar horas → promedio diario; promediar los últimos 7 días conocidos.
  - Persistir en tabla NUEVA `simem_precio_bolsa_diario` (separada de `precios_bolsa_diario`).
  - SIMEM es público (sin Tailscale ni token), datos con ~3 días de rezago (mucho mejor
    que el feed EVO actual, parado). Verificado en vivo 2026-08 (PB_Nal ~935–1033 COP/kWh).
- **costos regulatorios** = **costo regulatorio del mes anterior**. No existe en la BD
  hoy. **Fuente:** archivo `Cruce facturas M YYYY txf.xlsx` en
  `OneDrive/Estado Resultados/YYYY/MM_Mes/`, hoja **"Facturas XM"** (una por mes).
  **Regla de cálculo (confirmada):**
  - Tomar las facturas de tipo **GENERADOR**; **excluir** las de tipo **COMERCIALIZADOR**.
  - Sumar los conceptos de cada factura generador **excluyendo "Energía en bolsa"**
    (ese concepto es "compras", no regulatorio).
  - No sumar líneas de subtotal ("Valor total", "Total servicios de administración sic").
  - Ejemplo julio 2026 = **$67.191.598** (FAZNI 999.626 + Arranque y parada 9.658.866 +
    Cargo por confiabilidad 19.933.106 + ASIC125542 completa 36.600.000).

No usa tarifa de venta ni valorización de ventas.

## Déficit energético (la mitad energética)

Déficit = **remanente en bolsa** + **duplicados** (donde toda la energía es bolsa).
Ya derivable de `balance_energia` (tramos × % despacho, real + proyectado). El motor ya
hace el 80%: tramos, duplicados, uso del recurso, real/proyectado, neto.

## Enganche con `balance_energia` (decisiones)

`calcular_balance(db, year, month)` devuelve el libro mayor:
`balance.ungg.{venta_bolsa, compra_bolsa_directa, compra_bolsa_no_directa, compra_bolsa_total, neto}`
y `balance.ungc.venta_bolsa`; cada celda = `{real, proyectado, total, n_plantas}`.

- **compras = solo `compra_bolsa_directa`** (duplicados). El `neto` del motor NO sirve tal
  cual (resta compra_total). Se usa `venta_bolsa − compra_bolsa_directa`.
- **Unidad:** neto en MWh, precio SIMEM en COP/kWh → multiplicar por **1000** (MWh→kWh).
- **`calcular_balance` devuelve CEROS para un mes futuro** (corta si `es_mes_futuro`). Por eso:
  - Ventana "resto del mes actual" = campo **`proyectado`** del balance del mes actual.
  - Ventana "mes siguiente completo" = campo **`total`** del balance del mes actual, usado
    como **proxy** ("el mes que viene ≈ este mes a cierre"). Simplificación MVP,
    reemplazable por un pronóstico real después.
- **Término regulatorio por ventana:** resto-mes-actual → `costo_regulatorio_del_mes(mes
  anterior al actual)`; mes-siguiente → `costo_regulatorio_del_mes(mes actual)`.

## Dos estimaciones separadas (así publica XM)

Recalculadas **cada semana** (igual que los ajustes), con la generación que se va
acumulando:

| Estimación | Ventana | Fuente |
|---|---|---|
| 1. Resto del mes actual | días que faltan del mes en curso | parte `proyectado` de balance_energia |
| 2. Mes siguiente completo | todo el mes que viene | mes 100% proyectado |

Término regulatorio anclado al mes anterior de cada ventana (a validar):
- Est. 1 (mes actual) → regulatorios del mes anterior al actual.
- Est. 2 (mes siguiente) → regulatorios del mes actual.

## Recálculo semanal + snapshot

Cada semana entra generación nueva: `real` sube, `proyectado` baja, el mes se
"solidifica" y el neto se recalcula solo con re-correr el motor al corte de esa semana.
La generación es **la misma fuente que Cumplimiento** (API Unergy) → garantía y
cumplimiento se mueven en el mismo paso; conviene que lean un solo "corte de generación".

Decisión: **guardar snapshot semanal** (opción A) — histórico de cada recálculo
(neto, precio_7d, costo_reg, total, fecha_corte) para ver la evolución y auditar contra
lo que XM efectivamente precobró.

## Planta nueva (MVP simple)

XM, ante un contrato nuevo con planta nueva sin historia de despacho, cobra como si todo
fuera compra y va bajando semana a semana según genera. Para el MVP NO se modela ese
comportamiento fino:

- Selector manual por contrato nuevo: **"planta nueva" / "no es nueva"**.
- Si **no es nueva** → cálculo normal (neto × precio_7d).
- Si **es nueva** → override plano: **180 kWh por planta (editable) × precio_bolsa**.
  ⚠️ Confirmar: ¿180 es la energía asumida por planta valorizada a bolsa? ¿unidad kWh o
  MWh? (180 kWh parece muy pequeño para una planta).
- Cuando estabiliza, alguien apaga el flag y pasa al cálculo normal.

## Arquitectura: capa delgada sobre `balance_energia`

```
Proyecciones (Garantías)
  ├─ balance_energia con corte = { resto_mes_actual, mes_siguiente }
  │     → venta_bolsa − compra_bolsa_directa (MWh) por ventana
  ├─ × precio_bolsa_prom_7d_conocidos
  ├─ + costo_regulatorio(mes anterior a la ventana)      ← tabla NUEVA
  ├─ override "planta nueva": neto := 180 kWh(editable) × precio_bolsa
  └─ guarda SNAPSHOT semanal
```

Se reutiliza el motor; NO se reimplementa la lógica de bolsa (descartado: servicio
propio que recompute bolsa → se desincroniza; meter la garantía dentro de balance_energia
→ mezcla balance de energía con precobro financiero).

### Piezas nuevas
1. Tabla `costo_regulatorio_mensual` (año, mes, valor) — gap de las facturas.
2. Tabla `garantia_snapshot` — histórico semanal por estimación.
3. Flag "planta nueva" + parámetro editable (180 kWh) por contrato.
4. Conector SIMEM aislado + tabla `simem_precio_bolsa_diario` (NO tocar el pipeline
   EVO/`precios_bolsa_diario` existente — restricción explícita del usuario).
5. Endpoint `GET /garantias/proyecciones` + vista de la sub-pestaña.

## Estado de los datos

- ✅ Ventas futuras (volumen): `ppa_compromisos_energia` (min/max por contrato·año·mes).
- ✅ Neto ventas−compras: `balance_energia` (ajustar a compra_directa).
- ✅ Precio bolsa: **SIMEM EC6945 / PB_Nal** (conector nuevo aislado), no el feed EVO.
- ✅ Duplicados: GESCON `AsicSolicitud.es_duplicado`.
- ❌ Costos de comercialización (regulatorios) mes anterior → facturas.

## Pendientes antes de implementar
- [x] Fuente y regla del costo regulatorio: archivo `Cruce facturas` hoja "Facturas XM",
      facturas GENERADOR sin "Energía en bolsa", sin comercializador. Julio = $67.191.598.
- [x] Ingesta del costo regulatorio: el `Cruce facturas` **vive en el Drive de Estados de
      Resultados** (ya conectado). El backend lo lee del Drive por (año, mes) reusando
      `app/services/drive.py` (`er_folder_id`, `listar_carpeta`, `parse_nombre_er`,
      `descargar_archivo`) y lo parsea con `costo_regulatorio.py`. **Fallback:** si no está
      el del mes, usar el **último mes disponible**. **Sin tabla** `costo_regulatorio_mensual`
      (YAGNI): se lee on-demand y el valor usado queda en `garantia_snapshot`.
- [ ] Default del parámetro "planta nueva" (180 kWh/planta, editable) — ajustar con un
      caso real; no bloquea. Confirmar unidad (kWh vs MWh) cuando se recuerde.
- [ ] Verificar en prod: nº de compromisos futuros, duplicados en bolsa, compras sin
      volumen.
- [ ] Confirmar anclaje del término regulatorio por ventana.
- [ ] Confirmar si la garantía usa solo UNGG o también algo de UNGC.
