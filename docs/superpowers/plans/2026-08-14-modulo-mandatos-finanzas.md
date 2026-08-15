# Módulo "Mandatos (Finanzas)" — Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un módulo nuevo en Finanzas que muestra, por período, el estado de firma de los mandatos de ingresos y costos, alimentado desde el correo por un script local que hace POST a la API; los PDF firmados se guardan en Google Drive.

**Architecture:** Script local (ya existe) lee Gmail incremental → `POST /api/v1/finanzas/mandatos/ingest` (autenticado con API Key) → sube PDF a Drive + upsert por identidad `(proyecto,tercero,periodo,tipo)` → vista nueva en Finanzas lee `GET /finanzas/mandatos`. Independiente del módulo viejo `/mandatos` (no se toca).

**Tech Stack:** Backend FastAPI + SQLAlchemy (Postgres), Google Drive API (service account, patrón de `fallas.py`), auth por API Key (`X-API-Key`, tabla `api_keys` existente). Frontend Vue 3 `<script setup>` + PrimeVue + axios (`@/api/client`). Script local Python (imaplib + requests).

Spec de referencia: `docs/superpowers/specs/2026-08-14-modulo-mandatos-finanzas-design.md`.

---

## Task 0: Rama de trabajo

**Files:** ninguno (git).

- [ ] **Step 1: Crear rama limpia desde master**

El repo del backend puede estar en `feat/garantias-proyecciones`. Partir de master.

Run:
```bash
cd unergy-operaciones-backend
git fetch origin
git checkout -b feat/mandatos-finanzas origin/master
```
Expected: rama nueva `feat/mandatos-finanzas` creada.

---

## Task 1: Modelo `FinanzasMandato`

**Files:**
- Create: `app/models/finanzas_mandatos.py`
- Modify: `app/models/__init__.py` (agregar import junto a los otros, ~línea 41-47)
- Test: `tests/test_finanzas_mandatos_model.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_finanzas_mandatos_model.py
from datetime import date
from app.models.finanzas_mandatos import FinanzasMandato, TipoMandatoEnum, EstadoFirmaEnum

def test_modelo_campos_basicos():
    m = FinanzasMandato(
        proyecto="Minigranja Solar Baraya", tercero="SOLENIUM SAS",
        periodo=date(2026, 7, 1), tipo="costo", cmu="CMU0521", estado="sin_firma",
    )
    assert m.tipo == "costo"
    assert m.estado == "sin_firma"

def test_enums_valores():
    assert set(e.value for e in TipoMandatoEnum) == {"ingreso", "costo"}
    assert "firmado" in set(e.value for e in EstadoFirmaEnum)
    assert "con_comentarios" in set(e.value for e in EstadoFirmaEnum)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_finanzas_mandatos_model.py -v`
Expected: FAIL (ModuleNotFoundError: app.models.finanzas_mandatos)

- [ ] **Step 3: Write the model**

