# Unergy Database Atlas
> Full schema audit across 6 databases — 2026-05-19
> 511 tables · ~6.2M rows · ~49 GB

## Quick Reference

| # | Database | Host | PG | Size | Tables | Rows (est.) | Purpose |
|---|----------|------|----|------|--------|-------------|---------|
| 1 | **originabotdb** | 34.74.198.101:5432 | 17.2 | 30 GB | 269 | 3.4M | Django OriginaBot — legacy Klima/Unergy platform (projects, terrain, investments, contracts, validation) |
| 2 | **requestsdb** | 34.74.198.101:5432 | 17.2 | 17 GB | 101 | 2.5M | Django — supply requests, grid entities, transformers, PostGIS |
| 3 | **operations** | Railway (internal) | — | — | 62 | — | FastAPI — modern operations platform (proyectos, fallas, liquidaciones, PPA, monitoreo, clima) |
| 4 | **rag** | 54.174.147.51:5434 | 16.13 | 1 GB | 11 | 126K | LightRAG knowledge graph (pgvector 1536d + Neo4j) |
| 5 | **edubotapp** | 54.174.147.51:5434 | 16.13 | 42 MB | 7 | 86K | Discord message ingestion + chronological summaries |
| 6 | **samantha_memory** | 127.0.0.1:5433 | 17.9 | 441 MB | 61 | 50K | Eduardo's personal AI — memory, contracts, TRM, sensors, tasks |

### Server Map
```
┌─────────────────────────────────────────────────────────────┐
│  GCP 34.74.198.101:5432  (PG 17.2)                         │
│  ├── originabotdb  (30 GB, 269 tables) — Django OriginaBot │
│  └── requestsdb    (17 GB, 101 tables) — Django Requests   │
├─────────────────────────────────────────────────────────────┤
│  AWS 54.174.147.51:5434  (PG 16.13)                        │
│  ├── edubotapp  (42 MB, 7 tables) — Discord Edubot         │
│  └── rag        (1 GB, 11 tables) — LightRAG graph         │
├─────────────────────────────────────────────────────────────┤
│  Railway (internal)                                         │
│  └── operations (62 tables) — Modern ops backend            │
├─────────────────────────────────────────────────────────────┤
│  EVO-X2 127.0.0.1:5433  (PG 17.9)                         │
│  └── samantha_memory (441 MB, 61 tables) — Personal AI     │
└─────────────────────────────────────────────────────────────┘
```

---

## 1. originabotdb (30 GB · 269 tables · GCP)

The legacy Django platform (OriginaBot). Source of truth for Klima/Unergy project data, terrain management, investments, and contract templates. Extensions: `plpgsql`, `pg_trgm`, `unaccent`.

### Domain Modules

#### Core Business — Projects & Terrain
| Table | Rows | Key Columns | Notes |
|-------|------|-------------|-------|
| `minifarm_project` | 3,089 | id, name, code, stage, kw_capacity, municipality, department, grid_operator, ... (39 cols) | **Central entity.** Every solar project. FK to auth_user, territorial |
| `minifarm_projectprice` | 6,021 | project_id, date, price_type, value | Historical price records |
| `minifarm_projectstagechange` | 9,507 | project_id, old_stage, new_stage, date, user_id | Stage transition audit trail |
| `minifarm_viability` | 34,253 | project_id, terrain_id, ... | Grid viability assessments |
| `minifarm_paymentprojectconcept` | 3,446 | project_id, concept, amount | Payment tracking |
| `termsheet_terrain` | 6,332 | id, project, lat, lon, area_ha, owner, municipality, ... (54 cols) | Physical land parcels |
| `termsheet_landlord` | 2,423 | id, name, cedula, bank_info, ... (41 cols) | Landowners |
| `termsheet_terrainstatuschange` | 20,542 | terrain_id, old_status, new_status, date | Terrain audit trail |
| `termsheet_payment` | 3,221 | terrain_id, amount, date, concept, ... (37 cols) | Terrain payments to landlords |
| `termsheet_filesofterrain` | 29,769 | terrain_id, file_url, file_type | Terrain documents |
| `termsheet_termsheet` | 672 | id, terrain_id, investor_id, template | Lease term sheets |

#### Investments & Portfolios
| Table | Rows | Key Columns |
|-------|------|-------------|
| `investment_investment` | 78 | id, name, investor_type, target_kwh, ... (21 cols) |
| `investment_minifarm` | 3,089 | id, project, investor, ppa, ... (13 cols) — mirrors minifarm_project |
| `investment_portfolio` | 114 | id, name, investor_id |
| `investment_dataroomfolder` | 72,921 | id, project, folder_name, parent | Data room tree |
| `investment_dataroomfolder_fields` | 131,292 | folder_id, field_key, field_value | Data room metadata |
| `investment_ppa` | 0 | id, name, price, minifarms | (Deprecated — moved to operations) |

