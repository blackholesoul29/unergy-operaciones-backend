# API del pipeline de PPAs

Una llamada devuelve **los contratos de energía del pipeline comercial**, ordenados como
un árbol:

**PPA → PROYECTOS → detalles de cada proyecto.**

- **Base URL:** `https://backend-production-63d8.up.railway.app`
- **Endpoint:** `GET /api/v1/comercial/proyectos-operando`
- **Swagger:** https://backend-production-63d8.up.railway.app/docs
- **Solo lectura.** No escribe nada.
- **Auth:** header `X-API-Key`. Sirve cualquier rol; no exige rol comercial porque no
  expone precios, márgenes ni bitácora comercial.

> **Cambio de forma (2026-08-18).** Este endpoint devolvía **una fila por planta** en
> `items[]`. Ahora devuelve **un nodo por PPA** en `ppas[]`. Es un reemplazo, no una
> variante: `items` ya no existe.

---

## 1. La idea que hay que entender primero

**Un PPA que no está firmado no existe como contrato.** La oferta del CRM *es* el PPA
hasta que se firma. Eso se lee en un solo campo:

| | `ppa.id` es `null` | `ppa.id` con valor |
|---|---|---|
| Qué es | **Borrador** | Contrato real |
| Fila en `ppa_contratos` | No hay | Sí |
| Aparece en `/servicios` | **No** | Sí |
| De dónde salen las condiciones | De la oferta (tentativas) | Del contrato (pactadas) |

`aparece_en_servicios` viaja como booleano y dice exactamente lo mismo, para no obligar a
deducirlo.

Por eso no hay PPAs de mentira en la base: un borrador no tiene fila, así que no puede
colarse en Cumplimiento, GESCON, liquidaciones ni facturación, que son los módulos que
leen `ppa_contratos`.

---

## 2. `estado_ppa`

| Valor | Qué significa | Qué esperar |
|---|---|---|
| `borrador` | Etapa `oferta` o `contrato`: el PPA está en preparación | `id: null`. Condiciones tentativas. Es normal que no haya proyectos vinculados |
| `firmado` | El contrato existe | `id` poblado, condiciones del contrato |
| `sin_contrato` | **Inconsistencia.** La oferta está `firmado` u `operando` pero no hay PPA cargado | El negocio cerró y el contrato falta. Es dato por cargar de nuestro lado |

`sin_contrato` **no se rellena** inventando un contrato con fechas y tarifas nulas: eso
metería compromisos fantasma en Cumplimiento. Se muestra para que se corrija. Si te
aparece uno, avisá.

---

## 3. Qué entra al árbol

**Solo contratos de energía:** ofertas de `compra_energia` y de `comunidad_energetica`.

- Las ofertas de **servicios** (representación, CGM) **no** salen: desembocan en
  `contratos_servicio`, que es otra entidad. No son PPAs.
- **Comunidad energética no es un tipo aparte**: es un PPA con
  `es_comunidad_energetica: true`.
- Las **salidas** del pipeline (`declinado`, `terminado`) no producen PPA. Un negocio
  caído no es un contrato en preparación. Pedirlas da **422**, no una lista vacía.

Las cuatro etapas que sí producen PPA: `oferta`, `contrato`, `firmado`, `operando`.

---

## 4. La respuesta

```jsonc
{
  "generado_en": "2026-08-18T14:03:11-05:00",
  "estados_pipeline": ["oferta", "contrato", "firmado", "operando"],
  "total": 61,
  "por_estado_ppa": { "borrador": 49, "firmado": 5, "sin_contrato": 7 },
  "ppas": [
    {
      "ppa": {
        "id": null,
        "es_borrador": true,
        "estado_ppa": "borrador",
        "aparece_en_servicios": false,
        "etapa_comercial": "oferta",
        "numero_codigo_contrato": null,
        "nombre_interno": null,
        "planta_declarada": "Balmora 1 y 2",
        "condiciones": {
          "origen": "oferta",
          "fecha_inicio": "2026-09-01",
          "fecha_fin": "2033-08-31",
          "duracion_meses": 84,
          "duracion_anios": 7.0,
          "duracion_texto": "7 años",
          "meses_restantes": 84,
          "vigente": false,
          "energia_kwh_mes": 150000.0
        },
        "es_comunidad_energetica": false,
        "cantidad_proyectos": 2,
        "cliente": "INVERSIONES BIOSOSTENIBLES S.A.S.",
        "oferta_id": 33,
        "codigo_seguimiento": "OP.COM No.0051-3-2026",
        "oportunidad_id": 12,
        "tipo_contrato": null,
        "comprador": null,
        "vendedor": null
      },
      "proyectos": [
        {
          "proyecto_id": 276,
          "nombre": "GD Balmora 1",
          "api_id_unergy": "balmora1",
          "detalles": {
            "energia_promedio_mensual_mwh": 178.412,
            "energia_promedio_mensual_kwh": 178412.0,
            "energia_promedio_origen": "medido",
            "energia_promedio_detalle": {
              "dias_con_datos": 30,
              "ventana_desde": "2026-07-18",
              "ventana_hasta": "2026-08-17",
              "actualizado_en": "2026-08-17T21:18:45-05:00"
            }
          }
        }
      ]
    }
  ]
}
```

