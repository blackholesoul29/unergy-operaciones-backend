# RequestsDB Schema Discovery

**Database:** `requestsdb` on `34.24.192.147:5432`  
**Framework:** Django + Celery + PostGIS  
**Total tables:** 67 (21 domain, 18 Django/auth/admin, 10 Silk profiler, 8 Celery, 5 audit, 5 PostGIS system)  
**Date discovered:** 2026-05-18 (refreshed)

---

## Purpose

RequestsDB manages **Unergy's electrical grid connection requests** (solicitudes de conexion AGPE) filed with Colombian grid operators (Operadores de Red - OR). It tracks the full lifecycle: filing supply requests with ORs via web automation (Selenium), tracking ECS (Estudio de Conexion Simplificado) approval status, checking circuit/transformer capacity, and managing coexistence letters (consultas de coexistencia) with mining/oil companies and government entities.

---

## Row Counts Summary

| Table | Rows | Description |
|-------|------|-------------|
| `supplies_supplyrequest` | **17,987** | Grid connection requests (main table) |
| `supplies_statussupplyrequest` | **47,960** | Status history for each supply request |
| `supplies_supplyrequestattachment` | **20,818** | File attachments (sketches, IDs, CTLs) |
| `supplies_optionstatussupplyrequest` | **14** | Status workflow options |
| `supplies_company` | **216** | Companies filing requests |
| `supplies_companysupplyrequest` | **549** | Company contact info per request |
| `supplies_errorsupplyrequest` | **530** | Automation errors (Selenium failures) |
| `supplies_credentialscompany` | **3** | OR portal credentials (CENS, ESSA, Enel) |
| `management_transformer` | **81,826** | Distribution transformers with capacity data |
| `management_circuit` | **1,152** | Electrical circuits (feeders) |
| `management_substation` | **288** | Substations |
| `management_substation_circuits` | **231** | Substation-to-circuit M2M |
| `management_gridoperator` | **23** | Grid operators (Afinia, Air-e, EPM, etc.) |
| `management_multilinegeometry` | **617** | Circuit line geometries |
| `management_multipointgeometry` | **220** | Circuit point geometries |
| `entities_request` | **3,539** | Requests to government entities |
| `entities_requestresponse` | **1,875** | Responses from government entities |
| `entities_entity` | **14** | Government entities (ANLA, ANH, PNNC, etc.) |
| `entities_operator` | **84** | Mining/oil operators for coexistence checks |
| `entities_operatorcontact` | **38** | Operator contact info |
| `entities_coexistence` | **505** | Coexistence verifications |
| `entities_file` | **6,153** | Files attached to entity requests |
| `capacity_capacity` | **27** | Circuit capacity analysis results |
| `territorial_region` | **33** | Colombian departments |
| `territorial_city` | **1,121** | Colombian municipalities |
| `auth_user` | **13** | System users |

---

## Domain Model Overview

```
OriginabotDB.projects.id  <-->  supplies_supplyrequest.project (INTEGER)
                                entities_request.project_id (VARCHAR)
                                entities_coexistence.project_id (VARCHAR)

supplies_supplyrequest
  |-- company_id --> supplies_companysupplyrequest --> supplies_company
  |-- grid_operator_id --> management_gridoperator
  |-- transformer_id --> management_transformer
  |      |-- circuit_id --> management_circuit
  |      |                    |-- management_substation_circuits --> management_substation
  |      |                    |-- management_multilinegeometry (circuit path geometry)
  |      |                    |-- management_multipointgeometry (circuit point geometry)
  |      |-- grid_operator_id --> management_gridoperator
  |-- city_id --> territorial_city --> territorial_region --> territorial_country
  |-- supplies_statussupplyrequest (status history, M2O)
  |-- supplies_supplyrequestattachment (file attachments, M2O)
  |-- supplies_errorsupplyrequest (automation errors, M2O)
  |-- capacity_capacity (circuit capacity analysis)

entities_request
  |-- entity_id --> entities_entity (ANLA, ANH, PNNC, etc.)
  |-- entities_requestresponse_requests --> entities_requestresponse
  |-- entities_file (attached files)

entities_coexistence
  |-- operator_id --> entities_operator (mining/oil company)
  |-- entity_id --> entities_entity
```

---

## Core Tables: Supply Requests

### `supplies_supplyrequest` (17,987 rows)

