# RequestsDB Schema Discovery

**Database:** `requestsdb` on `34.74.198.101:5432`  
**Framework:** Django + Celery + PostGIS  
**Total tables:** 67 (21 domain, 18 Django/auth/admin, 10 Silk profiler, 8 Celery, 5 audit, 5 PostGIS system)  
**Date discovered:** 2026-05-18  

---

## Purpose

RequestsDB manages **Unergy's electrical grid connection requests** (solicitudes de conexion AGPE) filed with Colombian grid operators (Operadores de Red - OR). It tracks the full lifecycle: filing supply requests with ORs via web automation (Selenium), tracking ECS (Estudio de Conexion Simplificado) approval status, checking circuit/transformer capacity, and managing coexistence letters (consultas de coexistencia) with mining/oil companies and government entities.

---

## Table of Contents

1. [Row Counts Summary](#row-counts-summary)
2. [Domain Model Overview](#domain-model-overview)
3. [Core Tables: Supply Requests](#core-tables-supply-requests)
4. [Grid Management Tables](#grid-management-tables)
5. [Government Entity Requests](#government-entity-requests)
6. [Coexistence (Mining/Oil Overlap)](#coexistence)
7. [Territorial Geography](#territorial-geography)
8. [Capacity Analysis](#capacity-analysis)
9. [Supporting Tables](#supporting-tables)
10. [Foreign Key Relationships](#foreign-key-relationships)
11. [Enum/Status Values](#enum-status-values)
12. [Celery Periodic Tasks](#celery-periodic-tasks)
13. [Link to OriginabotDB](#link-to-originabotdb)
14. [Key Observations](#key-observations)

---

## Row Counts Summary

| Table | Rows | Description |
|-------|------|-------------|
| `supplies_supplyrequest` | **17,987** | Grid connection requests (main table) |
| `supplies_statussupplyrequest` | **47,960** | Status history for each supply request |
| `supplies_supplyrequestattachment` | **20,818** | File attachments (sketches, IDs, CTLs) |
| `management_transformer` | **81,826** | Distribution transformers with capacity data |
| `management_circuit` | **1,152** | Electrical circuits (feeders) |
| `management_substation` | **288** | Substations |
| `management_substation_circuits` | **231** | Substation-to-circuit M2M |
| `management_multilinegeometry` | **617** | Circuit line geometries |
| `management_multipointgeometry` | **220** | Circuit point geometries |
| `management_gridoperator` | **23** | Grid operators (Afinia, Air-e, EPM, etc.) |
| `entities_request` | **3,539** | Requests to government entities |
| `entities_requestresponse` | **1,875** | Responses from government entities |
| `entities_entity` | **14** | Government entities (ANLA, ANH, PNNC, etc.) |
| `entities_operator` | **84** | Mining/oil operators for coexistence checks |
| `entities_coexistence` | **505** | Coexistence verifications |
| `entities_file` | **6,153** | Files attached to entity requests |
| `supplies_company` | **216** | Companies filing requests |
| `supplies_companysupplyrequest` | **549** | Company contact info per request |
| `capacity_capacity` | **27** | Circuit capacity analysis results |
| `territorial_region` | **33** | Colombian departments |
| `territorial_city` | **1,121** | Colombian municipalities |
| `auth_user` | **13** | System users |
| `django_tracker_auditlog` | **2,448,336** | Change audit trail |

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
| `tension_level` | varchar(10) | YES | Voltage level: `13.8`, `34.5`, `13.2`, `220`, etc. (kV) |
| `customer_name` | varchar(255) | YES | Usually "Unergy Energia Digital S.A.S. E.S.P." |
| `customer_email` | varchar(254) | YES | Usually `minigranjas@unergy.io` |
| `updated_by_agent` | boolean | NO | Whether updated by automation bot |
| `geometry` | geography(Point) | NO | GPS coordinates of connection point |
| `project` | integer | YES | **FK to OriginabotDB projects.id** |
| `project_name` | varchar | YES | Project code (e.g., `COLCEST757P1_AGUSTIN-CODAZZI_SUR`) |
| `locality` | jsonb | YES | `{"locality": "437", "municipality": "44", "neighborhood": "23220"}` |
| `screenshot` | varchar(100) | YES | Screenshot of filed form |
| `requested_by` | varchar(255) | YES | Person who requested (e.g., "Silvia Munoz") |
| `requested_by_email` | varchar(254) | YES | Requester email |
| `requested_by_discord_id` | varchar(20) | YES | Discord user ID of requester |
| `company_id` | bigint | YES | FK to `supplies_companysupplyrequest` |
| `grid_operator_id` | varchar(255) | YES | FK to `management_gridoperator.code` |
| `transformer_id` | bigint | YES | FK to `management_transformer` |
| `type_supply` | varchar(255) | NO | `active` / `backup` / `expired` |
| `form` | text | YES | Raw form data from OR portal (JSON string) |
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
| `extra_electrical_details` | jsonb | YES | Additional electrical parameters (usually empty) |
| `ecs_conformity_file` | varchar(100) | YES | ECS conformity document |
| `ecs_file` | varchar(100) | YES | ECS document |

**Data range:** 2022-10-18 to 2026-05-16 (3.5 years)

### `supplies_statussupplyrequest` (47,960 rows)

Status history for each supply request. Multiple rows per supply request (status transitions).

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | bigint | NO | PK |
| `created` | timestamptz | NO | When status was set |
| `modified` | timestamptz | NO | Last modification |
| `initial_date` | date | YES | Status effective start date |
| `end_date` | date | YES | Status expiration date |
| `status_id` | bigint | NO | FK to `supplies_optionstatussupplyrequest` |
| `supply_request_id` | bigint | NO | FK to `supplies_supplyrequest` |
| `form_status` | jsonb | YES | Form state snapshot |
| `updated_by` | varchar(255) | YES | Who changed it (e.g., "InsumosBot") |

### `supplies_optionstatussupplyrequest` (14 rows)

The status lifecycle options (finite state machine for supply requests).

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

### `supplies_supplyrequestattachment` (20,818 rows)

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | bigint | NO | PK |
| `created` | timestamptz | NO | Upload time |
| `modified` | timestamptz | NO | Last modification |
| `file` | varchar(100) | NO | File path |
| `type_attachment` | varchar(255) | NO | `default` / `id` / `sketch` / `ctl` |
| `supply_request_id` | bigint | NO | FK to `supplies_supplyrequest` |

### `supplies_errorsupplyrequest` (530 rows)

Selenium automation errors when filing requests with OR portals.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | bigint | NO | PK |
| `created` | timestamptz | NO | Error time |
| `modified` | timestamptz | NO | |
| `error` | text | NO | Error message (Selenium exceptions) |
| `screenshot` | varchar(100) | YES | Screenshot of error |
| `supply_request_id` | bigint | NO | FK to `supplies_supplyrequest` |
| `traceback` | text | YES | Python traceback |

### `supplies_company` (216 rows)

Companies filing supply requests. Includes Unergy clients and third parties.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | bigint | NO | PK |
| `name` | varchar(255) | NO | Company name |
| `nit` | varchar(255) | YES | Colombian tax ID |
| `is_owner` | boolean | NO | Whether this is the asset owner |

**Top companies by request volume:** OTACC (4,493), Unergy (4,183), GMAIL (2,273), ERCO (560), WEPOWER (450), LICARENOVAVEIS (359), URSAE (358), CGM-I (356)

### `supplies_companysupplyrequest` (549 rows)

Contact info for companies per supply request.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | bigint | NO | PK |
| `address` | varchar(255) | YES | Company address |
| `city` | varchar(255) | YES | Company city |
| `email` | varchar(255) | NO | Contact email |
| `phone` | varchar(20) | YES | Phone |
| `customers` | ARRAY | NO | Customer list |
| `nit` | varchar(255) | YES | Tax ID |
| `company_id` | bigint | YES | FK to `supplies_company` |

### `supplies_credentialscompany` (3 rows)

Credentials for OR portal automation (Unergy's logins).

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | bigint | NO | PK |
| `username` | varchar(255) | NO | Portal username |
| `password` | varchar(255) | NO | Portal password |
| `company_id` | bigint | NO | FK to `supplies_company` |
| `grid_operator_id` | varchar(255) | NO | FK to `management_gridoperator.code` |

Stored credentials: Unergy accounts for CENS, ESSA, Enel portals.

### `supplies_restrictionoptionsupplyrequest` (28 rows)

Color-coded deadline restrictions for each status option.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | bigint | NO | PK |
| `remaining_days_limit` | integer | NO | Days remaining threshold |
| `color` | varchar(255) | NO | Color code for UI |
| `option_id` | bigint | NO | FK to `supplies_optionstatussupplyrequest` |

### `supplies_suppliesstatusnotificationsetting` (4 rows)

Notification settings for status changes.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | bigint | NO | PK |
| `is_active` | boolean | NO | Whether notifications are enabled |
| `days_threshold` | integer | NO | Days before expiry to notify |
| `status_option_id` | bigint | NO | FK to `supplies_optionstatussupplyrequest` |

### `supplies_colorhsba` (12 rows)

UI color configuration for status indicators.

---

## Grid Management Tables

### `management_gridoperator` (23 rows)

Colombian electrical grid operators (Operadores de Red).

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `code` | varchar(255) | NO | PK. Lowercase code: `afinia`, `aire`, `cens`, `epm`, etc. |
| `name` | varchar(255) | NO | Display name |
| `method` | varchar(10) | YES | Integration method (all `webpage`) |
| `url` | varchar(255) | YES | OR portal URL for filing |
| `url_transformers` | varchar(255) | YES | URL for transformer lookup |
| `created` | timestamptz | NO | |
| `modified` | timestamptz | NO | |

| Code | Name | Portal URL |
|------|------|-----------|
| `afinia` | Afinia | `https://servicios.energiacaribemar.co/Autogeneracion/` |
| `aire` | Air-e | `https://servicios.air-e.com/CREG030/` |
| `cens` | CENS | `https://portal.almeraim.com/login/sgicens/PAUTOG` |
| `essa` | ESSA | `https://www.essa.com.co/.../formulario-solicitud-conexion-agpe` |
| `enel` | Enel | `https://www.enel.com.co/es/AccessMyEnel.html` |
| `epm` | EPM | (no URL) |
| `celsia` | Celsia | (no URL) |
| Others | 16 more | (no URL) |

### `management_circuit` (1,152 rows)

Electrical circuits (feeders) in the distribution grid.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | bigint | NO | PK |
| `created` | timestamptz | NO | |
| `modified` | timestamptz | NO | |
| `name` | varchar(255) | NO | Circuit name (e.g., `PELC2`, `CURUMANI RURAL`) |
| `tension_level` | varchar(10) | YES | Voltage level (e.g., `13.8`) |
| `demand07` | double | NO | Demand at 07:00 |
| `demand12` | double | NO | Demand at 12:00 |
| `demand16` | double | NO | Demand at 16:00 |
| `demand21` | double | NO | Demand at 21:00 |
| `grid_operator_id` | varchar(255) | YES | FK to `management_gridoperator.code` |

**Circuits per operator:** Air-e (384), ESSA (309), Afinia (239), CENS (145), Transelca (44), GEB (31)

### `management_substation` (288 rows)

Electrical substations.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | bigint | NO | PK |
| `created` | timestamptz | NO | |
| `modified` | timestamptz | NO | |
| `name` | varchar(255) | NO | Substation name (e.g., `PELAYA`, `BAYUNCA`) |
| `geometry` | geography(Point) | NO | Geographic location |
| `capacity138` | double | NO | Capacity at 138kV (MVA) |
| `capacity345` | double | NO | Capacity at 345kV (MVA) |
| `grid_operator_id` | varchar(255) | YES | FK to `management_gridoperator.code` |

### `management_substation_circuits` (231 rows)

M2M linking substations to their circuits.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | bigint | NO | PK |
| `substation_id` | bigint | NO | FK to `management_substation` |
| `circuit_id` | bigint | NO | FK to `management_circuit` |

### `management_transformer` (81,826 rows)

Distribution transformers with detailed capacity and AGPE (autogeneracion a pequena escala) data.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | bigint | NO | PK |
| `created` | timestamptz | NO | |
| `modified` | timestamptz | NO | |
| `plate` | varchar(255) | NO | Transformer plate number (e.g., `2T01621`, `E2858`) |
| `geometry` | geography(Point) | YES | Geographic location |
| `circuit_id` | bigint | YES | FK to `management_circuit` |
| `grid_operator_id` | varchar(255) | NO | FK to `management_gridoperator.code` |
| `serial` | varchar(16) | YES | Serial number |
| `status` | varchar(10) | NO | Always `active` (100%) |
| `phases` | varchar(67) | YES | Phase config: `(3F) ABC`, `(2F) BC`, etc. |
| `voltage_pt` | varchar(9) | YES | Voltage: `120 V`, `127/208 V`, `120/240 V` |
| `installed_capacity_kva` | double | NO | Transformer rated capacity (kVA) |
| `clients_count` | integer | NO | Number of connected clients |
| `clients_consumption_kwh` | double | NO | Total client consumption (kWh/month) |
| `avg_consumption_clients` | double | NO | Average consumption per client |
| `avg_daily_consumption_kwh` | double | NO | Average daily consumption |
| `installed_load_clients_kva` | double | NO | Total installed client load (kVA) |
| `installed_power_clients_kw` | double | NO | Total installed client power (kW) |
| `delivered_power_capacity` | double | NO | Delivered power capacity |
| `available_power_kw` | double | NO | Available power for new connections |
| `available_agpe_capacity_kw` | double | NO | Available AGPE capacity (kW) |
| `available_agpe_capacity_pct` | double | NO | Available AGPE capacity (%) |
| `installed_agpe_capacity_kw` | double | NO | Already installed AGPE capacity |
| `max_injection_power_kw` | double | NO | Maximum injection power |
| `max_injection_energy_with_pv` | double | NO | Max injection energy with PV |
| `max_injection_energy_without_pv` | double | NO | Max injection energy without PV |
| `energy_capacity_with_pv` | double | NO | Energy capacity with PV |
| `energy_capacity_without_pv` | double | NO | Energy capacity without PV |
| `available_energy_kwh` | double | NO | Available energy capacity |
| `reserved_power_kw` | double | NO | Reserved power for pending requests |
| `approved_autogen_clients` | integer | NO | Number of approved autogenerators |
| `autogen_clients` | integer | NO | Number of connected autogenerators |
| `min_demand_factor` | varchar(7) | YES | Minimum demand factor |
| `daily_min_demand_factor` | varchar(7) | YES | Daily minimum demand factor |
| `shortcircuit_current_3f` | double | NO | 3-phase short-circuit current |

**Transformers per operator:** Air-e (49,738), CENS (24,394), Afinia (7,514), ESSA (90), EBSA (43)  
**With circuit_id:** 74,583 / 81,826 (91%)

### `management_multilinegeometry` (617 rows)

Geographic line geometries for circuit paths.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | bigint | NO | PK |
| `geometry` | geography(MultiLineString) | NO | Circuit path geometry |
| `circuit_id` | bigint | NO | FK to `management_circuit` |

### `management_multipointgeometry` (220 rows)

Geographic point geometries for circuit nodes.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | bigint | NO | PK |
| `geometry` | geography(MultiPoint) | NO | Circuit node geometry |
| `circuit_id` | bigint | NO | FK to `management_circuit` |

---

## Government Entity Requests

### `entities_entity` (14 rows)

Government entities that Unergy files coexistence/overlap requests with.

| ID | Code | Name | Active | Purpose |
|----|------|------|--------|---------|
| 1 | ANLA | Agencia Nacional de Licencias Ambientales | Yes | Licensed project overlap check |
| 2 | ANH | Agencia Nacional de Hidrocarburos | Yes | Hydrocarbon area overlap check |
| 3 | PNNC | Parques Naturales Nacionales de Colombia | Yes | RUNAP overlap check |
| 4 | MADS | Ministerio de Ambiente | Yes | Protected area overlap check |
| 5 | ANT | Agencia Nacional de Tierras | Yes | Ethnic group info for project |
| 6 | URT | Unidad de Restitucion de Tierras | Yes | Land restitution check |
| 7 | ANT_LEGAL | Agencia Nacional de Tierras Legal | Yes | Legal petition |
| 8 | MININT | Ministerio del Interior | Yes | Prior consultation check |
| 9 | ANI | Agencia Nacional de Infraestructura | Yes | Infrastructure restriction check |
| 10 | ICANH | Instituto Colombiano de Antropologia | No | (inactive) |
| 11 | CAR | Corporacion Autonoma | No | (inactive) |
| 12 | ANM | Agencia Nacional de Mineria | Yes | Mining overlap check |
| 13 | SGC | Servicio Geologico Colombiano | Yes | Overlap per Resolucion 40358/2025 |
| 14 | UPME | Unidad de Planeacion Minero-Energetica | Yes | Overlap per Resolucion 40358/2025 |

All entities use `type_request = 'email'`. The system generates templated emails with project KMZ/SHP files.

### `entities_request` (3,539 rows)

Requests sent to government entities.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | bigint | NO | PK |
| `created` | timestamptz | NO | Creation time |
| `modified` | timestamptz | NO | |
| `uuid` | varchar(50) | NO | Unique request ID |
| `status` | varchar(10) | NO | `responded` / `radicated` / `sent` / `created` |
| `entity_id` | bigint | NO | FK to `entities_entity` |
| `context` | jsonb | YES | Request context (city, dept, coords, file paths) |
| `filed` | varchar(255) | YES | Filing reference |
| `project_id` | varchar(255) | NO | **Link to OriginabotDB project** |
| `project_name` | varchar(255) | NO | Project code name |

**Status distribution:** responded (1,742), radicated (1,528), sent (254), created (15)

### `entities_requestresponse` (1,875 rows)

Responses received from government entities.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | bigint | NO | PK |
| `created` | timestamptz | NO | |
| `modified` | timestamptz | NO | |
| `response` | text | NO | Response content |
| `adjunt` | varchar(100) | YES | Attached file |
| `status` | varchar(20) | YES | `approved` or NULL (64 approved, 1811 NULL) |
| `comments` | text | YES | Comments |

Linked to requests via `entities_requestresponse_requests` M2M table.

### `entities_requiredfile` (6 rows)

Required file types for entity requests.

| ID | Name | Extension | Description |
|----|------|-----------|-------------|
| 1 | project_area | kmz | KMZ with project area |
| 2 | project_area | shp | Shapefile with project area |
| 3 | cc_unergy | .pdf | Unergy chamber of commerce doc |
| 4 | cc_nicolas | .pdf | Nicolas's ID (legal representative) |
| 5 | workbook | xlsx | Excel with project info |
| 6 | determinacion_procedencia | .docx | Prior consultation determination request |

---

## Coexistence

### `entities_coexistence` (505 rows)

Coexistence verification with mining/oil/infrastructure operators. Checks whether a solar project overlaps with mining concessions, oil blocks, or infrastructure corridors.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | bigint | NO | PK |
| `created` | timestamptz | NO | |
| `modified` | timestamptz | NO | |
| `data` | text | NO | Raw data from mining/oil registry (titles, expedientes, areas, minerals) |
| `status` | varchar(20) | NO | `approved` / `pending` / `sent` / `not_applicable` / `communication` |
| `date_updated` | date | YES | Last update date |
| `adjunt` | varchar(100) | YES | Attached file |
| `comments` | text | YES | Comments |
| `operator_id` | bigint | NO | FK to `entities_operator` (mining/oil company) |
| `entity_id` | bigint | YES | FK to `entities_entity` (government entity) |
| `project_id` | varchar(255) | YES | **Link to OriginabotDB project** |
| `project_name` | varchar(255) | YES | Project code name |

**Status distribution:** approved (239), pending (186), sent (41), not_applicable (20), communication (19)

### `entities_operator` (84 rows)

Mining, oil, gas, and infrastructure operators. NOT grid operators -- these are companies with concessions that may overlap with solar projects.

Examples: ECOPETROL, DRUMMOND ENERGY, PROMIGAS, FRONTERA ENERGY, HOLCIM, CEMEX, ISA (INTERCONEXION ELECTRICA), CENIT, EPM, etc.

### `entities_operatorcontact` (38 rows)

Contact info for mining/oil operators.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | bigint | NO | PK |
| `name` | varchar(255) | NO | Contact name |
| `phone` | varchar(20) | YES | Phone |
| `email` | varchar(255) | YES | Email |
| `notes` | text | YES | Notes |
| `operator_id` | bigint | NO | FK to `entities_operator` |

---

## Territorial Geography

### `territorial_country` (1 row)

Just Colombia.

### `territorial_region` (33 rows)

Colombian departments. Examples: Cesar, Atlantico, Bolivar, Boyaca, Santander, Antioquia, etc.

### `territorial_city` (1,121 rows)

Colombian municipalities with polygon geometries.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | bigint | NO | PK |
| `name` | varchar(255) | NO | Municipality name |
| `geometry` | geography | NO | Municipality boundary |
| `region_id` | bigint | NO | FK to `territorial_region` |

---

## Capacity Analysis

### `capacity_capacity` (27 rows)

Circuit capacity analysis results. Determines whether a circuit can support additional Minigranjas.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | bigint | NO | PK |
| `created` | timestamptz | NO | Analysis date |
| `modified` | timestamptz | NO | |
| `xlsx` | varchar(100) | YES | Source Excel file |
| `circuit_id` | bigint | NO | FK to `management_circuit` |
| `result` | jsonb | YES | Detailed results: line loading %, scenarios (2025_DMI, 2028_DMX), overloaded lines |
| `optimistic_result` | jsonb | YES | Optimistic scenario results |
| `base_id` | bigint | YES | FK to `supplies_supplyrequestattachment` (source data) |
| `ai_analysis` | text | YES | AI-generated capacity analysis summary |
| `has_capacity` | boolean | NO | Whether circuit has capacity for new connections |
| `latitude` | double | YES | Analysis point latitude |
| `longitude` | double | YES | Analysis point longitude |
| `requests_report` | text | YES | Report of discarded requests |

**Result JSONB structure (per scenario):**
```json
{
  "escenario": "2025_DMI",
  "total_lineas": 1882,
  "max_cargabilidad": 103.41,
  "lineas_sobrecargadas": 2,
  "porcentaje_sobrecargadas": 0.106,
  "promedio_cargabilidad": 6.22,
  "capacidad_suficiente": false,
  "top_5_sobrecargadas": [{"Nombre_Linea": 11866633, "Loading_Percent": 103.41}]
}
```

---

## Supporting Tables

### `entities_coexistenceannexes` (44 rows)

File annexes for coexistence records.

### `entities_coexistenceexemption` (0 rows)

Exempted projects (empty).

### `entities_file` (6,153 rows)

Files attached to entity requests. `type` field: likely `kmz`, `shp`, `pdf`, etc.

### `entities_filter` (4 rows)

UI filter configuration for admin interface.

---

## Foreign Key Relationships

### Domain Foreign Keys

| Source | Column | Target | Column |
|--------|--------|--------|--------|
| `supplies_supplyrequest` | `company_id` | `supplies_companysupplyrequest` | `id` |
| `supplies_supplyrequest` | `grid_operator_id` | `management_gridoperator` | `code` |
| `supplies_supplyrequest` | `transformer_id` | `management_transformer` | `id` |
| `supplies_supplyrequest` | `city_id` | `territorial_city` | `id` |
| `supplies_statussupplyrequest` | `supply_request_id` | `supplies_supplyrequest` | `id` |
| `supplies_statussupplyrequest` | `status_id` | `supplies_optionstatussupplyrequest` | `id` |
| `supplies_errorsupplyrequest` | `supply_request_id` | `supplies_supplyrequest` | `id` |
| `supplies_supplyrequestattachment` | `supply_request_id` | `supplies_supplyrequest` | `id` |
| `supplies_companysupplyrequest` | `company_id` | `supplies_company` | `id` |
| `supplies_credentialscompany` | `company_id` | `supplies_company` | `id` |
| `supplies_credentialscompany` | `grid_operator_id` | `management_gridoperator` | `code` |
| `supplies_restrictionoptionsupplyrequest` | `option_id` | `supplies_optionstatussupplyrequest` | `id` |
| `supplies_suppliesstatusnotificationsetting` | `status_option_id` | `supplies_optionstatussupplyrequest` | `id` |
| `management_circuit` | `grid_operator_id` | `management_gridoperator` | `code` |
| `management_transformer` | `circuit_id` | `management_circuit` | `id` |
| `management_transformer` | `grid_operator_id` | `management_gridoperator` | `code` |
| `management_substation` | `grid_operator_id` | `management_gridoperator` | `code` |
| `management_substation_circuits` | `substation_id` | `management_substation` | `id` |
| `management_substation_circuits` | `circuit_id` | `management_circuit` | `id` |
| `management_multilinegeometry` | `circuit_id` | `management_circuit` | `id` |
| `management_multipointgeometry` | `circuit_id` | `management_circuit` | `id` |
| `capacity_capacity` | `circuit_id` | `management_circuit` | `id` |
| `capacity_capacity` | `base_id` | `supplies_supplyrequestattachment` | `id` |
| `entities_request` | `entity_id` | `entities_entity` | `id` |
| `entities_requestresponse_requests` | `request_id` | `entities_request` | `id` |
| `entities_requestresponse_requests` | `requestresponse_id` | `entities_requestresponse` | `id` |
| `entities_file` | `request_id` | `entities_request` | `id` |
| `entities_coexistence` | `operator_id` | `entities_operator` | `id` |
| `entities_coexistence` | `entity_id` | `entities_entity` | `id` |
| `entities_coexistenceannexes` | `coexistence_id` | `entities_coexistence` | `id` |
| `entities_operatorcontact` | `operator_id` | `entities_operator` | `id` |
| `territorial_city` | `region_id` | `territorial_region` | `id` |
| `territorial_region` | `country_id` | `territorial_country` | `id` |

---

## Enum/Status Values

### `supplies_supplyrequest.type_supply`
| Value | Count |
|-------|-------|
| `active` | 15,076 |
| `backup` | 2,116 |
| `expired` | 795 |

### `supplies_supplyrequest.documentation_status`
| Value | Count |
|-------|-------|
| `missing_all` | 16,234 |
| `completed` | 1,061 |
| `missing_topography` | 623 |
| `missing_physical_disposition` | 69 |

### `supplies_supplyrequest.network_project_status`
| Value | Count |
|-------|-------|
| `pending` | 17,976 |
| `or_send` | 9 |
| `approved` | 1 |
| `developing` | 1 |

### `supplies_supplyrequest.tension_level`
| Value | Count |
|-------|-------|
| `13.8` | 8,903 |
| NULL | 8,131 |
| `34.5` | 628 |
| `13.2` | 291 |
| `220` | 15 |
| `11.4` | 9 |
| `110` | 7 |
| `240` | 2 |
| `230` | 1 |

### `entities_request.status`
| Value | Count |
|-------|-------|
| `responded` | 1,742 |
| `radicated` | 1,528 |
| `sent` | 254 |
| `created` | 15 |

### `entities_coexistence.status`
| Value | Count |
|-------|-------|
| `approved` | 239 |
| `pending` | 186 |
| `sent` | 41 |
| `not_applicable` | 20 |
| `communication` | 19 |

### `supplies_supplyrequest` by `grid_operator_id`
| Operator | Count |
|----------|-------|
| `afinia` | 12,027 |
| `aire` | 4,447 |
| `essa` | 525 |
| `cens` | 333 |
| `celsia` | 215 |
| `ebsa` | 175 |
| `enel` | 69 |
| `emsa` | 53 |
| `electrohuila` | 33 |
| Others | 110 |

---

## Celery Periodic Tasks

| Task | Schedule | Description |
|------|----------|-------------|
| Nuevas solicitudes Afinia | Cron | Fetch new requests from Afinia portal |
| Nuevas solicitudes Aire | Cron | Fetch new requests from Air-e portal |
| Update semanal solicitudes Aire | Weekly | Update Air-e request statuses |
| Update semanal solicitudes Afinia | Weekly | Update Afinia request statuses |
| Enviar resumen semanal | Weekly | Send weekly supply report |
| Alertas de Insumos | Cron | Supply input alert notifications |
| Vectorizacion de circuitos | Cron | Vectorize circuits without geometry |
| Marcar capacidades sin resultado como fallidas | Cron | Mark failed capacity analyses |

---

## Link to OriginabotDB

The **`project` field** in `supplies_supplyrequest` (INTEGER) is the primary cross-database link. It maps to OriginabotDB's `projects.id`. There are **1,938 distinct project IDs** referenced.

Additional cross-references:
- `entities_request.project_id` (VARCHAR) -- 425 distinct values
- `entities_coexistence.project_id` (VARCHAR) -- 303 distinct values
- `supplies_supplyrequest.project_name` follows the naming convention: `COL{REGION}{CITY}{N}P{N}_{MUNICIPALITY}_{DIRECTION}` (e.g., `COLCEST757P1_AGUSTIN-CODAZZI_SUR`)

**The full data chain for any Minigranja is:**

```
OriginabotDB.projects (project design, panels, inverters, financial)
    |
    v (project_id)
RequestsDB.supplies_supplyrequest (grid connection request)
    |
    +-> management_transformer (transformer capacity, phases, AGPE availability)
    |       |
    |       +-> management_circuit (feeder, voltage, demand profile)
    |               |
    |               +-> management_substation (substation name, location, MVA capacity)
    |               +-> capacity_capacity (power flow analysis, overloaded lines)
    |
    +-> entities_request (government entity filings)
    |       +-> entities_requestresponse (approval/denial)
    |
    +-> entities_coexistence (mining/oil overlap check)
```

---

## Key Observations

1. **Afinia + Air-e dominate**: 92% of all supply requests are filed with these two operators (Caribbean coast Colombia: Cesar, Atlantico, Bolivar, Magdalena, La Guajira).

2. **Selenium automation**: The system uses browser automation (Selenium) to file requests with OR portals. Error logs show common failures like missing HTML elements (`NoSuchElementException`). The `InsumosBot` user automates status updates.

3. **Transformer data completeness varies wildly**: Air-e (49,738) and CENS (24,394) have extensive transformer data. Most other operators have very few transformers in the database.

4. **Most requests are documentation-incomplete**: 90% have `documentation_status = 'missing_all'`. Only 6% are `completed`.

5. **Network project approval is a bottleneck**: 99.9% are `pending`. Only 1 is `approved`.

6. **Capacity analysis is rare**: Only 27 capacity analyses have been run (out of 1,152 circuits). All checked so far show `has_capacity = false`.

7. **Government entity requests track regulatory compliance**: The 14 entities cover environmental (ANLA, MADS, PNNC), mining (ANM), land (ANT, URT), indigenous consultation (MININT), infrastructure (ANI, UPME), and geological (SGC) approvals required before construction.

8. **Coexistence = overlap with extractive industries**: The `entities_coexistence` table tracks whether a solar project geographically overlaps with mining concessions (arcilla, carbon, calizas, etc.) or oil/gas blocks. The `data` field contains raw scrapes of mining titles, expedientes, and concession details.

9. **13 system users**: Diego Moreno (dev), Camilo (admin), Felipe Miranda, Silvia Munoz, Juan Cogollo, Santiago Suarez, Juan Hernandez, Juan Camilo, Victor Mendoza, and others.

10. **No direct FK enforcement to OriginabotDB**: The `project` field is just an integer -- no database-level foreign key. Cross-DB joins must be done in application code.