#### Contracts & Legal
| Table | Rows | Key Columns |
|-------|------|-------------|
| `contract_contract` | 30 | id, name, type, project_id, investor_id, template (12 cols) |
| `contract_clause` | 0 | id, title, body, order | Clause templates |
| `contract_variable` | 3,198 | id, clause_id, contract_id, key, value, description | Contract variables for template fill |
| `contract_docx` | 94 | id, name, file_url | Generated DOCX files |
| `contract_termsheetclause` | 0 | Deprecated |

#### Validation Engine (2.3M rows — heaviest module)
| Table | Rows | Key Columns |
|-------|------|-------------|
| `validation_field` | 1,148,326 | id, template_field_id, terrain_id, value, status, ... (24 cols) | Per-terrain validation field values |
| `validation_weightfield` | 1,164,770 | id, field_id, weight, criteria, score | Weighted scoring per field |
| `validation_templatefield` | 245 | id, category, name, type, required | Field definitions |
| `validation_subfield` | 4,025 | id, parent_field_id, name, value | Nested field values |

#### Prospecting & Sales
| Table | Rows | Key Columns |
|-------|------|-------------|
| `prospecting_contact` | 13,298 | id, name, phone, email, city, source | Lead contacts |
| `prospecting_contactnote` | 1,398 | contact_id, note, date, user_id | Follow-up notes |
| `prospecting_prospecting` | 0 | id, contact_id, stage, project_id | Sales pipeline (unused?) |

#### Easements
| Table | Rows | Key Columns |
|-------|------|-------------|
| `easements_easement` | 190 | id, project_id, area, status, type, ... (13 cols) |
| `easements_easementviability` | 950 | easement_id, viable, criteria |
| `easements_easementlandlord` | 35 | easement_id, landlord_id |

#### EPC (Engineering, Procurement, Construction)
| Table | Rows | Key Columns |
|-------|------|-------------|
| `epc_epcfolder` | 2,717 | id, project_id, epc_id, name, parent | EPC document tree |
| `epc_projectepc` | 526 | project_id, epc_id | Project ↔ EPC assignment |

#### WhatsApp Bot
| Table | Rows | Key Columns |
|-------|------|-------------|
| `whatsapp_bot_whatsappmessage` | 14,172 | id, phone, content, direction, timestamp | WhatsApp messages |
| `whatsapp_bot_whatsappdocument` | 18 | id, message_id, file_url | Attachments |

#### Audit & Infrastructure
| Table | Rows | Notes |
|-------|------|-------|
| `django_tracker_auditlog` | 584,938 | **Second-heaviest.** Model change tracking |
| `django_admin_log` | 16,828 | Django admin actions |
| `auth_user` | 262 | Platform users (Django auth) |
| `genai_apikeyuse` | 17,608 | AI API usage tracking |
| `logging_manager_log` | 3,973 | Application logs |

#### Empty Modules (0 rows in all tables)
`cities_light` (4), `dataroom` (10), `silk` (5), `easyaudit` (3), `timeline` (7), `legal_validation` (2), `engineering` (2), `government` (4 — 1 row total)

---

## 2. requestsdb (17 GB · 101 tables · GCP)

Django + Celery + PostGIS. Manages supply chain requests, grid entity mapping, and transformer management.

### Domain Modules

#### Supply Requests (core)
| Table | Rows | Key Columns |
|-------|------|-------------|
| `supplies_supplyrequest` | 18,416 | id, project, requester, status, ... (38 cols) | Main request entity |
| `supplies_statussupplyrequest` | 47,985 | request_id, status, date, user | Status change history |
| `supplies_supplyrequestattachment` | 20,852 | request_id, file_url, name | Request documents |
| `supplies_companysupplyrequest` | 549 | request_id, company_id | Company assignments |
| `supplies_company` | 216 | id, name, nit, type | Supplier companies |

#### Grid Entities & Coexistence
| Table | Rows | Key Columns |
|-------|------|-------------|
| `entities_request` | 3,540 | id, entity_id, type, status | Grid operator requests |
| `entities_file` | 6,153 | request_id, file_url | Request attachments |
| `entities_coexistence` | 505 | id, project, grid_operator, status (12 cols) | Coexistence agreements |
| `entities_operator` | 84 | id, name, code, region | Grid operators |

