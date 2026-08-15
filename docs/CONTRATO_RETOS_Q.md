# Contrato del módulo "Retos Q" — fuente única de verdad

Este archivo es el contrato que backend y frontend DEBEN respetar al pie de la letra.
Nombres de campos, tipos y rutas son normativos. No inventar variantes.

---

## 1. Concepto

Tablero trimestral de retos del equipo. Por año hay 4 trimestres (Q1..Q4).
Cada Q tiene un rango de fechas editable y N métricas. Cada métrica se llena
**una vez por semana**. El consolidado del Q se calcula agregando los valores
semanales según el `tipo_agregacion` de la métrica.

Es un tablero **compartido** (no por usuario). Cualquier usuario autenticado
puede leer y escribir. Se registra quién actualizó cada valor.

---

## 2. Tablas (PostgreSQL)

### `retos_trimestre`
| columna | tipo | notas |
|---|---|---|
| id | BigInteger PK | |
| anio | Integer NOT NULL | index |
| trimestre | Integer NOT NULL | 1..4 |
| nombre | String(160) NULL | ej. "Retos Q3 2026" |
| descripcion | Text NULL | |
| fecha_inicio | Date NOT NULL | |
| fecha_fin | Date NOT NULL | |
| created_at / updated_at | DateTime(timezone=True) | server_default=func.now(), onupdate |

`UniqueConstraint("anio", "trimestre", name="uq_retos_trimestre_anio_q")`

### `retos_metrica`
| columna | tipo | notas |
|---|---|---|
| id | BigInteger PK | |
| reto_id | BigInteger FK → retos_trimestre.id, ondelete="CASCADE" | index, NOT NULL |
| nombre | String(200) NOT NULL | |
| descripcion | Text NULL | |
| unidad | String(40) NULL | "MWh", "%", "#", "COP", "" |
| meta | Numeric(20,4) NULL | objetivo del trimestre completo |
| tipo_agregacion | String(20) NOT NULL default "suma" | `suma` \| `promedio` \| `ultimo` \| `maximo` |
| direccion | String(20) NOT NULL default "mayor_mejor" | `mayor_mejor` \| `menor_mejor` |
| decimales | Integer NOT NULL default 0 | 0..4 |
| responsable | String(120) NULL | texto libre |
| orden | Integer NOT NULL default 0 | |
| activa | Boolean NOT NULL default True | |
| created_at / updated_at | DateTime(timezone=True) | |

### `retos_valor_semanal`
| columna | tipo | notas |
|---|---|---|
| id | BigInteger PK | |
| metrica_id | BigInteger FK → retos_metrica.id, ondelete="CASCADE" | index, NOT NULL |
| semana_inicio | Date NOT NULL | **siempre el LUNES** de la semana |
| valor | Numeric(20,4) NULL | null = semana sin dato |
| nota | Text NULL | |
| actualizado_por_id | BigInteger FK → usuarios.id NULL | |
| created_at / updated_at | DateTime(timezone=True) | |

`UniqueConstraint("metrica_id", "semana_inicio", name="uq_retos_valor_metrica_semana")`

**Las semanas NO se persisten como tabla.** Se derivan del rango del Q.

---

## 3. Generación de semanas (lógica compartida, debe ser idéntica en back y front)

```
semanas(fecha_inicio, fecha_fin):
    cursor = fecha_inicio - timedelta(days=fecha_inicio.weekday())   # lunes de la semana de inicio
    numero = 1
    while cursor <= fecha_fin and numero <= 60:      # tope duro de 60 semanas
        fin_semana = cursor + timedelta(days=6)      # domingo
        yield {
          numero,
          inicio: cursor,                            # LUNES → es la clave de los valores
          fin: fin_semana,                           # domingo
          inicio_efectivo: max(cursor, fecha_inicio),
          fin_efectivo:    min(fin_semana, fecha_fin),
        }
        cursor += timedelta(days=7); numero += 1
```

`etiqueta` = `"S{numero}"`. `rango_label` = `"6–12 ene"` (día–día mes abreviado en
español, sin punto; si cruza mes: `"29 sep–5 oct"`). El backend manda ambos ya
formateados para que el front no reimplemente el formateo.

Si el usuario cambia las fechas del Q, los valores siguen anclados a su lunes real:
los que quedan fuera del nuevo rango simplemente no se muestran (no se borran).

---

## 4. Cálculo del consolidado

Sobre los valores **no nulos** de las semanas que caen dentro del rango:

| tipo_agregacion | consolidado |
|---|---|
| `suma` | sum(valores) |
| `promedio` | sum/len |
| `ultimo` | valor de la semana con `numero` más alto que tenga dato |
| `maximo` | max(valores) |

**Meta esperada a la fecha** (`meta_esperada`) — el ritmo que deberías llevar hoy:
- `suma` → `meta * semanas_transcurridas / total_semanas`
- resto → `meta` (no se prorratea)

`semanas_transcurridas` = número de la semana actual, acotado a `[0, total_semanas]`.
Si el Q ya cerró = `total_semanas`. Si aún no empieza = 0.

- `avance_pct` = `consolidado / meta * 100` (null si meta es null o 0)
- `cumplimiento_pct` = `consolidado / meta_esperada * 100` (null si meta_esperada es 0/null)

**`estado`** (string, lo calcula el backend; el front solo colorea):
- `sin_datos` — no hay ningún valor
- `en_riesgo` — cumplimiento_pct < 70
- `atencion` — 70 ≤ cumplimiento_pct < 100
- `cumple` — 100 ≤ cumplimiento_pct < 110
- `excede` — cumplimiento_pct ≥ 110

Para `direccion = "menor_mejor"` se invierte: `cumplimiento_pct` se calcula como
`meta_esperada / consolidado * 100` (y si consolidado es 0 → `excede`).

`avance_global_pct` del Q = promedio simple de `cumplimiento_pct` de las métricas
que tengan dato (null si ninguna tiene).

**`estado_periodo`** del Q, contra la fecha de hoy:
`proximo` (hoy < fecha_inicio) | `en_curso` | `cerrado` (hoy > fecha_fin)

---

## 5. API — prefijo `/api/v1/retos`

`router = APIRouter(prefix="/retos", tags=["Retos trimestrales"])`

Lecturas: `_=Depends(get_current_user)`.
Escrituras: `current: Usuario = Depends(get_current_user)` (para `actualizado_por_id`).

### `GET /retos?anio=2026`
**Autocrea** los 4 trimestres del año si no existen, con fechas de trimestre
calendario (Q1 1-ene→31-mar, Q2 1-abr→30-jun, Q3 1-jul→30-sep, Q4 1-oct→31-dic)
y `nombre = "Retos Q{n} {anio}"`. Responde ordenado por trimestre.

```json
{
  "anio": 2026,
  "anios_disponibles": [2025, 2026, 2027],
  "retos": [ RetoResumen, RetoResumen, RetoResumen, RetoResumen ]
}
```

**RetoResumen**
```json
{
  "id": 3,
  "anio": 2026,
  "trimestre": 3,
  "nombre": "Retos Q3 2026",
  "descripcion": null,
  "fecha_inicio": "2026-07-01",
  "fecha_fin": "2026-09-30",
  "total_semanas": 14,
  "semana_actual": 7,
  "estado_periodo": "en_curso",
  "total_metricas": 5,
  "semanas_con_datos": 6,
  "avance_global_pct": 82.4,
  "metricas": [ MetricaResumen ]
}
```
`semana_actual` = número de la semana que contiene hoy; `null` si hoy está fuera del rango.

**MetricaResumen**
```json
{
  "id": 10,
  "reto_id": 3,
  "nombre": "MWh comercializados",
  "descripcion": null,
  "unidad": "MWh",
  "meta": 1200.0,
  "tipo_agregacion": "suma",
  "direccion": "mayor_mejor",
  "decimales": 1,
  "responsable": "Laura",
  "orden": 0,
  "activa": true,
  "consolidado": 640.5,
  "meta_esperada": 600.0,
  "avance_pct": 53.4,
  "cumplimiento_pct": 106.8,
  "estado": "cumple",
  "semanas_con_dato": 7,
  "serie": [ {"semana": 1, "valor": 90.0}, {"semana": 2, "valor": null} ]
}
```
`serie` trae TODAS las semanas del Q en orden (valor null donde no hay dato) —
sirve para el sparkline sin que el front tenga que rellenar huecos.

### `GET /retos/{id}`
**RetoDetalle** = `RetoResumen` + estos dos campos:
```json
{
  "semanas": [
    {
      "numero": 1,
      "inicio": "2026-06-29",
      "fin": "2026-07-05",
      "inicio_efectivo": "2026-07-01",
      "fin_efectivo": "2026-07-05",
      "etiqueta": "S1",
      "rango_label": "29 jun–5 jul",
      "es_actual": false,
      "es_futura": false,
      "parcial": true
    }
  ],
  "valores": {
    "10": {
      "2026-06-29": {
        "valor": 90.0,
        "nota": "arranque lento",
        "actualizado_por": "Juan José",
        "updated_at": "2026-08-14T10:00:00Z"
      }
    }
  }
}
```
`valores` está indexado por `str(metrica_id)` → `str(semana_inicio ISO)`.
`parcial` = la semana no cae completa dentro del rango del Q.

