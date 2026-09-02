import enum
import json
from datetime import datetime, date, time, timezone, timedelta
from sqlalchemy import (BigInteger, String, Boolean, Date, Time,
                        DateTime, Integer, Numeric, ForeignKey, Enum as SAEnum, Text,
                        Column, Table)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base

# alarmas_monitoreo: tabla del motor MGS (app/services/mgs/scheduler.py),
# creada via SQL crudo (migracion 135) -- se declara acá como Table de
# SQLAlchemy Core, SIN clase ORM mapeada (nadie hace queries por objeto
# contra ella, todo el código que la usa sigue con text() a propósito), solo
# para que Falla.alarma_monitoreo_id pueda tener una ForeignKey real que
# SQLAlchemy sepa resolver (ver migracion 138, auditoria 2026-09-02).
alarmas_monitoreo = Table(
    "alarmas_monitoreo",
    Base.metadata,
    Column("id", BigInteger, primary_key=True),
    Column("proyecto_nombre", String(255), nullable=False),
    Column("severity", String(20), nullable=False),
    Column("alarm_type", String(50), nullable=False),
    Column("details", Text, nullable=False),
    Column("source_data", JSONB, nullable=True),
    Column("resolved_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


class FallaCatCategoria(Base):
    __tablename__ = "fallas_cat_categorias"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    codigo: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    etiqueta: Mapped[str] = mapped_column(String(255), nullable=False)
    icono: Mapped[str | None] = mapped_column(String(100), nullable=True)
    color_hex: Mapped[str | None] = mapped_column(String(7), nullable=True)
    orden: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    activa: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    tipos: Mapped[list["FallaCatTipo"]] = relationship("FallaCatTipo", back_populates="categoria")


class FallaCatTipo(Base):
    __tablename__ = "fallas_cat_tipos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    categoria_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fallas_cat_categorias.id"), nullable=False)
    codigo: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    etiqueta: Mapped[str] = mapped_column(String(255), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    activa: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    categoria: Mapped["FallaCatCategoria"] = relationship("FallaCatCategoria", back_populates="tipos")
    fallas: Mapped[list["Falla"]] = relationship("Falla", back_populates="tipo")


class FallaCatEstado(Base):
    __tablename__ = "fallas_cat_estados"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    codigo: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    etiqueta: Mapped[str] = mapped_column(String(255), nullable=False)
    orden: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    es_estado_final: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    fallas: Mapped[list["Falla"]] = relationship("Falla", back_populates="estado")
    seguimientos: Mapped[list["FallaSeguimiento"]] = relationship("FallaSeguimiento", back_populates="estado_nuevo")


class FallaCatPrioridad(Base):
    __tablename__ = "fallas_cat_prioridades"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    codigo: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    etiqueta: Mapped[str] = mapped_column(String(255), nullable=False)
    nivel: Mapped[int] = mapped_column(Integer, nullable=False)

    fallas: Mapped[list["Falla"]] = relationship("Falla", back_populates="prioridad")


class FallaCatResolucion(Base):
    __tablename__ = "fallas_cat_resoluciones"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    codigo: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    etiqueta: Mapped[str] = mapped_column(String(255), nullable=False)

    fallas: Mapped[list["Falla"]] = relationship("Falla", back_populates="resolucion")


class Falla(Base):
    __tablename__ = "fallas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    codigo_interno: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    proyecto_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("proyectos.id"), nullable=False, index=True)
    tipo_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("fallas_cat_tipos.id"), nullable=True, index=True)
    estado_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fallas_cat_estados.id"), nullable=False, index=True)
    prioridad_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fallas_cat_prioridades.id"), nullable=False, index=True)
    resolucion_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("fallas_cat_resoluciones.id"), nullable=True, index=True)
    registrado_por_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("usuarios.id"), nullable=False, index=True)
    asignado_a_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id"), nullable=True, index=True)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False)
    fecha_identificacion: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    hora_identificacion: Mapped[time | None] = mapped_column(Time, nullable=True)
    fecha_ocurrencia: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fecha_resolucion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sla_limite_horas: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sla_cumplido: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    fotos_urls: Mapped[str | None] = mapped_column(JSONB, nullable=True)
    centinela: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notificacion: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="false")
    # Feature 2: link to MGS alarm that auto-created this falla.
    # alarmas_monitoreo no tiene modelo ORM (tabla creada via SQL crudo en
    # la migracion 135) -- la FK se declara igual, contra el nombre de
    # tabla, para que SQLAlchemy la conozca aunque no exista una relacion
    # ORM del otro lado (ver migracion 138, auditoria 2026-09-02).
    alarma_monitoreo_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("alarmas_monitoreo.id", ondelete="SET NULL"), nullable=True, index=True)
    # Feature 4: impact on generation
    kwh_perdidos_estimado: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    impacto_economico_cop: Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    # Feature 5: documentation
    causa_raiz: Mapped[str | None] = mapped_column(Text, nullable=True)
    acciones_correctivas: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Feature 6: programado state — scheduled date for intervention
    fecha_programada: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    # ── Reporte estructurado (jerárquico por activo) — solo fallas nuevas ─────
    # Las fallas viejas dejan estos campos en NULL y siguen usando tipo_id.
    categoria_codigo: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    subtipo_codigo: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    subtipo_detalle: Mapped[str | None] = mapped_column(Text, nullable=True)
    clasificacion: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    pendiente_reclasificar: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="false")
    frontera_afecta_medicion: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    frontera_perdida_comunicacion: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    inversores_perdida_comunicacion: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    proyecto: Mapped["Proyecto"] = relationship("Proyecto", back_populates="fallas")
    tipo: Mapped["FallaCatTipo"] = relationship("FallaCatTipo", back_populates="fallas")
    estado: Mapped["FallaCatEstado"] = relationship("FallaCatEstado", back_populates="fallas")
    prioridad: Mapped["FallaCatPrioridad"] = relationship("FallaCatPrioridad", back_populates="fallas")
    resolucion: Mapped["FallaCatResolucion | None"] = relationship("FallaCatResolucion", back_populates="fallas")
    registrado_por: Mapped["Usuario"] = relationship("Usuario", foreign_keys=[registrado_por_id], back_populates="fallas_registradas")
    asignado_a: Mapped["Usuario | None"] = relationship("Usuario", foreign_keys=[asignado_a_id], back_populates="fallas_asignadas")
    seguimientos: Mapped[list["FallaSeguimiento"]] = relationship("FallaSeguimiento", back_populates="falla")
    intervalos: Mapped[list["FallaIntervalo"]] = relationship(
        "FallaIntervalo", back_populates="falla",
        cascade="all, delete-orphan", order_by="FallaIntervalo.inicio",
    )
    inversores_afectados: Mapped[list["FallaInversor"]] = relationship(
        "FallaInversor", back_populates="falla",
        cascade="all, delete-orphan",
    )

    @property
    def dias_abierta(self) -> int | None:
        if not self.fecha_identificacion:
            return None
        end = self.fecha_resolucion.date() if self.fecha_resolucion else date.today()
        return max(0, (end - self.fecha_identificacion).days)

    @property
    def tiempo_afectacion_horas(self) -> float | None:
        """Tiempo total de afectación de la falla en horas.

        - Si la falla tiene intervalos de disparo registrados, suma la duración
          de cada intervalo (fin − inicio); los intervalos aún abiertos (sin fin)
          se cierran provisionalmente con la hora actual.
        - Si no hay intervalos, cae al cálculo single-span: (fecha/hora solución
          − fecha/hora ocurrencia). Si no se registró fecha_ocurrencia, usa la
          fecha de identificación combinada con la hora_identificacion.
        Devuelve None si no hay forma de calcularlo (falla abierta sin intervalos).
        """
        col_tz = timezone(timedelta(hours=-5))  # Colombia (UTC-5)

        def _aware(dt: datetime, ref: datetime | None = None) -> datetime:
            if dt.tzinfo is not None:
                return dt
            return dt.replace(tzinfo=ref.tzinfo if ref and ref.tzinfo else col_tz)

        # 1) Preferir intervalos de disparo si los hay.
        intervalos = self.intervalos or []
        if intervalos:
            total_seg = 0.0
            ahora = datetime.now(col_tz)
            for iv in intervalos:
                if not iv.inicio:
                    continue
                inicio = _aware(iv.inicio)
                fin = _aware(iv.fin, inicio) if iv.fin else ahora
                total_seg += max(0.0, (fin - inicio).total_seconds())
            return round(total_seg / 3600, 2)

        # 2) Respaldo: span único ocurrencia → resolución.
        if not self.fecha_resolucion:
            return None
        inicio = self.fecha_ocurrencia
        if inicio is None:
            if not self.fecha_identificacion:
                return None
            inicio = datetime.combine(
                self.fecha_identificacion,
                self.hora_identificacion or time(0, 0),
                tzinfo=col_tz,
            )
        fin = self.fecha_resolucion
        inicio = _aware(inicio, fin)
        fin = _aware(fin, inicio)
        horas = (fin - inicio).total_seconds() / 3600
        return round(max(0.0, horas), 2)

    @property
    def sla_limite_dias(self) -> int | None:
        return self.sla_limite_horas // 24 if self.sla_limite_horas else None

    @property
    def tiene_fotos(self) -> bool:
        return bool(self.fotos_urls)

    @property
    def fotos_lista(self) -> list[str]:
        # Con JSONB el ORM ya devuelve list o str según cómo fue almacenado.
        # Manejamos ambos casos + doble-codificación de datos históricos.
        if not self.fotos_urls:
            return []
        if isinstance(self.fotos_urls, list):
            return self.fotos_urls
        # Caso legado: string JSON (antes de la migración a JSONB)
        try:
            result = json.loads(self.fotos_urls)
            if isinstance(result, list):
                return result
            # Doble-codificación histórica → decodificar una vez más
            if isinstance(result, str):
                inner = json.loads(result)
                return inner if isinstance(inner, list) else []
            return []
        except (json.JSONDecodeError, TypeError):
            return []