#### Grid Infrastructure (PostGIS)
| Table | Rows | Key Columns |
|-------|------|-------------|
| `management_transformer` | 2,603 | id, code, kva, geom, circuit_id, ... (35 cols) | Transformers with GIS |
| `management_circuit` | 1,153 | id, code, operator_id, voltage | Electrical circuits |
| `capacity_capacity` | 27 | id, transformer_id, available_kw | Available capacity |

#### Audit
| Table | Rows | Notes |
|-------|------|-------|
| `django_tracker_auditlog` | 2,438,465 | **Heaviest table.** ~80% of DB size. |

#### Dead Weight
- `tiger.*` (34 tables, 0 rows) — PostGIS geocoder, never populated
- `topology.*` (2 tables, 0 rows) — PostGIS topology, never used
- `silk_*` (5 tables, 0 rows) — Django Silk profiler, unused
- `spatial_ref_sys` (0 rows) — PostGIS reference, empty

---

## 3. operations (62 tables · Railway)

Modern FastAPI backend. The operational hub for day-to-day Unergy work: project management, falla tracking, liquidaciones, PPA contracts, energy monitoring.

### Core Entities

#### Projects (46 cols — richest entity)
```
proyectos:
  id, cliente_id→clientes, portafolio_id→portafolios, proyecto_padre_id→proyectos,
  nombre_comercial, nombre_bitacora, nombre_clientes, topic_slug,
  clasificacion_regulatoria (AGP/AGPE/AGGE/GD/DER),
  tipo_proyecto (minigranja/autoconsumo/gd/movilidad_electrica/otro),
  estado (en_desarrollo/en_operacion/suspendido/cancelado),
  tipo_tecnologia (solar/eolica/hidraulica/biomasa/otra),
  potencia_instalada_kwp, potencia_contratada_kw,
  departamento, municipio, latitud, longitud,
  codigo_sic, codigo_despacho_xm, nodo_xm,
  origina_code,              ← FK to originabotdb (text, not integer)
  requestsdb_supply_id,      ← FK to requestsdb (text)
  quoia_node_name,           ← FK to Quoia monitoring platform
  created_at, updated_at
  ... (+22 more cols)
```

#### Clients & Investors
| Table | Cols | Key Fields |
|-------|------|------------|
| `clientes` | 19 | razon_social, nit_cedula, tipo_persona, correo_*, direccion |
| `proyecto_inversionistas` | 10 | proyecto_id, cliente_id, porcentaje_participacion, es_patrimonio_autonomo |
| `portafolios` | 6 | nombre, descripcion, activo |

#### Fronteras (Metering Points — 88 cols!)
```
fronteras:
  id, proyecto_id→proyectos, frontera_gemela_id→fronteras,
  agrupada_bajo_id→fronteras, embebida_bajo_id→fronteras,
  codigo_frontera, nombre_frontera, codigo_propio,
  tipo_frontera (generacion/consumo/generacion_consumo/consumo_auxiliar/consumo_propio),
  tipo_medida, punto_conexion, nivel_tension_kv,
  estado_registro_xm, fecha_registro_xm,
  ... (80+ cols covering meter details, connection points, billing)
```

#### PPA Contracts
| Table | Cols | Key Fields |
|-------|------|------------|
| `ppa_contratos` | 29 | numero_codigo, comprador_id→clientes, vendedor_id→clientes, fecha_inicio, fecha_fin, energia_minima_anual, tarifa_base, formula_indexacion |
| `ppa_tarifas` | 5 | contrato_id, año, mes, tarifa |
| `ppa_compromisos_energia` | 7 | contrato_id, año, mes, energia_minima, energia_maxima |
| `ppa_contrato_proyectos` | 2 | contrato_id, proyecto_id (M2M) |

#### Fallas (Failure Tracking)
| Table | Cols | Key Fields |
|-------|------|------------|
| `fallas` | 22 | codigo_interno, proyecto_id, tipo_id→fallas_cat_tipos, estado_id→fallas_cat_estados, prioridad_id→fallas_cat_prioridades, resolucion_id, descripcion, fecha_reporte, fecha_resolucion |
| `fallas_cat_tipos` | 6 | categoria_id→fallas_cat_categorias, codigo, etiqueta |
| `fallas_cat_estados` | 6 | codigo, etiqueta, es_estado_final |
| `fallas_cat_prioridades` | 5 | codigo, etiqueta, nivel |
| `fallas_seguimientos` | 6 | falla_id, usuario_id, nota, estado_nuevo_id |

