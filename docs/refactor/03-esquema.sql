-- =====================================================================================
-- 03 · Esquema objetivo del núcleo — Plataforma de Operaciones Unergy
--
-- Resumen (3 líneas):
--   Núcleo del dominio con el proyecto como entidad central: red, proyecto, equipos,
--   propiedad con vigencia, contratos con roles y fallas multi-proyecto.
--   Ordenado por dependencias: se ejecuta de arriba a abajo sobre una base vacía.
--
-- ALCANCE: solo el núcleo (decisión D-19). NO redefine liquidaciones, Cumplimiento/MEM,
--   comercial/CRM, arriendos ni O&M. Lo mínimo indispensable para que el script corra
--   (usuarios, catálogos de fallas) va en el BLOQUE 0, marcado como preexistente.
-- NO INCLUIDO A PROPÓSITO: la frontera. Decisión D-06 pendiente de confirmación.
--   Ver el BLOQUE 13 al final, donde queda el hueco señalado.
-- CONVENCIONES: tablas en snake_case plural, columnas en español, PK bigint (BIGSERIAL),
--   enums nativos de Postgres, índice en toda FK, un COMMENT por tabla.
-- =====================================================================================


-- =====================================================================================
-- BLOQUE 0 · Tablas preexistentes fuera de alcance
-- Van aquí en forma mínima para que el script sea ejecutable. En producción ya existen
-- y NO se tocan: su definición real está en esquema-bd-produccion/esquema_produccion.sql
-- =====================================================================================

CREATE TYPE rol_enum AS ENUM (
    'admin', 'operaciones', 'monitoreo', 'liquidaciones', 'cgm',
    'solo_lectura', 'coordinador', 'tecnico', 'comercial'
);

CREATE TABLE usuarios (
    id          BIGSERIAL PRIMARY KEY,
    nombre      VARCHAR(255) NOT NULL,
    email       VARCHAR(255) NOT NULL UNIQUE,
    rol         rol_enum     NOT NULL DEFAULT 'solo_lectura',
    activo      BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);
COMMENT ON TABLE usuarios IS 'Preexistente, fuera de alcance: personas que usan la plataforma.';


-- =====================================================================================
-- BLOQUE 1 · Extensiones
-- =====================================================================================

-- btree_gist permite mezclar igualdad (proyecto_id) con solapamiento (daterange)
-- en el mismo EXCLUDE, que es lo que impide dos composiciones vigentes a la vez.
CREATE EXTENSION IF NOT EXISTS btree_gist;


-- =====================================================================================
-- BLOQUE 2 · Tipos ENUM
-- Conjuntos cerrados que solo cambian con un despliegue. Lo que el usuario administra
-- va como tabla de catálogo, no como enum (decisión D-15).
-- REGLA: los valores se agregan con ALTER TYPE ... ADD VALUE y NUNCA se renombran.
-- =====================================================================================

-- --- Reutilizados del esquema actual (mismos valores, mismo nombre de tipo) ---
CREATE TYPE estado_proyecto_enum          AS ENUM ('en_desarrollo', 'en_operacion', 'suspendido', 'cancelado');
CREATE TYPE clasificacion_regulatoria_enum AS ENUM ('AGP', 'AGPE', 'AGGE', 'GD', 'DER', 'otra');
CREATE TYPE tipo_tecnologia_enum          AS ENUM ('solar', 'eolica', 'hidraulica', 'biomasa', 'otra');
CREATE TYPE tipo_proyecto_enum            AS ENUM ('minigranja', 'autoconsumo', 'gd', 'movilidad_electrica', 'otro');
CREATE TYPE tipo_persona_enum             AS ENUM ('natural', 'juridica');
CREATE TYPE tipo_contacto_enum            AS ENUM ('operacional', 'cgm', 'liquidacion', 'comercial', 'contable');
CREATE TYPE estado_contrato_enum          AS ENUM ('vigente', 'vencido', 'terminado', 'en_renovacion');
CREATE TYPE periodicidad_enum             AS ENUM ('mensual', 'bimestral', 'trimestral', 'semestral', 'anual');
CREATE TYPE tipo_mantenimiento_enum       AS ENUM ('preventivo', 'correctivo', 'predictivo');
CREATE TYPE estado_mantenimiento_enum     AS ENUM ('programado', 'en_ejecucion', 'completado', 'cancelado');

-- --- Nuevos ---

-- Ciclo de vida fino del proyecto. Convive con estado_proyecto_enum, que es más grueso
-- y es el que expone el contrato congelado como estado_proyecto (ver 05).
CREATE TYPE proyecto_etapa_enum AS ENUM ('construccion', 'comisionamiento', 'operacion', 'comercial');

-- Escenarios de la simulación energética.
CREATE TYPE simulacion_escenario_enum AS ENUM ('p50', 'p90', 'p99');

-- Sistemas externos con los que se cruza la identidad de una planta.
CREATE TYPE sistema_externo_enum AS ENUM (
    'unergy_api', 'solenium', 'sunfactory', 'quoia', 'origina', 'liquidaciones', 'tsf', 'cnd'
);

-- Cómo se registra un tipo de equipo: uno por uno, o por cantidad.
CREATE TYPE equipo_granularidad_enum AS ENUM ('individual', 'cantidad');

-- Situación física del equipo. 'dado_de_baja' siempre va con fecha_baja.
CREATE TYPE equipo_estado_enum AS ENUM ('en_bodega', 'instalado', 'en_reparacion', 'dado_de_baja');

-- Por qué salió de servicio un equipo. Nunca se borra la fila: se marca la baja.
CREATE TYPE equipo_baja_motivo_enum AS ENUM (
    'falla', 'obsolescencia', 'robo', 'siniestro', 'fin_de_vida', 'reemplazo_preventivo', 'otro'
);

-- Los 5 tipos de contrato del negocio. El tipo NO abre una tabla nueva (decisión D-10).
CREATE TYPE contrato_tipo_enum AS ENUM (
    'representacion', 'compraventa_energia', 'arriendo', 'operacion', 'mantenimiento'
);

-- Papel de un cliente dentro de un contrato. Reemplaza las columnas contratante/prestador.
CREATE TYPE contrato_rol_enum AS ENUM (
    'propietario', 'arrendador', 'arrendatario', 'comprador', 'vendedor',
    'operador', 'mantenedor', 'representante'
);

-- Qué se cobra en un contrato. Cerrado a proposito: agregar un concepto es un
-- cambio de modelo de negocio, no un dato que administre el usuario (D-15).
CREATE TYPE tarifa_concepto_enum AS ENUM (
    'administracion', 'cgm', 'representacion', 'canon', 'energia'
);

-- En que unidad esta expresada una tarifa. Es OBLIGATORIA: en los datos de hoy
-- conviven porcentajes (administracion = 0.038 -> 3,8%) y COP/kWh (cgm = 6.0) en
-- columnas del mismo tipo, y sin unidad son indistinguibles.
CREATE TYPE tarifa_unidad_enum AS ENUM ('porcentaje', 'cop_kwh', 'cop_mes', 'cop_total');

-- Qué originó la falla. 'red' y 'evento_natural' son las causas externas del brief.
CREATE TYPE falla_origen_enum AS ENUM ('equipo', 'red', 'evento_natural', 'externo');


-- =====================================================================================
-- BLOQUE 3 · Catálogos sin dependencias
-- =====================================================================================

