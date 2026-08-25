# Panel Contable alimentado por la API de Liquidaciones

**Fecha:** 2026-08-25
**Estado:** diseño aprobado, sin implementar

## Problema

El Panel Contable —que produce las liquidaciones por proyecto y por inversionista—
se arma subiendo el Estado de Resultados en Excel de cada proyecto. Ese archivo llega
con las fórmulas sin evaluar, así que el backend necesita **LibreOffice headless** para
recalcularlo antes de parsearlo. De ahí cuelga todo: un parser de celdas, un mapeo por
tipo de panel, y un snapshot congelado que solo se refresca volviendo a subir el archivo.

La API de Liquidaciones ya expone esa misma información en JSON
(`income_statement_data`). Se verificó contra el período **2026-07**, 38 paneles
oficiales contra 52 proyectos de la API:

| Comparación | Resultado |
|---|---|
| Ingreso bruto | **31 de 37 cuadran con diferencia 0,0 %** (al peso) |
| Comercialización | Cuadra concepto por concepto, al peso |
| Los 6 que no cuadraban | 4 son NEU · 1 tenía cargado el ER equivocado · 1 tenía una compra errónea, ya corregida |

La API es una fuente equivalente al Excel para todo lo que no sea NEU ni Nitro.

## Objetivo

Que el Panel se arme desde la API para todos los proyectos salvo NEU y Nitro,
que los costos de OPEX vengan de nuestros módulos, que el reparto por inversionista
lo hagamos nosotros con nuestros porcentajes vigentes, y que el Estado de Resultados
lo generemos desde nuestra vista —por proyecto o por inversionista— en vez de
descargarlo de Drive.

## Arquitectura

```
income_statement_data (API) ──→ panel_desde_api.py ──┐
                                                      ├──→ ResultadoMensual
ER en Excel (SOLO NEU/Nitro) ──→ er_loader.parsear_er ┘         │
                                                                ↓
                                                    _construir_lineas_base
                                                                ↓
              módulos de costo: om · arriendos · starlink · polizas ─┤
                                                                ↓
                          reparto por NUESTROS inversionistas vigentes
                                                                ↓
                                            PanelContable + líneas (editables)
                                                                ↓
                                       ER propio .xlsx — proyecto o inversionista
```

La pieza central es **`ResultadoMensual`**: hoy existe como el `dict` que devuelve
`parsear_er()`, pero implícito. Al declararlo como contrato explícito, el Excel y la
API pasan a ser dos productores intercambiables y el resto del Panel —reparto,
impuestos, edición— no se entera de cuál se usó. Eso mantiene el cambio fuera de la
parte delicada.

## Componentes

### `app/services/panel_desde_api.py` — nuevo

Arma el `ResultadoMensual` desde `income_statement_data`.

- **Ingresos:** suma de las líneas `dispatch` y `dispatch_fazni`. Una línea por
  contrato: si la planta tiene dos, entran los dos (verificado en Vallenata, que trae
  40.189.569 + 37.275.016 y cuadra con el Excel al peso).
- **Compras:** solo se aceptan en los proyectos que legítimamente compran. En
  cualquier otro, la línea se excluye del cálculo y **el panel queda marcado**, porque
  es un error de datos aguas arriba.
- **Energía:** `generacion_kwh`.
- **Comercialización:** la que trae la API, **incluyendo `fazni_generador` y
  `cargo_confiabilidad_generador`**, que el Excel no tiene. Cuando la API avisa que
  esa fila le faltó (bug conocido de backend-inv), el concepto se marca como
  incompleto en vez de mostrarse como un cero legítimo.

**Tópicos que sí compran** (exactos, verificados contra la API):

```
naos1 · delta_1 · polaris_1 · baraya · jerico_el_son · ibirico · mapale · cacica · piloneras
```

Ojo: `delta_2`, `naos2`, `naos3` y `polaris_2` **no** están en la lista.

### `app/services/costos_panel.py` — extender

Hoy resuelve Mantenimiento (`om`), Arrendamiento (`arriendos`) e Internet
(contrato de servicio). Se agregan dos fuentes:

- **Internet ← Starlink.** La factura real del período, por proyecto. Verificado
  contra julio: 26 proyectos, los 26 al peso, total 3.894.133 en ambos lados. Las
  líneas de Starlink que no cruzan con un panel son plantas no operativas.
- **Póliza ← módulo `polizas`.** La tabla está vacía hoy (el módulo está en
  desarrollo); se conecta para que empiece a alimentar cuando tenga datos, sin
  romper nada mientras tanto.