#### Liquidaciones (Settlement)
| Table | Cols | Key Fields |
|-------|------|------------|
| `liquidaciones` | 21 | proyecto_id, periodo, tipo_venta, estado, energia_total_kwh, valor_bruto_cop |
| `liquidacion_xm_datos` | 10 | frontera_id, energia_kwh, tarifa, valor_bruto |
| `liquidacion_mandatos` | 24 | inversionista_id, tipo, beneficiario, valor_bruto |
| `liquidacion_costos` | 10 | tipo_costo, proveedor, valor_cop |
| `liquidacion_facturas` | 12 | tipo_servicio, numero_factura, valor_cop |

#### Energy Market & Climate
| Table | Cols | Key Fields |
|-------|------|------------|
| `precios_bolsa_diario` | 15 | fecha, precio_promedio/min/max, demanda_gwh, hidro_pct, termica_pct |
| `precios_bolsa_horario` | 10 | fecha, hora, precio_cop_kwh, gen by type |
| `clima_oni_monthly` | 9 | year, month, oni_value, soi_value, enso_phase |
| `clima_precip_monthly` | 8 | year, month, region, precip_mm, anomaly_pct |
| `clima_price_monthly` | 7 | year, month, price_cop_kwh, enso_phase |
| `clima_forecasts` | 5 | forecast_date, forecast_json, model_version |

#### Other Modules
| Table | Cols | Purpose |
|-------|------|---------|
| `contratos_servicio` | 29 | Service contracts (O&M, CGM, representation) |
| `contratos_arriendo` | 10 | Land lease contracts |
| `garantias` | 15 | Financial guarantees (XM compliance) |
| `generacion_diaria` | 10 | Daily generation records per project |
| `documentos` | 13 | Generic document store (entity_type polymorphic) |
| `mantenimientos` | 10 | Maintenance records |
| `servicio_operacion` | 16 | O&M service agreements |
| `servicio_representacion` | 10 | Market representation service |
| `servicio_cgm` | 9 | CGM (metering) service |
| `operacion_kpis` | 12 | Performance KPIs per project |
| `alarmas_monitoreo` | 8 | MGS alarm events |
| `rec_procesos` | 19 | Renewable Energy Certificate processes |
| `rec_certificados` | 12 | Issued REC certificates |
| `promotor_seguimientos` | 12 | Regulatory milestone tracking |
| `asic_solicitudes` | 23 | ASIC (XM market) requests |
| `informes_guardados` | 21 | Generated report snapshots |
| `reglas_contables` | 13 | Accounting rules engine |
| `usuarios` | 9 | Platform users (email, rol, password_hash) |

---

## 4. rag (1 GB · 11 tables · AWS)

LightRAG knowledge graph. Stores extracted entities, relations, and vector embeddings from Discord conversations. Used by Edubot for RAG queries. Gemini 2.5 Flash for extraction, `gemini-embedding-001` (1536d) for embeddings.

| Table | Key Columns |
|-------|-------------|
| `lightrag_doc_full` | workspace, id, title, content, metadata (JSONB) |
| `lightrag_doc_chunks` | workspace, id, doc_id, chunk_index, tokens, content, metadata |
| `lightrag_doc_status` | workspace, id, content_summary, content_length, chunks_count, status |
| `lightrag_full_entities` | workspace, id, entity_name, content, metadata |
| `lightrag_full_relations` | workspace, id, src_id, tgt_id, content, metadata |
| `lightrag_entity_chunks` | workspace, id, entity_name, chunk_id, content |
| `lightrag_relation_chunks` | workspace, id, relation_id, chunk_id, content |
| `lightrag_vdb_entity_gemini_*_1536d` | workspace, id, entity_name, content, embedding (vector 1536) |
| `lightrag_vdb_relation_gemini_*_1536d` | workspace, id, relation_id, content, embedding (vector 1536) |
| `lightrag_vdb_chunks_gemini_*_1536d` | workspace, id, chunk_id, content, embedding (vector 1536) |
| `lightrag_llm_cache` | workspace, id, mode, input_hash, output, model, tokens_used |

All tables use composite PK `(workspace, id)` — supports multi-tenant isolation.

---

## 5. edubotapp (42 MB · 7 tables · AWS)

Discord message ingestion pipeline. Captures raw messages, generates chronological summaries, feeds them into LightRAG.