404 si no existe.

### `PATCH /retos/{id}`
Body parcial: `{ "nombre": str, "descripcion": str, "fecha_inicio": "YYYY-MM-DD", "fecha_fin": "YYYY-MM-DD" }`
→ **RetoDetalle**.
- 400 `"La fecha de fin debe ser posterior a la de inicio"` si `fecha_fin <= fecha_inicio`.
- 400 `"El rango no puede superar 60 semanas"`.

### `POST /retos/{id}/metricas` → 201, **MetricaResumen**
Body: `{ "nombre": str (req), "descripcion": str?, "unidad": str?, "meta": float?, "tipo_agregacion": str?, "direccion": str?, "decimales": int?, "responsable": str? }`
`orden` se asigna solo (max+1) si no viene.
- 400 si `tipo_agregacion` o `direccion` no están en los valores permitidos.
- 404 si el reto no existe.

### `PATCH /retos/metricas/{metrica_id}` → **MetricaResumen**
Body parcial con los mismos campos + `orden`, `activa`.

### `DELETE /retos/metricas/{metrica_id}` → 204
Borra la métrica y sus valores (cascade).

### `PUT /retos/metricas/{metrica_id}/valores/{semana_inicio}` → **MetricaResumen**
`semana_inicio` en path como `YYYY-MM-DD`. Body: `{ "valor": float|null, "nota": str|null }`
Upsert. Devuelve la MetricaResumen **recalculada** para que el front actualice el
consolidado sin recargar todo.
- 400 `"La semana debe empezar en lunes"` si `semana_inicio.weekday() != 0`.
- 400 `"La semana está fuera del rango del trimestre"` si no corresponde a una semana generada.
- 404 si la métrica no existe.

### `POST /retos/{id}/metricas/copiar-desde/{origen_id}` → lista de **MetricaResumen**
Clona las métricas `activa=True` del reto origen (nombre, unidad, meta, tipo, dirección,
decimales, responsable, orden) SIN los valores. No duplica métricas cuyo `nombre` ya
exista en el destino.
- 400 si `origen_id == id`.
- 404 si cualquiera de los dos no existe.

---

## 6. Frontend — rutas y navegación

- `src/views/Retos/RetosListView.vue` → `/general/retos` · name `Retos`
- `src/views/Retos/RetoDetailView.vue` → `/general/retos/:id` · name `RetoDetalle`
- **Sin `meta.roles`** (visible a cualquier usuario logueado), igual que `/general/proximos-energizar`.
- Sidebar `AppSidebar.vue` → grupo **General**, después de "Próximos a energizar":
  `{ to: '/general/retos', label: 'Retos Q', icon: 'pi pi-flag-fill' }`

---

## 7. UX / visual — reglas obligatorias

Marca (de `tailwind.config.js` y `main.css`):
- Púrpura energético `#915BD8` · púrpura profundo `#2C2039` · avena `#FDFAF7` (fondo de página, ya global) · amarillo solar `#F6FF72`
- Tipografía: **Lato** (ya global, no declararla)
- Cards: `bg-white rounded-xl shadow-sm` + `style="border: 1px solid #e8e0f0"`
- Texto secundario: `#6b5a8a` / `#9b8fb0`
- Contenedor raíz de la vista: `<div class="space-y-4">` (el padding lo pone App.vue)
- Usar el `<PageHeader>` global (title + subtitle + slots `lead` / `actions`)

Semáforo de estados (consistente con Cumplimiento):
| estado | color | uso |
|---|---|---|
| `sin_datos` | `#9b8fb0` gris malva | |
| `en_riesgo` | `#D64455` rojo | |
| `atencion` | `#CA8A04` ámbar | |
| `cumple` | `#10B981` verde | |
| `excede` | `#14B8A6` turquesa | excedente, NO dorado |

PrimeVue: **importar cada componente localmente** en el SFC (no hay registro global
salvo `PageHeader` e `InfoField`). `DataTable` nunca recibe un `computed`, solo un `ref` plano.

Densidad: compacta. Texto base 12–13px, headers de tabla 10–11px uppercase tracking-wide,
filas `py-2`. Nada de aire de sobra: el usuario pidió "visualmente compacta".