```python
# app/models/finanzas_mandatos.py
import enum
from datetime import datetime, date
from sqlalchemy import (
    BigInteger, String, Text, Date, DateTime, Enum as SAEnum, UniqueConstraint, Index,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.models.base import Base


class TipoMandatoEnum(str, enum.Enum):
    ingreso = "ingreso"
    costo = "costo"


class EstadoFirmaEnum(str, enum.Enum):
    sin_firma = "sin_firma"
    firmado = "firmado"
    con_comentarios = "con_comentarios"


class FinanzasMandato(Base):
    """Mandato (ingreso o costo) rastreado desde el correo de la revisoría.

    Identidad lógica = (proyecto, tercero, periodo, tipo). El CMU es un atributo
    que puede corregirse (se guarda cmu_anterior). Independiente de la tabla
    `mandatos` (módulo viejo de Costos).
    """
    __tablename__ = "finanzas_mandatos"
    __table_args__ = (
        UniqueConstraint("proyecto", "tercero", "periodo", "tipo",
                         name="uq_finmandato_identidad"),
        Index("ix_finmandatos_periodo", "periodo"),
        Index("ix_finmandatos_cmu", "cmu"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto: Mapped[str] = mapped_column(String(255), nullable=False)
    tercero: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    periodo: Mapped[date] = mapped_column(Date, nullable=False)  # primer día del mes
    tipo: Mapped[str] = mapped_column(
        SAEnum(TipoMandatoEnum, name="tipo_mandato_fin_enum"), nullable=False)
    cmu: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cmu_anterior: Mapped[str | None] = mapped_column(String(20), nullable=True)
    estado: Mapped[str] = mapped_column(
        SAEnum(EstadoFirmaEnum, name="estado_firma_fin_enum"),
        nullable=False, default="sin_firma")
    comentario: Mapped[str | None] = mapped_column(Text, nullable=True)
    fecha_envio: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_firma: Mapped[date | None] = mapped_column(Date, nullable=True)
    drive_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    drive_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    correo_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

- [ ] **Step 4: Register the model so create_all picks it up**

En `app/models/__init__.py`, junto al import de mandatos (~línea 41), agregar:
```python
from app.models.finanzas_mandatos import (
    FinanzasMandato, TipoMandatoEnum, EstadoFirmaEnum,
)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_finanzas_mandatos_model.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add app/models/finanzas_mandatos.py app/models/__init__.py tests/test_finanzas_mandatos_model.py
git commit -m "feat(finanzas-mandatos): modelo FinanzasMandato"
```

---

## Task 2: Servicio de parsing (funciones puras)

Toda la lógica de interpretación del correo/nombre. Puro, sin ORM → 100% testeable.

**Files:**
- Create: `app/services/finanzas_mandatos_service.py`
- Test: `tests/test_finanzas_mandatos_service.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_finanzas_mandatos_service.py
from datetime import date
from app.services.finanzas_mandatos_service import (
    tipo_de_nombre, extraer_cmu, extraer_periodo_de_asunto,
    parsear_proyecto_tercero, estado_por_direccion, detectar_comentario,
)

def test_tipo_de_nombre():
    assert tipo_de_nombre("CMU0521-Mandato-Costos-Baraya-SOLENIUM.pdf") == "costo"
    assert tipo_de_nombre("CMU 0183 - Mandato-El Llano-Ayura.pdf") == "ingreso"

def test_extraer_cmu():
    assert extraer_cmu("CMU0521-Mandato-Costos-x.pdf") == "CMU0521"
    assert extraer_cmu("CMU 0183 - Mandato-x.pdf") == "CMU0183"
    assert extraer_cmu("Ajuste Mandato sin codigo.pdf") is None

def test_periodo_de_asunto_con_mes():
    assert extraer_periodo_de_asunto("Re: Revisión mandatos de ingresos - Junio",
                                     date(2026, 8, 1)) == date(2026, 6, 1)

def test_periodo_de_asunto_con_anio_explicito():
    assert extraer_periodo_de_asunto("Revisión Mandatos de Ingresos Febrero - 2026",
                                     date(2026, 3, 1)) == date(2026, 2, 1)

def test_periodo_borde_diciembre():
    # asunto dice Diciembre, correo llegó en enero del año siguiente
    assert extraer_periodo_de_asunto("Re: Revisión Mandatos - Diciembre",
                                     date(2027, 1, 5)) == date(2026, 12, 1)

def test_estado_por_direccion():
    rev = "vlondono@jbp.com.co"
    assert estado_por_direccion(f"Vanessa <{rev}>", rev) == "firmado"
    assert estado_por_direccion("Adhara <adhara@unergy.io>", rev) == "sin_firma"

def test_detectar_comentario():
    cuerpo = "Buen día, el CMU0521 tiene una diferencia en el valor, favor corregir."
    assert detectar_comentario(cuerpo, "CMU0521") is not None
    assert detectar_comentario("Adjunto firmados, gracias", "CMU0521") is None

def test_parsear_proyecto_tercero_costo():
    proj, terc = parsear_proyecto_tercero(
        "CMU0521-Mandato-Costos-Minigranja Solar Baraya-SOLENIUM SAS.pdf", "costo")
    assert proj == "Minigranja Solar Baraya"
    assert terc == "SOLENIUM SAS"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_finanzas_mandatos_service.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write the service**