| Table | Rows | Key Columns |
|-------|------|-------------|
| `discord_servers` | 7 | id (Discord snowflake), name |
| `discord_channels` | 1,137 | id, guild_id→servers, name, channel_type, parent_channel_id |
| `discord_users` | 332 | id, guild_id→servers, is_bot, global_name, display_name |
| `discord_messages` | 82,481 | id, guild_id→servers, channel_id→channels, user_id, content, reply_to, attachments (JSON), attachments_explanation |
| `discord_message_extraction_log` | 162 | channel_id→channels, messages_extracted, extracted_at |
| `channel_chronological_summary` | 852 | channel_id→channels, start_time, end_time, number_messages, summary (TEXT), summary_embedding (vector 3072), key_words (JSON), status (enum: in_lightrag/ready) |
| `lightrag_docs` | 851 | summary_id→summaries, doc_id (varchar), is_in_lightrag (boolean) |

**Data Flow**: discord_messages → channel_chronological_summary (LLM summarizes) → lightrag_docs → LightRAG rag DB

---

## 6. samantha_memory (441 MB · 61 tables · EVO-X2)

Eduardo's personal AI intelligence. Memory, contracts analysis, TRM forecasting, sensor data, task management. Extensions: `pg_cron`, `pg_trgm`, `uuid-ossp`, `vector`.

### Core Memory
| Table | Rows | Key Columns |
|-------|------|-------------|
| `memories` | 6,137 | id, content, category, importance (1-3), trust_level, source, embedding (vector 1024), created_at |
| `episodes` | 2,131 | id, session_id, summary, score, consolidated, age_class (0-3), embedding |
| `raw_interactions` | 28,258 | id, session_id, speaker, role, content, channel (mobile/voice/whatsapp/telegram), direction (in/out), ts, classification, importance, embedding |
| `knowledge` | 255 | id, title, content, source, category, embedding | Business knowledge base |
| `knowledge_gaps` | 0 | id, question, best_similarity, resolved | Unanswered questions |

### People & Social
| Table | Rows | Key Columns |
|-------|------|-------------|
| `people` | 27 | id, name, role, trust_level, organization, embedding |
| `person_facts` | 57 | person_id→people, fact, category, source, confidence, embedding |
| `eduardo_profile` | 7 | id, dimension, content, embedding | Self-model |

### Contracts Intelligence
| Table | Rows | Key Columns |
|-------|------|-------------|
| `contracts` | 15 | id, title, counterparty, contract_type, status, risk_score, updated_at |
| `contract_clauses` | 427 | contract_id, clause_type (42-type taxonomy), original_text, our_version, risk_level, outcome |
| `contract_patterns` | 42 | clause_type, pattern_text, frequency, embedding | Learned negotiation patterns |

### TRM (USD/COP) Forecasting
| Table | Rows | Key Columns |
|-------|------|-------------|
| `trm_macro_daily` | 1,919 | date, trm, dxy, vix, sp500, wti, brent, usd_brl, eur_usd, us_10y, banrep_rate, fed_funds, yield_curve, log-returns |
| `trm_forecasts` | 180 | date, horizons (JSONB), macro_drivers, model_version |
| `trm_snapshots` | 1 | date, session_type, trm_open, trm_close, high, low, analysis |
| `trm_alerts` | 0 | date, alert_type, message, trm_value |

### Tasks & Ideas
| Table | Rows | Key Columns |
|-------|------|-------------|
| `tasks` | 68 | id, title, status, priority (1-4), due_date, notes, tags, embedding |
| `ideas` | 94 | id, title, status (raw/developing/parked/done), importance (1-5), notes, embedding |

### Sensors & IoT
| Table | Rows | Key Columns |
|-------|------|-------------|
| `sensor_readings` | 4,428 | entity_id, ts, value, unit | UNIQUE(entity_id, ts) |
| `daily_physiology` | 0 | date, sleep_*, spo2, hr_*, co2_*, predicted_perf | (Pending HA deploy) |
| `radar_windows` | 0 | zone, ts, targets (JSONB) | (Pending sensor deploy) |
| `appliance_events` | 0 | ts, event_type, watt_delta, appliance_guess | (Pending NILM) |

### Other
| Table | Rows | Purpose |
|-------|------|---------|
| `agent_sessions` | 52 | Agent conversation memory (4h TTL) |
| `audit_log` | 1,833 | Security audit trail |
| `self_eval_log` | 0 | Nightly self-evaluation |
| `deep_work_queue` | 2 | Background AI task queue |
| `daemon_work_log` | 47 | Completed background work |
| `meetings` | 0 | Meeting notes + action items |
| `english_sessions` | 0 | English practice sessions |
| `voice_profiles` | 0 | Speaker recognition embeddings |
| `guest_sessions` | 0 | Visitor interaction tracking |
| `remarkable_pages` | 0 | reMarkable tablet sync |
| `sentinel_runs` | 0 | Sentinel test harness tracking |
| `schema_migrations` | 34 | Migration tracking |

