"""Catalogo de parametros del proceso CND (conexion ante XM).

Escrito a mano a partir de los documentos reales del expediente
(Contexto_registros/CND/): las cartas 9.1, 9.2, 9.4, 9.7, 9.9 y 9.10, y el
Anexo 4 del Acuerdo 1816 (item 9.3, hojas PLANTA_SOLAR y UNIDAD_SOLAR).

Aqui esta la deduplicacion que mas trabajo ahorra: seis datos del Anexo 4 son
EL MISMO dato que ya pide la hoja de vida del proceso SIC. No se redefinen: se
reusan sus claves (REUSADOS_DE_SIC). El usuario los diligencia una vez y sirven
para los dos procesos.

  Anexo 4 (CND)              ->  clave reutilizada del catalogo SIC
  1  NOMBRE DE LA PLANTA         frontera.nombre_frontera
  2  DEPARTAMENTO                frontera.departamento
  3  MUNICIPIO                   frontera.ciudad_municipio
  8  LATITUD                     frontera.latitud
  9  LONGITUD                    frontera.longitud
  12 VOLTAJE DE CONEXION         frontera.tension_de_servicio

Lo que NO se dedujo como el mismo dato, aunque se parezca:
  - "CAPACIDAD DE TRANSPORTE / POTENCIA NOMINAL" (MW, CND) vs "Capacidad
    Instalada" (kVA, hoja de vida): magnitudes distintas en unidades distintas.
  - "OPERADOR" (empresa que opera ante el CND) vs "Agente RF" (representante de
    la frontera ante el ASIC): suele ser la misma empresa, pero son dos roles
    regulatorios distintos y pueden diferir.
"""

from __future__ import annotations


# Claves del catalogo SIC que el proceso CND reutiliza tal cual. Ver D-13.
REUSADOS_DE_SIC: dict[str, str] = {
    "frontera.nombre_frontera":     "Anexo 4 #1 - Nombre de la planta",
    "frontera.departamento":        "Anexo 4 #2 - Departamento",
    "frontera.ciudad_municipio":    "Anexo 4 #3 - Municipio",
    "frontera.latitud":             "Anexo 4 #8 - Latitud",
    "frontera.longitud":            "Anexo 4 #9 - Longitud",
    "frontera.tension_de_servicio": "Anexo 4 #12 - Voltaje de conexion",
}


def _p(clave, titulo, tipo="TEXTO", unidad="", grupo="planta", requerido=True,
       origen="", ambito="PROYECTO", **extra):
    d = {"clave": clave, "titulo": titulo, "tipo": tipo, "unidad": unidad,
         "grupo": grupo, "requerido": requerido, "ambito": ambito,
         "equipo_tipos": [], "instancias": 1, "origen_cnd": origen}
    d.update(extra)
    return d