```python
# app/services/finanzas_mandatos_service.py
"""Lógica pura del módulo Mandatos (Finanzas): parsing de nombre/asunto/cuerpo."""
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
    "diferencia", "corregir", "correccion", "corrección", "ajuste", "ajustar",
    "esta mal", "está mal", "error", "no cuadra", "revisar",
)


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
    """Mes del asunto + año (del asunto si aparece; si no, de fecha_correo con
    ajuste de borde: si el correo es de enero y el asunto dice diciembre → año-1)."""
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
    """Si el cuerpo menciona el CMU y trae lenguaje de corrección, devuelve el
    fragmento (una oración alrededor). None si no aplica."""
    cuerpo_n = _norm(cuerpo)
    if cmu and _norm(cmu) not in cuerpo_n.replace(" ", ""):
        # el CMU puede no estar textual; igual revisamos correcciones globales
        pass
    if not any(p in cuerpo_n for p in _PALABRAS_CORRECCION):
        return None
    # Devuelve la primera oración con palabra de corrección (máx 300 chars).
    for frag in re.split(r"[.\n]", cuerpo or ""):
        if any(p in _norm(frag) for p in _PALABRAS_CORRECCION):
            return frag.strip()[:300]
    return (cuerpo or "").strip()[:300]


def parsear_proyecto_tercero(nombre: str, tipo: str) -> tuple[str, str]:
    """Extrae (proyecto, tercero) del nombre del archivo. Best-effort.

    Costos: 'CMU####-Mandato-Costos-{Proyecto}-{Tercero}.pdf' → split por último '-'.
    Ingresos: 'CMU #### - Mandato-{Proyecto}-{Tercero}.pdf' u otras variantes.
    Si no se puede separar, devuelve (resto, '').
    """
    base = re.sub(r"\.pdf$", "", nombre or "", flags=re.IGNORECASE)
    base = _CMU_RE.sub("", base).strip(" -")
    base = re.sub(r"(?i)^ajuste\s+", "", base).strip()
    base = re.sub(r"(?i)^mandato-?costos-?", "", base)
    base = re.sub(r"(?i)^mandato-?", "", base).strip(" -")
    if "-" in base:
        proyecto, tercero = base.rsplit("-", 1)
        return proyecto.strip(), tercero.strip()
    return base.strip(), ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_finanzas_mandatos_service.py -v`
Expected: PASS (8 passed). Si `test_parsear_proyecto_tercero_costo` falla por espacios, ajustar el `strip`.

- [ ] **Step 5: Commit**

```bash
git add app/services/finanzas_mandatos_service.py tests/test_finanzas_mandatos_service.py
git commit -m "feat(finanzas-mandatos): servicio de parsing (nombre/asunto/cuerpo)"
```

---

## Task 3: Helper de subida a Drive

Copia el patrón de `fallas.py` (no hay helper central). Aislado para poder mockearlo en tests.

**Files:**
- Create: `app/services/finanzas_mandatos_drive.py`

- [ ] **Step 1: Write the helper (no test unitario; se mockea en Task 4)**

```python
# app/services/finanzas_mandatos_drive.py
"""Subida de PDFs de mandatos a Google Drive (patrón de fallas.py)."""
from __future__ import annotations
import io
import json
import os
from fastapi import HTTPException

# Carpeta raíz en el shared drive donde vivirán los mandatos. Override por env.
DRIVE_MANDATOS_FOLDER_ID = os.environ.get(
    "DRIVE_MANDATOS_FOLDER_ID", "0AD_e3wIWHByDUk9PVA")


def _service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_json:
        raise HTTPException(500, "Google Drive no configurado (GOOGLE_SERVICE_ACCOUNT_JSON)")
    info = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _folder(service, name: str, parent_id: str) -> str:
    q = (f"name='{name}' and mimeType='application/vnd.google-apps.folder' "
         f"and '{parent_id}' in parents and trashed=false")
    res = service.files().list(q=q, fields="files(id)", supportsAllDrives=True,
                               includeItemsFromAllDrives=True).execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]
    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id]}
    return service.files().create(body=meta, fields="id",
                                  supportsAllDrives=True).execute()["id"]


def subir_pdf(contenido: bytes, nombre: str, subcarpeta: str) -> dict:
    """Sube el PDF a DRIVE_MANDATOS_FOLDER_ID/subcarpeta. Devuelve {id, url}."""
    from googleapiclient.http import MediaIoBaseUpload
    service = _service()
    folder_id = _folder(service, subcarpeta, DRIVE_MANDATOS_FOLDER_ID)
    media = MediaIoBaseUpload(io.BytesIO(contenido), mimetype="application/pdf")
    up = service.files().create(
        body={"name": nombre, "parents": [folder_id]},
        media_body=media, fields="id, webViewLink", supportsAllDrives=True).execute()
    fid = up["id"]
    return {"id": fid, "url": up.get("webViewLink", f"https://drive.google.com/file/d/{fid}/view")}
```