CREATE TABLE portafolios (
    id          BIGSERIAL PRIMARY KEY,
    nombre      VARCHAR(255) NOT NULL UNIQUE,
    descripcion TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE portafolios IS 'Agrupación comercial de plantas para reportes e informes conjuntos.';

-- --- Clientes y sus contactos ---

CREATE TABLE clientes (
    id                   BIGSERIAL PRIMARY KEY,
    razon_social_nombre  VARCHAR(255) NOT NULL,
    nit_cedula           VARCHAR(20)  UNIQUE,
    tipo_persona         tipo_persona_enum,
    representante_legal  VARCHAR(255),
    direccion            VARCHAR(500),
    ciudad               VARCHAR(100),
    departamento         VARCHAR(100),
    iva_pct              NUMERIC(5,2),
    retencion_pct        NUMERIC(5,2),
    reteica_pct          NUMERIC(5,2),
    reteiva_pct          NUMERIC(5,2),
    origen_tipo          VARCHAR(30),
    origen_detalle       VARCHAR(255),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at           TIMESTAMPTZ,
    CONSTRAINT ck_clientes_pct CHECK (
        (iva_pct       IS NULL OR iva_pct       BETWEEN 0 AND 100) AND
        (retencion_pct IS NULL OR retencion_pct BETWEEN 0 AND 100) AND
        (reteica_pct   IS NULL OR reteica_pct   BETWEEN 0 AND 100) AND
        (reteiva_pct   IS NULL OR reteiva_pct   BETWEEN 0 AND 100)
    )
);
COMMENT ON TABLE clientes IS 'Persona natural o jurídica con la que Unergy tiene relación: dueño, contraparte de contrato o proveedor.';

CREATE TABLE contactos (
    id                     BIGSERIAL PRIMARY KEY,
    cliente_id             BIGINT NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    nombre                 VARCHAR(255),
    email                  VARCHAR(255) NOT NULL,
    telefono               VARCHAR(50),
    tipo                   tipo_contacto_enum NOT NULL,
    recibe_notificaciones  BOOLEAN NOT NULL DEFAULT TRUE,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_contactos UNIQUE (cliente_id, email, tipo)
);
COMMENT ON TABLE contactos IS 'Persona de contacto de un cliente, clasificada por el área que atiende.';

-- --- Catálogo de equipos: fabricante y tipo ---

CREATE TABLE fabricantes (
    id         BIGSERIAL PRIMARY KEY,
    nombre     VARCHAR(255) NOT NULL UNIQUE,
    nit        VARCHAR(20),
    sitio_web  VARCHAR(255),
    activo     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE fabricantes IS 'Catálogo de marcas de equipo; reemplaza las columnas marca_* en texto libre.';

CREATE TABLE equipo_tipos (
    id                        BIGSERIAL PRIMARY KEY,
    codigo                    VARCHAR(50)  NOT NULL UNIQUE,
    nombre                    VARCHAR(120) NOT NULL,
    granularidad              equipo_granularidad_enum NOT NULL,
    admite_componentes        BOOLEAN NOT NULL DEFAULT FALSE,
    esquema_especificaciones  JSONB   NOT NULL DEFAULT '{}'::jsonb,
    es_base                   BOOLEAN NOT NULL DEFAULT FALSE,
    activo                    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_equipo_tipos_esquema CHECK (jsonb_typeof(esquema_especificaciones) = 'object')
);
COMMENT ON TABLE equipo_tipos IS 'Catálogo extensible de tipos de equipo; cada tipo declara el JSON Schema de sus especificaciones.';
COMMENT ON COLUMN equipo_tipos.esquema_especificaciones IS 'JSON Schema que valida equipos.especificaciones; el usuario puede crear tipos nuevos sin migración.';
COMMENT ON COLUMN equipo_tipos.es_base IS 'TRUE en los tipos precargados por el sistema; los creados por el usuario van en FALSE.';

-- --- Operador de red ---

CREATE TABLE operadores_red (
    id               BIGSERIAL PRIMARY KEY,
    nombre_legal     VARCHAR(255) NOT NULL UNIQUE,
    nombre_comercial VARCHAR(100),
    nit              VARCHAR(20) UNIQUE,
    activo           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE operadores_red IS 'Operador de red al que se conectan las plantas; catálogo, no texto libre.';

CREATE TABLE operadores_red_contactos (
    id              BIGSERIAL PRIMARY KEY,
    operador_red_id BIGINT NOT NULL REFERENCES operadores_red(id) ON DELETE CASCADE,
    nombre          VARCHAR(255),
    email           VARCHAR(255) NOT NULL,
    telefono        VARCHAR(50),
    activo          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_operadores_red_contactos UNIQUE (operador_red_id, email)
);
COMMENT ON TABLE operadores_red_contactos IS 'Correos y nombres de contacto de un operador de red.';

-- Catálogos de fallas: preexistentes y se conservan intactos (decisión D-18).
CREATE TABLE fallas_cat_categorias (
    id         BIGSERIAL PRIMARY KEY,
    codigo     VARCHAR(50)  NOT NULL UNIQUE,
    nombre     VARCHAR(120) NOT NULL,
    orden      INTEGER NOT NULL DEFAULT 0,
    activo     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE fallas_cat_categorias IS 'Preexistente: categoría de primer nivel de una falla (sistema afectado).';

CREATE TABLE fallas_cat_tipos (
    id            BIGSERIAL PRIMARY KEY,
    categoria_id  BIGINT REFERENCES fallas_cat_categorias(id) ON DELETE SET NULL,
    codigo        VARCHAR(80)  NOT NULL UNIQUE,
    nombre        VARCHAR(180) NOT NULL,
    activo        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE fallas_cat_tipos IS 'Preexistente: tipo de falla dentro de una categoría.';

CREATE TABLE fallas_cat_estados (
    id              BIGSERIAL PRIMARY KEY,
    codigo          VARCHAR(50)  NOT NULL UNIQUE,
    nombre          VARCHAR(120) NOT NULL,
    es_estado_final BOOLEAN NOT NULL DEFAULT FALSE,
    orden           INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE fallas_cat_estados IS 'Preexistente: estados por los que pasa una falla (identificado, programado, resuelto, cancelado).';

CREATE TABLE fallas_cat_prioridades (
    id         BIGSERIAL PRIMARY KEY,
    codigo     VARCHAR(50)  NOT NULL UNIQUE,
    nombre     VARCHAR(120) NOT NULL,
    nivel      INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE fallas_cat_prioridades IS 'Preexistente: prioridad de atención de una falla.';

CREATE TABLE fallas_cat_resoluciones (
    id     BIGSERIAL PRIMARY KEY,
    codigo VARCHAR(50)  NOT NULL UNIQUE,
    nombre VARCHAR(180) NOT NULL
);
COMMENT ON TABLE fallas_cat_resoluciones IS 'Preexistente: cómo se resolvió una falla.';


-- =====================================================================================
-- BLOQUE 4 · Red eléctrica (jerarquía) — decisión D-07
-- Es lo que permite que un daño en un punto compartido sea UN incidente y no N fallas.
-- =====================================================================================

CREATE TABLE red_circuitos (
    id               BIGSERIAL PRIMARY KEY,
    operador_red_id  BIGINT NOT NULL REFERENCES operadores_red(id) ON DELETE RESTRICT,
    codigo           VARCHAR(60)  NOT NULL,
    nombre           VARCHAR(180),
    nivel_tension_kv NUMERIC(8,3),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_red_circuitos UNIQUE (operador_red_id, codigo),
    CONSTRAINT ck_red_circuitos_tension CHECK (nivel_tension_kv IS NULL OR nivel_tension_kv > 0)
);
COMMENT ON TABLE red_circuitos IS 'Circuito de un operador de red; agrupa los puntos de conexión que dependen de él.';

CREATE TABLE red_puntos_conexion (
    id                    BIGSERIAL PRIMARY KEY,
    circuito_id           BIGINT NOT NULL REFERENCES red_circuitos(id) ON DELETE RESTRICT,
    codigo                VARCHAR(60) NOT NULL,
    nombre                VARCHAR(180),
    subestacion           VARCHAR(180),
    transformador_codigo  VARCHAR(60),
    latitud               NUMERIC(9,6),
    longitud              NUMERIC(9,6),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_red_puntos_conexion UNIQUE (circuito_id, codigo)
);
COMMENT ON TABLE red_puntos_conexion IS 'Punto físico donde una o varias plantas se conectan a la red; un daño acá afecta a todas.';


-- =====================================================================================
-- BLOQUE 5 · Proyecto (entidad central)
-- =====================================================================================

CREATE TABLE proyectos (
    id                        BIGSERIAL PRIMARY KEY,
    nombre_comercial          VARCHAR(255) NOT NULL,
    portafolio_id             BIGINT REFERENCES portafolios(id) ON DELETE SET NULL,

    -- Clasificación
    clasificacion_regulatoria clasificacion_regulatoria_enum,
    tipo_tecnologia           tipo_tecnologia_enum,
    tipo_proyecto             tipo_proyecto_enum,
    es_comunidad_energetica   BOOLEAN NOT NULL DEFAULT FALSE,
    nombre_comunidad          VARCHAR(255),

    -- Ciclo de vida. 'estado' es el grueso que expone la API; 'etapa' es el fino del brief.
    estado                    estado_proyecto_enum NOT NULL DEFAULT 'en_desarrollo',
    etapa                     proyecto_etapa_enum,

    -- Técnicos (ver D-20: tracker y subestación NO van acá, son equipos)
    potencia_dc_kwp           NUMERIC(12,3),
    potencia_ac_kw            NUMERIC(12,3),
    altitud_msnm              NUMERIC(7,1),
    produccion_especifica_kwh_kwp NUMERIC(10,2),

    -- Ubicación. Strings a propósito, no catálogo DIVIPOLA (ver D-16).
    departamento              VARCHAR(100),
    municipio                 VARCHAR(100),
    direccion_vereda          VARCHAR(500),
    latitud                   NUMERIC(9,6),
    longitud                  NUMERIC(9,6),
    url_ubicacion             VARCHAR(500),

    -- Red
    operador_red_id           BIGINT REFERENCES operadores_red(id) ON DELETE SET NULL,
    punto_conexion_id         BIGINT REFERENCES red_puntos_conexion(id) ON DELETE SET NULL,
    tipo_conexion             VARCHAR(100),

    -- Fechas del ciclo de vida
    fecha_estimada_energizacion  DATE,
    fecha_fin_comisionamiento    DATE,
    -- Estas dos se conservan por el CONTRATO CONGELADO, no por diseño:
    -- alimentan construccion.fase y construccion.origen_registro de la API externa.
    -- `etapa` es el eje normalizado; `fase_construccion` es el texto que el consumidor ya lee.
    fase_construccion            VARCHAR(40),
    origen                       VARCHAR(20) DEFAULT 'manual',
    fecha_entrada_operacion      DATE,
    fecha_inicio_comercializacion DATE,
    fecha_comercializacion_editada_manual BOOLEAN NOT NULL DEFAULT FALSE,
    avance_obra_pct              NUMERIC(5,2),

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,

    CONSTRAINT ck_proyectos_potencia CHECK (
        (potencia_dc_kwp IS NULL OR potencia_dc_kwp > 0) AND
        (potencia_ac_kw  IS NULL OR potencia_ac_kw  > 0)
    ),
    CONSTRAINT ck_proyectos_avance CHECK (avance_obra_pct IS NULL OR avance_obra_pct BETWEEN 0 AND 100),
    CONSTRAINT ck_proyectos_latlon CHECK (
        (latitud IS NULL OR latitud BETWEEN -90 AND 90) AND
        (longitud IS NULL OR longitud BETWEEN -180 AND 180)
    ),
    -- Coherencia de fechas: no se puede comercializar antes de entrar en operación.
    CONSTRAINT ck_proyectos_orden_fechas CHECK (
        fecha_entrada_operacion IS NULL
        OR fecha_inicio_comercializacion IS NULL
        OR fecha_inicio_comercializacion >= fecha_entrada_operacion
    ),
    CONSTRAINT ck_proyectos_comunidad CHECK (
        es_comunidad_energetica = FALSE OR nombre_comunidad IS NOT NULL
    ),
    CONSTRAINT ck_proyectos_origen CHECK (origen IS NULL OR origen IN ('manual', 'tsf_sync'))
);
COMMENT ON TABLE proyectos IS 'Planta de generación distribuida: la entidad central del dominio.';
COMMENT ON COLUMN proyectos.punto_conexion_id IS 'Punto de red compartido; es lo que permite agrupar una falla de red en un solo incidente.';
COMMENT ON COLUMN proyectos.etapa IS 'Ciclo de vida fino (construcción/comisionamiento/operación/comercial); eje normalizado que convive con fase_construccion.';
COMMENT ON COLUMN proyectos.fase_construccion IS 'CONTRATO CONGELADO: alimenta construccion.fase de la API externa. No se elimina sin avisar al consumidor.';
COMMENT ON COLUMN proyectos.origen IS 'CONTRATO CONGELADO: alimenta construccion.origen_registro. manual | tsf_sync.';

-- --- Satélites del proyecto: identidad externa, simulación, caché y estado ---

CREATE TABLE proyecto_identificacion_externa (
    id          BIGSERIAL PRIMARY KEY,
    proyecto_id BIGINT NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
    sistema     sistema_externo_enum NOT NULL,
    clave       VARCHAR(120) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_proyecto_id_externa_sistema  UNIQUE (proyecto_id, sistema),
    CONSTRAINT uq_proyecto_id_externa_clave    UNIQUE (sistema, clave)
);
COMMENT ON TABLE proyecto_identificacion_externa IS 'Clave de la planta en cada sistema externo; reemplaza las 10 columnas de id de integración.';

CREATE TABLE proyecto_simulacion (
    id           BIGSERIAL PRIMARY KEY,
    proyecto_id  BIGINT NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
    escenario    simulacion_escenario_enum NOT NULL,
    mes          SMALLINT NOT NULL,
    energia_kwh  NUMERIC(14,3) NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_proyecto_simulacion UNIQUE (proyecto_id, escenario, mes),
    CONSTRAINT ck_proyecto_simulacion_mes    CHECK (mes BETWEEN 1 AND 12),
    CONSTRAINT ck_proyecto_simulacion_energia CHECK (energia_kwh >= 0)
);
COMMENT ON TABLE proyecto_simulacion IS 'Energía simulada por mes y escenario (P50/P90/P99); reemplaza los 3 arrays JSONB sin validar.';

CREATE TABLE proyecto_generacion_promedio (
    proyecto_id      BIGINT PRIMARY KEY REFERENCES proyectos(id) ON DELETE CASCADE,
    energia_mwh_mes  NUMERIC(12,3),
    origen           VARCHAR(10),
    dias_con_datos   INTEGER,
    ventana_desde    DATE,
    ventana_hasta    DATE,
    actualizado_en   TIMESTAMPTZ,
    CONSTRAINT ck_pgp_ventana CHECK (ventana_desde IS NULL OR ventana_hasta IS NULL OR ventana_hasta >= ventana_desde),
    CONSTRAINT ck_pgp_origen  CHECK (origen IS NULL OR origen IN ('medido', 'manual', 'estimado', 'declarado'))
);
COMMENT ON TABLE proyecto_generacion_promedio IS 'CACHÉ declarada de la generación promedio mensual: es derivada de la serie, se guarda por rendimiento (D-12).';

CREATE TABLE proyecto_estado_historial (
    id           BIGSERIAL PRIMARY KEY,
    proyecto_id  BIGINT NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
    estado       estado_proyecto_enum NOT NULL,
    etapa        proyecto_etapa_enum,
    vigencia     DATERANGE NOT NULL,
    motivo       TEXT,
    usuario_id   BIGINT REFERENCES usuarios(id) ON DELETE SET NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ex_proyecto_estado_sin_solape
        EXCLUDE USING gist (proyecto_id WITH =, vigencia WITH &&)
);
COMMENT ON TABLE proyecto_estado_historial IS 'En qué estado y etapa estuvo la planta en cada periodo; hoy el estado se sobrescribe sin dejar rastro.';

CREATE TABLE proyecto_area_contacto (
    id          BIGSERIAL PRIMARY KEY,
    proyecto_id BIGINT NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
    tipo        tipo_contacto_enum NOT NULL,
    cliente_id  BIGINT NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_proyecto_area_contacto UNIQUE (proyecto_id, tipo)
);
COMMENT ON TABLE proyecto_area_contacto IS 'Preexistente: qué cliente atiende cada área de una planta.';


-- =====================================================================================
-- BLOQUE 6 · Equipos — decisiones D-01 a D-05
-- Catálogo (modelo) separado de instancia (equipo físico instalado).
-- =====================================================================================

CREATE TABLE equipo_modelos (
    id                BIGSERIAL PRIMARY KEY,
    equipo_tipo_id    BIGINT NOT NULL REFERENCES equipo_tipos(id) ON DELETE RESTRICT,
    fabricante_id     BIGINT REFERENCES fabricantes(id) ON DELETE SET NULL,
    nombre            VARCHAR(180) NOT NULL,
    especificaciones  JSONB NOT NULL DEFAULT '{}'::jsonb,
    datasheet_url     VARCHAR(500),
    activo            BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_equipo_modelos UNIQUE (fabricante_id, nombre),
    CONSTRAINT ck_equipo_modelos_especs CHECK (jsonb_typeof(especificaciones) = 'object')
);
COMMENT ON TABLE equipo_modelos IS 'Catálogo de modelos de equipo (marca + referencia + ficha técnica); no es el equipo instalado.';

CREATE TABLE equipo_modelo_componentes (
    id               BIGSERIAL PRIMARY KEY,
    modelo_padre_id  BIGINT NOT NULL REFERENCES equipo_modelos(id) ON DELETE CASCADE,
    equipo_tipo_id   BIGINT NOT NULL REFERENCES equipo_tipos(id) ON DELETE RESTRICT,
    cantidad         INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT uq_equipo_modelo_componentes UNIQUE (modelo_padre_id, equipo_tipo_id),
    CONSTRAINT ck_equipo_modelo_componentes_cant CHECK (cantidad >= 1)
);
COMMENT ON TABLE equipo_modelo_componentes IS 'De qué componentes consta un modelo (un Starlink trae antena, fuente, módem y cableado).';

-- --- Instancia: el equipo físico instalado ---

CREATE TABLE equipos (
    id                  BIGSERIAL PRIMARY KEY,
    proyecto_id         BIGINT NOT NULL REFERENCES proyectos(id) ON DELETE RESTRICT,
    equipo_tipo_id      BIGINT NOT NULL REFERENCES equipo_tipos(id) ON DELETE RESTRICT,
    equipo_modelo_id    BIGINT REFERENCES equipo_modelos(id) ON DELETE SET NULL,
    parent_equipo_id    BIGINT REFERENCES equipos(id) ON DELETE CASCADE,

    nombre              VARCHAR(180),
    numero_serie        VARCHAR(120),
    cantidad            INTEGER NOT NULL DEFAULT 1,
    especificaciones    JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Campos comunes a todo equipo (los 4 que pide el brief)
    fecha_compra                 DATE,
    fecha_puesta_servicio        DATE,
    garantia_dias                INTEGER,
    mantenimiento_intervalo_dias INTEGER,
    documentacion_url            VARCHAR(500),

    -- Derivado GARANTIZADO por Postgres, indexable. Excepción documentada (D-04).
    garantia_vence_el   DATE GENERATED ALWAYS AS (fecha_puesta_servicio + garantia_dias) STORED,

    estado              equipo_estado_enum NOT NULL DEFAULT 'instalado',
    fecha_baja          DATE,
    baja_motivo         equipo_baja_motivo_enum,
    reemplaza_a_equipo_id BIGINT REFERENCES equipos(id) ON DELETE SET NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT ck_equipos_cantidad CHECK (cantidad >= 1),
    -- El serial identifica una unidad: solo tiene sentido si la fila es una unidad.
    CONSTRAINT ck_equipos_serie_unitaria CHECK (numero_serie IS NULL OR cantidad = 1),
    CONSTRAINT ck_equipos_garantia CHECK (garantia_dias IS NULL OR garantia_dias >= 0),
    CONSTRAINT ck_equipos_mant_intervalo CHECK (mantenimiento_intervalo_dias IS NULL OR mantenimiento_intervalo_dias > 0),
    -- La baja nunca borra la fila, pero tiene que estar completa.
    CONSTRAINT ck_equipos_baja CHECK (
        (estado = 'dado_de_baja' AND fecha_baja IS NOT NULL AND baja_motivo IS NOT NULL)
        OR (estado <> 'dado_de_baja' AND fecha_baja IS NULL AND baja_motivo IS NULL)
    ),
    CONSTRAINT ck_equipos_baja_posterior CHECK (
        fecha_baja IS NULL OR fecha_puesta_servicio IS NULL OR fecha_baja >= fecha_puesta_servicio
    ),
    CONSTRAINT ck_equipos_no_es_su_padre CHECK (parent_equipo_id IS NULL OR parent_equipo_id <> id),
    CONSTRAINT ck_equipos_especs CHECK (jsonb_typeof(especificaciones) = 'object')
);
COMMENT ON TABLE equipos IS 'Equipo físico instalado en una planta; un componente de otro equipo también es un equipo y puede fallar solo.';
COMMENT ON COLUMN equipos.cantidad IS 'Unidades que representa la fila: 1 en los tipos individuales, N en los que se registran por cantidad (paneles).';
COMMENT ON COLUMN equipos.garantia_vence_el IS 'Columna generada: fecha_puesta_servicio + garantia_dias. Derivada a propósito, para poder indexar el vencimiento.';
COMMENT ON COLUMN equipos.reemplaza_a_equipo_id IS 'Al reemplazar, el equipo que sale se marca de baja y el que entra apunta acá: no se pierde historia.';

CREATE TABLE equipo_mantenimientos (
    id                     BIGSERIAL PRIMARY KEY,
    equipo_id              BIGINT NOT NULL REFERENCES equipos(id) ON DELETE CASCADE,
    tipo                   tipo_mantenimiento_enum NOT NULL,
    estado                 estado_mantenimiento_enum NOT NULL DEFAULT 'programado',
    fecha_programada       DATE,
    fecha_ejecucion        DATE,
    descripcion            TEXT,
    ejecutado_por_cliente_id BIGINT REFERENCES clientes(id) ON DELETE SET NULL,
    registrado_por_id      BIGINT REFERENCES usuarios(id) ON DELETE SET NULL,
    costo_cop              NUMERIC(16,2),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_equipo_mant_ejecucion CHECK (
        estado <> 'completado' OR fecha_ejecucion IS NOT NULL
    )
);
COMMENT ON TABLE equipo_mantenimientos IS 'Mantenimiento programado o ejecutado sobre un equipo; de acá sale qué mantenimiento está pendiente.';


-- =====================================================================================
-- BLOQUE 7 · Propiedad con vigencia — decisiones D-08 y D-09
-- Las liquidaciones de un periodo se calculan con la composición vigente EN ese periodo.
-- =====================================================================================

CREATE TABLE proyecto_composiciones (
    id                BIGSERIAL PRIMARY KEY,
    proyecto_id       BIGINT NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
    vigencia          DATERANGE NOT NULL,
    motivo            TEXT,
    documento_url     VARCHAR(500),
    registrado_por_id BIGINT REFERENCES usuarios(id) ON DELETE SET NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_proyecto_composiciones_vigencia CHECK (NOT isempty(vigencia)),
    CONSTRAINT ex_proyecto_composiciones_sin_solape
        EXCLUDE USING gist (proyecto_id WITH =, vigencia WITH &&)
);
COMMENT ON TABLE proyecto_composiciones IS 'Composición accionaria de una planta vigente en un periodo; cada cambio de propiedad crea una nueva.';
COMMENT ON COLUMN proyecto_composiciones.vigencia IS 'Rango de fechas [desde, hasta); el EXCLUDE impide dos composiciones solapadas del mismo proyecto.';

CREATE TABLE proyecto_composicion_lineas (
    id                     BIGSERIAL PRIMARY KEY,
    composicion_id         BIGINT NOT NULL REFERENCES proyecto_composiciones(id) ON DELETE CASCADE,
    cliente_id             BIGINT NOT NULL REFERENCES clientes(id) ON DELETE RESTRICT,
    porcentaje             NUMERIC(9,6) NOT NULL,
    es_patrimonio_autonomo BOOLEAN NOT NULL DEFAULT FALSE,
    contrato_id            BIGINT,  -- FK agregada en el BLOQUE 8, cuando contratos ya existe
    CONSTRAINT uq_proyecto_composicion_lineas UNIQUE (composicion_id, cliente_id),
    CONSTRAINT ck_proyecto_composicion_lineas_pct CHECK (porcentaje > 0 AND porcentaje <= 100)
);
COMMENT ON TABLE proyecto_composicion_lineas IS 'Qué porcentaje tiene cada cliente en una composición; la suma de la composición debe ser 100.';


-- =====================================================================================
-- BLOQUE 8 · Contratos — decisión D-10
-- Una tabla, el tipo como enum, los roles en tabla puente.
-- =====================================================================================

CREATE TABLE contratos (
    id                  BIGSERIAL PRIMARY KEY,
    tipo                contrato_tipo_enum NOT NULL,
    estado              estado_contrato_enum NOT NULL DEFAULT 'vigente',
    numero_contrato     VARCHAR(120),
    nombre_interno      VARCHAR(255),
    fecha_firma         DATE,
    fecha_inicio        DATE,
    fecha_fin           DATE,
    tarifa_base         NUMERIC(18,4),
    periodicidad_pago   periodicidad_enum,
    indice_indexacion   VARCHAR(60),
    renovacion_automatica BOOLEAN NOT NULL DEFAULT FALSE,
    documento_url       VARCHAR(500),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at          TIMESTAMPTZ,
    CONSTRAINT ck_contratos_fechas CHECK (fecha_fin IS NULL OR fecha_inicio IS NULL OR fecha_fin >= fecha_inicio),
    CONSTRAINT ck_contratos_tarifa CHECK (tarifa_base IS NULL OR tarifa_base >= 0)
);
COMMENT ON TABLE contratos IS 'Acuerdo entre partes sobre una o varias plantas; el tipo distingue representación, compraventa, arriendo, operación y mantenimiento.';

CREATE TABLE contrato_partes (
    id          BIGSERIAL PRIMARY KEY,
    contrato_id BIGINT NOT NULL REFERENCES contratos(id) ON DELETE CASCADE,
    cliente_id  BIGINT NOT NULL REFERENCES clientes(id) ON DELETE RESTRICT,
    rol         contrato_rol_enum NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_contrato_partes UNIQUE (contrato_id, cliente_id, rol)
);
COMMENT ON TABLE contrato_partes IS 'Qué papel juega cada cliente en un contrato; reemplaza las columnas contratante/prestador/comprador/vendedor.';

CREATE TABLE contrato_tarifas (
    id            BIGSERIAL PRIMARY KEY,
    contrato_id   BIGINT NOT NULL REFERENCES contratos(id) ON DELETE CASCADE,
    concepto      tarifa_concepto_enum NOT NULL,
    valor         NUMERIC(14,6) NOT NULL,
    unidad        tarifa_unidad_enum   NOT NULL,
    vigencia      DATERANGE            NOT NULL,

    -- De donde salio este valor: la base pactada, o una indexacion sobre la
    -- anterior. Reemplaza el {ipc, esBase} de los JSONB indexacion_* de hoy.
    es_base       BOOLEAN NOT NULL DEFAULT FALSE,
    indice        VARCHAR(20),
    indice_pct    NUMERIC(8,4),

    registrado_por_id BIGINT REFERENCES usuarios(id) ON DELETE SET NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT ck_contrato_tarifas_valor    CHECK (valor >= 0),
    CONSTRAINT ck_contrato_tarifas_vigencia CHECK (NOT isempty(vigencia)),
    -- Un porcentaje se guarda como fraccion (0.038 = 3,8%), como ya esta hoy.
    CONSTRAINT ck_contrato_tarifas_pct      CHECK (
        unidad <> 'porcentaje' OR valor <= 1
    ),
    -- La base no se indexa; lo indexado dice sobre que indice y cuanto.
    CONSTRAINT ck_contrato_tarifas_indice   CHECK (
        (es_base AND indice IS NULL AND indice_pct IS NULL)
        OR NOT es_base
    ),
    -- Un concepto no puede tener dos valores vigentes a la vez en el mismo
    -- contrato. Es el mismo mecanismo que protege la composicion accionaria.
    CONSTRAINT ex_contrato_tarifas_sin_solape
        EXCLUDE USING gist (contrato_id WITH =, concepto WITH =, vigencia WITH &&)
);
COMMENT ON TABLE contrato_tarifas IS 'Qué se cobra en un contrato, por concepto y con vigencia: las tarifas se renegocian e indexan cada año.';
COMMENT ON COLUMN contrato_tarifas.vigencia IS 'Rango [desde, hasta); la liquidación de un periodo usa la tarifa vigente EN ese periodo, no la actual.';
COMMENT ON COLUMN contrato_tarifas.unidad IS 'Obligatoria: administracion es un porcentaje y cgm es COP/kWh, y en las columnas de hoy son indistinguibles.';

CREATE TABLE contrato_proyectos (
    contrato_id BIGINT NOT NULL REFERENCES contratos(id) ON DELETE CASCADE,
    proyecto_id BIGINT NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
    PRIMARY KEY (contrato_id, proyecto_id)
);
COMMENT ON TABLE contrato_proyectos IS 'Qué plantas cubre un contrato; unifica el caso 1 planta y el caso varias plantas.';

-- Ahora que contratos existe, se cierra la FK que quedó pendiente en el BLOQUE 7.
ALTER TABLE proyecto_composicion_lineas
    ADD CONSTRAINT fk_pcl_contrato FOREIGN KEY (contrato_id) REFERENCES contratos(id) ON DELETE SET NULL;
COMMENT ON COLUMN proyecto_composicion_lineas.contrato_id IS 'Contrato que sustenta la participación; reemplaza contrato_ref en texto libre.';


-- =====================================================================================
-- BLOQUE 9 · Fallas — decisión D-11
-- Se conserva la tabla `fallas`; se le agrega lo que le falta.
-- =====================================================================================

CREATE TABLE fallas (
    id                  BIGSERIAL PRIMARY KEY,
    codigo_interno      VARCHAR(30) NOT NULL UNIQUE,
    codigo_legado       VARCHAR(30) UNIQUE,

    origen              falla_origen_enum NOT NULL DEFAULT 'equipo',
    -- Solo para las fallas de red: el punto compartido que las causa.
    punto_conexion_id   BIGINT REFERENCES red_puntos_conexion(id) ON DELETE SET NULL,

    tipo_id             BIGINT REFERENCES fallas_cat_tipos(id) ON DELETE SET NULL,
    estado_id           BIGINT NOT NULL REFERENCES fallas_cat_estados(id) ON DELETE RESTRICT,
    prioridad_id        BIGINT NOT NULL REFERENCES fallas_cat_prioridades(id) ON DELETE RESTRICT,
    resolucion_id       BIGINT REFERENCES fallas_cat_resoluciones(id) ON DELETE SET NULL,

    descripcion         TEXT NOT NULL,
    causa_raiz          TEXT,
    acciones_correctivas TEXT,

    fecha_identificacion DATE NOT NULL,
    hora_identificacion  TIME,
    fecha_programada     DATE,
    fecha_resolucion     TIMESTAMPTZ,
    sla_limite_horas     INTEGER,

    registrado_por_id   BIGINT NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    asignado_a_id       BIGINT REFERENCES usuarios(id) ON DELETE SET NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,

    -- NOTA: no se puede poner un CHECK de fecha_resolucion >= fecha_identificacion.
    -- Comparar timestamptz con date exige un cast STABLE, y Postgres solo admite
    -- funciones IMMUTABLE en un CHECK. Esa coherencia se valida en la capa de entrada.
    -- Una falla de red se explica por su punto de conexión; una de equipo, no.
    CONSTRAINT ck_fallas_origen_red CHECK (origen = 'red' OR punto_conexion_id IS NULL)
);
COMMENT ON TABLE fallas IS 'Incidente único: puede afectar a una o varias plantas y se origina en un equipo o en una causa externa.';
COMMENT ON COLUMN fallas.punto_conexion_id IS 'Solo en fallas de red: el punto compartido, que es lo que hace que un corte sea un incidente y no N.';

-- --- Satélites de falla: proyectos, equipos, historial, adjuntos e impacto ---

CREATE TABLE falla_proyectos (
    falla_id    BIGINT NOT NULL REFERENCES fallas(id) ON DELETE CASCADE,
    proyecto_id BIGINT NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
    PRIMARY KEY (falla_id, proyecto_id)
);
COMMENT ON TABLE falla_proyectos IS 'Qué plantas afecta una falla; lo normal es una, una falla de red son varias.';

CREATE TABLE falla_equipos (
    falla_id   BIGINT NOT NULL REFERENCES fallas(id) ON DELETE CASCADE,
    equipo_id  BIGINT NOT NULL REFERENCES equipos(id) ON DELETE RESTRICT,
    detalle    TEXT,
    PRIMARY KEY (falla_id, equipo_id)
);
COMMENT ON TABLE falla_equipos IS 'Qué equipos concretos están involucrados en una falla; generaliza falla_inversores.';

CREATE TABLE falla_estado_historial (
    id                 BIGSERIAL PRIMARY KEY,
    falla_id           BIGINT NOT NULL REFERENCES fallas(id) ON DELETE CASCADE,
    estado_anterior_id BIGINT REFERENCES fallas_cat_estados(id) ON DELETE SET NULL,
    estado_nuevo_id    BIGINT NOT NULL REFERENCES fallas_cat_estados(id) ON DELETE RESTRICT,
    usuario_id         BIGINT REFERENCES usuarios(id) ON DELETE SET NULL,
    nota               TEXT,
    ocurrido_en        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_falla_estado_distinto CHECK (estado_anterior_id IS NULL OR estado_anterior_id <> estado_nuevo_id)
);
COMMENT ON TABLE falla_estado_historial IS 'Bitácora de cambios de estado de una falla, con el estado anterior y el nuevo.';

CREATE TABLE falla_adjuntos (
    id            BIGSERIAL PRIMARY KEY,
    falla_id      BIGINT NOT NULL REFERENCES fallas(id) ON DELETE CASCADE,
    url           VARCHAR(1000) NOT NULL,
    nombre        VARCHAR(255),
    content_type  VARCHAR(120),
    tamano_bytes  BIGINT,
    subido_por_id BIGINT REFERENCES usuarios(id) ON DELETE SET NULL,
    subido_en     TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE falla_adjuntos IS 'Archivos adjuntos de una falla; reemplaza el JSONB fotos_urls con doble codificación histórica.';

CREATE TABLE falla_impactos (
    id                    BIGSERIAL PRIMARY KEY,
    falla_id              BIGINT NOT NULL REFERENCES fallas(id) ON DELETE CASCADE,
    proyecto_id           BIGINT NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
    kwh_perdidos_estimado NUMERIC(14,3),
    cop_estimado          NUMERIC(16,2),
    metodo                VARCHAR(60),
    calculado_en          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_falla_impactos UNIQUE (falla_id, proyecto_id),
    CONSTRAINT ck_falla_impactos_kwh CHECK (kwh_perdidos_estimado IS NULL OR kwh_perdidos_estimado >= 0)
);
COMMENT ON TABLE falla_impactos IS 'Energía y dinero perdidos por falla y por planta; si el incidente afecta a varias, el impacto es de cada una.';
COMMENT ON COLUMN falla_impactos.metodo IS 'Con qué método se estimó; hoy hay tres formas distintas de calcular energía esperada en el código.';


-- =====================================================================================
-- BLOQUE 10 · Garantía del invariante «los porcentajes suman 100» — decisión D-09
-- Un CHECK no puede sumar filas: hace falta un constraint trigger diferido, que se
-- evalúa al COMMIT y por eso permite insertar las líneas de a una.
-- =====================================================================================

CREATE OR REPLACE FUNCTION fn_composicion_suma_100() RETURNS TRIGGER AS $$
DECLARE
    v_composicion_id BIGINT;
    v_suma           NUMERIC(12,6);
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_composicion_id := OLD.composicion_id;
    ELSE
        v_composicion_id := NEW.composicion_id;
    END IF;

    SELECT COALESCE(SUM(porcentaje), 0) INTO v_suma
      FROM proyecto_composicion_lineas
     WHERE composicion_id = v_composicion_id;

    -- Una composición sin líneas es válida (planta sin propiedad registrada todavía).
    IF v_suma = 0 THEN
        RETURN NULL;
    END IF;

    IF v_suma <> 100 THEN
        RAISE EXCEPTION
            'La composicion % suma % por ciento y debe sumar 100. Revisa proyecto_composicion_lineas.',
            v_composicion_id, v_suma
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION fn_composicion_suma_100() IS 'Verifica al COMMIT que las líneas de una composición accionaria sumen exactamente 100 por ciento.';

CREATE CONSTRAINT TRIGGER tg_composicion_suma_100
    AFTER INSERT OR UPDATE OR DELETE ON proyecto_composicion_lineas
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION fn_composicion_suma_100();


-- =====================================================================================
-- BLOQUE 11 · Índices
-- Toda FK lleva índice. Se agregan los de los filtros y ordenamientos que ya existen hoy.
-- =====================================================================================

-- Catálogos y clientes
CREATE INDEX ix_contactos_cliente_id                ON contactos (cliente_id);
CREATE INDEX ix_clientes_deleted                    ON clientes (deleted_at) WHERE deleted_at IS NOT NULL;
CREATE INDEX ix_fallas_cat_tipos_categoria_id       ON fallas_cat_tipos (categoria_id);
CREATE INDEX ix_operadores_red_contactos_operador   ON operadores_red_contactos (operador_red_id);
CREATE INDEX ix_equipo_tipos_activo                 ON equipo_tipos (activo) WHERE activo;

-- Red
CREATE INDEX ix_red_circuitos_operador_red_id       ON red_circuitos (operador_red_id);
CREATE INDEX ix_red_puntos_conexion_circuito_id     ON red_puntos_conexion (circuito_id);

-- Proyecto
CREATE INDEX ix_proyectos_portafolio_id             ON proyectos (portafolio_id);
CREATE INDEX ix_proyectos_operador_red_id           ON proyectos (operador_red_id);
CREATE INDEX ix_proyectos_punto_conexion_id         ON proyectos (punto_conexion_id);
CREATE INDEX ix_proyectos_estado                    ON proyectos (estado);
CREATE INDEX ix_proyectos_etapa                     ON proyectos (etapa);
CREATE INDEX ix_proyectos_deleted                   ON proyectos (deleted_at) WHERE deleted_at IS NOT NULL;
CREATE INDEX ix_proyecto_id_externa_proyecto_id     ON proyecto_identificacion_externa (proyecto_id);
CREATE INDEX ix_proyecto_simulacion_proyecto_id     ON proyecto_simulacion (proyecto_id);
CREATE INDEX ix_proyecto_estado_hist_proyecto_id    ON proyecto_estado_historial (proyecto_id);
CREATE INDEX ix_proyecto_estado_hist_usuario_id     ON proyecto_estado_historial (usuario_id);
CREATE INDEX ix_proyecto_area_contacto_proyecto_id  ON proyecto_area_contacto (proyecto_id);
CREATE INDEX ix_proyecto_area_contacto_cliente_id   ON proyecto_area_contacto (cliente_id);

-- Equipos
CREATE INDEX ix_equipo_modelos_tipo_id              ON equipo_modelos (equipo_tipo_id);
CREATE INDEX ix_equipo_modelos_fabricante_id        ON equipo_modelos (fabricante_id);
CREATE INDEX ix_equipo_modelo_comp_padre_id         ON equipo_modelo_componentes (modelo_padre_id);
CREATE INDEX ix_equipo_modelo_comp_tipo_id          ON equipo_modelo_componentes (equipo_tipo_id);
CREATE INDEX ix_equipos_proyecto_id                 ON equipos (proyecto_id);
CREATE INDEX ix_equipos_equipo_tipo_id              ON equipos (equipo_tipo_id);
CREATE INDEX ix_equipos_equipo_modelo_id            ON equipos (equipo_modelo_id);
CREATE INDEX ix_equipos_parent_equipo_id            ON equipos (parent_equipo_id);
CREATE INDEX ix_equipos_reemplaza_a_equipo_id       ON equipos (reemplaza_a_equipo_id);
-- El inventario vigente es lo que se consulta el 99 % de las veces.
CREATE INDEX ix_equipos_vigentes                    ON equipos (proyecto_id, equipo_tipo_id) WHERE fecha_baja IS NULL;
-- «Qué equipos tienen la garantía por vencer»: este índice es la razón de D-04.
CREATE INDEX ix_equipos_garantia_vence              ON equipos (garantia_vence_el) WHERE fecha_baja IS NULL;
CREATE UNIQUE INDEX uq_equipos_serie                ON equipos (proyecto_id, numero_serie) WHERE numero_serie IS NOT NULL;
CREATE INDEX ix_equipo_mant_equipo_id               ON equipo_mantenimientos (equipo_id);
CREATE INDEX ix_equipo_mant_cliente_id              ON equipo_mantenimientos (ejecutado_por_cliente_id);
CREATE INDEX ix_equipo_mant_registrado_por_id       ON equipo_mantenimientos (registrado_por_id);
CREATE INDEX ix_equipo_mant_pendientes              ON equipo_mantenimientos (fecha_programada) WHERE estado IN ('programado', 'en_ejecucion');

-- Propiedad
CREATE INDEX ix_proyecto_composiciones_proyecto_id  ON proyecto_composiciones (proyecto_id);
CREATE INDEX ix_proyecto_composiciones_usuario_id   ON proyecto_composiciones (registrado_por_id);
-- «Dueños del proyecto X a fecha Y» en un solo predicado de rango.
CREATE INDEX ix_proyecto_composiciones_vigencia     ON proyecto_composiciones USING gist (vigencia);
CREATE INDEX ix_pcl_composicion_id                  ON proyecto_composicion_lineas (composicion_id);
CREATE INDEX ix_pcl_cliente_id                      ON proyecto_composicion_lineas (cliente_id);
CREATE INDEX ix_pcl_contrato_id                     ON proyecto_composicion_lineas (contrato_id);

-- Contratos
CREATE INDEX ix_contratos_tipo_estado               ON contratos (tipo, estado);
CREATE INDEX ix_contratos_deleted                   ON contratos (deleted_at) WHERE deleted_at IS NOT NULL;
CREATE INDEX ix_contrato_partes_contrato_id         ON contrato_partes (contrato_id);
CREATE INDEX ix_contrato_partes_cliente_id          ON contrato_partes (cliente_id);
CREATE INDEX ix_contrato_proyectos_proyecto_id      ON contrato_proyectos (proyecto_id);
CREATE INDEX ix_contrato_tarifas_contrato_id        ON contrato_tarifas (contrato_id);
CREATE INDEX ix_contrato_tarifas_registrado_por_id  ON contrato_tarifas (registrado_por_id);
-- «La tarifa de CGM de este contrato en junio de 2026» en un solo predicado.
CREATE INDEX ix_contrato_tarifas_vigencia           ON contrato_tarifas USING gist (vigencia);

-- Fallas
CREATE INDEX ix_fallas_estado_id                    ON fallas (estado_id);
CREATE INDEX ix_fallas_tipo_id                      ON fallas (tipo_id);
CREATE INDEX ix_fallas_prioridad_id                 ON fallas (prioridad_id);
CREATE INDEX ix_fallas_resolucion_id                ON fallas (resolucion_id);
CREATE INDEX ix_fallas_registrado_por_id            ON fallas (registrado_por_id);
CREATE INDEX ix_fallas_asignado_a_id                ON fallas (asignado_a_id);
CREATE INDEX ix_fallas_punto_conexion_id            ON fallas (punto_conexion_id);
CREATE INDEX ix_fallas_fecha_identificacion         ON fallas (fecha_identificacion DESC);
CREATE INDEX ix_fallas_abiertas                     ON fallas (estado_id, fecha_identificacion DESC) WHERE deleted_at IS NULL AND fecha_resolucion IS NULL;
CREATE INDEX ix_falla_proyectos_proyecto_id         ON falla_proyectos (proyecto_id);
CREATE INDEX ix_falla_equipos_equipo_id             ON falla_equipos (equipo_id);
CREATE INDEX ix_falla_estado_hist_falla_id          ON falla_estado_historial (falla_id);
CREATE INDEX ix_falla_estado_hist_anterior_id       ON falla_estado_historial (estado_anterior_id);
CREATE INDEX ix_falla_estado_hist_nuevo_id          ON falla_estado_historial (estado_nuevo_id);
CREATE INDEX ix_falla_estado_hist_usuario_id        ON falla_estado_historial (usuario_id);
CREATE INDEX ix_falla_adjuntos_falla_id             ON falla_adjuntos (falla_id);
CREATE INDEX ix_falla_adjuntos_subido_por_id        ON falla_adjuntos (subido_por_id);
CREATE INDEX ix_falla_impactos_falla_id             ON falla_impactos (falla_id);
CREATE INDEX ix_falla_impactos_proyecto_id          ON falla_impactos (proyecto_id);


-- =====================================================================================
-- BLOQUE 12 · Vistas
-- Todo lo derivado que NO se guarda como columna sale por acá.
-- =====================================================================================

-- Requisito del brief: «qué equipos tienen la garantía por vencer».
CREATE VIEW v_equipo_garantia_por_vencer AS
SELECT e.id AS equipo_id,
       e.proyecto_id,
       p.nombre_comercial,
       t.nombre AS tipo_equipo,
       e.nombre,
       e.numero_serie,
       e.garantia_vence_el,
       (e.garantia_vence_el - CURRENT_DATE) AS dias_para_vencer
  FROM equipos e
  JOIN proyectos   p ON p.id = e.proyecto_id
  JOIN equipo_tipos t ON t.id = e.equipo_tipo_id
 WHERE e.fecha_baja IS NULL
   AND e.garantia_vence_el IS NOT NULL;
COMMENT ON VIEW v_equipo_garantia_por_vencer IS 'Equipos vigentes con fecha de vencimiento de garantía y cuántos días faltan.';

-- Requisito del brief: «qué equipos tienen mantenimiento pendiente».
-- No puede ser columna generada: depende del último mantenimiento, que está en otra tabla.
CREATE VIEW v_equipo_mantenimiento_pendiente AS
SELECT e.id AS equipo_id,
       e.proyecto_id,
       t.nombre AS tipo_equipo,
       e.nombre,
       e.mantenimiento_intervalo_dias,
       ult.ultima_ejecucion,
       COALESCE(ult.ultima_ejecucion, e.fecha_puesta_servicio) + e.mantenimiento_intervalo_dias AS proximo_mantenimiento
  FROM equipos e
  JOIN equipo_tipos t ON t.id = e.equipo_tipo_id
  LEFT JOIN (
        SELECT equipo_id, MAX(fecha_ejecucion) AS ultima_ejecucion
          FROM equipo_mantenimientos
         WHERE estado = 'completado'
         GROUP BY equipo_id
  ) ult ON ult.equipo_id = e.id
 WHERE e.fecha_baja IS NULL
   AND e.mantenimiento_intervalo_dias IS NOT NULL;
COMMENT ON VIEW v_equipo_mantenimiento_pendiente IS 'Cuándo toca el próximo mantenimiento de cada equipo vigente, según su intervalo y el último ejecutado.';

-- «Días vigentes» de una falla: derivado, nunca columna.
CREATE VIEW v_falla_dias_vigentes AS
SELECT f.id AS falla_id,
       f.codigo_interno,
       f.fecha_identificacion,
       f.fecha_resolucion,
       COALESCE(f.fecha_resolucion::date, CURRENT_DATE) - f.fecha_identificacion AS dias_vigentes,
       (f.fecha_resolucion IS NULL) AS abierta
  FROM fallas f
 WHERE f.deleted_at IS NULL;
COMMENT ON VIEW v_falla_dias_vigentes IS 'Días que lleva abierta cada falla; sustituye la columna derivada.';

-- Propiedad vigente hoy, con la forma que espera el consumidor de inversionistas.
CREATE VIEW v_proyecto_propiedad_vigente AS
SELECT c.proyecto_id,
       l.cliente_id,
       cl.razon_social_nombre,
       l.porcentaje,
       l.es_patrimonio_autonomo,
       lower(c.vigencia) AS vigente_desde,
       upper(c.vigencia) AS vigente_hasta
  FROM proyecto_composiciones c
  JOIN proyecto_composicion_lineas l ON l.composicion_id = c.id
  JOIN clientes cl ON cl.id = l.cliente_id
 WHERE c.vigencia @> CURRENT_DATE;
COMMENT ON VIEW v_proyecto_propiedad_vigente IS 'Dueños actuales de cada planta y su porcentaje; para fechas pasadas se consulta la composición del periodo.';


-- =====================================================================================
-- BLOQUE 13 · Valores iniciales de los catálogos
-- Los 6 tipos base del brief. `es_base = TRUE` los distingue de los que cree el usuario.
-- =====================================================================================

INSERT INTO equipo_tipos (codigo, nombre, granularidad, admite_componentes, es_base, esquema_especificaciones) VALUES
('panel',        'Paneles',            'cantidad',   FALSE, TRUE,
 '{"type":"object","required":["referencia"],"properties":{"referencia":{"type":"string"},"potencia_wp":{"type":"number","minimum":0}}}'),
('inversor',     'Inversores',         'individual', FALSE, TRUE,
 '{"type":"object","properties":{"potencia_nominal_kw":{"type":"number","minimum":0},"tipo":{"enum":["string","central","microinversor","hibrido","otro"]}}}'),
('tracker',      'Tracker',            'cantidad',   FALSE, TRUE,
 '{"type":"object","properties":{"tipo":{"enum":["1P","2P"]}}}'),
('subestacion',  'Subestación',        'individual', TRUE,  TRUE,
 '{"type":"object","required":["tipo"],"properties":{"tipo":{"enum":["shelter","skid","mamposteria"]},"planos_url":{"type":"string"}}}'),
('camara',       'Sistema de cámaras', 'individual', FALSE, TRUE,
 '{"type":"object","properties":{"resolucion":{"type":"string"},"ubicacion":{"type":"string"}}}'),
('starlink',     'Starlink',           'individual', TRUE,  TRUE,
 '{"type":"object","properties":{"modelo":{"type":"string"},"numero_kit":{"type":"string"},"plan_datos_gb":{"type":"number"}}}'),
-- Componentes de los tipos compuestos: cada uno puede fallar por separado.
('antena',       'Antena',             'individual', FALSE, TRUE, '{"type":"object"}'),
('fuente',       'Fuente de poder',    'individual', FALSE, TRUE, '{"type":"object"}'),
('modem',        'Módem',              'individual', FALSE, TRUE, '{"type":"object"}'),
('cableado',     'Cableado',           'cantidad',   FALSE, TRUE, '{"type":"object"}'),
-- Equipos de medición y protección que hoy viven como columnas marca_* en proyecto_info_tecnica.
('medidor',      'Medidor',            'individual', FALSE, TRUE,
 '{"type":"object","properties":{"clase":{"type":"string"},"numero_elementos":{"type":"integer"}}}'),
('transformador','Transformador',      'individual', FALSE, TRUE, '{"type":"object"}'),
('reconectador', 'Reconectador / relé','individual', FALSE, TRUE, '{"type":"object"}');

INSERT INTO fallas_cat_estados (codigo, nombre, es_estado_final, orden) VALUES
('identificado', 'Identificado', FALSE, 1),
('programado',   'Programado',   FALSE, 2),
('resuelto',     'Resuelto',     TRUE,  3),
('cancelado',    'Cancelado',    TRUE,  4);


-- =====================================================================================
-- BLOQUE 14 · HUECO DECLARADO: frontera
--
-- La frontera NO está en este esquema. La decisión D-06 (cardinalidad proyecto↔frontera)
-- quedó pendiente de confirmación y no se implementa hasta entonces.
--
-- Cuando se confirme, entran acá tres piezas y ninguna antes:
--   fronteras                   -- registro de frontera comercial de la planta
--   frontera_codigo_historial   -- historial de códigos FRT/SIC, que cambian en el trámite
--   (y la FK correspondiente desde/hacia proyectos, según la cardinalidad que se decida)
--
-- Nada del resto del esquema depende de la frontera: ninguna tabla de arriba la referencia,
-- así que agregarla después no obliga a recrear nada.
-- =====================================================================================

-- FIN DEL ESQUEMA OBJETIVO DEL NÚCLEO