---

## Cross-Database Entity Map

### The Project Entity (most important)

```
originabotdb.minifarm_project     requestsdb.supplies_supplyrequest
         │ (id=integer)                    │ (project refs)
         │                                 │
         └──── origina_code ──────┐        │
                                  ▼        ▼
              operations.proyectos ◄── requestsdb_supply_id
                   │ (id=bigint)
                   │
                   ├── quoia_node_name ──► Quoia monitoring platform
                   │
                   └── nombre_comercial ─► edubotapp.discord_messages.content
                                           (name mentioned in Discord, no FK)
                                          ► samantha.ideas.title
                                           (referenced by name, no FK)
```

**Link fields in `operations.proyectos`:**
- `origina_code VARCHAR` → matches `originabotdb.minifarm_project.code`
- `requestsdb_supply_id VARCHAR` → matches `requestsdb.supplies_supplyrequest.id`
- `quoia_node_name VARCHAR` → Quoia API node identifier

### Entity Correlation Matrix

| Entity | originabotdb | requestsdb | operations | edubotapp | rag | samantha |
|--------|-------------|------------|------------|-----------|-----|----------|
| **Project** | `minifarm_project` (3,089) | via supply requests | `proyectos` (SoT) | mentioned in messages | in knowledge graph | `ideas`, `tasks` |
| **Terrain/Land** | `termsheet_terrain` (6,332) | — | `contratos_arriendo` | — | — | — |
| **Contract/PPA** | `contract_contract` (30) | — | `ppa_contratos`, `contratos_servicio` | — | — | `contracts` (15, AI-analyzed) |
| **Client/Company** | — | `supplies_company` (216) | `clientes` (SoT) | — | — | — |
| **Investor** | `investment_investment` (78) | — | `proyecto_inversionistas` | — | — | — |
| **User/Person** | `auth_user` (262) | `auth_user` (13) | `usuarios` | `discord_users` (332) | — | `people` (27) |
| **Landlord** | `termsheet_landlord` (2,423) | — | — | — | — | — |
| **Contact** | `prospecting_contact` (13,298) | `entities_operatorcontact` (29) | `proyecto_contactos` | — | — | `person_facts` |
| **Grid Operator** | `grid_operator_request_gridoperator` | `entities_operator` (84) | via `fronteras` | — | — | — |
| **Transformer** | — | `management_transformer` (2,603) | — | — | — | — |
| **Metering Point** | — | — | `fronteras` (88 cols!) | — | — | — |
| **Falla/Alarm** | `monitoring_*` (8 tables) | — | `fallas` (22 cols) | — | — | — |
| **Energy Price** | — | — | `precios_bolsa_*` | — | — | `trm_macro_daily` (market data) |
| **Document** | `dataroom_*`, `epc_*` | `entities_file`, `supplies_*attachment` | `documentos` | — | — | `knowledge`, `remarkable_pages` |
| **Audit Log** | `django_tracker_auditlog` (585K) | `django_tracker_auditlog` (2.4M) | (none!) | — | — | `audit_log` (1.8K) |
| **WhatsApp** | `whatsapp_bot_*` (14K) | — | — | — | — | `raw_interactions` channel=whatsapp |
| **Discord** | — | — | — | `discord_messages` (82K) | knowledge graph | — |

### Data Flow Diagram
```
                    ┌──────────────┐
                    │  Discord     │
                    │  (Messages)  │
                    └──────┬───────┘
                           │ DiscordEchoSaver
                           ▼
                    ┌──────────────┐     LLM summarize     ┌─────────────┐
                    │  edubotapp   │ ──────────────────────►│    rag      │
                    │  (82K msgs)  │  chronological_summary │ (LightRAG)  │
                    └──────────────┘                        └──────┬──────┘
                                                                   │ query_lightrag
                                                                   ▼
┌──────────────────┐                                        ┌─────────────┐
│  originabotdb    │──── origina_code ─────────────────────►│  operations │
│  (legacy SoT)    │                                        │  (modern)   │
│  3,089 projects  │◄── Django admin writes here            │  62 tables  │
└──────────────────┘                                        └──────┬──────┘
                                                                   │ API
┌──────────────────┐                                               ▼
│  requestsdb      │──── requestsdb_supply_id ─────────────► operations
│  (supply chain)  │                                        ┌─────────────┐
│  18K requests    │                                        │  Frontend   │
└──────────────────┘                                        │  (Vue 3)   │
                                                            └─────────────┘
┌──────────────────┐
│  samantha_memory  │ ◄── Eduardo's AI reads from operations,
│  (personal AI)   │      Discord, WhatsApp, Gmail, Calendar
│  61 tables       │ ──── contract analysis, TRM forecasts
└──────────────────┘
```

