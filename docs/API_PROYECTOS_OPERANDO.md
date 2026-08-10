# API de Proyectos en Operación

Una sola llamada devuelve **todas las plantas que hoy están operando**, con estos datos por
planta:

**nombre · ubicación · operador de red · generación mensual promedio · fecha de inicio de
comercialización · tiempo del contrato de energía.**

Es la misma lista que se ve en la plataforma en `/comercial` filtrando por la etapa
**Operando**, pero agrupada por planta y en un JSON pensado para integrar.

- **Base URL:** `https://backend-production-63d8.up.railway.app`
- **Endpoint:** `GET /api/v1/comercial/proyectos-operando`
- **Swagger:** https://backend-production-63d8.up.railway.app/docs
- **Solo lectura.** Este endpoint no escribe nada; no hay forma de romper datos con él.

---

## 1. Autenticación

Header `X-API-Key` en cada request. La key la emite Juan José desde la plataforma.

```bash
export UNERGY_API_KEY="uop_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
export BASE="https://backend-production-63d8.up.railway.app/api/v1"

# ¿la key sirve?
curl "$BASE/api-keys/verify" -H "X-API-Key: $UNERGY_API_KEY"
# → {"user_id": 12, "nombre": "...", "rol": "operaciones"}
```

**Sirve cualquier rol** (`operaciones`, `monitoreo`, `comercial`, `admin`): a diferencia del
resto de `/comercial`, este endpoint no exige rol comercial porque no expone precios,
márgenes ni bitácora comercial. Si `verify` responde 200, el endpoint responde 200.

La key hereda todos los permisos del usuario dueño: trátenla como una contraseña, guárdenla
en variable de entorno y **nunca** la pongan en un frontend ni en el repo.

---

## 2. Quickstart

```bash
curl "$BASE/comercial/proyectos-operando" -H "X-API-Key: $UNERGY_API_KEY"
```

Respuesta:

```json
{
  "generado_en": "2026-08-09T21:21:49-05:00",
  "estado": "operando",
  "total": 6,
  "items": [ { … una entrada por planta … } ]
}
```

`items` no está paginado: vienen todas las plantas operando. Hoy son unas decenas y la
llamada tarda menos de un segundo.

---

## 3. Una planta, entera

```json
{
  "proyecto_id": 9,
  "nombre": "La Catedral",
  "ubicacion": {
    "municipio": "Corozal",
    "departamento": "Sucre",
    "texto": "Corozal, Sucre",
    "latitud": 9.317,
    "longitud": -75.293
  },
  "operador_red": "AFINIA S.A.S. E.S.P.",
  "operador_red_id": 7,
  "gen_promedio_mensual_mwh": 178.412,
  "gen_promedio_mensual_kwh": 178412.0,
  "gen_promedio_origen": "medido",
  "gen_promedio_detalle": {
    "dias_con_datos": 30,
    "ventana_desde": "2026-07-10",
    "ventana_hasta": "2026-08-08",
    "actualizado_en": "2026-08-09T21:18:45-05:00"
  },
  "fecha_inicio_comercializacion": "2026-02-12",
  "fecha_entrada_operacion": "2026-02-01",
  "contrato_energia": {
    "fecha_inicio": "2026-02-12",
    "fecha_fin": "2032-12-31",
    "duracion_meses": 83,
    "duracion_anios": 6.9,
    "duracion_texto": "6 años y 11 meses",
    "meses_restantes": 77,
    "vigente": true,
    "ppa_contrato_id": 1,
    "numero_codigo_contrato": "UNG-2026-014",
    "nombre_interno": "PPA Catedral",
    "tipo": "compra",
    "comprador": "UNERGY S.A.S.",
    "vendedor": "INVERSIONES TECNI-PLAST S.A.S.",
    "cantidad_minima_kwh_mes": 150000.0
  },
  "cliente": "INVERSIONES TECNI-PLAST S.A.S.",
  "potencia_instalada_kwp": 990.0,
  "ofertas": [
    {
      "oferta_id": 1,
      "codigo_seguimiento": "OP.COM No.0051-3-2026",
      "tipo": "compra_energia",
      "estado": "operando",
      "oportunidad_id": 2
    }
  ],
  "fuentes": {
    "nombre": "proyecto",
    "municipio": "proyecto",
    "departamento": "proyecto",
    "operador_red": "proyecto",
    "gen_promedio_mensual": "medido",
    "fecha_inicio_comercializacion": "proyecto",
    "contrato_energia": "contrato"
  }
}
```

