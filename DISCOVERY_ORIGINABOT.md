# OriginabotDB Schema Discovery

> Generated 2026-05-18 by scanning all Unergy repos under `/home/eduardo/Claude/`

## Connection Info

| Property | Value |
|----------|-------|
| Database name | `originabotdb` |
| Engine | PostgreSQL |
| Host (production) | `34.74.198.101` (GCP, found in `pagos_Backend/minigranjas_project/settings.py`) |
| Port | `5432` |
| User | `silvia` (read-only user in pagos_Backend) |
| Env var (boardneitor) | `ORIGINA_DB_URL=postgresql://user:password@host:5432/originabotdb` |
| Env var (075bot) | `DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/originabotdb` |

**Second database**: `requestsdb` (same host, different DB name). Used by boardneitor
for ECS/supply request data. Connection derived programmatically:
```python
_REQUESTS_DB_URL = _DB_URL.replace("/originabotdb", "/requestsdb")
```

### Projects that connect

| Project | Connection style | Access mode |
|---------|-----------------|-------------|
| `boardneitor` | `psycopg2` (sync) + `sqlalchemy` (sync, `_q()` helper) | Read-only |
| `075bot` | `sqlalchemy.ext.asyncio` (async) | Read-only |
| `pagos_Backend` | Django ORM (`django.db.backends.postgresql`) | Read-only (`minifarm_db` alias) |
| `edubot` | SQLAlchemy async (adds new tables, reads existing ones) | Read + Write (own tables only) |
| `unergy-operaciones-backend` | SQLAlchemy (reads `supplies_*` for ECS cross-ref) | Read-only (requestsdb) |

---

## Tables Discovered in OriginabotDB

### Core Domain: Projects & Pipeline

#### `minifarm_project`
The central table. Each row = one solar "minigranja" project.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |
| `name` | VARCHAR | Project code (e.g. "COLCORT7P1") |
| `code` | VARCHAR | Alternative code field (used by 075bot) |
| `stage` | VARCHAR | Pipeline stage (see stage values below) |
| `project_installed_power` | FLOAT | kWac (AC capacity) |
| `project_dc_capacity` | FLOAT | kWdc (DC nameplate) |
| `project_panels_count` | INT | Number of panels |
| `project_inverter_description` | TEXT | Inverter specs |
| `lat` | FLOAT | Latitude |
| `lng` | FLOAT | Longitude |
| `location` | VARCHAR | Location name |
| `department` | VARCHAR | Department |
| `city` | VARCHAR | City |
| `operator` | VARCHAR | Grid operator |
| `grid_operator_id` | VARCHAR | Grid operator identifier |
| `road_distance` | FLOAT | Distance to road |
| `network_distance` | FLOAT | Distance to grid |
| `terrain_id` | BIGINT FK | -> `termsheet_terrain.id` |
| `termsheet_id` | BIGINT FK | -> `termsheet_termsheet.id` |
| `annual_price` | FLOAT | Annual lease cost (COP) |
| `creg_174_approved` | BOOLEAN | CREG 174 compliance |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |

**Stage values** (canonical order from `boardneitor/constants.py`):
```
prospect -> negociation -> signed -> portfolio -> due_diligence
-> bt_and_contract -> deploy -> construction -> operation
```
Terminal: `dead`, `uci`, `paused`

#### `minifarm_projectstagechange`
Stage transition history. Critical for pipeline velocity, cohort analysis, and churn tracking.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |
| `project_id` | BIGINT FK | -> `minifarm_project.id` |
| `previous_stage` | VARCHAR | Stage before transition |
| `current_stage` | VARCHAR | Stage after transition |
| `justification` | TEXT | Reason for change |
| `created_at` | TIMESTAMPTZ | When the transition occurred |

---

### Investment & Capital

#### `investment_minifarm`
Per-project investment/construction details.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |
| `project_id` | BIGINT FK | -> `minifarm_project.id` |
| `capex` | FLOAT | Capital expenditure (M USD) |
| `construction_start` | DATE | |
| `construction_end` | DATE | |
| `percentage_of_completion` | FLOAT | RTB (Ready-to-Build) 0.0-1.0 |
| `first_disbursement` | DATE | |
| `energy_yield_p90_kwh` | FLOAT | (referenced but may not exist yet) |

#### `investment_portfolio`
Investment portfolios grouping minigranja projects.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |
| `name` | VARCHAR | e.g. "Sun Factory 1.1", "Skandia 1", "Exagon 1" |
| `expected` | FLOAT | Expected return % |
| `financing` | VARCHAR | Financing type |

