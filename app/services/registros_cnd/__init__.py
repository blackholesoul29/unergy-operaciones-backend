"""Servicios de la seccion "Registros CND/ASIC".

Logica de dominio portada del prototipo (Next.js/TS) al stack de la plataforma:
 - dominio: etapas, estados, hitos, ponderacion, catalogos, reglas de vigencia
 - state_machine: transiciones validas, hitos al entrar, responsable por estado
 - avance: calculo de % de avance por hitos completados
 - validaciones_93: validaciones del requisito 9.3
 - alertas: motor de alertas del proceso
 - service: orquestacion con la sesion DB
 - correos: generacion de borradores de correo tipo (OR / XM / Solenium)
"""