### Los seis campos pedidos

| Lo que pidieron | Dónde está |
|---|---|
| Nombre | `nombre` |
| Ubicación | `ubicacion.texto` (o `municipio` / `departamento` por separado) |
| Operador de red | `operador_red` |
| Generación mensual promedio | `gen_promedio_mensual_mwh` (y `…_kwh`) |
| Fecha de inicio de comercialización | `fecha_inicio_comercializacion` |
| Tiempo del contrato de energía | `contrato_energia.duracion_texto` (y `duracion_meses` / `duracion_anios`) |

### Referencia completa

| Campo | Tipo | Qué es |
|---|---|---|
| `proyecto_id` | `int \| null` | Id de la planta en la plataforma. **`null`** = la planta todavía no existe como proyecto, los datos vienen de la oferta comercial |
| `nombre` | `string \| null` | Nombre de la planta |
| `ubicacion.municipio` | `string \| null` | Municipio |
| `ubicacion.departamento` | `string \| null` | Departamento |
| `ubicacion.texto` | `string \| null` | `"Municipio, Departamento"` armado; `null` si no hay ninguno de los dos |
| `ubicacion.latitud` / `longitud` | `float \| null` | Coordenadas, si la planta las tiene cargadas |
| `operador_red` | `string \| null` | **Nombre legal** del operador de red |
| `operador_red_id` | `int \| null` | Su id en el catálogo `operadores_red` |
| `gen_promedio_mensual_mwh` | `float \| null` | Generación de un mes típico, en **MWh** |
| `gen_promedio_mensual_kwh` | `float \| null` | Lo mismo en **kWh** (× 1000, ya convertido) |
| `gen_promedio_origen` | `string \| null` | `medido` · `manual` · `estimado` · `declarado` — ver abajo |
| `gen_promedio_detalle.dias_con_datos` | `int \| null` | Cuántos días con lectura entraron al promedio (de 30) |
| `gen_promedio_detalle.ventana_desde` / `hasta` | `date \| null` | Qué ventana se promedió |
| `gen_promedio_detalle.actualizado_en` | `datetime \| null` | Cuándo se calculó |
| `fecha_inicio_comercializacion` | `date \| null` | Primer día con generación real de energía |
| `fecha_entrada_operacion` | `date \| null` | Entrada en operación de la planta — **otro hecho**, no confundir |
| `contrato_energia.fecha_inicio` / `fecha_fin` | `date \| null` | Periodo del contrato |
| `contrato_energia.duracion_meses` | `int \| null` | Duración en meses calendario |
| `contrato_energia.duracion_anios` | `float \| null` | La misma duración en años, 1 decimal |
| `contrato_energia.duracion_texto` | `string \| null` | `"6 años y 11 meses"` — listo para mostrar |
| `contrato_energia.meses_restantes` | `int \| null` | Meses que le quedan desde hoy; `0` si ya venció |
| `contrato_energia.vigente` | `bool \| null` | Si el contrato está corriendo hoy |
| `contrato_energia.ppa_contrato_id` | `int \| null` | Id del contrato en la plataforma |
| `contrato_energia.numero_codigo_contrato` | `string \| null` | Código del contrato |
| `contrato_energia.tipo` | `string \| null` | `compra` (Unergy le compra la energía a la planta) o `venta` |
| `contrato_energia.comprador` / `vendedor` | `string \| null` | Las partes |
| `contrato_energia.cantidad_minima_kwh_mes` | `float \| null` | Energía comprometida por mes. **No es lo mismo que la generación promedio** |
| `cliente` | `string \| null` | Razón social del cliente dueño del negocio |
| `potencia_instalada_kwp` | `float \| null` | Potencia instalada |
| `ofertas[]` | `array` | Las ofertas comerciales de esa planta que están en Operando |
| `fuentes` | `object` | De dónde salió cada dato — ver abajo |