The main table. Each row = one grid connection request (solicitud de punto de conexion) filed with a grid operator.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | bigint | NO | PK |
| `created` | timestamptz | NO | Record creation time |
| `modified` | timestamptz | NO | Last modification |
| `external_code` | varchar(255) | YES | OR-assigned code (e.g., `CEGD26000185`) |
| `tension_level` | varchar(10) | YES | Voltage level: `13.8`, `34.5` kV |
| `customer_name` | varchar(255) | YES | Usually "Unergy Energia Digital S.A.S. E.S.P." |
| `customer_email` | varchar(254) | YES | Usually `minigranjas@unergy.io` |
| `updated_by_agent` | boolean | NO | Whether updated by automation bot |
| `geometry` | geography(Point) | NO | GPS coordinates of connection point |
| `project` | integer | YES | **FK to OriginabotDB projects.id** |
| `project_name` | varchar | YES | Project code (e.g., `COLCEST757P1_AGUSTIN-CODAZZI_SUR`) |
| `locality` | jsonb | YES | Locality IDs |
| `screenshot` | varchar(100) | YES | Screenshot of filed form |
| `requested_by` | varchar(255) | YES | Person who requested |
| `requested_by_email` | varchar(254) | YES | Requester email |
| `requested_by_discord_id` | varchar(20) | YES | Discord user ID of requester |
| `company_id` | bigint | YES | FK to `supplies_companysupplyrequest` |
| `grid_operator_id` | varchar(255) | YES | FK to `management_gridoperator.code` |
| `transformer_id` | bigint | YES | FK to `management_transformer` |
| `type_supply` | varchar(255) | NO | `active` / `backup` / `expired` |
| `form` | text | YES | Raw form data from OR portal |
| `city_id` | bigint | YES | FK to `territorial_city` |
| `enc_str` | varchar(256) | YES | Encrypted query string for OR portal |
| `generation_start_date` | timestamptz | YES | Planned generation start |
| `kva` | double | NO | Requested capacity in kVA |
| `kwp` | double | NO | Requested capacity in kWp |
| `exp_code` | varchar(255) | YES | OR expedition/file code |
| `filing_date` | date | YES | Date filed with OR |
| `validation_code` | varchar(255) | YES | OR validation code |
| `supply_repeated` | boolean | NO | Whether this is a duplicate request |
| `comment` | text | YES | Free-text comments |
| `documentation_status` | varchar(30) | YES | `missing_all` / `completed` / `missing_topography` / `missing_physical_disposition` |
| `network_project` | varchar(100) | YES | Network project code |
| `network_project_status` | varchar(30) | YES | `pending` / `or_send` / `approved` / `developing` |
| `order_in_queue` | integer | NO | Position in processing queue |
| `extra_electrical_details` | jsonb | YES | Additional electrical parameters |
| `ecs_conformity_file` | varchar(100) | YES | ECS conformity document |
| `ecs_file` | varchar(100) | YES | ECS document |

### `supplies_optionstatussupplyrequest` (14 rows -- workflow states)

| ID | Name | Days to Expire | Manager | Description |
|----|------|---------------|---------|-------------|
| 1 | Insumos solicitados | 60 | or | Inputs requested from OR |
| 2 | Fallo formulario OR | 0 | not_managed | OR form submission failed |
| 3 | Insumos recibidos | 150 | internal | Inputs received from OR |
| 4 | Insumos en correccion | 30 | internal | Inputs being corrected |
| 5 | ECS en proceso | 150 | internal | ECS in progress |
| 6 | ECS por enviar | 150 | internal | ECS ready to send |
| 7 | ECS enviado al OR | 30 | or | ECS sent to OR |
| 8 | ECS por corregir | 15 | internal | ECS needs corrections |
| 9 | ECS comentarios enviados | 30 | or | ECS comments sent |
| 10 | ECS aprobado | 180 | internal | ECS approved |
| 11 | ECS aprobado, prorroga | 270 | internal | ECS approved with extension |
| 12 | Punto fisico aprobado | 0 | approved | Physical connection point approved |
| 13 | Rechazado | 0 | not_managed | Rejected |
| 14 | Insumos dados de baja | 0 | not_managed | Inputs decommissioned |

### `supplies_statussupplyrequest` (47,960 rows)

Status history log -- each row = one status transition.

| Column | Type | Description |
|--------|------|-------------|
| `id` | bigint PK | |
| `created` / `modified` | timestamptz | |
| `initial_date` | date | Status effective start date |
| `end_date` | date | Status expiration date |
| `status_id` | bigint FK | -> `optionstatussupplyrequest.id` |
| `supply_request_id` | bigint FK | -> `supplyrequest.id` |
| `form_status` | jsonb | Form state snapshot |
| `updated_by` | varchar(255) | Who changed it (e.g., "InsumosBot") |

### `supplies_company` (216 rows)

Companies filing supply requests. Includes Unergy clients and EPC partners.

### `supplies_credentialscompany` (3 rows)

Automated portal login credentials: `proyectos@unergy.io` for CENS, ESSA, Enel portals (company_id=117).

---

## Grid Management Tables

### `management_gridoperator` (23 rows -- PK = `code`)