---

## Critical Findings & Improvements

### 🔴 Critical Issues

**1. Audit log explosion (3M rows, ~75% of requestsdb + originabotdb size)**
- `requestsdb.django_tracker_auditlog`: 2,438,465 rows
- `originabotdb.django_tracker_auditlog`: 584,938 rows
- These are likely the main drivers of the 47 GB total.
- **Action**: Add pg_cron retention (DELETE WHERE timestamp < NOW() - INTERVAL '1 year'), or archive to cold storage. Consider switching to append-only event sourcing for the new operations platform.

**2. Operations DB has NO audit logging**
- `operations` has no `audit_log` or change-tracking table.
- If someone updates a proyecto or deletes a falla, the change is invisible.
- **Action**: Add an `audit_log` table (like samantha_memory has) or use PostgreSQL logical replication for CDC.

**3. Cross-DB references are string-based, not enforced**
- `proyectos.origina_code` is VARCHAR, not a foreign key.
- `proyectos.requestsdb_supply_id` is VARCHAR, not a foreign key.
- Data can silently desync if a project is deleted in originabotdb.
- **Action**: Build a reconciliation cron that checks cross-DB consistency weekly. Consider a project_registry microservice.

**4. requestsdb tiger schema is dead weight (34 empty tables)**
- PostGIS Tiger geocoder was installed but never populated.
- **Action**: `DROP SCHEMA tiger CASCADE; DROP SCHEMA topology CASCADE;` — saves complexity and backup size.

**5. edubotapp/rag statistics are stale**
- `pg_stat_user_tables.n_live_tup` shows 0 for all tables, but actual data exists (82K messages).
- **Action**: Run `ANALYZE` on both databases. Set `autovacuum = on` if not already.

### 🟡 Architecture Improvements

**6. Embedding space fragmentation**
| Database | Model | Dimensions |
|----------|-------|-----------|
| edubotapp | Google (unknown) | 3072 |
| rag | gemini-embedding-001 | 1536 |
| samantha | mxbai-embed-large | 1024 |
| operations | (none) | — |

Three incompatible vector spaces. Cross-database semantic search is impossible.
- **Action**: Standardize on Gemini embeddings (1536d) for Unergy business data, keep mxbai (1024d) for personal. Or use a reranker that works across spaces.

**7. `fronteras` table has 88 columns**
- The widest table in the entire ecosystem. Classic "god table" anti-pattern.
- **Action**: Decompose into `fronteras` (core: id, proyecto_id, codigo, tipo) + `fronteras_xm` (XM registration fields) + `fronteras_medicion` (meter details) + `fronteras_facturacion` (billing).

**8. `validation_field` + `validation_weightfield` = 2.3M rows**
- These are the heaviest tables in originabotdb after audit logs.
- Each of the 6,332 terrains has ~181 validation fields × ~184 weight scores.
- **Action**: Review if all terrains need all 245 template fields. Sparse storage (JSONB per terrain) would be 10x smaller.

**9. investment_minifarm mirrors minifarm_project**
- Same 3,089 rows. `investment_minifarm` adds investor/PPA fields to the same projects.
- **Action**: These should be FK relationships, not duplicated entities. The investment layer should JOIN to minifarm_project, not copy it.

**10. originabotdb → operations migration is incomplete**
- Operations has modernized schemas (enums, proper types) but only covers a subset of originabotdb's 269 tables.
- Not covered in operations: terrain, landlords, validation, prospecting, EPC, investments, dataroom.
- **Action**: Define migration roadmap — which originabotdb modules move to operations, which stay.

### 🟢 Quick Wins

**11. Add indexes on operations.proyectos**
```sql
CREATE INDEX idx_proyectos_estado ON proyectos(estado);
CREATE INDEX idx_proyectos_cliente ON proyectos(cliente_id);
CREATE INDEX idx_proyectos_origina ON proyectos(origina_code) WHERE origina_code IS NOT NULL;
CREATE INDEX idx_fallas_estado ON fallas(estado_id, proyecto_id);
```