PARAMETROS_CND: list[dict] = [
    # --- Tramite: identifica cada carta del expediente ---------------------
    # Radicado y fecha son por documento, no por proyecto: viven en el propio
    # registro del documento (documentos_proyecto.radicado / fecha_emision),
    # no como parametros. Ver D-14.

    # --- Datos de conexion (carta 9.1 y Anexo 4) ---------------------------
    _p("conexion.punto_conexion", "Punto de conexion", "TEXTO", "", "conexion",
       origen="9.1 / Anexo 4 #6"),
    _p("conexion.barra_stn_str", "Barra del STN/STR donde se refleja la generacion",
       "TEXTO", "", "conexion", origen="9.1 / Anexo 4 #11"),
    _p("conexion.capacidad_transporte_mw", "Capacidad de transporte asignada",
       "NUMERO", "MW", "conexion", origen="9.1 / 9.7"),
    _p("conexion.fpo", "Fecha de puesta en operacion (FPO)", "FECHA", "", "conexion",
       origen="9.1"),
    _p("conexion.vigencia_aprobacion", "Vigencia de la aprobacion de la conexion",
       "FECHA", "", "conexion", origen="9.1"),
    _p("conexion.promotor", "Promotor del proyecto", "TEXTO", "", "conexion",
       origen="9.1"),
    _p("conexion.tecnologia", "Tecnologia (y combustible si es termico)", "TEXTO", "",
       "conexion", origen="9.1"),
    _p("conexion.sistema", "Sistema al que se conecta (SDL / STR / STN)", "CATEGORIA",
       "", "conexion", origen="9.1"),
    _p("conexion.operador_red", "Operador de red / transportador del area", "TEXTO", "",
       "conexion", origen="9.1 / 9.7 / 9.9"),
    _p("conexion.agente_representante", "Agente generador que representa el proyecto",
       "TEXTO", "", "conexion", origen="9.2"),
    _p("conexion.fecha_entrada_operacion", "Fecha y hora de entrada en operacion",
       "FECHA", "", "conexion", origen="9.10", requerido=False),

    # --- Anexo 4, hoja PLANTA ---------------------------------------------
    _p("planta.numero_unidades_equivalentes", "Numero de unidades equivalentes",
       "NUMERO", "", origen="Anexo 4 #4"),
    _p("planta.operador", "Operador de la planta ante el CND", "TEXTO", "",
       origen="Anexo 4 #5"),
    _p("planta.acuerdo_conexion_compartida", "Acuerdo de conexion compartida",
       "CATEGORIA", "Si/No", origen="Anexo 4 #7"),
    _p("planta.altitud", "Altitud", "NUMERO", "m.s.n.m.", origen="Anexo 4 #10"),
    _p("planta.potencia_nominal", "Potencia nominal", "NUMERO", "MW",
       origen="Anexo 4 #13"),
    _p("planta.potencia_maxima", "Potencia maxima de la planta", "NUMERO", "MW",
       origen="Anexo 4 #14"),
    _p("planta.minimo_tecnico", "Minimo tecnico", "NUMERO", "MW", origen="Anexo 4 #15"),
    _p("planta.capacidad_efectiva_neta", "Capacidad efectiva neta de la planta",
       "NUMERO", "MW", origen="Anexo 4 #16"),
    _p("planta.arranque_autonomo", "Arranque autonomo", "CATEGORIA", "Si/No",
       origen="Anexo 4 #17"),
    _p("planta.curva_capacidad_pq", "Curva de capacidad de la planta a voltaje nominal (PQ)",
       "ADJUNTO", "", origen="Anexo 4 #18", requerido=False),
    _p("planta.archivos_modelo_conversion",
       "Archivos de configuracion del modelo de conversion del recurso primario",
       "ADJUNTO", "", origen="Anexo 4 #19", requerido=False),
    _p("planta.caracteristicas_inversor",
       "Caracteristicas tecnicas del inversor (fabricante)", "ADJUNTO", "",
       origen="Anexo 4 #20", requerido=False),
    _p("planta.estatismo_frecuencia", "Estatismo en frecuencia", "NUMERO", "%",
       origen="Anexo 4 #21"),
    _p("planta.estatismo_frecuencia_min", "Estatismo en frecuencia minimo", "NUMERO", "%",
       origen="Anexo 4 #22"),
    _p("planta.estatismo_frecuencia_max", "Estatismo en frecuencia maximo", "NUMERO", "%",
       origen="Anexo 4 #23"),
    _p("planta.estatismo_tension", "Estatismo en tension", "NUMERO", "%",
       origen="Anexo 4 #24"),
    _p("planta.banda_muerta", "Banda muerta de operacion", "NUMERO", "mHz",
       origen="Anexo 4 #25"),
    _p("planta.rango_banda_muerta", "Rango de la banda muerta de operacion", "NUMERO",
       "mHz", origen="Anexo 4 #26"),
    _p("planta.absorcion_reactivos_pmin", "Capacidad de absorcion de reactivos (a P minima)",
       "NUMERO", "MVAR", origen="Anexo 4 #27"),
    _p("planta.generacion_reactivos_pmin", "Capacidad de generacion de reactivos (a P minima)",
       "NUMERO", "MVAR", origen="Anexo 4 #28"),
    _p("planta.absorcion_reactivos_pmax", "Capacidad de absorcion de reactivos (a P maxima)",
       "NUMERO", "MVAR", origen="Anexo 4 #29"),
    _p("planta.generacion_reactivos_pmax", "Capacidad de generacion de reactivos (a P maxima)",
       "NUMERO", "MVAR", origen="Anexo 4 #30"),
    _p("planta.constante_k_inyeccion", "Constante K de inyeccion rapida de corriente reactiva",
       "NUMERO", "", origen="Anexo 4 #31"),
    _p("planta.t_respuesta_control_reactiva",
       "Tiempo de respuesta inicial del control rapido de corriente reactiva",
       "NUMERO", "ms", origen="Anexo 4 #32"),
    _p("planta.t_respuesta_inicial_frecuencia",
       "Tiempo de respuesta inicial maximo - frecuencia", "NUMERO", "s",
       origen="Anexo 4 #33"),
    _p("planta.t_establecimiento_frecuencia",
       "Tiempo de establecimiento maximo - frecuencia", "NUMERO", "s",
       origen="Anexo 4 #34"),
    _p("planta.t_respuesta_inicial_tension", "Tiempo de respuesta inicial de tension",
       "NUMERO", "s", origen="Anexo 4 #35"),
    _p("planta.t_establecimiento_tension", "Tiempo de establecimiento de tension",
       "NUMERO", "s", origen="Anexo 4 #36"),
    _p("planta.rata_toma_carga", "Rata de toma de carga", "NUMERO", "MW/min",
       origen="Anexo 4 #37"),
    _p("planta.rata_descarga", "Rata de descarga", "NUMERO", "MW/min",
       origen="Anexo 4 #38"),

    # --- Anexo 4, hoja UNIDAD EQUIVALENTE ---------------------------------
    _p("unidad.nombre", "Nombre de la unidad", "TEXTO", "", "unidad",
       origen="Anexo 4 unidad #1"),
    _p("unidad.voltaje_maximo", "Voltaje maximo", "NUMERO", "kV", "unidad",
       origen="Anexo 4 unidad #2"),
    _p("unidad.voltaje_minimo", "Voltaje minimo", "NUMERO", "kV", "unidad",
       origen="Anexo 4 unidad #3"),
    _p("unidad.voltaje_nominal", "Voltaje nominal", "NUMERO", "kV", "unidad",
       origen="Anexo 4 unidad #4"),
    _p("unidad.frecuencia_maxima", "Frecuencia maxima", "NUMERO", "Hz", "unidad",
       origen="Anexo 4 unidad #5"),
    _p("unidad.frecuencia_minima", "Frecuencia minima", "NUMERO", "Hz", "unidad",
       origen="Anexo 4 unidad #6"),
    _p("unidad.numero_inversores", "Numero de inversores", "NUMERO", "", "unidad",
       origen="Anexo 4 unidad #7"),
    _p("unidad.impedancia_equivalente", "Impedancia equivalente", "NUMERO", "ohm",
       "unidad", origen="Anexo 4 unidad #8"),
    _p("unidad.potencia_nominal_inversor_ac", "Potencia nominal del inversor AC",
       "NUMERO", "MW", "unidad", origen="Anexo 4 unidad #9"),
    _p("unidad.modelo_inversor", "Modelo del inversor", "TEXTO", "", "unidad",
       origen="Anexo 4 unidad #10"),
    _p("unidad.factor_eficiencia_inversor", "Factor de eficiencia del inversor",
       "NUMERO", "%", "unidad", origen="Anexo 4 unidad #11"),
    _p("unidad.coef_derrateo_altura",
       "Coeficiente de derrateo de capacidad nominal del inversor por altura",
       "TEXTO", "p.u.", "unidad", origen="Anexo 4 unidad #12"),
    _p("unidad.icc_subtrans_pico", "Corriente de cortocircuito subtransitorio pico",
       "NUMERO", "kAp", "unidad", origen="Anexo 4 unidad #13"),
    _p("unidad.icc_subtrans_3f", "Corriente de cortocircuito subtransitorio - fallas 3F",
       "NUMERO", "kA", "unidad", origen="Anexo 4 unidad #14"),
    _p("unidad.icc_subtrans_2f", "Corriente de cortocircuito subtransitorio - fallas 2F",
       "NUMERO", "kA", "unidad", origen="Anexo 4 unidad #15"),
    _p("unidad.icc_subtrans_1f", "Corriente de cortocircuito subtransitorio - fallas 1F",
       "NUMERO", "kA", "unidad", origen="Anexo 4 unidad #16"),
    _p("unidad.icc_estado_estable", "Nivel de cortocircuito en estado estable",
       "NUMERO", "kA", "unidad", origen="Anexo 4 unidad #17"),
    _p("unidad.icc_secuencia_negativa",
       "Corriente de cortocircuito de secuencia negativa", "NUMERO", "kA", "unidad",
       origen="Anexo 4 unidad #18", requerido=False),

    # --- Carta 9.4: ajustes de protecciones -------------------------------
    # Tabla de funciones ANSI con etapa, ajuste y temporizacion. Es una tabla,
    # no un campo por funcion: se guarda como TABLA. Ver D-05.
    _p("protecciones.ajustes", "Ajustes de las funciones de proteccion", "TABLA", "",
       "protecciones", origen="9.4",
       columnas=["funcion_ansi", "etapa", "ajuste", "unidad", "temporizacion_s",
                 "observaciones"]),
    _p("protecciones.tipo_anti_isla", "Tipo de proteccion anti-isla", "TEXTO", "",
       "protecciones", origen="9.4"),
]

PARAMETROS_CND_POR_CLAVE: dict[str, dict] = {p["clave"]: p for p in PARAMETROS_CND}

ETIQUETAS_GRUPO_CND = {
    "conexion":     "Datos de la conexion",
    "planta":       "Anexo 4 - planta",
    "unidad":       "Anexo 4 - unidad equivalente",
    "protecciones": "Ajustes de protecciones (9.4)",
}