| Code | Name | Portal URL |
|------|------|-----------|
| `afinia` | Afinia | servicios.energiacaribemar.co/Autogeneracion/ |
| `aire` | Air-e | servicios.air-e.com/CREG030/ |
| `cens` | CENS | portal.almeraim.com/login/sgicens/PAUTOG |
| `essa` | ESSA | essa.com.co/.../formulario-solicitud-conexion-agpe |
| `enel` | Enel | enel.com.co/es/AccessMyEnel.html |
| 18 more | EPM, Celsia, EBSA, etc. | (no URL) |

### `management_circuit` (1,152 rows)

| Column | Type | Description |
|--------|------|-------------|
| `name` | varchar(255) | Circuit code (e.g., `BELC31`, `SEVC22`) |
| `tension_level` | varchar(10) | `13.8` or `34.5` kV |
| `demand07/12/16/21` | double | Demand at 7am/12pm/4pm/9pm (MW) |
| `grid_operator_id` | varchar FK | -> `gridoperator.code` |

Distribution: Air-e 384, ESSA 309, Afinia 239, CENS 145, Transelca 44, GEB 31

### `management_substation` (288 rows)

Substations with PostGIS geometry and capacity at 138kV / 345kV.

### `management_substation_circuits` (231 rows -- M2M)

Links substations to circuits. Top: SEVILLA (8), BELEN (8), SANMATEO (7).

### `management_transformer` (81,826 rows)

Distribution transformers with detailed CREG capacity data:

| Column | Type | Description |
|--------|------|-------------|
| `plate` | varchar(255) | Transformer plate number |
| `serial` | varchar(16) | Serial number |
| `circuit_id` | bigint FK | -> `circuit.id` |
| `grid_operator_id` | varchar FK | -> `gridoperator.code` |
| `status` | varchar(10) | Always `active` |
| `phases` | varchar(67) | `(3F) ABC`, `(2F) BC`, etc. |
| `voltage_pt` | varchar(9) | `120 V`, `127/208 V`, etc. |
| `installed_capacity_kva` | double | Rated capacity |
| `clients_count` | integer | Connected clients |
| `installed_agpe_capacity_kw` | double | Installed autogeneration |
| `available_agpe_capacity_kw` | double | Available AGPE capacity |
| `available_agpe_capacity_pct` | double | Available as % |
| `approved_autogen_clients` | integer | Approved autogenerators |
| `autogen_clients` | integer | Current autogenerators |
| `max_injection_power_kw` | double | Maximum injection power |
| `shortcircuit_current_3f` | double | 3-phase short-circuit current |
| `geometry` | PostGIS | Location |

Distribution: Air-e 49,738 (61%), CENS 24,394 (30%), Afinia 7,514 (9%)

### Grid Topology Hierarchy

```
GridOperator (23)
  +-- Substation (288) via grid_operator_id
  |     +-- [M2M] substation_circuits -- Circuit (1,152) via grid_operator_id
  |                                        +-- Transformer (81,826) via circuit_id
  |                                              +-- SupplyRequest (17,987) via transformer_id
  +-- MultiLineGeometry (617) -- circuit paths
  +-- MultiPointGeometry (220) -- circuit nodes
```

---

## Government Entity Requests

### `entities_entity` (14 rows)

| ID | Code | Name | Purpose |
|----|------|------|---------|
| 1 | ANLA | Agencia Nacional de Licencias Ambientales | Environmental license overlap |
| 2 | ANH | Agencia Nacional de Hidrocarburos | Hydrocarbon area overlap |
| 3 | PNNC | Parques Naturales Nacionales | National park overlap |
| 4 | MADS | Ministerio de Ambiente | Protected area overlap |
| 5 | ANT | Agencia Nacional de Tierras | Ethnic group info |
| 6 | URT | Unidad de Restitucion de Tierras | Land restitution check |
| 7 | ANT_LEGAL | Agencia Nacional de Tierras Legal | Legal petition |
| 8 | MININT | Ministerio del Interior | Prior consultation check |
| 9 | ANI | Agencia Nacional de Infraestructura | Infrastructure overlap |
| 12 | ANM | Agencia Nacional de Mineria | Mining overlap |
| 13 | SGC | Servicio Geologico Colombiano | Geological overlap |
| 14 | UPME | Unidad de Planeacion Minero-Energetica | Energy planning overlap |

### `entities_request` (3,539 rows)

Consultation requests sent per project. Fields: `uuid`, `status` (sent/responded/radicated), `entity_id`, `project_id` (-> OriginabotDB), `project_name`, `context` (jsonb).

### `entities_coexistence` (505 rows)

Coexistence verification with mining/oil/infrastructure operators. Status: approved (239), pending (186), sent (41), not_applicable (20).

---

## Capacity Analysis

### `capacity_capacity` (27 rows)

Circuit capacity (hosting capacity) analysis results:

| Column | Type | Description |
|--------|------|-------------|
| `circuit_id` | bigint FK | Target circuit |
| `has_capacity` | boolean | Can circuit support new minigranjas? |
| `ai_analysis` | text | LLM-generated analysis summary |
| `result` | jsonb | Detailed power flow: cargabilidad %, overloaded lines, scenarios |
| `optimistic_result` | jsonb | Optimistic scenario |
| `latitude` / `longitude` | double | Analysis location |

---

## Foreign Key Relationships

### Core Business FKs
```
supplies_supplyrequest.company_id           -> supplies_companysupplyrequest.id
supplies_supplyrequest.grid_operator_id     -> management_gridoperator.code
supplies_supplyrequest.transformer_id       -> management_transformer.id
supplies_supplyrequest.city_id              -> territorial_city.id
supplies_statussupplyrequest.supply_request_id -> supplies_supplyrequest.id
supplies_statussupplyrequest.status_id      -> supplies_optionstatussupplyrequest.id
supplies_errorsupplyrequest.supply_request_id -> supplies_supplyrequest.id
supplies_supplyrequestattachment.supply_request_id -> supplies_supplyrequest.id
supplies_companysupplyrequest.company_id    -> supplies_company.id
supplies_credentialscompany.company_id      -> supplies_company.id
supplies_credentialscompany.grid_operator_id -> management_gridoperator.code
```

### Grid Topology FKs
```
management_circuit.grid_operator_id          -> management_gridoperator.code
management_substation.grid_operator_id       -> management_gridoperator.code
management_substation_circuits.substation_id  -> management_substation.id
management_substation_circuits.circuit_id     -> management_circuit.id
management_transformer.circuit_id             -> management_circuit.id
management_transformer.grid_operator_id       -> management_gridoperator.code
management_multilinegeometry.circuit_id       -> management_circuit.id
management_multipointgeometry.circuit_id      -> management_circuit.id
```

### Entity/Regulatory FKs
```
entities_request.entity_id                    -> entities_entity.id
entities_file.request_id                      -> entities_request.id
entities_requestresponse_requests.request_id  -> entities_request.id
entities_coexistence.operator_id              -> entities_operator.id
entities_coexistence.entity_id                -> entities_entity.id
entities_operatorcontact.operator_id          -> entities_operator.id
capacity_capacity.circuit_id                  -> management_circuit.id
territorial_city.region_id                    -> territorial_region.id
territorial_region.country_id                 -> territorial_country.id
```

---

## Link to OriginabotDB

Three tables reference OriginabotDB projects:

1. **`supplies_supplyrequest.project`** (integer) -- OriginabotDB project ID
2. **`entities_request.project_id`** (varchar) -- OriginabotDB project ID as string
3. **`entities_coexistence.project_id`** (varchar) -- OriginabotDB project ID as string

All three also carry `project_name` (e.g., `COLCEST757P1_AGUSTIN-CODAZZI_SUR`).

**The full data chain for any Minigranja:**
```
OriginabotDB.projects (project design, panels, inverters, financial)
    |
    v (project_id)
RequestsDB.supplies_supplyrequest (grid connection request)
    |
    +-> management_transformer (capacity, phases, AGPE availability)
    |       +-> management_circuit (feeder, voltage, demand)
    |               +-> management_substation (MVA capacity)
    |               +-> capacity_capacity (power flow analysis)
    |
    +-> entities_request -> entities_requestresponse (gov approvals)
    +-> entities_coexistence (mining/oil overlap)
```

---

## Enum/Status Distributions

| Field | Value | Count |
|-------|-------|-------|
| `type_supply` | active | 15,076 |
| | backup | 2,116 |
| | expired | 795 |
| `documentation_status` | missing_all | 16,234 |
| | completed | 1,061 |
| | missing_topography | 623 |
| `network_project_status` | pending | 17,976 |
| | or_send | 9 |
| `grid_operator_id` | afinia | 12,027 |
| | aire | 4,447 |
| | essa | 525 |
| | cens | 333 |

---

## Key Observations

1. **Afinia + Air-e dominate**: 92% of supply requests (Caribbean coast: Cesar, Atlantico, Bolivar, Magdalena, La Guajira)
2. **Selenium automation**: Files requests via browser automation; `InsumosBot` user handles status updates
3. **90% documentation-incomplete**: Only 6% of requests have `completed` documentation
4. **Network approval bottleneck**: 99.9% remain `pending`; only 1 approved
5. **Capacity analysis sparse**: 27 analyses out of 1,152 circuits
6. **PostGIS everywhere**: Substations, transformers, requests, cities all have spatial geometry
7. **No direct FK to OriginabotDB**: Cross-DB joins must be done in application code
8. **Coexistence = extractive industry overlap**: Tracks mining/oil/gas concession overlaps with solar projects