- [ ] **Step 2: Commit**

```bash
git add app/services/finanzas_mandatos_drive.py
git commit -m "feat(finanzas-mandatos): helper de subida a Drive"
```

---

## Task 4: Endpoint `/ingest` + upsert por identidad

**Files:**
- Create: `app/api/v1/finanzas_mandatos.py`
- Create: `app/schemas/finanzas_mandatos.py`
- Test: `tests/test_finanzas_mandatos_ingest.py`

- [ ] **Step 1: Write schemas**

```python
# app/schemas/finanzas_mandatos.py
from pydantic import BaseModel


class MandatoOut(BaseModel):
    id: int
    proyecto: str
    tercero: str
    periodo: str          # "YYYY-MM"
    tipo: str
    cmu: str | None
    cmu_anterior: str | None
    estado: str
    comentario: str | None
    fecha_envio: str | None
    fecha_firma: str | None
    drive_url: str | None
```

- [ ] **Step 2: Write the upsert function + failing test**

La lógica de upsert vive en el service (testeable con una sesión de DB en memoria o mock). Añadir a `app/services/finanzas_mandatos_service.py`:

```python
# (añadir al final de finanzas_mandatos_service.py)
from datetime import date as _date

def upsert_mandato(db, *, proyecto, tercero, periodo, tipo, cmu, estado,
                   comentario=None, fecha=None, correo_ref=None,
                   drive_file_id=None, drive_url=None):
    """Crea o actualiza por identidad (proyecto,tercero,periodo,tipo).
    Nunca degrada 'firmado' → 'sin_firma'. Guarda cmu_anterior si cambia el CMU."""
    from app.models.finanzas_mandatos import FinanzasMandato
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
    else:  # sin_firma
        m.fecha_envio = m.fecha_envio or hoy
        # no degrada un firmado
    db.flush()
    return m, creado
```

```python
# tests/test_finanzas_mandatos_ingest.py
from datetime import date
from app.services.finanzas_mandatos_service import upsert_mandato

def test_upsert_crea_y_no_duplica(db_session):
    kw = dict(proyecto="Baraya", tercero="SOLENIUM", periodo=date(2026,7,1),
              tipo="costo", cmu="CMU0521")
    m1, c1 = upsert_mandato(db_session, estado="sin_firma", **kw)
    m2, c2 = upsert_mandato(db_session, estado="firmado", **kw)
    assert c1 is True and c2 is False
    assert m1.id == m2.id
    assert m2.estado == "firmado"

def test_no_degrada_firmado(db_session):
    kw = dict(proyecto="X", tercero="Y", periodo=date(2026,7,1), tipo="ingreso", cmu="CMU1")
    upsert_mandato(db_session, estado="firmado", **kw)
    m, _ = upsert_mandato(db_session, estado="sin_firma", **kw)
    assert m.estado == "firmado"

def test_cmu_corregido_guarda_anterior(db_session):
    base = dict(proyecto="X", tercero="Y", periodo=date(2026,7,1), tipo="costo")
    upsert_mandato(db_session, estado="sin_firma", cmu="CMU100", **base)
    m, _ = upsert_mandato(db_session, estado="firmado", cmu="CMU200", **base)
    assert m.cmu == "CMU200" and m.cmu_anterior == "CMU100"
```

Nota: `db_session` es una fixture de pytest. Revisar `tests/conftest.py`; si no existe fixture de DB, seguir el patrón de `tests/test_liquidaciones.py` (que ya usa DB). Si esos tests usan una DB real/temporal, reusar su fixture.

