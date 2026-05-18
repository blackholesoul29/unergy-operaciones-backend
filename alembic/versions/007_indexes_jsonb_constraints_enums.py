"""add indexes, jsonb columns, check constraints, enums, updated_at

Revision ID: 007
Revises: 006_add_autoconsumo_tipo_venta
Create Date: 2026-05-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "007"
down_revision = "006_add_autoconsumo_tipo_venta"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ──────────────────────────────────────────────
    # 1. INDEXES on Foreign Keys (PostgreSQL does NOT auto-index FKs)
    # ──────────────────────────────────────────────

    # proyectos
    op.create_index("ix_proyectos_cliente_id", "proyectos", ["cliente_id"])
    op.create_index("ix_proyectos_portafolio_id", "proyectos", ["portafolio_id"])
    op.create_index("ix_proyectos_proyecto_padre_id", "proyectos", ["proyecto_padre_id"])

    # proyecto sub-tables
    op.create_index("ix_proyecto_info_tecnica_proyecto_id", "proyecto_info_tecnica", ["proyecto_id"])
    op.create_index("ix_proyecto_grupos_panel_proyecto_id", "proyecto_grupos_panel", ["proyecto_id"])
    op.create_index("ix_proyecto_inversores_proyecto_id", "proyecto_inversores", ["proyecto_id"])
    op.create_index("ix_proyecto_contactos_proyecto_id", "proyecto_contactos", ["proyecto_id"])
    op.create_index("ix_proyecto_inversionistas_proyecto_id", "proyecto_inversionistas", ["proyecto_id"])
    op.create_index("ix_proyecto_inversionistas_cliente_id", "proyecto_inversionistas", ["cliente_id"])

    # clientes
    op.create_index("ix_cliente_servicios_cliente_id", "cliente_servicios", ["cliente_id"])
    op.create_index("ix_cliente_docs_comerciales_cliente_id", "cliente_documentos_comerciales", ["cliente_id"])
    op.create_index("ix_cliente_docs_comerciales_servicio_id", "cliente_documentos_comerciales", ["servicio_id"])

    # fallas
    op.create_index("ix_fallas_proyecto_id", "fallas", ["proyecto_id"])
    op.create_index("ix_fallas_tipo_id", "fallas", ["tipo_id"])
    op.create_index("ix_fallas_estado_id", "fallas", ["estado_id"])
    op.create_index("ix_fallas_prioridad_id", "fallas", ["prioridad_id"])
    op.create_index("ix_fallas_resolucion_id", "fallas", ["resolucion_id"])
    op.create_index("ix_fallas_registrado_por_id", "fallas", ["registrado_por_id"])
    op.create_index("ix_fallas_asignado_a_id", "fallas", ["asignado_a_id"])
    op.create_index("ix_fallas_fecha_identificacion", "fallas", ["fecha_identificacion"])
    op.create_index("ix_fallas_seguimientos_falla_id", "fallas_seguimientos", ["falla_id"])
    op.create_index("ix_fallas_seguimientos_usuario_id", "fallas_seguimientos", ["usuario_id"])
    op.create_index("ix_fallas_seguimientos_estado_nuevo_id", "fallas_seguimientos", ["estado_nuevo_id"])

    # liquidaciones
    op.create_index("ix_liquidaciones_proyecto_id", "liquidaciones", ["proyecto_id"])
    op.create_index("ix_liquidaciones_generado_por_id", "liquidaciones", ["generado_por_id"])
    op.create_index("ix_liquidacion_costos_liquidacion_id", "liquidacion_costos", ["liquidacion_id"])
    op.create_index("ix_liquidacion_xm_datos_liquidacion_id", "liquidacion_xm_datos", ["liquidacion_id"])
    op.create_index("ix_liquidacion_xm_datos_frontera_id", "liquidacion_xm_datos", ["frontera_id"])
    op.create_index("ix_liquidacion_mandatos_liquidacion_id", "liquidacion_mandatos", ["liquidacion_id"])
    op.create_index("ix_liquidacion_mandatos_inversionista_id", "liquidacion_mandatos", ["inversionista_id"])
    op.create_index("ix_liquidacion_mandato_lineas_mandato_id", "liquidacion_mandato_lineas", ["mandato_id"])
    op.create_index("ix_liquidacion_facturas_liquidacion_id", "liquidacion_facturas", ["liquidacion_id"])

    # fronteras
    op.create_index("ix_fronteras_proyecto_id", "fronteras", ["proyecto_id"])
    op.create_index("ix_fronteras_frontera_gemela_id", "fronteras", ["frontera_gemela_id"])
    op.create_index("ix_fronteras_agrupada_bajo_id", "fronteras", ["agrupada_bajo_id"])
    op.create_index("ix_fronteras_embebida_bajo_id", "fronteras", ["embebida_bajo_id"])
    op.create_index("ix_fronteras_lecturas_frontera_id", "fronteras_lecturas", ["frontera_id"])
    op.create_index("ix_frontera_lectura_frontera_fecha", "fronteras_lecturas", ["frontera_id", "fecha_hora"])

    # equipos
    op.create_index("ix_equipos_frontera_id", "equipos", ["frontera_id"])
    op.create_index("ix_equipos_sellos_equipo_id", "equipos_sellos", ["equipo_id"])

    # servicios
    op.create_index("ix_representacion_gescon_proyecto_id", "representacion_gescon", ["proyecto_id"])
    op.create_index("ix_representacion_gescon_servicio_id", "representacion_gescon", ["servicio_representacion_id"])
    op.create_index("ix_operacion_kpis_proyecto_id", "operacion_kpis", ["proyecto_id"])
    op.create_index("ix_operacion_kpis_servicio_id", "operacion_kpis", ["servicio_operacion_id"])

    # contratos
    op.create_index("ix_contratos_servicio_proyecto_id", "contratos_servicio", ["proyecto_id"])
    op.create_index("ix_contratos_servicio_contratante_id", "contratos_servicio", ["contratante_id"])
    op.create_index("ix_contratos_servicio_prestador_id", "contratos_servicio", ["prestador_id"])
    op.create_index("ix_ppa_contratos_comprador_id", "ppa_contratos", ["comprador_id"])
    op.create_index("ix_ppa_contratos_vendedor_id", "ppa_contratos", ["vendedor_id"])
    op.create_index("ix_ppa_tarifas_contrato_id", "ppa_tarifas", ["contrato_id"])
    op.create_index("ix_ppa_compromisos_contrato_id", "ppa_compromisos_energia", ["contrato_id"])
    op.create_index("ix_contratos_arriendo_proyecto_id", "contratos_arriendo", ["proyecto_id"])

    # promotor
    op.create_index("ix_promotor_seguimientos_proyecto_id", "promotor_seguimientos", ["proyecto_id"])
    op.create_index("ix_promotor_seguimientos_requisito_id", "promotor_seguimientos", ["requisito_id"])

    # rec
    op.create_index("ix_rec_procesos_proyecto_id", "rec_procesos", ["proyecto_id"])
    op.create_index("ix_rec_certificados_proceso_id", "rec_certificados", ["proceso_id"])

    # asic
    op.create_index("ix_asic_solicitudes_proyecto_id", "asic_solicitudes", ["proyecto_id"])
    op.create_index("ix_asic_cambios_solicitud_id", "asic_cambios_contratos", ["solicitud_id"])
    op.create_index("ix_asic_cambios_proyecto_original_id", "asic_cambios_contratos", ["proyecto_original_id"])
    op.create_index("ix_asic_cambios_proyecto_nuevo_id", "asic_cambios_contratos", ["proyecto_nuevo_id"])

    # mantenimientos
    op.create_index("ix_mantenimientos_proyecto_id", "mantenimientos", ["proyecto_id"])
    op.create_index("ix_mantenimientos_registrado_por_id", "mantenimientos", ["registrado_por_id"])

    # generacion
    op.create_index("ix_generacion_diaria_fecha", "generacion_diaria", ["fecha"])

    # gestion
    op.create_index("ix_gestion_registros_proyecto_id", "gestion_registros", ["proyecto_id"])

    # informes
    op.create_index("ix_informes_guardados_creado_por_id", "informes_guardados", ["creado_por_id"])
    op.create_index("ix_informes_guardados_editado_por_id", "informes_guardados", ["editado_por_id"])
    op.create_index("ix_informes_guardados_aprobado_por_id", "informes_guardados", ["aprobado_por_id"])

    # ──────────────────────────────────────────────
    # 2. TEXT → JSONB conversions (cast existing data)
    # ──────────────────────────────────────────────

    op.execute("ALTER TABLE fallas ALTER COLUMN fotos_urls TYPE JSONB USING fotos_urls::jsonb")
    op.execute("ALTER TABLE proyectos ALTER COLUMN p90_mensual_kwh TYPE JSONB USING p90_mensual_kwh::jsonb")
    op.execute("ALTER TABLE proyectos ALTER COLUMN p50_mensual_kwh TYPE JSONB USING p50_mensual_kwh::jsonb")
    op.execute("ALTER TABLE gestion_registros ALTER COLUMN archivos_json TYPE JSONB USING archivos_json::jsonb")
    op.execute("ALTER TABLE informes_guardados ALTER COLUMN charts_data TYPE JSONB USING charts_data::jsonb")

    # ──────────────────────────────────────────────
    # 3. New ENUM types + column type changes
    # ──────────────────────────────────────────────

    # ContratoArriendo.estado: VARCHAR → enum
    estado_arriendo = sa.Enum("vigente", "vencido", "terminado", "en_renovacion", name="estado_arriendo_enum")
    estado_arriendo.create(op.get_bind(), checkfirst=True)
    op.execute("ALTER TABLE contratos_arriendo ALTER COLUMN estado TYPE estado_arriendo_enum USING estado::estado_arriendo_enum")

    # GestionRegistro.tipo: VARCHAR → enum
    tipo_gestion = sa.Enum("pqr", "preventivo", "correctivo", name="tipo_gestion_enum")
    tipo_gestion.create(op.get_bind(), checkfirst=True)
    op.execute("ALTER TABLE gestion_registros ALTER COLUMN tipo TYPE tipo_gestion_enum USING tipo::tipo_gestion_enum")

    # InformeGuardado.tipo: VARCHAR → enum
    tipo_informe = sa.Enum("op", "fmo", "port", name="tipo_informe_enum")
    tipo_informe.create(op.get_bind(), checkfirst=True)
    op.execute("ALTER TABLE informes_guardados ALTER COLUMN tipo TYPE tipo_informe_enum USING tipo::tipo_informe_enum")

    # InformeGuardado.estado: VARCHAR → enum
    estado_informe = sa.Enum("borrador", "revisado", "aprobado", name="estado_informe_enum")
    estado_informe.create(op.get_bind(), checkfirst=True)
    op.execute("ALTER TABLE informes_guardados ALTER COLUMN estado TYPE estado_informe_enum USING estado::estado_informe_enum")

    # ──────────────────────────────────────────────
    # 4. CHECK CONSTRAINTS
    # ──────────────────────────────────────────────

    op.create_check_constraint("ck_inversionista_pct_rango", "proyecto_inversionistas",
                               "porcentaje_participacion >= 0 AND porcentaje_participacion <= 100")
    op.create_check_constraint("ck_ppa_tarifa_mes_rango", "ppa_tarifas", "mes >= 1 AND mes <= 12")
    op.create_check_constraint("ck_ppa_compromiso_mes_rango", "ppa_compromisos_energia", "mes >= 1 AND mes <= 12")

    # ──────────────────────────────────────────────
    # 5. Add updated_at where missing
    # ──────────────────────────────────────────────

    op.add_column("liquidacion_costos", sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=True))
    op.add_column("liquidacion_mandato_lineas", sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=True))

    # ──────────────────────────────────────────────
    # 6. Remove duplicate string columns from fronteras
    # ──────────────────────────────────────────────

    op.drop_column("fronteras", "agrupada_bajo")
    op.drop_column("fronteras", "embebida_bajo")


def downgrade() -> None:
    # Re-add dropped columns
    op.add_column("fronteras", sa.Column("agrupada_bajo", sa.String(50), nullable=True))
    op.add_column("fronteras", sa.Column("embebida_bajo", sa.String(50), nullable=True))

    # Remove updated_at
    op.drop_column("liquidacion_mandato_lineas", "updated_at")
    op.drop_column("liquidacion_costos", "updated_at")

    # Remove check constraints
    op.drop_constraint("ck_ppa_compromiso_mes_rango", "ppa_compromisos_energia")
    op.drop_constraint("ck_ppa_tarifa_mes_rango", "ppa_tarifas")
    op.drop_constraint("ck_inversionista_pct_rango", "proyecto_inversionistas")

    # Revert enums to VARCHAR
    op.execute("ALTER TABLE informes_guardados ALTER COLUMN estado TYPE VARCHAR(20) USING estado::text")
    op.execute("ALTER TABLE informes_guardados ALTER COLUMN tipo TYPE VARCHAR(20) USING tipo::text")
    op.execute("ALTER TABLE gestion_registros ALTER COLUMN tipo TYPE VARCHAR(50) USING tipo::text")
    op.execute("ALTER TABLE contratos_arriendo ALTER COLUMN estado TYPE VARCHAR(100) USING estado::text")
    sa.Enum(name="estado_informe_enum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="tipo_informe_enum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="tipo_gestion_enum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="estado_arriendo_enum").drop(op.get_bind(), checkfirst=True)

    # Revert JSONB to TEXT
    op.execute("ALTER TABLE informes_guardados ALTER COLUMN charts_data TYPE TEXT USING charts_data::text")
    op.execute("ALTER TABLE gestion_registros ALTER COLUMN archivos_json TYPE TEXT USING archivos_json::text")
    op.execute("ALTER TABLE proyectos ALTER COLUMN p50_mensual_kwh TYPE TEXT USING p50_mensual_kwh::text")
    op.execute("ALTER TABLE proyectos ALTER COLUMN p90_mensual_kwh TYPE TEXT USING p90_mensual_kwh::text")
    op.execute("ALTER TABLE fallas ALTER COLUMN fotos_urls TYPE TEXT USING fotos_urls::text")

    # Drop all indexes (in reverse order)
    op.drop_index("ix_gestion_registros_proyecto_id")
    op.drop_index("ix_generacion_diaria_fecha")
    op.drop_index("ix_mantenimientos_registrado_por_id")
    op.drop_index("ix_mantenimientos_proyecto_id")
    op.drop_index("ix_asic_cambios_proyecto_nuevo_id")
    op.drop_index("ix_asic_cambios_proyecto_original_id")
    op.drop_index("ix_asic_cambios_solicitud_id")
    op.drop_index("ix_asic_solicitudes_proyecto_id")
    op.drop_index("ix_rec_certificados_proceso_id")
    op.drop_index("ix_rec_procesos_proyecto_id")
    op.drop_index("ix_promotor_seguimientos_requisito_id")
    op.drop_index("ix_promotor_seguimientos_proyecto_id")
    op.drop_index("ix_contratos_arriendo_proyecto_id")
    op.drop_index("ix_ppa_compromisos_contrato_id")
    op.drop_index("ix_ppa_tarifas_contrato_id")
    op.drop_index("ix_ppa_contratos_vendedor_id")
    op.drop_index("ix_ppa_contratos_comprador_id")
    op.drop_index("ix_contratos_servicio_prestador_id")
    op.drop_index("ix_contratos_servicio_contratante_id")
    op.drop_index("ix_contratos_servicio_proyecto_id")
    op.drop_index("ix_operacion_kpis_servicio_id")
    op.drop_index("ix_operacion_kpis_proyecto_id")
    op.drop_index("ix_representacion_gescon_servicio_id")
    op.drop_index("ix_representacion_gescon_proyecto_id")
    op.drop_index("ix_equipos_sellos_equipo_id")
    op.drop_index("ix_equipos_frontera_id")
    op.drop_index("ix_frontera_lectura_frontera_fecha")
    op.drop_index("ix_fronteras_lecturas_frontera_id")
    op.drop_index("ix_fronteras_embebida_bajo_id")
    op.drop_index("ix_fronteras_agrupada_bajo_id")
    op.drop_index("ix_fronteras_frontera_gemela_id")
    op.drop_index("ix_fronteras_proyecto_id")
    op.drop_index("ix_liquidacion_facturas_liquidacion_id")
    op.drop_index("ix_liquidacion_mandato_lineas_mandato_id")
    op.drop_index("ix_liquidacion_mandatos_inversionista_id")
    op.drop_index("ix_liquidacion_mandatos_liquidacion_id")
    op.drop_index("ix_liquidacion_xm_datos_frontera_id")
    op.drop_index("ix_liquidacion_xm_datos_liquidacion_id")
    op.drop_index("ix_liquidacion_costos_liquidacion_id")
    op.drop_index("ix_liquidaciones_generado_por_id")
    op.drop_index("ix_liquidaciones_proyecto_id")
    op.drop_index("ix_fallas_seguimientos_estado_nuevo_id")
    op.drop_index("ix_fallas_seguimientos_usuario_id")
    op.drop_index("ix_fallas_seguimientos_falla_id")
    op.drop_index("ix_fallas_fecha_identificacion")
    op.drop_index("ix_fallas_asignado_a_id")
    op.drop_index("ix_fallas_registrado_por_id")
    op.drop_index("ix_fallas_resolucion_id")
    op.drop_index("ix_fallas_prioridad_id")
    op.drop_index("ix_fallas_estado_id")
    op.drop_index("ix_fallas_tipo_id")
    op.drop_index("ix_fallas_proyecto_id")
    op.drop_index("ix_cliente_docs_comerciales_servicio_id")
    op.drop_index("ix_cliente_docs_comerciales_cliente_id")
    op.drop_index("ix_cliente_servicios_cliente_id")
    op.drop_index("ix_proyecto_inversionistas_cliente_id")
    op.drop_index("ix_proyecto_inversionistas_proyecto_id")
    op.drop_index("ix_proyecto_contactos_proyecto_id")
    op.drop_index("ix_proyecto_inversores_proyecto_id")
    op.drop_index("ix_proyecto_grupos_panel_proyecto_id")
    op.drop_index("ix_proyecto_info_tecnica_proyecto_id")
    op.drop_index("ix_proyectos_proyecto_padre_id")
    op.drop_index("ix_proyectos_portafolio_id")
    op.drop_index("ix_proyectos_cliente_id")
    op.drop_index("ix_informes_guardados_aprobado_por_id")
    op.drop_index("ix_informes_guardados_editado_por_id")
    op.drop_index("ix_informes_guardados_creado_por_id")
