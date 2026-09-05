"""Reglas de borrado de un registro GESCON.

Un registro cuya energía alimenta el cálculo de Cumplimiento no se puede
borrar: quitarlo cambiaría meses ya cerrados sin dejar rastro.
"""

from apps.mercado_xm import models as mx_models
from apps.mercado_xm.services.asic_errores import Bloqueado
from apps.ppa import models as ppa_models


def razones_para_no_borrar(solicitud) -> list[str]:
    razones = []

    cambios = mx_models.AsicCambioContrato.objects.filter(
        solicitud=solicitud
    ).count()
    if cambios:
        razones.append(f"Tiene {cambios} cambio(s) de contrato asociados")

    # Las TERMINACIONES quedan exentas: la regla protege filas cuya energía
    # alimenta el cálculo, y una terminación no aporta ninguna (Cumplimiento la
    # salta). Sin la exención serían imposibles de borrar desde que heredan
    # `contrato_interno`, y radicar una terminación equivocada dejaría de tener
    # arreglo desde la vista.
    #
    # Ojo: borrar la terminación NO devuelve la `fecha_fin` que estampó en los
    # registros del SIC — eso se corrige editando cada registro.
    if solicitud.tipo_solicitud == "terminacion":
        return razones

    ppa = _ppa_del_registro(solicitud)
    if ppa is None:
        return razones

    cumplimientos = mx_models.CumplimientoMensual.objects.filter(
        contrato_ppa=ppa
    ).count()
    if cumplimientos:
        nombre = (
            ppa.nombre_interno or ppa.numero_codigo_contrato or f"ID {ppa.id}"
        )
        razones.append(
            f'Vinculado al contrato PPA "{nombre}" que tiene '
            f"{cumplimientos} registro(s) de cumplimiento"
        )
    return razones


def _ppa_del_registro(solicitud):
    if solicitud.contrato_ppa_id:
        return ppa_models.PpaContrato.objects.filter(
            pk=solicitud.contrato_ppa_id
        ).first()
    interno = (solicitud.contrato_interno or "").strip()
    if not interno:
        return None
    return ppa_models.PpaContrato.objects.filter(
        numero_codigo_contrato=interno, deleted_at__isnull=True
    ).first()


def borrar(solicitud) -> None:
    razones = razones_para_no_borrar(solicitud)
    if razones:
        raise Bloqueado(f'No se puede eliminar: {"; ".join(razones)}.')
    solicitud.delete()