- [ ] **Step 3: Run tests to verify they fail then implement passes**

Run: `python -m pytest tests/test_finanzas_mandatos_ingest.py -v`
Expected: primero FAIL (falta la función), luego PASS tras el Step 2.

- [ ] **Step 4: Write the router (ingest + list + resumen)**

```python
# app/api/v1/finanzas_mandatos.py
"""API del módulo Mandatos (Finanzas). Ingesta desde el script + lecturas."""
from __future__ import annotations
from datetime import date, datetime
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models.finanzas_mandatos import FinanzasMandato
from app.services import finanzas_mandatos_service as svc
from app.services.finanzas_mandatos_drive import subir_pdf

router = APIRouter(prefix="/finanzas/mandatos", tags=["Finanzas · Mandatos"])


def _to_dict(m: FinanzasMandato) -> dict:
    return {
        "id": m.id, "proyecto": m.proyecto, "tercero": m.tercero,
        "periodo": m.periodo.strftime("%Y-%m") if m.periodo else None,
        "tipo": m.tipo, "cmu": m.cmu, "cmu_anterior": m.cmu_anterior,
        "estado": m.estado, "comentario": m.comentario,
        "fecha_envio": m.fecha_envio.isoformat() if m.fecha_envio else None,
        "fecha_firma": m.fecha_firma.isoformat() if m.fecha_firma else None,
        "drive_url": m.drive_url,
    }


@router.post("/ingest")
async def ingest(
    proyecto: str = Form(...), tercero: str = Form(""), periodo: str = Form(...),
    tipo: str = Form(...), estado: str = Form(...), cmu: str = Form(None),
    comentario: str = Form(None), correo_ref: str = Form(None), fecha: str = Form(None),
    file: UploadFile = File(None),
    db: Session = Depends(get_db), _=Depends(get_current_user),
):
    """Idempotente. Autenticar con header X-API-Key. Sube PDF a Drive si viene y
    el estado es 'firmado'. Upsert por identidad."""
    try:
        per = datetime.strptime(periodo.strip()[:7], "%Y-%m").date()
    except ValueError:
        raise HTTPException(422, "periodo debe ser YYYY-MM")
    f = datetime.strptime(fecha[:10], "%Y-%m-%d").date() if fecha else None

    drive_id = drive_url = None
    if file is not None and estado == "firmado":
        contenido = await file.read()
        sub = f"{per.strftime('%Y-%m')}-{tipo}"
        res = subir_pdf(contenido, file.filename or f"{cmu or 'mandato'}.pdf", sub)
        drive_id, drive_url = res["id"], res["url"]

    m, creado = svc.upsert_mandato(
        db, proyecto=proyecto.strip(), tercero=tercero.strip(), periodo=per,
        tipo=tipo, cmu=svc.extraer_cmu(cmu) if cmu else None, estado=estado,
        comentario=comentario, fecha=f, correo_ref=correo_ref,
        drive_file_id=drive_id, drive_url=drive_url)
    db.commit()
    return {"ok": True, "creado": creado, "mandato": _to_dict(m)}


@router.get("")
def listar(periodo: str = Query(...), tipo: str = Query(None),
           db: Session = Depends(get_db), _=Depends(get_current_user)):
    try:
        per = datetime.strptime(periodo.strip()[:7], "%Y-%m").date()
    except ValueError:
        raise HTTPException(422, "periodo debe ser YYYY-MM")
    q = db.query(FinanzasMandato).filter(FinanzasMandato.periodo == per)
    if tipo:
        q = q.filter(FinanzasMandato.tipo == tipo)
    filas = q.order_by(FinanzasMandato.proyecto, FinanzasMandato.tercero).all()
    return {"periodo": periodo, "mandatos": [_to_dict(m) for m in filas]}


@router.get("/resumen")
def resumen(periodo: str = Query(...), db: Session = Depends(get_db),
            _=Depends(get_current_user)):
    per = datetime.strptime(periodo.strip()[:7], "%Y-%m").date()
    filas = db.query(FinanzasMandato).filter(FinanzasMandato.periodo == per).all()
    def conteo(tp):
        sub = [m for m in filas if m.tipo == tp]
        return {
            "total": len(sub),
            "firmados": sum(1 for m in sub if m.estado == "firmado"),
            "falta_firma": sum(1 for m in sub if m.estado == "sin_firma"),
            "con_comentarios": sum(1 for m in sub if m.estado == "con_comentarios"),
        }
    return {"periodo": periodo, "ingreso": conteo("ingreso"), "costo": conteo("costo")}
```