### `condiciones`

Periodo, duración y energía del PPA. **`origen` dice si son pactadas o tentativas** —
`"contrato"` o `"oferta"`. Sin ese campo, una fecha de la oferta y una firmada se leen
idénticas.

`energia_kwh_mes` ocupa la misma casilla en los dos casos pero no es el mismo hecho: del
contrato es `cantidad_minima_kwh_mes` (un compromiso), de la oferta es la estimación
técnica de la planta. `origen` avisa.

`meses_restantes` de un contrato que todavía no arrancó es su duración completa, nunca la
distancia hasta el fin. Nunca es mayor que `duracion_meses`.

### `proyectos[]` y sus `detalles`

Las plantas del PPA. **De dónde salen depende del estado:** si el contrato existe, son las
de `ppa_contrato_proyectos` (la verdad contractual); si es borrador, las que declaró la
oferta.

Un PPA puede traer **varias** plantas (`cantidad_proyectos`): hay ofertas que cubren dos
("Balmora 1 y 2"). Y puede traer **cero**: hoy el 74% del pipeline no tiene la planta
vinculada como proyecto en la plataforma, y en esos casos `proyectos` viene vacío con
`planta_declarada` como único nombre disponible. El nodo existe igual — el negocio existe.

`energia_promedio_origen` **hay que leerlo siempre**:

| Valor | Qué es | Confiabilidad |
|---|---|---|
| `medido` | Promedio de generación real de los últimos 30 días | Alta |
| `manual` | Lo cargó una persona (planta sin histórico) | Media |
| `estimado` | Proyección de ingeniería (curva P50) | Baja para operación |
| `declarado` | Lo declaró la oferta; la planta no existe en la plataforma | Baja |
| `null` | Nadie lo aportó. **No es un error** | — |

**No hay energía acumulada en la respuesta, a propósito.** `api_id_unergy` es la llave para
consultarla contra la API de generación de Unergy cuando se necesite: calcular acumulados
históricos por planta en cada request haría lenta una llamada que se usa en cada refresco.

---

## 5. Filtros

| Parámetro | Qué hace |
|---|---|
| `estado_pipeline` | Acota a etapas: `oferta` · `contrato` · `firmado` · `operando`. Repetible. Por defecto vienen las cuatro |
| `todas_las_etapas` | Ya es el comportamiento por defecto. Se conserva para no romper llamadas que lo vienen mandando |
| `q` | Busca en planta declarada, cliente, código de seguimiento, código de contrato y nombre de cada proyecto |

Acotar la etapa **elige PPAs, no recorta su contenido**: un PPA que entra sigue trayendo
todas sus plantas.

```bash
export BASE="https://backend-production-63d8.up.railway.app/api/v1"

# todo el pipeline de contratos
curl "$BASE/comercial/proyectos-operando" -H "X-API-Key: $UNERGY_API_KEY"

# solo los contratos ya firmados y operando
curl "$BASE/comercial/proyectos-operando?estado_pipeline=firmado&estado_pipeline=operando" \
  -H "X-API-Key: $UNERGY_API_KEY"

# solo los borradores
curl "$BASE/comercial/proyectos-operando?estado_pipeline=oferta&estado_pipeline=contrato" \
  -H "X-API-Key: $UNERGY_API_KEY"
```

---

## 6. Errores

| Código | Cuándo |
|---|---|
| 401 | Falta el header `X-API-Key`, o la key no existe / está desactivada |
| 422 | `estado_pipeline` recibió algo que no es una de las cuatro etapas con PPA (incluye `declinado` y `terminado`, que existen en el CRM pero nunca tienen contrato) |

Un resultado vacío no es un error: 200 con `total: 0`, `ppas` vacío y `por_estado_ppa` vacío.

---

## 7. Recomendaciones

- **Cacheá de tu lado.** Los datos cambian a lo sumo una vez al día. Una vez por hora sobra.
- **Timeout de 60 s**: la llamada tarda menos de un segundo, pero Railway puede tener
  arranque en frío.
- **`generado_en`** dice de cuándo es la foto. Mostrala si tu tablero cachea.

---

## 8. Cómo se materializa un PPA

`POST /comercial/ofertas/{id}/firmar` es la única puerta: crea la fila en `ppa_contratos`
con las condiciones pactadas, expande la tabla de precios anuales a tarifas mensuales,
pasa **todas** las plantas de la oferta al contrato y mueve la oferta a `firmado`. Desde
ese momento el PPA aparece en `/servicios` y su nodo deja de ser borrador.

Es idempotente por enlace: si la oferta ya tiene contrato responde 409 en vez de crear un
segundo.

---

## 9. Contacto

Juan José (juanjose@unergy.io) para API keys, para reportar datos en `null` o
`sin_contrato`, y para pedir campos nuevos.