**12. Add soft delete to operations**
```sql
ALTER TABLE proyectos ADD COLUMN deleted_at TIMESTAMPTZ;
ALTER TABLE clientes ADD COLUMN deleted_at TIMESTAMPTZ;
ALTER TABLE ppa_contratos ADD COLUMN deleted_at TIMESTAMPTZ;
```

**13. VACUUM FULL on requestsdb**
The 2.4M audit log rows likely have significant bloat from updates. `VACUUM FULL django_tracker_auditlog` could reclaim significant space (estimate: 5-8 GB).

**14. Unify user identity**
Four separate user tables with no cross-reference:
- originabotdb: `auth_user` (262, Django)
- requestsdb: `auth_user` (13, Django)
- operations: `usuarios` (FastAPI)
- edubotapp: `discord_users` (332, Discord snowflakes)

**Action**: Create a `user_directory` mapping table in operations:
```sql
CREATE TABLE user_directory (
    id BIGSERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    origina_user_id INTEGER,      -- → originabotdb.auth_user.id
    requests_user_id INTEGER,     -- → requestsdb.auth_user.id
    operations_user_id BIGINT,    -- → operations.usuarios.id
    discord_user_id BIGINT,       -- → edubotapp.discord_users.id
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**15. Consolidate WhatsApp data**
WhatsApp messages exist in two places:
- `originabotdb.whatsapp_bot_whatsappmessage` (14,172 rows)
- `samantha.raw_interactions` WHERE channel='whatsapp'

No dedup or cross-reference between them.

---

## Appendix: Recommended Data Mesh Architecture

```
┌─────────────────────────────────────────────────────┐
│                 Unergy Data Mesh                     │
│                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────┐ │
│  │ Project      │  │ Energy       │  │ People     │ │
│  │ Domain       │  │ Domain       │  │ Domain     │ │
│  │              │  │              │  │            │ │
│  │ SoT:         │  │ SoT:         │  │ SoT:       │ │
│  │ operations   │  │ energy-api   │  │ operations │ │
│  │ .proyectos   │  │ + operations │  │ .clientes  │ │
│  │              │  │ .precios_*   │  │ .usuarios  │ │
│  │ Reads from:  │  │              │  │            │ │
│  │ originabotdb │  │ Reads from:  │  │ Reads:     │ │
│  │ requestsdb   │  │ XM FTPS/REST │  │ originabot │ │
│  │ Discord      │  │ Open-Meteo   │  │ Discord    │ │
│  └──────────────┘  └──────────────┘  └────────────┘ │
│                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────┐ │
│  │ Intelligence │  │ Compliance   │  │ Documents  │ │
│  │ Domain       │  │ Domain       │  │ Domain     │ │
│  │              │  │              │  │            │ │
│  │ SoT:         │  │ SoT:         │  │ SoT:       │ │
│  │ samantha_mem │  │ requestsdb   │  │ originabot │ │
│  │ + rag        │  │ + originabot │  │ .dataroom  │ │
│  │              │  │ .validation  │  │ .epc_*     │ │
│  │ Feeds:       │  │              │  │ operations │ │
│  │ TRM, ENSO    │  │ Feeds:       │  │ .documentos│ │
│  │ contracts AI │  │ grid reqs    │  │            │ │
│  │ Edubot RAG   │  │ coexistence  │  │            │ │
│  └──────────────┘  └──────────────┘  └────────────┘ │
└─────────────────────────────────────────────────────┘
```

### Source of Truth (SoT) by Entity

| Entity | Current SoT | Recommended SoT | Migration Path |
|--------|-------------|-----------------|----------------|
| Projects | originabotdb (legacy) | operations.proyectos | Sync via origina_code, deprecate writes to originabotdb |
| Terrain | originabotdb only | Keep in originabotdb until operations terrain module built |
| Contracts/PPA | Split (originabot templates + operations active) | operations.ppa_contratos | Template engine can stay in originabotdb |
| Clients | operations | operations.clientes | Already correct |
| Supply Requests | requestsdb | Keep — specialized workflow | Link via requestsdb_supply_id |
| Grid Infrastructure | requestsdb | Keep — PostGIS specialized | Expose via API |
| Energy Prices | energy-api cache + operations | operations tables (durable) | energy-api writes → operations |
| Discord Knowledge | edubotapp → rag | Keep pipeline | Add operations project tagging |
| Personal Intelligence | samantha_memory | Keep isolated | Read-only access to operations |

---

*Generated 2026-05-19 by deep audit of all 6 PostgreSQL databases.*
*Raw data: `data/db_audit_raw.json` (2.2 MB) + `data/db_audit_operations.json` (122 KB)*