- [ ] **Step 5: Register the router**

En `app/api/v1/router.py`: agregar `finanzas_mandatos` al import masivo de la línea 2, y tras `include_router(mandatos.maestra_router)` (~línea 45) añadir:
```python
api_router.include_router(finanzas_mandatos.router)
```

- [ ] **Step 6: Verify endpoints load (import smoke test)**

Run: `python -c "from app.api.v1.router import api_router; print([r.path for r in api_router.routes if 'finanzas/mandatos' in r.path])"`
Expected: imprime las 3 rutas `/api/v1/finanzas/mandatos...`

- [ ] **Step 7: Commit**

```bash
git add app/api/v1/finanzas_mandatos.py app/schemas/finanzas_mandatos.py app/api/v1/router.py app/services/finanzas_mandatos_service.py tests/test_finanzas_mandatos_ingest.py
git commit -m "feat(finanzas-mandatos): endpoint /ingest + list + resumen"
```

---

## Task 5: API Key para el script (acción de admin, documentada)

**Files:** ninguno (se ejecuta contra prod/local).

- [ ] **Step 1: Crear una API Key para el script**

El endpoint `POST /api/v1/api-keys` (solo admin) devuelve la key `uop_...` una vez. Documentar en el README del script cómo obtenerla (un admin la crea desde la app o vía curl con su JWT):
```bash
curl -X POST https://<host>/api/v1/api-keys \
  -H "Authorization: Bearer <JWT_ADMIN>" \
  -H "Content-Type: application/json" \
  -d '{"nombre":"script-mandatos"}'
```
Guardar el `uop_...` devuelto para el script (Task 6). No commitear la key.

---

## Task 6: Extender el script local para hacer POST /ingest

**Files:**
- Modify: `C:\Users\jessi\OneDrive\Documentos\MandatosRevisoria\mandatos_revisoria.py`

- [ ] **Step 1: Añadir config de API + envío**

Agregar al CONFIG: `API_BASE = "https://<host>/api/v1"`, `API_KEY = "uop_..."`. Requiere `pip install requests`.

- [ ] **Step 2: En el loop por correo, además de guardar a carpeta, hacer POST**

Por cada adjunto ya clasificado, construir y enviar (usa lo que ya calcula el script: estado por dirección, tipo por nombre; añadir período del asunto y proyecto/tercero del nombre reusando la MISMA lógica del backend, portada a Python en el script):
```python
import requests
def _post_ingest(meta, pdf_bytes, filename):
    files = {"file": (filename, pdf_bytes, "application/pdf")} if meta["estado"] == "firmado" else None
    data = {k: v for k, v in meta.items() if v is not None}
    r = requests.post(f"{API_BASE}/finanzas/mandatos/ingest",
                      headers={"X-API-Key": API_KEY}, data=data, files=files, timeout=60)
    r.raise_for_status()
```
`meta` = {proyecto, tercero, periodo (YYYY-MM del asunto), tipo, estado, cmu, comentario, correo_ref, fecha (YYYY-MM-DD del correo)}.

- [ ] **Step 3: Incremental — no reprocesar el pasado**

Mantener el `estado_procesados.json` (ya existe): solo se hace POST de los correos nuevos. Verificar que un segundo run no reenvía nada (idempotente en backend de todos modos).

- [ ] **Step 4: Correr contra local/staging y verificar**

Ejecutar el script apuntando a un backend local; confirmar que `GET /finanzas/mandatos?periodo=...` devuelve registros. Revisar que no haya duplicados al correr dos veces.

- [ ] **Step 5: Commit (en el repo del script, o dejar el .py en su carpeta)**

El script vive fuera del repo; guardar copia en `docs/` si se quiere versionar, o solo dejar el archivo actualizado.

---

## Task 7: Vista frontend `MandatosFinanzas.vue`