### `app/api/v1/panel_contable.py` — endpoint nuevo

`POST /panel-contable/cargar-periodo` arma todos los paneles del mes de una sola
llamada, sin subir archivos. `cargar-er` sobrevive **solo para NEU y Nitro**, que
siguen necesitando el Excel porque su dato de API no sirve.

### `app/services/er_export.py` — nuevo

Genera el Estado de Resultados en `.xlsx` desde las líneas del panel, con los
**valores ya calculados** —no fórmulas sin evaluar, que es el defecto del archivo de
ellos. Dos alcances: proyecto completo (100 %) o un inversionista puntual.

## Reglas de negocio

| Concepto | Fórmula | Si falta la tarifa |
|---|---|---|
| Representación | `tarifa_representacion` indexada × kWh | No se cobra |
| CGM | `tarifa_cgm` indexada × kWh | No se cobra |
| Administración | `tarifa_admin` × suma de ingresos | **No se cobra** |

**Sin valores por defecto.** Nueve proyectos GD (Bayunca, Sirius, San Onofre,
Astrolumen, Biosolar, La Catedral, Yurbaqua, Los Bongos, Ciénaga) tienen tarifa de
representación y CGM pero **no** de administración, porque no tienen servicio de
operación. Que no se les cobre es lo correcto: hoy el Excel les carga 3,8 % que no
corresponde.

La Administración se calcula sobre la **suma de ventas**, nunca sobre el neto de
compras. Una compra errónea no puede bajar el fee sin que nadie se entere.

## Datos a corregir antes de encender

1. **Cedillanos:** `topico_liquidaciones = 'cedillanosexc'`. Nuestro tópico
   `cedillanos` apunta al lado de consumo (`from_generator=False`); el que liquida es
   `cedillanosexc`, que da 21.140.803 y cuadra con el panel al peso. Además
   `tarifa_admin = 0.05` (se venía calculando por fuera del Excel).
2. **Sabana de Torres:** crear contrato de representación con `tarifa_admin = 0.038`,
   `tarifa_representacion = 6`, `tarifa_cgm = 6`.
3. **Contratos de representación duplicados:** 66 filas para 38 proyectos, algunas con
   tarifas contradictorias —Joropo tiene una en 0 y otra en 5. El código toma el de
   menor `id`, que puede ser el equivocado. Se define una regla determinista:
   vigente + con tarifa cargada + el más reciente.

## Efecto en la liquidación (julio como referencia)

| | |
|---|---|
| Administración que los 9 GD no debían pagar | **−26.443.140** |
| FAZNI y cargo por confiabilidad que no se cobraban | **+10.564.281** |
| Repre y CGM que dejan de arrastrarse del Excel | 72,6 M pasan a calcularse |

## Errores que este cambio deja a la vista

El cruce contra la API es, además, una auditoría. En julio destapó dos cosas que
llevaban meses sin verse:

- **Chiriguana Norte 2** tiene cargado el ER de **Agustín 2**
  (`er_filename = "Estado resultados FONSAR S.A.S. Agustín 2 7 2026.xlsx"`). Su
  liquidación de julio salió con los números de otra planta.
- **Agustín 1** trae una compra de 122.324.739 por los mismos 173.354,45 kWh que
  vendió, cuando su importación real son 596,56 kWh. Es el mismo error que tenía
  Verso, ya corregido de ese lado.

## Fuera de alcance

- **NEU y Nitro** siguen con el Excel. Su dato de API está malo y no se toca.
- El **reparto por inversionista de la API** no se usa. Sus
  `participant_project_agreements` quedaron congelados antes del traspaso de marzo:
  para Merengue siguen reportando a Ayurá al 50 % cuando lo vigente desde marzo es
  Patrimonios Autónomos al 100 %. El reparto lo hacemos nosotros, con nuestros
  porcentajes vigentes, que sí están bien.
- **PDF del ER.** Por ahora solo Excel; no hay plantilla definida.

## Verificación

El período **2026-07** es el caso de prueba: hay 38 paneles oficiales cargados desde
el Excel y la API responde los 52 proyectos sin errores. La implementación debe poder
armar los paneles desde la API y cuadrar contra los del Excel en los conceptos donde
ambos deben coincidir, con las diferencias esperadas ya documentadas arriba
(administración de los 9 GD, FAZNI y confiabilidad, y los 4 NEU).
