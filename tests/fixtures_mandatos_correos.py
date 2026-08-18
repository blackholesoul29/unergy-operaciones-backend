"""Correos reales revisados el 2026-08-18, usados como fixtures del parser.

Transcritos de capturas del buzón adhara@unergy.io. Se conservan tal cual --
la redacción exacta ES el caso de prueba. No "limpiar" ni normalizar nada acá.

Las "fuentes" que nombran las secciones son las tres del spec
(docs/superpowers/specs/2026-08-18-mandatos-fase-b-imap-design.md §6.4):

  Fuente 1  observaciones de la revisoría          → estado con_correcciones
  Fuente 2  PDF firmado adjunto por la revisoría   → estado firmado
  Fuente 3  envío de Jessica al inversionista      → estado enviado_inversionista

Un mismo correo puede alimentar varias fuentes: el del 14 jul trae PDFs
firmados y observaciones a la vez.
"""

# ── Fuente 1/2 -- revisoría (vlondono@jbp.com.co) ─────────────────────────────

# 2026-08-10 2:25 p.m. -- observaciones nuevas, con tabla HTML embebida.
REVISORIA_OBSERVACIONES = """Buenas tardes Adhara,

Revisando la información que me compartes, encuentro las siguientes observaciones:

1. Certificado CMU1255 el valor a pagar no coincide con la suma de los conceptos detallados, además encuentro una diferencia entre contabilidad y el certificado así:

2. Certificados CMU1266,CMU1269,CMU1270 y CMU1271   no se evidencia contabilización del internet, el IVA y el arriendo.
3. Certificado CMU1284 no se evidencia contabilización

Quedo atenta,

Cordialmente
Vanessa Londoño Sánchez
Asistente de auditoria
JB Pérez & Cía S.A.S."""

# 2026-08-10 5:50 p.m. -- respuesta en el hilo. CMU1255 quedó RESUELTO.
# Caso de regresión más importante del sistema: un regex de CMU\\d+ marcaría
# CMU1255 como con_correcciones siendo el único que quedó bien.
REVISORIA_SEGUIMIENTO = """Hola Vanessa,

Agradezco su respuesta y los ajustes realizados para el mandato CMU1255. Sin embargo, para los mandatos CMU1266, CMU1269, CMU1271 y CMU1284, las observaciones siguen siendo las mismas.

Por favor, valide los conceptos y los comentarios anteriores para realizar la contabilización o los ajustes correspondientes, ya que en algunos casos se evidencia la contabilización pero no de todos los conceptos que se encuentran certificados.

Cordialmente
Vanessa Londoño Sánchez"""

# 2026-07-14 3:20 p.m. -- PDFs firmados Y observaciones en el mismo correo.
REVISORIA_MIXTO = """Buenas tardes, Adhara:

Adjunto comparto los certificados de Sol de la Sierra debidamente firmados. Asimismo, relaciono a continuación las diferencias identificadas en los certificados de costos:

CMU1052 No se evidencia contabilización del mantenimiento y el IVA de este.
CMU1122 Evidencio que el arrendamiento se encuentra contabilizado al debito y al crédito generado un efecto 0 en el valor y una diferencia con el certificado

Los demás certificados se encuentran actualmente en proceso de firma y se los estaré compartiendo tan pronto estén listos.

Cordialmente
Vanessa Londoño Sánchez"""

# El MISMO correo de REVISORIA_OBSERVACIONES (10 ago 2:25 p.m.), pero en su
# versión HTML con la tabla embebida. No es un cuarto correo: existe aparte
# para ejercitar html_a_texto() contra entidades, <p> y <table> reales.
REVISORIA_HTML = """<div dir="ltr"><p>Buenas tardes Adhara,</p>
<p>Revisando la informaci&oacute;n que me compartes, encuentro las siguientes observaciones:</p>
<p>1. Certificado CMU1255 el valor a pagar no coincide con la suma de los conceptos detallados, adem&aacute;s encuentro una diferencia entre contabilidad y el certificado as&iacute;:</p>
<table><tr><td>Certificado</td><td>Contabilidad</td></tr>
<tr><td>5,703,802</td><td>5,475,170.65</td></tr></table>
<p>2. Certificados CMU1266,CMU1269,CMU1270 y CMU1271 &nbsp; no se evidencia contabilizaci&oacute;n del internet, el IVA y el arriendo.</p>
<p>3. Certificado CMU1284 no se evidencia contabilizaci&oacute;n</p>
<p>Cordialmente</p></div>"""

# ── Fuente 3 -- envío a inversionistas (jessica@unergy.io) ────────────────────

# 2026-08-12 8:14 a.m. -- el correo real declara 8 adjuntos; acá van los 5
# visibles en la captura (1 xlsx + 4 PDFs de mandato). Basta para el caso de
# prueba: lo que se ejercita es que el .xlsx se descarte y que cada PDF aporte
# su CMU, no cuántos adjuntos traía el correo.
ENVIO_INVERSIONISTA = """Cordial saludo equipo de PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA , espero se encuentren muy bien.

La presente es con el fin de informarles que los certificados de mandato de costos de los proyectos asociados al 17844 - P.A SOL DE LA SIERRA del mes de junio ya se encuentran emitidos y firmados con fecha actual. Anexo bajo este correo cada uno de estos certificados de mandato

--
Cordialmente,
Jessica Ramirez"""

ENVIO_INVERSIONISTA_ADJUNTOS = [
    "REGISTRO MANDATOS.xlsx",
    "CMU1135-Mandato-Costos-Sol de la Sierra-Bancolombia.pdf",
    "CMU1141-Mandato-Costos-Sol de la Sierra-Bancolombia.pdf",
    "CMU1139-Mandato-Costos-Sol de la Sierra-Bancolombia.pdf",
    "CMU1142-Mandato-Costos-Sol de la Sierra-Bancolombia.pdf",
]

# 2026-08-12 5:05 p.m. -- "Liquidación preliminar". Caso NEGATIVO: es de Jessica,
# va a un inversionista y menciona "certificados de mandato", pero no trae
# adjuntos de mandato. La regla de Fuente 3 debe descartarlo sin excepciones.
LIQUIDACION_PRELIMINAR = """LIQUIDACIÓN PRELIMINAR
ESTRADA

Cordial saludo,

Esperamos que se encuentren muy bien.

Por medio del presente, les compartimos la información preliminar de liquidación correspondiente a la operación del mes de julio. Tenga en cuenta que estos datos son preliminares y no oficiales; los valores definitivos serán comunicados una vez se emitan los certificados de mandato y las facturas oficiales.

RELACIÓN DE PROYECTOS
Minigranja Solar La Reserva"""

LIQUIDACION_PRELIMINAR_ADJUNTOS = []
