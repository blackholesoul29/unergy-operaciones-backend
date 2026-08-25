# Pendientes de la API de Liquidaciones — para backend-inv

Todo lo de aquí está verificado contra producción entre el 24 y el 25 de agosto de
2026, con la cuenta `admin_jessica`. Cada punto trae cómo reproducirlo.

Están en orden de impacto: lo primero afecta plata que se liquida.

---

## 1. Compra fantasma en GD Agustín 1 — afecta la liquidación

`GET /api/liquidaciones/income_statement_data/?month=7&year=2026&version=txf`

```
GD Agustin 1  venta=58.940.513  compra=122.324.739  ingreso_bruto=-63.384.226
   UNERGY ENERGIA DIGITAL S.A.S ESP Venta   [dispatch]  kwh=173.354,45    58.940.513
   UNERGY ENERGIA DIGITAL S.A.S ESP Compra  [purchase]  kwh=173.354,45  -122.324.739
```

La compra cubre **exactamente los mismos 173.354,45 kWh** que la venta, cuando la
importación real del proyecto son **596,56 kWh**. El ingreso bruto queda negativo.

Es el mismo error que tenía `verso`, que ustedes ya corrigieron: hoy `verso` responde
`compra=0` y cuadra al peso con nuestro Panel. Falta aplicarle lo mismo a `agustin_1`.

**Los proyectos que sí compran legítimamente son solo estos** (tópicos exactos):

```
naos1 · delta_1 · polaris_1 · baraya · jerico_el_son · ibirico · mapale · cacica · piloneras
```

Cualquier `purchase` fuera de esa lista es un contrato mal clasificado.

---

## 2. FAZNI y cargo por confiabilidad faltan en 41 de 52 proyectos

Es el fallo del paso 12 que ustedes ya documentan en la §8 de la guía. Lo confirmamos
en 2026-07: **41 de 52** proyectos traen los dos warnings.

```
"Falta la fila 'fazni_generador'. Es un fallo conocido del paso 12 y subestima los costos."
"Falta la fila 'cargo_confiabilidad_generador'. ..."
```

Importa más de lo que parece: son cargos **reales** que hay que cobrar. Donde sí se
crean suman 10.564.281 en julio. Al faltar, la utilidad queda inflada y se reparte de
más.

---

## 3. `participant_project_agreements` quedaron congelados antes de marzo

El reparto por partícipe que devuelve la API no refleja los traspasos de propiedad.
En 2026-07, seis proyectos no reparten el 100 %:

| Proyecto | La API reparte | Lo vigente en julio |
|---|---|---|
| MGS 0019 El Merengue | 50 % (Ayurá) | Patrimonios Autónomos 100 % |
| MGS 0012 La Reserva | 75 % | Estrada 63,17 % · Strada 11,83 % · SUNO 25 % |
| Minigranja Solar Uruaco | 77,2 % | Patrimonios 77,19 % · Rodríguez 11,06 % · SUNO 11,75 % |
| MiniGranja 0033 Sabana de Torres | 57 % | — |
| MGS 0025 El Copey Occidente | **0,1 %** | Patrimonios 100 % |
| MGS 0027 Valencia Oriente 2 | **0,05 %** | Patrimonios 100 % |

Los dos últimos parecen un error de escala: reparten 0,05 % donde debería ser 100 %,
o sea 1/2000 del valor.

Nosotros no vamos a consumir ese reparto —lo hacemos con nuestros porcentajes
vigentes— pero mientras esté así, el `income_statement_data` no sirve para facturarle
a un partícipe.

---

## 4. `GET /create_revenue_and_cost_xlsx/` responde 400

```
GET /api/liquidaciones/create_revenue_and_cost_xlsx/
→ 400 {"errors":"name 'pd' is not defined"}
```

Falta el `import pandas as pd`. Es la ruta que baja la plantilla de carga de costos;
por eso no exponemos ese botón. El `POST` de la misma ruta sí funciona.