**Todas las fechas son `YYYY-MM-DD`.** Los `datetime` van en ISO 8601 con offset de Colombia
(`-05:00`).

---

## 4. `gen_promedio_origen` — léanlo siempre

El número está siempre en la misma casilla, pero no siempre vale lo mismo. **Muestren el
origen al lado del número** (aunque sea un ícono o un tooltip):

| Valor | Qué significa | Confiabilidad |
|---|---|---|
| `medido` | Promedio de la generación **real** de los últimos 30 días | Alta — es el dato duro |
| `manual` | Lo cargó una persona porque la planta no tiene histórico (recién energizada) | Media |
| `estimado` | Proyección de ingeniería de la planta (curva P50), no medición | Baja para operación |
| `declarado` | Lo declaró la oferta comercial; la planta aún no existe en la plataforma | Baja |
| `null` | Nadie lo aportó todavía. **No es un error** | — |

Con `medido`, `gen_promedio_detalle.dias_con_datos` dice sobre cuántos días se promedió: 30
es una ventana completa, 27 es una ventana con huecos de monitoreo. No vale lo mismo.

---

## 5. `fuentes` — distinguir "no aplica" de "todavía no lo sabemos"

Sin este mapa, un dato que no aplica y un dato que falta se ven idénticos (los dos `null`).

| Valor | Significa |
|---|---|
| `"proyecto"` | Salió de la planta cargada en la plataforma |
| `"proyecto_legacy"` | Salió de un campo de texto viejo, sin validar contra el catálogo. Úsenlo, pero sepan que puede estar mal escrito |
| `"oferta"` | Lo declaró la oferta comercial (la planta aún no existe como proyecto) |
| `"contrato"` | Salió del contrato PPA |
| `"medido"` / `"manual"` / `"estimado"` / `"declarado"` | Solo para `gen_promedio_mensual`, ver arriba |
| `null` | **Nadie lo aportó todavía.** No es un error |

`fuentes` siempre trae estas 7 llaves: `nombre`, `municipio`, `departamento`, `operador_red`,
`gen_promedio_mensual`, `fecha_inicio_comercializacion`, `contrato_energia`.

---

## 6. Tres cosas que conviene saber antes de integrar

**1. La forma de la respuesta nunca cambia.** Todas las llaves están siempre, aunque el valor
sea `null`. No hace falta programar defensivamente contra llaves ausentes — sí contra valores
`null`.

**2. `fecha_inicio_comercializacion` no se rellena con nada.** Son tres hechos distintos y
cada uno tiene su casilla:

- `fecha_inicio_comercializacion` → primer día con generación real de energía
- `fecha_entrada_operacion` → cuándo entró en operación la planta
- `contrato_energia.fecha_inicio` → cuándo arranca el suministro del contrato

Si necesitan "desde cuándo produce", es la primera. Si viene `null`, es que ese dato todavía
no está cargado en la plataforma — háblenlo con Juan José, no lo sustituyan por otra fecha.

**3. Una planta = una fila, aunque tenga varias ofertas.** Una planta suele tener la oferta de
compra de energía y la de servicios operacionales. Salen agrupadas en una sola entrada, con
los dos códigos en `ofertas[]`. No hay que deduplicar.

---

## 7. Filtro

Solo hay uno, y es opcional:

| Parámetro | Qué hace |
|---|---|
| `q` | Busca texto en el nombre de la planta, la razón social del cliente y el código de seguimiento |

```bash
curl "$BASE/comercial/proyectos-operando?q=catedral" -H "X-API-Key: $UNERGY_API_KEY"
```

No hay parámetro para cambiar de etapa: este endpoint es **siempre** de las plantas operando.
Quien necesite ver otras etapas del pipeline comercial tiene
`GET /comercial/ofertas?estado=firmado` (ese sí pide rol `comercial` o `admin`).

---

## 8. Ejemplos

### Python

```python
import os
import requests

BASE = "https://backend-production-63d8.up.railway.app/api/v1"
KEY = os.environ["UNERGY_API_KEY"]

r = requests.get(f"{BASE}/comercial/proyectos-operando",
                 headers={"X-API-Key": KEY}, timeout=60)
r.raise_for_status()
datos = r.json()

print(f"{datos['total']} plantas operando (al {datos['generado_en']})")
for p in datos["items"]:
    gen = p["gen_promedio_mensual_mwh"]
    gen_txt = f"{gen:,.1f} MWh/mes ({p['gen_promedio_origen']})" if gen is not None else "sin dato"
    print(f"{p['nombre']:35} {p['ubicacion']['texto'] or '—':30} "
          f"{p['operador_red'] or '—':25} {gen_txt:28} "
          f"{p['contrato_energia']['duracion_texto'] or '—'}")
```

### JavaScript

```js
const BASE = "https://backend-production-63d8.up.railway.app/api/v1";

const res = await fetch(`${BASE}/comercial/proyectos-operando`, {
  headers: { "X-API-Key": process.env.UNERGY_API_KEY },
});
if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
const { total, items } = await res.json();

items.forEach((p) => {
  console.log(
    p.nombre,
    p.ubicacion.texto ?? "—",
    p.operador_red ?? "—",
    p.gen_promedio_mensual_mwh ?? "—",
    p.fecha_inicio_comercializacion ?? "—",
    p.contrato_energia.duracion_texto ?? "—",
  );
});
```

### Pasar a Excel / CSV

```bash
curl -s "$BASE/comercial/proyectos-operando" -H "X-API-Key: $UNERGY_API_KEY" \
| jq -r '["nombre","ubicacion","operador","gen_mwh_mes","origen","inicio_comercializacion","contrato"],
         (.items[] | [.nombre, .ubicacion.texto, .operador_red,
                      .gen_promedio_mensual_mwh, .gen_promedio_origen,
                      .fecha_inicio_comercializacion,
                      .contrato_energia.duracion_texto]) | @csv' > plantas_operando.csv
```

---

## 9. Errores

| Código | Cuándo | Qué hacer |
|---|---|---|
| 401 | `Token requerido` — no mandaron el header `X-API-Key` | Revisar el header |
| 401 | `API Key inválida` — la key no existe o está desactivada | Pedirle una nueva a Juan José |
| 401 | `Usuario inactivo o no encontrado` | El usuario dueño de la key se desactivó |
| 422 | Parámetro mal formado | Revisar `q` |

Un resultado vacío **no es un error**: responde 200 con `total: 0` e `items: []`.

---

## 10. Recomendaciones de uso

- **Cachéen del lado de ustedes.** Los datos cambian a lo sumo una vez al día (la generación
  promedio se recalcula por lote). Llamar cada 5 minutos no aporta nada; una vez por hora
  sobra.
- **Timeout de 60 s** en el cliente. La llamada tarda menos de un segundo, pero Railway puede
  tener un arranque en frío.
- **Reintenten con espera** ante un 5xx: un reintento a los 30 s, no un bucle.
- **`generado_en`** dice de cuándo es la foto. Muéstrenla si el tablero se cachea.

---

## 11. Contacto

Juan José (juanjose@unergy.io) para API keys, para reportar datos que salgan en `null` y para
pedir campos nuevos.