#### `investment_portfolio_minifarm`
M2M: portfolio <-> investment_minifarm.

| Column | Type | Notes |
|--------|------|-------|
| `portfolio_id` | BIGINT FK | -> `investment_portfolio.id` |
| `minifarm_id` | BIGINT FK | -> `investment_minifarm.id` |

#### `investment_portfolio_investments`
M2M: portfolio <-> investor.

| Column | Type | Notes |
|--------|------|-------|
| `portfolio_id` | BIGINT FK | -> `investment_portfolio.id` |
| `investment_id` | BIGINT FK | -> `investment_investment.id` |

#### `investment_investment`
Investor profiles.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |
| `name` | VARCHAR | Investor name |
| `status` | VARCHAR | e.g. active, inactive, dead, rejected |
| `currency_type` | VARCHAR | |
| `financiation_type` | VARCHAR | |
| `max_inversion_capacity` | FLOAT | |
| `minimum_inversion_capacity` | FLOAT | |
| `created_at` | TIMESTAMPTZ | |

#### `investment_ppa`
Power Purchase Agreements.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |
| `off_taker_id` | BIGINT FK | -> `investment_offtaker.id` |
| `expected_minifarms` | INT | Number of committed minigranja units |

#### `investment_offtaker`
Energy offtaker (buyer) profiles.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |
| `name` | VARCHAR | |

---

### Terrain & Prospection

#### `termsheet_terrain`
Land parcels evaluated for solar projects.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |
| `name` | VARCHAR | Terrain code |
| `status` | VARCHAR | e.g. new, check, follow-up, pre-validation, completed, dead, uci |
| `label` | VARCHAR | Classification label |
| `area_m2` | FLOAT | Area in square meters |
| `radiation` | FLOAT | Solar radiation (PSH kWh/m2/day) |
| `has_access_road` | BOOLEAN | |
| `has_threephase_network` | BOOLEAN | |
| `tilt` | VARCHAR | e.g. 'suitable' |
| `latitude` | FLOAT | |
| `longitude` | FLOAT | |
| `city_id` | BIGINT FK | -> `territorial_subregion.id` |
| `customer_agent_id` | BIGINT FK | -> `prospecting_customeragent.id` |
| `originator_id` | BIGINT FK | -> `termsheet_originator.id` |
| `created_at` | TIMESTAMPTZ | |

#### `termsheet_terrainstatuschange`
Terrain status transition history.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |
| `terrain_id` | BIGINT FK | -> `termsheet_terrain.id` |
| `previous_status` | VARCHAR | |
| `current_status` | VARCHAR | |
| `created_at` | TIMESTAMPTZ | |

#### `termsheet_termsheet`
Termsheets (contractual agreements).

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |
| `signed_at` | TIMESTAMPTZ | Date signed |
| `zapsign_response` | TEXT/JSON | Digital signature response (non-null = signed) |

#### `termsheet_originator`
Origination agents/companies.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |
| `name` | VARCHAR | |

#### `prospecting_customeragent`
Customer/prospection agents.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |
| `name` | VARCHAR | e.g. "Lorena Lopez", "Carolina Castano" |

---

### Geographic

#### `territorial_region`
Departments/regions.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |
| `display_name` | VARCHAR | e.g. "Cesar, Colombia" |

#### `territorial_subregion`
Cities/municipalities.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |
| `region_id` | BIGINT FK | -> `territorial_region.id` |

---

### Construction & EPC

#### `epc_projectepc`
EPC (Engineering, Procurement, Construction) tracking.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |
| `project_id` | BIGINT FK | -> `minifarm_project.id` |
| `construction_advance` | FLOAT | Overall construction advance % (0-100) |

---

### Validation & Compliance

#### `validation_field`
Per-project or per-terrain validation fields (legal, electrical, forestry, civil).

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |
| `uuid` | UUID | Identifies field type (e.g. FPO, CAR, Estado Forestal) |
| `name` | VARCHAR | Human-readable field name |
| `status` | VARCHAR | approved, preapproved, pending, rejected, correction, no_apply, exonerated |
| `value` | TEXT | Field value (dates, text, select options) |
| `is_active` | BOOLEAN | |
| `is_parent` | BOOLEAN | |
| `project_id` | BIGINT FK | -> `minifarm_project.id` |
| `terrain_id` | BIGINT FK | -> `termsheet_terrain.id` |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |

Known UUIDs:
- `b9d37676-30be-49e8-bb21-c3109d2f7882` = FPO (Fecha Puesta en Operacion)
- `964f1aff-0483-43d8-8225-45066ec91c65` = Estado Forestal
- `35eb0abf-57ad-41fc-aaa1-37fe003af43c` = CAR (environmental authority)
- `e30f74cd-5843-4439-b6ac-462038dcd237` = Estudio de suelos (terrain field)
- `424475cd-70db-456f-b903-c5deec073f8c` = Topografia (terrain field)

#### `validation_weightfield`
Links validation_field to categories/subcategories with weights.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |
| `field_id` | BIGINT FK | -> `validation_field.id` |
| `category_id` | BIGINT FK | -> `validation_category.id` |
| `subcategory_id` | BIGINT FK | -> `validation_subcategory.id` |

#### `validation_category`
Categories: legal, electrical, forest, civil, epc, etc.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |
| `type` | VARCHAR | Category name |

#### `validation_subcategory`
Subcategories within each validation category.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |
| `type` | VARCHAR | Subcategory name |
| `weigth` | FLOAT | Weight for RTB calculation (note: typo in DB, "weigth") |

---

### Timeline & Activities

#### `timeline_timeline`
Project timelines.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |
| `project_id` | BIGINT FK | -> `minifarm_project.id` |
| `is_active` | BOOLEAN | |

#### `timeline_activity`
Activities within a project timeline.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |
| `timeline_id` | BIGINT FK | -> `timeline_timeline.id` |
| `category_id` | BIGINT FK | -> `timeline_activitycategory.id` |
| `status` | VARCHAR | |

#### `timeline_activitycategory`
Activity categories.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |
| `name` | VARCHAR | |

---

### Payments (from pagos_Backend)

#### `termsheet_payment`
Lease payments to landowners.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |
| (joined with `termsheet_payment_payment_project_concept`) | | |

#### `termsheet_payment_payment_project_concept`
M2M linking payments to project concepts.

| Column | Type | Notes |
|--------|------|-------|
| `payment_id` | BIGINT FK | -> `termsheet_payment.id` |
| (other FKs) | | |

#### `minifarm_paymentprojectconcept`
Payment concepts per project.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |

#### `termsheet_landlord`
Landowners receiving lease payments.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |

---

### Monitoring (from edubot/075bot)

#### `monitoring_discorduser`
Discord user profiles (read by edubot).

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |

---

## Tables in RequestsDB (separate database, same host)

Used for ECS (Estudio de Conexion Solar) tracking.

#### `supplies_supplyrequest`
ECS requests submitted to grid operators.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |
| `company_id` | INT | 117 = Unergy |
| `project` | INT | -> `minifarm_project.id` (cross-DB FK) |
| `grid_operator_id` | VARCHAR | |
| `documentation_status` | VARCHAR | completed, missing_topography, etc. |
| `tension_level` | VARCHAR | Voltage level in kV |
| `created` | TIMESTAMPTZ | |

#### `supplies_statussupplyrequest`
ECS status history.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |
| `supply_request_id` | BIGINT FK | -> `supplies_supplyrequest.id` |
| `status_id` | BIGINT FK | -> `supplies_optionstatussupplyrequest.id` |
| `created` | TIMESTAMPTZ | |

#### `supplies_optionstatussupplyrequest`
ECS status options.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |
| `name` | VARCHAR | e.g. "ECS aprobado", "ECS en proceso", "Rechazado" |
| `manager` | VARCHAR | |
| `order` | INT | Display order |

#### `supplies_circuit`, `supplies_substation`, `supplies_transformer`
Grid infrastructure tables (referenced in joins).

#### `supplies_company`
Companies registered in the platform.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INT PK | 117 = Unergy Energia Digital S.A.S |
| `is_owner` | BOOLEAN | |

#### `entities_request`
Government entity requests (ANLA, ANH, PNNC, MADS, etc.).

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |
| `entity_id` | BIGINT FK | -> `entities_entity.id` |
| `project_id` | INT | |
| `status` | VARCHAR | responded, radicated, sent |
| `created` | TIMESTAMPTZ | |

#### `entities_entity`
Government entities.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |
| `nomenclature` | VARCHAR | Code |
| `name` | VARCHAR | Full name |

---

## Tables Added by Edubot (live in originabotdb)

These are NOT original Django ORM tables -- they were added by the Edubot project:

- `discord_guilds` - Discord servers
- `discord_channels` - Channels linked to `minifarm_project.id`
- `discord_messages` - Raw messages (7-day retention)
- `channel_contexts` - AI-compressed channel context
- `daily_summaries` - AI daily summaries per channel
- `discord_alerts` - Automated alerts
- `discord_access_permissions` - User access control
- `discord_sync_log` - Sync execution log
- `discord_query_log` - Query audit log
- `channel_links` - Cross-guild channel relationships
- `api_keys` - External API key management
- `cross_guild_reports` - AI cross-guild comparison reports

---

## Tables Added by 075bot (live in originabotdb)

Used for CREG 174 deadline tracking:

- `alerts_sent` - Dedup table for sent alerts
- `creg_status_history` - Regulatory status snapshots
- `run_log` - Execution log

---

## Entity Relationship Summary

```
termsheet_terrain (land)
  |-- city_id -> territorial_subregion -> territorial_region
  |-- customer_agent_id -> prospecting_customeragent
  |-- originator_id -> termsheet_originator
  |-- terrainstatuschange (history)
  |-- validation_field (terrain-level: suelos, topografia)
  |
  +-- minifarm_project (1:N -- multiple projects per terrain)
        |-- termsheet_id -> termsheet_termsheet
        |-- stage changes -> minifarm_projectstagechange
        |-- validation_field (project-level: legal, electrical, etc.)
        |     +-- validation_weightfield -> category + subcategory
        |-- epc_projectepc (construction tracking)
        |-- timeline_timeline -> timeline_activity
        |-- investment_minifarm (capex, RTB)
        |     +-- investment_portfolio_minifarm -> investment_portfolio
        |           +-- investment_portfolio_investments -> investment_investment
        |-- termsheet_payment (lease payments)
        |-- discord_channels (edubot)
        |
        +-- [requestsdb] supplies_supplyrequest (ECS, cross-DB by project ID)
```

---

## Questions for Eduardo

1. **Django admin / models.py**: The Django ORM with ~280 tables is mentioned but NOT present in any cloned repo under `~/Claude/`. Is the Django project (OriginaBot proper) hosted in a different repo? What's the repo URL?

2. **Database credentials**: The `.env.example` files show placeholder credentials. The only real host found is `34.74.198.101` (GCP) in `pagos_Backend/settings.py` with user `silvia`. Is this still the production host? What read-only credentials should the operations backend use?

3. **Schema dump**: Can you provide a `pg_dump --schema-only originabotdb > schema.sql` from the production server? That would give us the full ~280 tables instead of the ~30 we can see via SQL queries in existing code.

4. **Missing tables**: The code references these tables but we have zero column info:
   - `monitoring_discorduser` (referenced by edubot as read-only)
   - `supplies_circuit`, `supplies_substation`, `supplies_transformer` (grid infra)
   - `supplies_company` (only know `id` and `is_owner`)
   - Full payment chain: `termsheet_payment` -> `termsheet_landlord`

5. **RequestsDB ownership**: Is `requestsdb` a separate Django project? Who maintains it? The boardneitor code connects to it for ECS data, and unergy-operaciones-backend references `supplies_*` tables.

6. **Write access**: All current consumers are read-only. If the operations backend needs to write (e.g., status updates, alerts), is there a write-enabled user, or should all writes go through the OriginaBot Django admin/API?

7. **Data freshness**: Is there a replication lag? All consumers connect directly to `34.74.198.101:5432`. Is this the primary or a replica?

---

## Coverage Summary

| Category | Tables found | Columns mapped | Source |
|----------|-------------|---------------|--------|
| Projects & Pipeline | 2 | ~25 | boardneitor, 075bot, pagos |
| Investment & Capital | 5 | ~20 | boardneitor |
| Terrain & Prospection | 5 | ~20 | boardneitor |
| Geographic | 2 | ~3 | boardneitor |
| Construction/EPC | 1 | ~3 | boardneitor |
| Validation | 4 | ~15 | boardneitor |
| Timeline | 3 | ~6 | boardneitor |
| Payments | 3 | partial | pagos_Backend |
| RequestsDB (ECS) | 6 | ~15 | boardneitor |
| Edubot additions | 12 | full | edubot |
| 075bot additions | 3 | minimal | 075bot |
| **Total discovered** | **~46** | | |
| **Estimated remaining** | **~234** | | Need `pg_dump --schema-only` |