---

## 5. Cinco contratos PLG sin `code` quedaron imposibles de editar

`PATCH /api/liquidaciones/contract_energies/{id}/` **revalida el objeto completo**, no
es parcial. Con cuerpo vacío sobre el contrato 124:

```
→ 400 {"non_field_errors":["code es requerido para los contratos PLC y PLG (es el código del contrato en XM)."]}
```

Ese contrato está guardado con `code: null` y `contract_type: ppa_pay_as_generated`, o
sea **en un estado que su propio validador rechaza**. No se puede tocar sin inventarle
un código.

De 106 contratos, 25 no tienen código: 20 son `no_contract` (correcto) y **5 son PLG
sin código** (bloqueados).

Dos opciones: que el PATCH sea parcial de verdad, o corregirles el código.

---

## 6. No hay forma de borrar ni anular un contrato

```
contract_energies/            → GET, POST
contract_energies/{id}/       → GET, PUT, PATCH
contract_energy_projects/     → GET, POST
contract_energy_projects/{id}/→ GET, PUT, PATCH
```

Sin `DELETE` en ninguno. Un contrato creado por error se queda para siempre, y como no
hay bandera de anulado, la única forma de sacarlo de la liquidación es ponerle
`date_to` en el pasado. El listado va acumulando contratos muertos sin manera de
distinguirlos.

Preferiríamos un **campo de anulado** antes que un borrado real: un contrato ya
liquidado no debería poder desaparecer sin dejar rastro.

---

## 7. Filtros que faltan en `revenue_and_costs/`

Es el único listado con problema de tamaño: 10.536 filas, 22 páginas, ~11 s traerlo
entero. Los otros dos históricos son más grandes (`market_settlements` 31.853,
`disp_contracts_ftp_xm` 20.993) y **no** dan problema, porque su `?year=&month=` sí
funciona.

| Filtro | Estado | Cuánto ayudaría |
|---|---|---|
| `?group=` | no filtra | Nuestra pantalla solo usa `xm`: 5.930 de 10.536. El campo `group` ya existe en `revenue_and_cost_types` |
| `?year=&month=` | no filtra | Igual que en los tres históricos. Dejaría la consulta en cientos de filas |
| `?value__gt=0` | no filtra | **6.063 de 10.536 valen cero** (57 %), casi todos filas que el reparto crea para proyectos a los que el concepto no aplica |

Con `?group=` y el período nos ahorramos la caché que tuvimos que poner de nuestro lado.

---

## 8. Los parámetros desconocidos se ignoran en silencio

Esto es lo más peligroso de la lista, aunque parezca menor.

| Endpoint | Sin filtro | Con `?parametro_que_no_existe=zzz` |
|---|---|---|
| `revenue_and_costs/` | 10.536 | 10.536 |
| `market_settlements/` | 31.853 | 31.853 |
| `disp_contracts_ftp_xm/` | 20.993 | 20.993 |
| `contract_energies/` | 107 | 107 |
| `projects/` | 112 | 112 |

Todos responden **200 con el listado completo**. Quien escriba `?grupo=xm` en vez de
`?group=xm` recibe las diez mil filas creyendo que filtró. Un **400 diciendo que ese
filtro no existe** evitaría toda esa clase de error.

(La guía promete 400 para un filtro *mal tipado* —`?year=julio`— y eso sí funciona. El
problema es el parámetro *inexistente*.)

---

## Lo que ya arreglaron y confirmamos

- **`?payment_type=`** ya no da 500. Funciona y lo estamos usando.
- **`verso`** ya no trae la compra fantasma: `compra=0`, cuadra al peso con nuestro Panel.
- **La paginación** quedó bien. Solo avisen antes la próxima vez que cambien el
  contrato de respuesta: nuestro cliente esperaba una lista pelada y estuvo devolviendo
  error hasta que lo migramos.
