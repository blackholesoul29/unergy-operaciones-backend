"""Job programado: monitoreo de cobertura de garantías.

Recorre todas las garantías con `monitoreo_cobertura_activo = True`, calcula su
cobertura con `garantia_coverage_service`, guarda una fila en
`garantia_cobertura_historico` y, si el nivel es AMARILLO o ROJO, notifica
(campana in-app + correo best-effort).

Se agenda desde `app/main.py` (scheduler diario). El scheduler del proyecto es
un `BackgroundScheduler` síncrono, así que exponemos `run_...` como wrapper
síncrono sobre la corrutina.
"""
import asyncio

from app.core.database import SessionLocal
from app.models.garantias import Garantia
from app.models.garantia_cobertura import GarantiaCoberturaHistorico
from app.models.notificaciones import Notificacion, TipoNotificacionEnum
from app.models.usuarios import Usuario, RolEnum
from app.services.garantia_coverage_service import calcular_cobertura_garantia

ROLES_NOTIF = (RolEnum.admin, RolEnum.operaciones, RolEnum.monitoreo)
NIVELES_ALERTA = ("AMARILLO", "ROJO")


def _notificar_alerta(db, garantia: Garantia, resultado: dict) -> None:
    """Notificación in-app (campana) a los roles operativos + correo best-effort."""
    nivel = resultado["nivel_alerta"]
    proyecto_nombre = garantia.proyecto.nombre_comercial if garantia.proyecto else f"Garantía #{garantia.id}"
    cobertura = resultado.get("cobertura_porcentaje")
    cobertura_pct = f"{cobertura * 100:.1f}%" if cobertura is not None else "N/D"
    titulo = f"Cobertura de garantía {nivel} — {proyecto_nombre}"
    mensaje = (
        f"La garantía #{garantia.id} ({proyecto_nombre}) tiene una cobertura de {cobertura_pct} "
        f"(requerido estimado ${resultado['valor_requerido']:,.0f} / actual ${resultado['valor_actual_garantia']:,.0f}). "
        f"Nivel de alerta: {nivel}. "
        "El valor requerido es una estimación provisional (generación 30d × precio de bolsa × factor); "
        "la fórmula contractual definitiva está pendiente."
    )
    link = f"/garantias/{garantia.id}"

    usuarios = (
        db.query(Usuario)
        .filter(Usuario.activo == True, Usuario.rol.in_(list(ROLES_NOTIF)))  # noqa: E712
        .all()
    )
    for u in usuarios:
        db.add(Notificacion(
            usuario_id=u.id,
            tipo=TipoNotificacionEnum.alerta,
            titulo=titulo,
            mensaje=mensaje,
            link=link,
        ))

    # Correo best-effort (no bloquea el job si SMTP no está configurado).
    try:
        from app.services.email_service import send_alarm_notification_email
        emails = [u.email for u in usuarios if getattr(u, "email", None)]
        if emails:
            send_alarm_notification_email(
                to_emails=emails,
                proyecto_nombre=proyecto_nombre,
                alarm_type="Cobertura de garantía",
                severity="CRITICAL" if nivel == "ROJO" else "WARNING",
                details=mensaje,
            )
    except Exception as e:  # noqa: BLE001
        print(f"[garantia_monitor] email alerta falló para garantía {garantia.id}: {e}")


async def verificar_cobertura_de_garantias() -> dict:
    """Verifica la cobertura de todas las garantías con monitoreo activo.

    Devuelve un resumen {procesadas, alertas, errores} para logging/tests.
    """
    db = SessionLocal()
    procesadas = 0
    alertas = 0
    errores = 0
    try:
        garantias = (
            db.query(Garantia)
            .filter(Garantia.monitoreo_cobertura_activo == True)  # noqa: E712
            .all()
        )
        for garantia in garantias:
            try:
                resultado = await calcular_cobertura_garantia(db, garantia)
                registro = GarantiaCoberturaHistorico(
                    garantia_id=garantia.id,
                    valor_requerido=resultado["valor_requerido"],
                    valor_actual_garantia=resultado["valor_actual_garantia"],
                    cobertura_porcentaje=resultado["cobertura_porcentaje"],
                    nivel_alerta=resultado["nivel_alerta"],
                    detalles_calculo=resultado["detalles_calculo"],
                )
                db.add(registro)

                if resultado["nivel_alerta"] in NIVELES_ALERTA:
                    _notificar_alerta(db, garantia, resultado)
                    alertas += 1

                db.commit()
                procesadas += 1
            except Exception as e:  # noqa: BLE001
                db.rollback()
                errores += 1
                print(f"[garantia_monitor] error en garantía {garantia.id}: {e}")

        print(
            f"[garantia_monitor] OK — {procesadas} procesadas, {alertas} alertas, {errores} errores"
        )
        return {"procesadas": procesadas, "alertas": alertas, "errores": errores}
    finally:
        db.close()


def run_verificar_cobertura_de_garantias() -> dict:
    """Wrapper síncrono para el BackgroundScheduler."""
    return asyncio.run(verificar_cobertura_de_garantias())