**Files:**
- Create: `unergy-operaciones-frontend/src/views/Finanzas/MandatosFinanzas.vue`
- Modify: `src/router/index.js` (bloque Finanzas ~línea 68)
- Modify: `src/components/AppSidebar.vue` (children de Finanzas ~línea 330)

- [ ] **Step 1: Crear la vista** (copiar la estructura de `MandatosOperaciones.vue`)

Requisitos de la vista:
- Selector de mes (reusar patrón `anio`/`mes`/`periodo` computed de MandatosOperaciones, o el stepper de flechas del Panel Contable).
- Pestañas **Ingresos / Costos** (`tipo = ref('ingreso')`).
- Tarjetas de métricas desde `/finanzas/mandatos/resumen` (Total, Firmados, Falta firma, Con comentarios) para el tipo activo.
- Tabla desde `/finanzas/mandatos?periodo=&tipo=`: columnas CMU, proyecto, tercero, estado (badge), fecha envío, fecha firma, comentario, y link "Ver PDF" (`drive_url`, `target=_blank`).
- Filtro "solo falta firma".

Carga (patrón exacto del cliente API):
```javascript
import api from '@/api/client'
const { data } = await api.get('/finanzas/mandatos', { params: { periodo: periodo.value, tipo: tipo.value } })
mandatos.value = data.mandatos
const r = await api.get('/finanzas/mandatos/resumen', { params: { periodo: periodo.value } })
resumen.value = r.data[tipo.value]
```

- [ ] **Step 2: Registrar la ruta** en `src/router/index.js` (bloque Finanzas):
```javascript
{ path: '/finanzas/mandatos', name: 'MandatosFinanzas', component: () => import('@/views/Finanzas/MandatosFinanzas.vue'), meta: { roles: ['admin', 'liquidaciones'] } },
```

- [ ] **Step 3: Agregar al sidebar** en `src/components/AppSidebar.vue`, dentro del `children` de Finanzas:
```javascript
{ to: '/finanzas/mandatos', label: 'Mandatos' },
```

- [ ] **Step 4: Verificar en el navegador**

Levantar el dev server (`preview_start` name `frontend-dev`), navegar a `/finanzas/mandatos`, confirmar que la vista carga, cambia de período/pestaña y muestra los datos ingestados. Revisar `read_console_messages` sin errores.

- [ ] **Step 5: Commit**

```bash
cd unergy-operaciones-frontend
git add src/views/Finanzas/MandatosFinanzas.vue src/router/index.js src/components/AppSidebar.vue
git commit -m "feat(finanzas-mandatos): vista Mandatos en Finanzas"
```

---

## Task 8: Prueba de punta a punta + despliegue

- [ ] **Step 1: Backend a prod**

Merge/push de `feat/mandatos-finanzas` del backend a master → Railway construye. Verificar en logs `Application startup complete` y que `create_all` creó `finanzas_mandatos` (o revisar la tabla en prod). Configurar env vars en Railway: `GOOGLE_SERVICE_ACCOUNT_JSON` (ya existe para fallas) y opcional `DRIVE_MANDATOS_FOLDER_ID`.

- [ ] **Step 2: Correr el script apuntando a prod**

Con la API Key de prod, correr el script (histórico incremental). Confirmar registros vía la vista.

- [ ] **Step 3: Frontend a prod**

Push del frontend a master. Hard-reload y verificar la vista con datos reales.

- [ ] **Step 4: Verificación final con la usuaria**

Jessica verifica en prod: abre Finanzas → Mandatos, elige un mes, revisa firmados vs falta firma en ingresos y costos, abre un PDF desde Drive.

---

## Notas de decisiones (del spec)

- Firma: manejo normal (volvió = firmado). Sin verificación por peso (comprobado no confiable) ni botón manual "revisar" (fuera de v1).
- Identidad `(proyecto,tercero,periodo,tipo)`; CMU atributo con `cmu_anterior` para consecutivos corregidos.
- Período del asunto; tipo del nombre; "con comentarios" del cuerpo (heurístico).
- El backend NO lee Gmail; lo hace el script local. Credencial de Gmail nunca en el servidor.
- Riesgo a validar temprano (Task 6): calidad del parsing de proyecto/tercero en ingresos.
