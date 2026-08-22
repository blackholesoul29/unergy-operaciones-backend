"""Logica pura del modulo Mandatos (Finanzas): parsing de nombre/asunto/cuerpo."""
from __future__ import annotations
import re
import unicodedata
from datetime import date

_CMU_RE = re.compile(r"CMU\s*0*\d+", re.IGNORECASE)
_MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
_PALABRAS_CORRECCION = (
    "diferencia", "corregir", "correccion", "ajuste", "ajustar",
    "esta mal", "error", "no cuadra", "revisar",
)

# Transiciones permitidas del estado de firma. Mismo criterio que TRANSICIONES en
# mandatos_service.py: el grafo es la red de seguridad de la ingesta automática --
# si un correo propone un salto que no está acá, no se aplica y queda registrado.
TRANSICIONES_FIRMA = {
    "sin_firma":             {"con_comentarios", "firmado"},
    "con_comentarios":       {"corregido"},
    # `con_comentarios` desde `corregido` cierra el lazo observar → corregir →
    # volver a observar, que en la práctica ocurre: la revisoría revisa lo
    # corregido y a veces le encuentra algo nuevo (3 casos en la corrida del
    # 2026-08-20). Un mandato corregido todavía NO está firmado, así que no
    # contradice la regla de que un mandato firmado no lleva correcciones.
    "corregido":             {"firmado", "sin_firma", "con_comentarios"},
    "firmado":               {"enviado_inversionista"},
    "enviado_inversionista": set(),
}


def transicion_firma_valida(estado_actual: str, estado_nuevo: str) -> bool:
    return estado_nuevo in TRANSICIONES_FIRMA.get(estado_actual, set())


def _norm(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def tipo_de_nombre(nombre: str) -> str:
    """'costo' si el nombre contiene 'mandato-costos', si no 'ingreso'."""
    return "costo" if "mandato-costos" in _norm(nombre).replace(" ", "") else "ingreso"


def extraer_cmu(texto: str) -> str | None:
    """Primer CMU, normalizado sin espacios (CMU0521). None si no hay."""
    m = _CMU_RE.search(texto or "")
    if not m:
        return None
    return re.sub(r"\s+", "", m.group(0).upper())


def extraer_periodo_de_asunto(asunto: str, fecha_correo: date) -> date | None:
    """Mes del asunto + anio (del asunto si aparece; si no, de fecha_correo con
    ajuste de borde diciembre/enero)."""
    n = _norm(asunto)
    mes = next((num for nombre, num in _MESES.items() if nombre in n), None)
    if not mes:
        return None
    m_anio = re.search(r"(20\d{2})", asunto)
    if m_anio:
        anio = int(m_anio.group(1))
    else:
        anio = fecha_correo.year
        if mes == 12 and fecha_correo.month == 1:
            anio -= 1
        elif mes > fecha_correo.month and (mes - fecha_correo.month) > 6:
            anio -= 1
    return date(anio, mes, 1)


def estado_por_direccion(de: str, revisora: str) -> str:
    """'firmado' si la revisora es el remitente (De); si no 'sin_firma'."""
    return "firmado" if revisora.lower() in _norm(de) else "sin_firma"


def detectar_comentario(cuerpo: str, cmu: str) -> str | None:
    """Si el cuerpo trae lenguaje de correccion, devuelve el fragmento. None si no."""
    cuerpo_n = _norm(cuerpo)
    if not any(p in cuerpo_n for p in _PALABRAS_CORRECCION):
        return None
    for frag in re.split(r"[.\n]", cuerpo or ""):
        if any(p in _norm(frag) for p in _PALABRAS_CORRECCION):
            return frag.strip()[:300]
    return (cuerpo or "").strip()[:300]


def parsear_proyecto_tercero(nombre: str, tipo: str) -> tuple[str, str]:
    """Extrae (proyecto, tercero) del nombre del archivo. Best-effort.
    Split por el ultimo '-' tras quitar CMU y el prefijo 'Mandato(-Costos)'.
    Si no se puede separar, devuelve (resto, '')."""
    base = re.sub(r"\.pdf$", "", nombre or "", flags=re.IGNORECASE)
    base = re.sub(r"\s*\(\d+\)", "", base)   # quita sufijos (1),(2) que agrega Gmail
    base = _CMU_RE.sub("", base).strip(" -")
    base = re.sub(r"(?i)^ajuste\s+", "", base).strip()
    base = re.sub(r"(?i)^mandato-?costos-?", "", base)
    base = re.sub(r"(?i)^mandato-?", "", base).strip(" -")
    if "-" in base:
        proyecto, tercero = base.rsplit("-", 1)
        return proyecto.strip(), tercero.strip()
    return base.strip(), ""


from datetime import date as _date


def upsert_mandato(db, *, proyecto, tercero, periodo, tipo, cmu, estado,
                   comentario=None, fecha=None, correo_ref=None,
                   drive_file_id=None, drive_url=None):
    """Crea o actualiza un mandato. Emparejamiento: PRIMERO por CMU (el
    identificador confiable; tolera que el nombre del proyecto/tercero varie entre
    el enviado y el firmado), y como RESPALDO por (proyecto, tercero, periodo,
    tipo) — que cubre el consecutivo corregido (mismo proyecto+inversionista, otro
    CMU) y los mandatos sin CMU. Nunca degrada 'firmado' -> 'sin_firma'.
    Devuelve (mandato, creado: bool)."""
    from app.models.finanzas_mandatos import FinanzasMandato
    m = None
    if cmu:
        m = (db.query(FinanzasMandato)
             .filter(FinanzasMandato.cmu == cmu,
                     FinanzasMandato.periodo == periodo,
                     FinanzasMandato.tipo == tipo).first())
    if m is None:
        m = (db.query(FinanzasMandato)
             .filter(FinanzasMandato.proyecto == proyecto,
                     FinanzasMandato.tercero == tercero,
                     FinanzasMandato.periodo == periodo,
                     FinanzasMandato.tipo == tipo).first())
    creado = m is None
    if creado:
        m = FinanzasMandato(proyecto=proyecto, tercero=tercero, periodo=periodo,
                            tipo=tipo, estado="sin_firma")
        db.add(m)
    if cmu and m.cmu and cmu != m.cmu:
        m.cmu_anterior = m.cmu
    if cmu:
        m.cmu = cmu
    if correo_ref:
        m.correo_ref = correo_ref
    hoy = fecha or _date.today()
    if estado == "firmado":
        m.estado = "firmado"
        m.fecha_firma = m.fecha_firma or hoy
        if drive_file_id:
            m.drive_file_id, m.drive_url = drive_file_id, drive_url
    elif estado == "con_comentarios":
        if m.estado != "firmado":
            m.estado = "con_comentarios"
        m.comentario = comentario
    elif estado == "corregido":
        # Se rehizo lo que la revisoria objeto; vuelve a estar en juego.
        m.estado = "corregido"
        m.comentario = None
    elif estado == "enviado_inversionista":
        m.estado = "enviado_inversionista"
        m.fecha_envio_inversionista = m.fecha_envio_inversionista or hoy
        if drive_file_id:
            m.drive_file_id, m.drive_url = drive_file_id, drive_url
    else:  # sin_firma
        m.fecha_envio = m.fecha_envio or hoy
    db.flush()
    return m, creado
