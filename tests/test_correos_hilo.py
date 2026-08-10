"""Parser de hilos de correo del CRM comercial. Fragmentos reales de los .eml
de Ofertas/Correos: el marcador de cita viene partido en varias lineas y el
correo del remitente trae delante los '>' del citado."""
from datetime import date

from app.utils.correos_hilo import (
    codigo_partes, datos_envio, hilo_completo, mensajes_citados,
)

# Texto REAL de los .eml, con tildes. Escribir estos fixtures sin acentos ya
# oculto un fallo: el patron buscaba "escribio:" y el correo dice "escribió:"
# —la tilde va sobre la o, no sobre la i— asi que no encontraba ningun mensaje
# citado y todos los hilos parecian tener un solo correo.
BARISOL = """Estamos atentos a sus comentarios y aceptación de la oferta.

El lun, 22 jun 2026 a la(s) 11:23 a.m., Alejandro Sepulveda (
alejandros@unergy.io) escribió:

> Cordial saludo Daniel,
"""

MONTERREY = """Buen día Diana.

El vie, 26 jun 2026 a la(s) 3:49 p.m., Diana Beltran (
mejoracontinua@grupomonterrey.com.co) escribió:

>> Buenas tardes.
>>
>> El lun, 13 abr 2026 a las 15:02, Alejandro Sepulveda (<
>>> alejandros@unergy.io>) escribió:
>>>
>>>> El jue, 12 mar 2026 a las 12:12, Alejandro Sepulveda (<
>>>>> alejandros@unergy.io>) escribió:
>>>>>
>>>>>> El mié, 3 sept 2025 a la(s) 5:57 p.m., Alejandro Sepulveda (
>>>>>>> alejandros@unergy.io) escribió:
"""


def test_marcador_partido_en_dos_lineas():
    assert mensajes_citados(BARISOL) == [(date(2026, 6, 22), "alejandros@unergy.io")]


def test_mes_de_cuatro_letras_y_correo_con_prefijo_de_citado():
    fechas = dict(mensajes_citados(MONTERREY))
    assert fechas[date(2025, 9, 3)] == "alejandros@unergy.io"
    assert fechas[date(2026, 3, 12)] == "alejandros@unergy.io"


def test_hilo_completo_ordena_de_viejo_a_nuevo_e_incluye_el_de_arriba():
    h = hilo_completo(BARISOL, date(2026, 7, 17), "alejandros@unergy.io")
    assert [f for f, _ in h] == [date(2026, 6, 22), date(2026, 7, 17)]


def test_fecha_de_la_oferta_sale_del_mes_del_codigo():
    # El hilo de Monterrey cubre DOS ofertas: servicios (sep-2025) y energia
    # (mar-2026). La de energia NO se fecha con el primer mensaje del hilo.
    h = hilo_completo(MONTERREY, date(2026, 7, 16), "alejandros@unergy.io")
    assert datos_envio(h, 3, 2026)["fecha_oferta"] == date(2026, 3, 12)
    assert datos_envio(h, 9, 2025)["fecha_oferta"] == date(2025, 9, 3)


def test_seguimientos_se_cuentan_desde_la_fecha_de_esa_oferta():
    h = hilo_completo(MONTERREY, date(2026, 7, 16), "alejandros@unergy.io")
    # Nuestros mensajes: 2025-09-03, 2026-03-12, 2026-04-13, 2026-07-16.
    assert datos_envio(h, 9, 2025)["seguimientos"] == 4
    # La oferta de energia nace en marzo: no carga con el toque de septiembre.
    assert datos_envio(h, 3, 2026)["seguimientos"] == 3


def test_ultima_respuesta_es_el_mensaje_ajeno_mas_reciente():
    h = hilo_completo(MONTERREY, date(2026, 7, 16), "alejandros@unergy.io")
    assert datos_envio(h, 3, 2026)["fecha_ultima_respuesta"] == date(2026, 6, 26)


def test_sin_respuestas_del_cliente_devuelve_none():
    h = hilo_completo(BARISOL, date(2026, 7, 17), "alejandros@unergy.io")
    assert datos_envio(h, 6, 2026)["fecha_ultima_respuesta"] is None


def test_mes_del_codigo_sin_coincidencia_usa_el_mensaje_mas_antiguo_nuestro():
    h = hilo_completo(BARISOL, date(2026, 7, 17), "alejandros@unergy.io")
    assert datos_envio(h, 1, 2020)["fecha_oferta"] == date(2026, 6, 22)


def test_codigo_partes_lee_el_nombre_del_adjunto():
    assert codigo_partes("PPA Barisol I (V2.17.07.26 OF.COM No.0103-6-2026 ) - 8.pdf") == (103, 6, 2026)
    assert codigo_partes("Propuesta de Compra de Energia(No.0120-7-2026) - Los Apostoles.pdf") == (120, 7, 2026)
    assert codigo_partes("OP.REPCGM No.0163-07-2026") == (163, 7, 2026)
    assert codigo_partes("Respuesta XM.pdf") is None