class FallaSeguimiento(Base):
    __tablename__ = "fallas_seguimientos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    falla_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fallas.id"), nullable=False, index=True)
    usuario_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("usuarios.id"), nullable=False, index=True)
    nota: Mapped[str | None] = mapped_column(Text, nullable=True)
    estado_nuevo_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("fallas_cat_estados.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    falla: Mapped["Falla"] = relationship("Falla", back_populates="seguimientos")
    usuario: Mapped["Usuario"] = relationship("Usuario", back_populates="seguimientos_falla")
    estado_nuevo: Mapped["FallaCatEstado | None"] = relationship("FallaCatEstado", back_populates="seguimientos")


class FallaIntervalo(Base):
    """Intervalo de afectación (disparo) de una falla.

    Permite agrupar varios disparos del mismo proyecto bajo una sola falla,
    guardando el inicio y fin exactos de cada afectación. El tiempo total de
    afectación de la falla es la suma de las duraciones de sus intervalos.
    """
    __tablename__ = "fallas_intervalos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    falla_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fallas.id"), nullable=False, index=True)
    inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fin: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    nota: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    falla: Mapped["Falla"] = relationship("Falla", back_populates="intervalos")

    @property
    def duracion_horas(self) -> float | None:
        if not self.inicio:
            return None
        col_tz = timezone(timedelta(hours=-5))
        ini = self.inicio if self.inicio.tzinfo else self.inicio.replace(tzinfo=col_tz)
        if self.fin:
            fin = self.fin if self.fin.tzinfo else self.fin.replace(tzinfo=col_tz)
        else:
            fin = datetime.now(col_tz)
        return round(max(0.0, (fin - ini).total_seconds() / 3600), 2)


class FallaInversor(Base):
    """Inversor afectado en una falla estructurada de categoría 'inversores'.

    Un renglón por (falla, inversor). `tipos` guarda la lista de códigos de tipo de
    falla de ese inversor (no_generacion, perdida_comunicacion, etc.). Habilita
    indicadores: inversor con más fallas, tipos de falla más frecuentes por inversor.
    `proyecto_inversor_id` puede quedar NULL si el inversor se borra del catálogo;
    `nombre`/`potencia_kw` son un snapshot para conservar el reporte histórico.
    """
    __tablename__ = "falla_inversores"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    falla_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fallas.id"), nullable=False, index=True)
    proyecto_inversor_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("proyecto_inversores.id", ondelete="SET NULL"), nullable=True, index=True)
    nombre: Mapped[str | None] = mapped_column(String(120), nullable=True)
    potencia_kw: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    tipos: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    falla: Mapped["Falla"] = relationship("Falla", back_populates="inversores_afectados")
