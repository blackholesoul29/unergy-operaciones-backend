# OriginabotDB Schema Discovery

> **Database:** `originabotdb` on `34.74.198.101:5432`
> **Framework:** Django ORM (Python)
> **Discovered:** 2026-05-18
> **Size:** 30 GB | **Tables:** 269 | **Indexes:** 1,000 | **Views:** 0 | **Foreign Keys:** 0 (Django manages at app level, `db_constraint=False`)

---

## Table of Contents

1. [Summary Statistics](#summary-statistics)
2. [Projects Domain](#1-projects-domain)
3. [Terrain / Land Domain](#2-terrain--land-domain)
4. [Landlords & People Domain](#3-landlords--people-domain)
5. [Termsheet Domain](#4-termsheet-domain)
6. [Contract Domain](#5-contract-domain)
7. [Payments Domain](#6-payments-domain)
8. [Investment & Portfolio Domain](#7-investment--portfolio-domain)
9. [Grid Operators & Engineering](#8-grid-operators--engineering)
10. [Easements Domain](#9-easements-domain)
11. [EPC (Construction) Domain](#10-epc-construction-domain)
12. [Prospecting & Contacts Domain](#11-prospecting--contacts-domain)
13. [Validation / Checklist Engine](#12-validation--checklist-engine)
14. [Timeline / Activities Domain](#13-timeline--activities-domain)
15. [Territorial / Geography Domain](#14-territorial--geography-domain)
16. [Visitor / Field Inspection Domain](#15-visitor--field-inspection-domain)
17. [Dataroom Domain](#16-dataroom-domain)
18. [Land Evaluator Domain](#17-land-evaluator-domain)
19. [Government Requests Domain](#18-government-requests-domain)
20. [WhatsApp Bot Domain](#19-whatsapp-bot-domain)
21. [Monitoring / DevOps Domain](#20-monitoring--devops-domain)
22. [GenAI Domain](#21-genai-domain)
23. [Accounting / HR Domain](#22-accounting--hr-domain)
24. [Identity & Auth Domain](#23-identity--auth-domain)
25. [Infrastructure Tables](#24-infrastructure-tables)
26. [Entity Relationship Map](#entity-relationship-map)
27. [Data Volume Summary](#data-volume-summary)

---

## Summary Statistics

| Metric | Value |
|--------|-------|
| Total tables | 269 |
| Total projects | 3,084 |
| Total terrains | 6,330 |
| Total landlords | 2,423 |
| Total termsheets | 672 |
| Total leasing contracts | 141 |
| Total payments | 3,221 |
| Total contacts (prospecting) | 13,295 |
| Total validation fields | 1,147,520 |
| Total audit log entries | 20,533,878 |
| Total dataroom files | 21,719 |
| Database size | 30 GB |

---

## 1. Projects Domain

### `minifarm_project` (3,084 rows, 39 cols) -- CENTRAL TABLE

The core entity. Every solar minifarm project. All `project_type = 'minifarm'`.

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| id | bigint | NO | PK |
| name | varchar | NO | e.g. `COLBOYT591P1_SOTAQUIRA_NORTE` (COL + dept code + terrain# + P# + city + zone) |
| project_type | varchar | NO | Always `'minifarm'` |
| stage | varchar | NO | Pipeline stage (see distribution below) |
| circuit | varchar | YES | Grid circuit name |
| lat / lng | double | YES | Project coordinates |
| area_m2 | double | NO | Land area in m2 |
| project_installed_power | double | NO | AC capacity kW (typically 996.0) |
| project_dc_capacity | double | NO | DC capacity kW (typically 1320.48) |
| project_panels_count | integer | NO | Panel count (typically 2016) |
| project_panels_description | varchar | YES | Panel model text |
| project_inverter_description | varchar | NO | Inverter model text |
| protection_elements_description | varchar | NO | Grid protection description |
| contract_type | varchar | YES | `rental` / `purchase` / `purchase_option` |
| annual_price | numeric | YES | Annual land lease COP |
| network_distance | double | NO | Distance to grid (m) |
| road_distance | double | NO | Distance to road (m) |
| project_extension | double | YES | |
| grid_operator_id | varchar | YES | FK to `grid_operator_request_gridoperator.code` |
| terrain_id | bigint | YES | FK to `termsheet_terrain.id` |
| termsheet_id | bigint | YES | FK to `termsheet_termsheet.id` |
| city_id | bigint | YES | FK to `territorial_city.id` |
| city_prev_id | integer | YES | Legacy FK to `cities_light_city.id` |
| clickup_task_id | varchar | YES | ClickUp integration |
| clickup_list_id | varchar | YES | ClickUp list |
| phase_id | varchar | YES | |
| supplies_status_external | varchar | YES | |
| supplies_status_internal_id | varchar | YES | |
| unergy_topic_name | varchar | YES | |
| drive | varchar | YES | Google Drive folder URL |
| odoo_analytic_account_id | varchar | YES | Odoo integration |
| banner | varchar | YES | |
| is_microfarm | boolean | NO | Always `false` (3,084/3,084) |
| has_been_order | boolean | NO | |
| rank | varchar | YES | |
| act_comment | text | YES | |
| created_at / updated_at | timestamptz | NO | |

#### Stage Distribution

| Stage | Count | Description |
|-------|-------|-------------|
| dead | 2,602 | Killed/rejected |
| prospect | 83 | Initial prospecting |
| due_diligence | 76 | Under due diligence |
| uci | 67 | UCI process |
| paused | 65 | Paused |
| portfolio | 35 | In investment portfolio |
| negociation | 34 | In negotiation |
| operation | 30 | Operational (generating) |
| signed | 28 | Contract signed |
| construction | 27 | Under construction |
| deploy | 23 | Being deployed |
| bt_and_contract | 14 | BT + contract stage |

#### Contract Type Distribution

| Type | Count |
|------|-------|
| rental | 2,827 |
| purchase | 165 |
| purchase_option | 36 |

### `minifarm_projectstagechange` (9,497 rows)

Stage transition audit trail.

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| id | bigint | NO | PK |
| project_id | bigint | NO | FK to project |
| previous_stage | varchar | YES | |
| current_stage | varchar | NO | |
| justification | varchar | YES | Reason for change |
| review_date | date | YES | Scheduled review |
| review_date_notified_at | timestamptz | YES | |
| created_at | timestamptz | NO | |

### `minifarm_projectprice` (6,011 rows)

Price history per project.

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| id | bigint | NO | PK |
| project_id | bigint | NO | FK |
| annual_price | double | NO | COP/year |
| reason | varchar | NO | |
| type | varchar | NO | |
| description | text | YES | |
| apply_from_date / apply_until_date | date | NO/YES | |
| created_at / updated_at | timestamptz | NO | |

### `minifarm_viability` (34,235 rows)

Per-project viability assessments by discipline.

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| id | bigint | NO | PK |
| project_id | bigint | YES | FK |
| terrain_id | bigint | YES | FK |
| type | varchar | NO | `civil` / `electrical` / `environmental` / `forest` / `legal` / `origination` / `other` |
| status | varchar | NO | `viable` / `not_viable` / `viable_conditional` / `pending` / `correction` |
| comment | text | YES | |
| conditional_comment | text | YES | |
| viability_person | varchar | YES | |
| update_at | timestamptz | NO | |

#### Viability Status by Type

| Type | viable | conditional | not_viable | pending |
|------|--------|------------|------------|---------|
| civil | 97 | 263 | 2,170 | 524 |
| electrical | 169 | 120 | 2,083 | 700 |
| environmental | 101 | 184 | 4,175 | 1,867 |
| forest | 101 | 87 | 4,172 | 1,970 |
| legal | 80 | 120 | 1,558 | 4,563 |
| origination | 62 | - | 4,160 | 2,108 |

### `minifarm_viabilityfile` (rows linked to viability)

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| viability_id | bigint | FK |
| file | varchar | File path |
| updated_at | timestamptz | |

### `minifarm_filesofproject` (582 rows)

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| project_id | bigint | FK |
| file | varchar | |
| type | varchar | |
| created_at / updated_at | timestamptz | |

### `minifarm_paymentprojectconcept` (3,446 rows)

Payment concepts per project (land lease terms).

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| project_id | bigint | FK |
| project_stage | varchar | |
| name | varchar | |
| type | varchar | |
| amount | bigint | COP |
| area_m2 | double | |
| annual_price | double | |
| periodicity | integer | |
| total_payments | integer | |
| is_advance_payment | boolean | |
| comment | text | |
| created_at | timestamptz | |

### `minifarm_projectpowerofattorney` (rows)

Power of attorney documents per project.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| project_id | bigint | FK |
| type | varchar | |
| status | varchar | |
| generated_document / signed_document | varchar | File paths |
| generated_at / sent_at / signed_at | timestamptz | |

### `minifarm_previousprojectname` (rows)

Historical name changes.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| project_id | bigint | FK |
| name | varchar | Previous name |
| main | boolean | |
| created / modified | timestamptz | |

---

## 2. Terrain / Land Domain

### `termsheet_terrain` (6,330 rows, 54 cols) -- SECOND MOST IMPORTANT TABLE

The land parcel. Multiple projects can share one terrain. ~2:1 ratio terrains to projects.

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| id | bigint | NO | PK |
| name | varchar | NO | e.g. `COLBOYT604` |
| status | varchar | NO | Pipeline status |
| label | varchar | NO | `undefined` / etc. |
| area_m2 | double | NO | Land area |
| latitude / longitude | double | NO | GPS coords |
| radiation | double | NO | Solar radiation kWh/m2/day |
| tilt | varchar | NO | Land tilt/slope |
| has_threephase_network | boolean | NO | 3-phase grid available |
| has_access_road | boolean | NO | Road access |
| has_servitude | boolean | YES | Easement present |
| minimum_requirements | boolean | NO | Meets minimum criteria |
| completed_documentation | boolean | NO | All docs complete |
| registry_number | varchar | YES | Land registry # |
| registry_id | varchar | YES | Matricula inmobiliaria |
| land_boundaries_registry | varchar | YES | |
| sketch | varchar | YES | Sketch file |
| hamlet | varchar | NO | Vereda name |
| description | text | YES | |
| drive | varchar | YES | Google Drive URL |
| google_maps | varchar | YES | Google Maps URL |
| internal_code | varchar | YES | |
| ip_office | varchar | YES | Instrumentos publicos office |
| location | varchar | YES | |
| use_land | varchar | YES | Land use classification |
| actual_address / previous_address | varchar | YES | |
| block_number / lot_number | varchar | YES | Cadastral |
| commune / neighborhood / township | varchar | YES | |
| sector_id | bigint | YES | FK to sector |
| socioeconomic_status | varchar | YES | Estrato |
| soil_classification | varchar | YES | |
| subdivision_license | varchar | YES | |
| purchase_option | boolean | NO | |
| purchase_option_area_m2 | double | YES | |
| purchase_option_years_validity | integer | YES | |
| purchase_optionm_amount_per_hectare | double | YES | |
| apportionment | varchar | YES | |
| special_characteristic | varchar | NO | |
| is_top | boolean | NO | Priority terrain flag |
| ctl_date_generated | date | YES | CTL generation date |
| environment | jsonb | YES | Environmental data JSON |
| originator_id | bigint | YES | FK to originator |
| solenium_originator_id | bigint | YES | Solenium partner originator |
| contact_id | bigint | YES | FK to prospecting contact |
| customer_agent_id | bigint | YES | FK to customer agent |
| lost_reason_id | bigint | YES | FK to lost reason |
| city_id | bigint | YES | FK to territorial_city |
| city_prev_id | integer | YES | Legacy city FK |
| created_at / updated_at | timestamptz | NO | |

#### Terrain Status Distribution

| Status | Count |
|--------|-------|
| dead | 5,660 |
| follow-up | 181 |
| completed | 141 |
| stand_by | 106 |
| check | 103 |
| pre-validation | 49 |
| new | 34 |
| uci | 31 |
| negotiation | 25 |

### `termsheet_terrainstatuschange` (rows)

Status transition audit for terrains.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| terrain_id | bigint | FK |
| previous_status | varchar | |
| current_status | varchar | |
| justification | varchar | |
| review_date | date | |
| review_date_notified_at | timestamptz | |
| created_at | timestamptz | |

### `termsheet_terraincomment` (16,403 rows)

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| terrain_id | bigint | FK |
| comment | text | |
| category | varchar | |
| unergy_investment_user_name | varchar | |
| external_user_id | bigint | |
| hidden | boolean | |
| created_at / updated_at | timestamptz | |

### `termsheet_terrainimage` (210 rows)

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| terrain_id | bigint | FK |
| file | varchar | Image file path |

### `termsheet_filesofterrain` (29,750 rows)

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| terrain_id | bigint | FK |
| name_file | varchar | |
| file | varchar | File path |
| category | varchar | |
| created_at / updated_at | timestamptz | |

### `termsheet_previousterrainname` (110 rows)

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| terrain_id | bigint | FK |
| name | varchar | |
| main | boolean | |

### `termsheet_boundary` (0 rows)

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| terrain_id | bigint | FK |
| cardinal_point | varchar | N/S/E/W |
| length | integer | |
| border_with | varchar | Adjacent property |

### `termsheet_settingsofterrain` (rows)

Global terrain settings key-value store.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| name | varchar | Setting key |
| value | varchar | Setting value |

---

## 3. Landlords & People Domain

### `termsheet_landlord` (2,423 rows, 41 cols)

Land owners / signers of lease agreements.

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| id | bigint | NO | PK |
| name | varchar | NO | Full name |
| document_type | varchar | NO | CC, NIT, etc. |
| document_number | varchar | YES | |
| person_type | varchar | YES | Natural/juridica |
| responsability_type | varchar | YES | Tax type |
| address | varchar | YES | |
| telephone | varchar | YES | |
| telephone_country_code | varchar | NO | |
| email | varchar | YES | |
| legal_representative_name | varchar | YES | For companies |
| legal_representative_id | varchar | YES | |
| is_unergy_signer | boolean | NO | Internal signer |
| signature_type | varchar | NO | |
| available | boolean | NO | |
| termsheet_receiver | boolean | NO | Receives termsheet |
| is_new_payment_receiver | boolean | NO | |
| is_income_withholding | boolean | NO | |
| documents_status | varchar | NO | |
| type_of_linked_person | varchar | NO | |
| bank_id | bigint | YES | FK |
| bank_account | varchar | YES | |
| bank_account_type | varchar | YES | |
| bank_certificate | varchar | YES | File |
| rut | varchar | YES | File |
| national_document_file | varchar | YES | File |
| power_of_attorney_document | varchar | YES | File |
| charge_account_number | integer | YES | |
| payment_percentage | double | YES | |
| id_odoo | integer | YES | Odoo integration |
| zapsign_* | various | YES | Electronic signature fields |
| city_id | bigint | YES | FK |

### `termsheet_landlordterrain` (2,059 rows)

Many-to-many: landlord <-> terrain.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| landlord_id | bigint | FK |
| terrain_id | bigint | FK |
| payment_percentage | double | % of rent this landlord receives |
| signer | boolean | Is this landlord a signer |
| termsheet_receiver | boolean | Receives the termsheet |

### `termsheet_originator` (34 rows)

Field originators (sales agents who source terrains).

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| id | bigint | NO | PK |
| name | varchar | NO | |
| role | varchar | NO | |
| document_type / document_number | varchar | NO/YES | |
| email / telephone | varchar | YES | |
| discord_id | varchar | YES | |
| clickup_id | varchar | NO | |
| user_id | integer | YES | FK to auth_user |
| is_active | boolean | NO | |
| city_id | bigint | YES | FK |

### `termsheet_company` (2 rows)

Company entities (Unergy companies).

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| name | varchar | |
| document_number | varchar | NIT |
| email / telephone / address | varchar | |
| rut_file | varchar | |
| odoo_company_id | integer | |
| email_domain | varchar | |
| payroll_account_number | varchar | |

### `termsheet_terrainpowerofattorney` (rows)

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| terrain_id | bigint | FK |
| type | varchar | |
| status | varchar | |
| generated_document / signed_document | varchar | |
| generated_at / sent_at / signed_at | timestamptz | |

---

## 4. Termsheet Domain

### `termsheet_termsheet` (672 rows, 28 cols)

The lease termsheet -- commercial terms before formal contract.

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| id | bigint | NO | PK |
| rent_area_m2 | double | NO | Leased area |
| rent_annual_cost_cop | double | NO | Annual rent COP |
| apportionment | varchar | NO | `none` / etc. |
| purchase_option | boolean | NO | |
| purchase_option_area_m2 | double | YES | |
| purchase_option_years_validity | integer | YES | |
| purchase_optionm_amount_per_hectare | double | YES | |
| first_payment_amount | double | NO | |
| frequency | varchar | NO | `monthly` / etc. |
| initial_percentage | double | NO | IPC increase % |
| percentage_to_increase | double | NO | |
| initial_percentage_by_originator | double | NO | |
| initial_percentage_defined_by | varchar | NO | |
| periodicity_accumulated | integer | NO | |
| months_to_validate_terrain | double | NO | |
| has_servitude | boolean | YES | |
| enable_automatic_payment | boolean | NO | |
| is_validated | boolean | NO | |
| is_signed_by_users | boolean | NO | |
| originator_id | bigint | YES | FK |
| docx_id | bigint | YES | FK to contract_docx |
| file | varchar | YES | Generated PDF |
| file_mannually_signed | varchar | YES | Manually signed PDF |
| signed_at | timestamptz | YES | |
| created_at | timestamptz | YES | |
| zapsign_response | jsonb | YES | |
| zapsign_signer_token_list | ARRAY | NO | |

### `termsheet_termsheetmodel` (rows)

Templates for termsheet commercial terms.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| name | varchar | Model name |
| version / status | varchar | |
| first_payment_amount | double | |
| frequency | varchar | |
| initial_percentage / percentage_to_increase | double | |
| periodicity_accumulated | integer | |
| months_to_validate_terrain | double | |

### `termsheet_termsheetprice` (rows)

Price change history per termsheet.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| termsheet_id | bigint | FK |
| rent_annual_cost_cop | double | |
| reason / type | varchar | |
| description | text | |
| apply_from_date / apply_until_date | date | |

### `termsheet_termsheetsigner` (rows, 26 cols)

Signers of the termsheet (landlords + Unergy reps).

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| termsheet_id | bigint | FK |
| name | varchar | |
| document_type / document_number | varchar | |
| email / telephone / address | varchar | |
| is_unergy_signer | boolean | |
| signature_type | varchar | |
| zapsign_* | various | Electronic signature |
| city_id | bigint | FK |

### `termsheet_clause` / `termsheet_subclause`

Clause library for termsheet models.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| termsheet_model_id / clause_id | bigint | FK (parent) |
| title | varchar | |
| content | text | |
| order | integer | |
| image | varchar | |

### `termsheet_validation` (879 rows) / `termsheet_validationperterrain` (867 rows)

Validation checklists applied to terrains.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| tipo_de_validacion | varchar | Validation type |
| nombre_de_validacion | varchar | Name |
| peso_de_validacion | double | Weight/score |
| status | integer | |
| position | double | |

### `termsheet_activities` (3,516 rows) / `termsheet_activitiestemplate` (12 rows)

Activities required for terrain validation.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| validations_id / validation_template_id | bigint | FK |
| name | varchar | |
| descripcion | text | |
| estado | boolean | Completed |
| document_uploaded | boolean | |

---

## 5. Contract Domain

### `termsheet_leasingcontract` (141 rows, 14 cols)

Formal leasing contracts (generated from termsheets).

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| id | bigint | NO | PK |
| termsheet_id | bigint | NO | FK |
| project_id | bigint | YES | FK |
| status | varchar | NO | All `'created'` |
| include_servitude | boolean | YES | |
| is_signed_by_users | boolean | NO | |
| contract_file_initial | varchar | YES | |
| contract_file_reviewed | varchar | YES | |
| contract_final_pdf | varchar | YES | |
| contract_final_pdf_signed | varchar | YES | |
| signed_at | timestamptz | YES | |
| created_at | timestamptz | YES | |
| zapsign_response | jsonb | YES | |
| zapsign_signer_token_list | ARRAY | NO | |

### `termsheet_leasingcontractsigner` (rows, 26 cols)

Contract signers (same structure as termsheetsigner).

### `contract_contract` (30 rows)

Separate contract model (appears to be an older/parallel system).

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| termsheet_id | bigint | FK |
| project_id | bigint | FK |
| docx_id | bigint | FK to contract_docx |
| has_servitude | boolean | |
| is_signed_by_users | boolean | |
| file / file_mannually_signed | varchar | |
| signed_at / created_at | timestamptz | |
| zapsign_response | jsonb | |

### `contract_clause` (15 rows) / `contract_clauseparagraph` (19 rows)

Contract clause library.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| title | varchar | |
| content | text | |
| type | varchar | |
| order | integer | |

### `contract_termsheetclause` (1,512 rows)

Clauses associated with specific termsheets.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| termsheet_id | bigint | FK |
| template_id | bigint | FK |
| title | varchar | |
| content | text | |
| type | varchar | |
| order | integer | |

### `contract_variable` (3,198 rows) / `contract_variabledescription` (rows)

Template variable system for contract generation.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| key | varchar | Variable placeholder key |
| value | varchar | Resolved value |
| docx_id | bigint | FK |
| object_id | varchar | |
| variable_description_id | bigint | FK |

### `contract_docx` (rows)

Generated DOCX documents.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| name | varchar | |
| external_id | varchar | Google Drive ID |

---

## 6. Payments Domain

### `termsheet_payment` (3,221 rows, 37 cols)

Land lease payments to landlords. UUID primary key.

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| id | uuid | NO | PK |
| alt_id | bigint | NO | Sequential alt ID |
| termsheet_id | bigint | YES | FK |
| land_lord_id | bigint | YES | FK |
| payment_receiver_id | bigint | YES | FK |
| sheet_id | bigint | YES | FK to paymentsheetrecord |
| status | varchar | NO | `paid` / `wait_for_document` / `uploaded_documents` |
| date | date | NO | Payment due date |
| amount | bigint | NO | COP amount |
| iva_amount | bigint | NO | IVA |
| income_withholding | bigint | NO | Retefuente |
| iva_withholding | bigint | NO | ReteIVA |
| advance_payment | boolean | NO | |
| advance_payment_instance_id | bigint | YES | FK |
| creation_type | varchar | NO | `manual` / `automatic` |
| is_validated | boolean | NO | |
| charge_account / charge_account_sent | varchar | YES | Account doc files |
| charge_account_number | varchar | YES | |
| charge_account_signed_at | timestamptz | YES | |
| electronic_invoice | varchar | YES | |
| social_security_certificate | varchar | YES | |
| payment_voucher | varchar | YES | |
| payment_types | ARRAY | YES | |
| project_payment_description | jsonb | YES | |
| charge_account_whatsapp_response | jsonb | YES | |
| charge_account_whatsapp_sent | boolean | NO | |
| charge_account_zapsign_sign_url | varchar | YES | |
| zapsign_token | varchar | YES | |
| notified_paid_to_originator / notified_paid_to_receiver | boolean | NO | |
| notified_paid_to_originator_at / notified_paid_to_receiver_at | timestamptz | YES | |
| comment | text | YES | |
| created_at / updated_at | timestamptz | NO | |

#### Payment Status Distribution

| Status | Count |
|--------|-------|
| paid | 2,746 |
| wait_for_document | 362 |
| uploaded_documents | 113 |

### `termsheet_paymentreceiver` (136 rows, 29 cols)

Payment recipients (may differ from landlord).

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| termsheet_id | bigint | FK |
| name | varchar | |
| document_type / document_number | varchar | |
| bank_id | bigint | FK |
| bank_account / bank_account_type | varchar | |
| payment_percentage | double | |
| is_monthly_receiver | boolean | |
| termsheet_receiver | boolean | |
| person_type / responsability_type | varchar | |
| bank_certificate / rut / national_document_file | varchar | Files |

### `termsheet_advancepayment` (11 rows)

Advance payment definitions.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| project_id | bigint | FK |
| amount | bigint | COP |
| max_payment_cap | bigint | COP cap |

### `termsheet_paymentsheetrecord` (rows)

Bulk payment sheet uploads.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| file | varchar | |
| uploaded_by | varchar | |

### `termsheet_bankandrutrequest` (341 rows)

Requests to landlords for bank/RUT documents.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| land_lord_id | bigint | FK |
| request_date | timestamptz | |
| is_completed | boolean | |

### `termsheet_remindermessage` (11 rows)

Reminder messages sent to various recipients.

---

## 7. Investment & Portfolio Domain

### `investment_investment` (78 rows)

Investors/funds interested in Unergy projects.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| name | varchar | Investor name |
| code | varchar | |
| email / phone | varchar | |
| source | varchar | `OP`/`LO`/`FL`/`RF`/`OT`/`IB` |
| status | varchar | `closed`/`investment`/`blocked`/`open`/`portfolio`/`dd`/`nda` |
| currency_type | varchar | `cop`/etc. |
| financiation_type | varchar | `equity`/etc. |
| clusters_interest | boolean | |
| fulfilment_ifc | boolean | IFC compliance |
| max_inversion_capacity / minimum_inversion_capacity | double | |
| minimum_radiation | double | |
| prefer_structure | varchar | |
| business_registry / rut | varchar | |
| color_hsba_id | bigint | FK |

### `investment_portfolio` (114 rows)

Investment portfolios (groups of minifarms for investors).

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| name | varchar | |
| expected | integer | Expected # of minifarms |
| financing | varchar | `DE` (debt) / `EQ` (equity) |
| color_hsba_id | bigint | FK |
| search_vector | tsvector | |

### `investment_minifarm` (3,084 rows)

Investment view of each project (1:1 with minifarm_project).

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| project_id | bigint | FK to minifarm_project |
| name | varchar | |
| capex | numeric | Capital expenditure |
| priority | varchar | `UR`/`ME`/etc. |
| percentage_of_completion | numeric | 0.00 - 1.00 |
| construction_start / construction_end | date | |
| first_advance / first_disbursement | date | |
| search_vector | tsvector | |

### `investment_ppa` (22 rows)

Power Purchase Agreements.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| name | varchar | e.g. `Unergy`, `GREENYELLOW`, `NEU I`, `PROELÉCTRICA` |
| number_of_years | integer | |
| start_date | date | |
| off_taker_id | bigint | FK to offtaker |
| expected_minifarms | integer | |

### `investment_offtaker` (16 rows)

PPA energy buyers.

| Name |
|------|
| Terpel, Unergy, NEU, GreenYellow, GreenWood, Nitro Energy, EDF, Proeléctrica, Afinia, Aire, ESSA, Santa Fé Energy, Lumina, Klik, CHEC, CENS |

### `investment_supplie` (rows)

Yearly supply pricing per PPA.

### Junction tables

| Table | Rows | Relationship |
|-------|------|-------------|
| `investment_portfolio_minifarm` | 247 | Portfolio <-> Minifarm |
| `investment_portfolio_investments` | 138 | Portfolio <-> Investment |
| `investment_portfolio_bank` | 22 | Portfolio <-> Bank |
| `investment_ppa_minifarms` | - | PPA <-> Minifarm |
| `investment_ppa_portfolios` | - | PPA <-> Portfolio |
| `investment_investment_deal_leader` | - | Investment <-> DealLeader |
| `investment_investment_financial_leader` | - | Investment <-> FinancialLeader |
| `investment_investment_technical_leader` | - | Investment <-> TechnicalLeader |
| `investment_investment_interest_zones` | - | Investment <-> Region |

### `investment_commentminifarm` (rows)

Comments on minifarms (investment review).

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| minifarm_id | bigint | FK |
| terrain_id | bigint | FK |
| status | varchar | |
| comment | text | |
| type_validation | varchar | |
| username | varchar | |
| hidden | boolean | |

### `investment_bank` (8 rows)

Banks involved in project financing.

### `investment_dataroomfolder` (72,796 rows)

Data room folder structure for investment due diligence.

### `investment_minifarmdataroom` (rows)

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| minifarm_id | bigint | FK |

### `investment_minifarmportfoliohistory` (rows)

Portfolio assignment change log.

---

## 8. Grid Operators & Engineering

### `grid_operator_request_gridoperator` (21 rows)

Colombian electricity grid operators.

| Code | Name | Legal Name | Automated | In Termsheets |
|------|------|-----------|-----------|---------------|
| afinia | Afinia | CARIBEMAR DE LA COSTA S.A.S E.S.P. | Yes | Yes |
| aire | Air-e | AIR-E S.A.S E.S.P. | Yes | Yes |
| celsia | CELSIA | CELSIA | No | Yes |
| essa | ESSA | ELECTRIFICADOR DE SANTANDER S.A. E.S.P. | Yes | Yes |
| ebsa | Energia de Boyaca | - | No | No |
| enel | Enel | - | No | No |
| cens | CENS | - | Yes | No |
| epm | EPM | - | No | No |
| electrohuila | Electro Huila | - | No | No |
| emsa | EMSA | - | No | No |
| enerca | ENERCA | - | No | No |
| chec | CHEC | - | No | No |
| + 9 others | | | | |

#### Projects per Grid Operator

| Operator | Projects |
|----------|----------|
| afinia | 1,060 |
| aire | 533 |
| essa | 299 |
| celsia | 291 |
| ebsa | 247 |
| enel | 152 |
| cens | 125 |
| epm | 99 |
| electrohuila | 52 |
| emsa | 52 |
| enerca | 49 |

### `engineering_gridoperatordocument` (16 rows)

Grid operator document submissions.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| project_id | bigint | FK |
| format_id | bigint | FK |
| input_file / output_file | varchar | |
| date_time_created | timestamptz | |

### `engineering_gridoperatordocumentformat` (rows)

Document format templates.

### `termsheet_institutionrequest` (25 rows)

Formal requests to institutions (grid operators, municipalities).

| Column | Type | Notes |
|--------|------|-------|
| id | uuid | PK |
| project_id | bigint | FK |
| request_type | varchar | |
| recipient | varchar | |
| subject / body | text | |
| status | varchar | |
| external_code_1 / external_code_2 | varchar | Tracking codes |
| date_time | timestamptz | |
| date_time_acknowledged | timestamptz | |

---

## 9. Easements Domain

### `easements_easement` (190 rows)

Easement (servidumbre) records for terrain access/grid connection.

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| id | bigint | NO | PK |
| terrain_id | bigint | YES | FK |
| type | varchar | NO | `own` / `foreign` / `public` |
| character | varchar | NO | `electrical` |
| foreign_status | varchar | NO | `pending` / etc. |
| public_status | varchar | NO | `initial` / etc. |
| price | double | NO | COP |
| agency | varchar | YES | e.g. `ani` |
| contract / letter | varchar | YES | File paths |
| comment | text | YES | |
| created_at / updated_at | timestamptz | NO | |

### `easements_easementviability` (rows)

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| easement_id | bigint | FK |
| team | varchar | |
| concept | text | |
| status | varchar | |

### `easements_easementlandlord` / `easements_easementcontact` / `easements_easementannexes`

Junction tables linking easements to landlords, contacts, and file annexes.

---

## 10. EPC (Construction) Domain

### `epc_epc` (1 row)

EPC (Engineering, Procurement, Construction) companies.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| name | varchar | |
| nit | varchar | |
| address / telephone / email | varchar | |
| logo | varchar | |

### `epc_projectepc` (526 rows)

EPC assignment per project.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| project_id | bigint | FK |
| epc_id | bigint | FK |
| construction_advance | double | 0-1 completion |

### `epc_epcasignee` (6 rows)

EPC team members.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| epc_id | bigint | FK |
| first_name / last_name | varchar | |
| profile | varchar | Role/profile |
| document_type / document_number | varchar | |
| email / telephone | varchar | |

### `epc_epcfolder` / `epc_epcfoldertemplate`

Document folder structure per EPC project.

### `epc_epcprojectfile` (rows) / `epc_epcprojectreport` (rows)

Construction files and reports per project.

---

## 11. Prospecting & Contacts Domain

### `prospecting_contact` (13,295 rows)

Landowner contacts from prospecting campaigns.

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| id | bigint | NO | PK |
| name | varchar | NO | |
| email | varchar | YES | |
| telephone | varchar | NO | |
| telephone_country_code | varchar | NO | |
| address | text | YES | |
| campaign | varchar | NO | Source campaign |
| final_step_id | bigint | NO | FK to step |
| identity_document_file | varchar | YES | |
| created_at / updated_at | timestamptz | NO | |

### `prospecting_customeragent` (34 rows)

Customer agents who do prospecting.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| name | varchar | |
| email | varchar | |
| user_id | integer | FK to auth_user |

### `prospecting_step` (1 row)

Pipeline steps for contacts.

### `prospecting_pre_validation` (2,161 rows)

Pre-validation results per terrain.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| terrain_id | bigint | FK |
| is_valid | boolean | |
| count_of_prospects / count_of_valid_prospects | integer | |
| igac_names | jsonb | IGAC cadastral names |
| legal_validation | boolean | |
| legal_validation_result | jsonb | |
| prospects_file | varchar | |

### `prospecting_prospecting` (3 rows)

Prospecting area polygons.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| pre_validation_id | bigint | FK |
| name | varchar | |
| area | double | |
| centroid | varchar | |
| coordinates | text | Polygon coords |
| is_valid | boolean | |

### `prospecting_contactnote` (1,391 rows)

Notes on contacts.

### `prospecting_chattigoreport` (61,488 rows)

Chatbot (Chattigo) conversation reports with landowners.

| Column | Type | Notes |
|--------|------|-------|
| id_chat | bigint | PK |
| campaign / did / agent | varchar | |
| user_nickname / user_phonenumber | varchar | |
| start_date / end_date | timestamptz | |
| duration | integer | Seconds |
| messages_count / client_messages_count | integer | |
| channel | varchar | |
| state | varchar | |

### `prospecting_lostreason` (rows)

Reasons for lost prospects.

### `prospecting_department` (57 rows)

Departments enabled for prospecting.

### `prospecting_energyreportmessage` (6 rows)

Energy report messages linked to contacts and terrains.

---

## 12. Validation / Checklist Engine

The largest data volume after audit logs. A generic, configurable validation field system.

### `validation_field` (1,147,520 rows, 24 cols) -- LARGEST BUSINESS TABLE

Individual validation field instances per project/terrain.

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| id | bigint | NO | PK |
| name | varchar | NO | Field label |
| description | text | YES | |
| type | varchar | NO | Field type |
| value | varchar | YES | Current value |
| status | varchar | NO | |
| type_association | varchar | NO | |
| order | double | NO | |
| uuid | varchar | NO | Unique field identifier |
| is_active | boolean | NO | |
| is_parent | boolean | NO | |
| has_investment_view | boolean | NO | |
| has_view | boolean | NO | |
| can_edit_value | boolean | NO | |
| show_status | boolean | NO | |
| comment | text | YES | |
| extra_file | varchar | YES | |
| select_id | bigint | YES | FK to validation_select |
| parent_id | bigint | YES | FK self-reference |
| project_id | bigint | YES | FK |
| terrain_id | bigint | YES | FK |
| search_vector | tsvector | YES | |
| created_at / updated_at | timestamptz | NO | |

### `validation_templatefield` (244 rows)

Template definitions for validation fields.

### `validation_weightfield` (1,164,214 rows)

Weighted scores per field + category + subcategory.

### `validation_select` / `validation_option` / `validation_select_options`

Dropdown option definitions.

### `validation_subfield` (4,021 rows)

Sub-fields with expiration tracking.

### `validation_template` / `validation_category` / `validation_subcategory`

Template + category hierarchy.

### `validation_fieldaction` (rows)

Automated actions triggered by field changes (Discord webhooks, etc.).

### `validation_dynamicfield` / `validation_dependentfield`

Dynamic field relationships and dependencies.

---

## 13. Timeline / Activities Domain

### `timeline_timeline` (418 rows)

Project timelines linking to templates.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| project_id | bigint | FK |
| template_id | bigint | FK |
| name | varchar | |
| is_active | boolean | |

### `timeline_activity` (15,466 rows)

Individual activities in project timelines.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| timeline_id | bigint | FK |
| category_id | bigint | FK |
| activity_template_id | bigint | FK |
| parent_activity_id | bigint | FK (self) |
| name | varchar | |
| duration | integer | Days |
| start_date / end_date | date | |
| status | varchar | |
| order | integer | |
| days_from_dependency_start / days_from_dependency_end | integer | |

### `timeline_activitycategory` (rows)

Activity categories with colors.

### `timeline_activitytemplate` / `timeline_timelinetemplate`

Template definitions for timelines and activities.

### `timeline_activity_dependency` / `timeline_activitytemplate_dependency`

Activity dependency relationships (from/to).

---

## 14. Territorial / Geography Domain

### `territorial_city` (1,169 rows, 19 cols)

Colombian municipalities with geo data.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| name / name_ascii / slug | varchar | |
| display_name / search_names | varchar/text | |
| latitude / longitude | numeric | |
| population | bigint | |
| or_code / or_name | varchar | Grid operator codes |
| dian_code | varchar | |
| country_id | bigint | FK |
| region_id | bigint | FK |
| subregion_id | bigint | FK |
| geoname_id | integer | |
| feature_code / timezone | varchar | |

### `territorial_region` (57 rows)

Departments (departamentos).

### `territorial_subregion` (1,346 rows)

Sub-regions / provinces.

### `territorial_locality` (5,586 rows) / `territorial_neighborhood` (20,238 rows)

Localidades and barrios.

### `territorial_or*` tables

Grid operator territorial mappings:
- `territorial_orlocality` (10,998 rows)
- `territorial_orneighborhood` (24,329 rows)
- `territorial_orregion` (50 rows)
- `territorial_orsubregion` (1,572 rows)

Each maps a territorial entity to a `grid_operator_id`.

### `territorial_victimizationriskindex` (1,122 rows)

Armed conflict victimization risk index per municipality.

### Legacy: `cities_light_*` tables

Older geographic data (django-cities-light). Being migrated to `territorial_*`.

### `termsheet_subregionclimaticzone` (1,091 rows)

Climatic zones per sub-region (relevant for solar radiation estimates).

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| sub_region_id | bigint | FK |

### `termsheet_sector` (0 rows)

Sectors within sub-regions.

---

## 15. Visitor / Field Inspection Domain

### `visitor_visit` (120 rows, 18 cols)

Field visits to terrains.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| terrain_id | bigint | FK |
| visitor_id | bigint | FK |
| visit_type_id | bigint | FK |
| datetime | timestamptz | |
| status | varchar | |
| attended_by_id / attended_by_name | varchar | |
| attended_by_landlord | boolean | |
| comment / observation | text | |
| record | varchar | |
| active | boolean | |
| finished_at / last_seen_at | timestamptz | |

### `visitor_visitor` (25 rows)

People who conduct field visits.

### `visitor_visitreport` (647 rows)

Georeferenced reports from visits.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| visit_id | bigint | FK |
| latitude / longitude | double | |
| type | varchar | |
| priority | varchar | |
| water_type | varchar | Water source type |
| comment | text | |

### `visitor_forestalreport` (25 rows)

Tree/forest surveys during visits.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| visit_id | bigint | FK |
| tree_species_id | bigint | FK |
| latitude / longitude | double | |
| tree_height / commercial_tree_height | double | |
| diameter_crown_projection_ns / diameter_crown_projection_eo | double | |
| circunference_at_chest_height | double | |
| phytosanitary_status | varchar | |
| hedge | varchar | |
| type | varchar | |

### `visitor_treespecies` (45 rows)

Tree species catalog.

### `visitor_note` (2 rows) / `visitor_visitfiles` (3 rows)

Visit notes and file attachments.

### `visitor_polygontrack` (27 rows)

GPS polygon tracks recorded during visits.

### `visitor_visitobservationlog` (10 rows) / `visitor_visitparticipant` (61 rows)

Observation logs and participant records.

---

## 16. Dataroom Domain

### `dataroom_duediligence` (30 rows)

Due diligence processes for investors.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| name | varchar | |
| active | boolean | |
| create_default_folders | boolean | |
| folder_id / parent_folder_id | bigint | FK |

### `dataroom_file` (21,719 rows)

Files in the data room (Google Drive sync).

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| name | varchar | |
| google_id | varchar | Drive file ID |
| mime_type | varchar | |
| web_view_link / web_content_link | varchar | |
| size | numeric | |
| created_time / modified_time | timestamptz | |
| deleted | boolean | |
| parent_id / target_id | bigint | FK |

### `dataroom_projectfolder` (250 rows)

Google Drive folders mapped to projects.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| project_id | bigint | FK |
| folder_id | bigint | FK to dataroom_file |
| sync_status | varchar | |
| sync_date | timestamptz | |

### `dataroom_investor` / `dataroom_permission`

Investor access and Google Drive permission management.

---

## 17. Land Evaluator Domain

### `land_evaluator_category` (rows) / `land_evaluator_criterion` (18 rows)

AHP-based land evaluation criteria with comparison matrices.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| name | varchar | |
| category_id | bigint | FK |
| criterion_type | varchar | |
| evaluation_type | varchar | |
| weight | double | AHP weight |
| values_matrix / comparison_matrix | jsonb | Pairwise comparison |
| function_path / function_kwargs | varchar/jsonb | Custom evaluation functions |

### `land_evaluator_evaluation` (0 rows)

Evaluation results per terrain (not yet populated).

### `land_evaluator_terrainevaluation` / `land_evaluator_terrainevaluationfieldscore` (56,115 rows)

Individual field scores per terrain evaluation.

---

## 18. Government Requests Domain

### `government_entities` (10 rows)

Government entities for environmental/grid permits.

| Column | Type | Notes |
|--------|------|-------|
| id | integer | PK |
| name / nomenclature | varchar | |
| request / template / subject / message | varchar/text | Request templates |
| type_request / format | varchar | |
| response_time | integer | Expected response days |
| is_active | boolean | |
| in_charge_id | bigint | FK |

### `government_requests_page` (188 rows) / `government_requests_email` (rows)

Submitted requests to government via web/email.

### `government_request_responses` (rows)

Responses received from government entities.

---

## 19. WhatsApp Bot Domain

### `whatsapp_bot_whatsappmessage` (14,172 rows)

WhatsApp messages (automated landlord communication).

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| wa_id | varchar | WhatsApp ID |
| timestamp | timestamptz | |
| text | text | Message content |
| type | varchar | Message type |
| sent_to / received_from | varchar | Phone numbers |
| template_name | varchar | WA template used |
| document_id | varchar | FK |
| error_message | text | |
| raw_message | jsonb | Full WA API payload |

### `whatsapp_bot_whatsappdocument` (109 rows)

Documents sent/received via WhatsApp.

---

## 20. Monitoring / DevOps Domain

### `monitoring_task` (843 rows, 22 cols)

Development tasks tracked from Discord/GitLab.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| title / description | varchar/text | |
| type / status | varchar | |
| discord_user_id / discord_jump_url | varchar | |
| gitlab_project_id / gitlab_issue_id / gitlab_issue_url | varchar | |
| responsible_id | varchar | |
| message_id / channel_id | varchar | |
| start_date / end_date | date | |
| working_on_at / in_review_at / ready_for_review_at / ready_for_deployment_at / solved_at | timestamptz | |

### `monitoring_clickuptask` (423 rows)

ClickUp task references.

### `monitoring_discorduser` (rows) / `monitoring_gitlabproject` (rows)

Discord user and GitLab project mappings.

### `monitoring_fieldwatcheraction` (rows)

Watchers that trigger Discord/webhook notifications on field changes.

### `monitoring_eventtype` (rows)

Event types for field watcher system.

---

## 21. GenAI Domain

### `genai_apikey` (9 rows) / `genai_genaimodel` (2 rows)

API keys and model definitions for AI features.

### `genai_apikeyuse` (17,579 rows)

Token usage tracking per API key call.

---

## 22. Accounting / HR Domain

### `accounting_expense` (105 rows) / `accounting_expenseattachment` (rows)

Employee expense reports with Odoo integration.

### `accounting_novedadrequest` (32 rows)

HR requests (novedades de nomina).

### `accounting_employeeprofile` (14 rows)

Employee profiles linked to auth_user.

### `accounting_expensecategorylimit` / `accounting_gimnasiolimit`

Expense limits by category and gym allowances.

---

## 23. Identity & Auth Domain

### `identity_management_identity` (259 rows)

Cross-platform identity mapping.

| Column | Type | Notes |
|--------|------|-------|
| id | bigint | PK |
| user_id | integer | FK to auth_user |
| discord_id / clickup_id / gitlab_id / auth_id | varchar | Platform IDs |
| role | varchar | |

### `identity_management_profile` (262 rows)

User profiles with phone numbers.

### `auth_user` (262 rows)

Django users.

---

## 24. Infrastructure Tables

| Table | Rows | Purpose |
|-------|------|---------|
| `django_tracker_auditlog` | 20,533,878 | **15 GB** - All model change tracking |
| `easyaudit_crudevent` | ~large | **14 GB** - CRUD event log (django-easyaudit) |
| `easyaudit_requestevent` | ~some | HTTP request log |
| `easyaudit_loginevent` | ~some | Login event log |
| `django_admin_log` | rows | Django admin actions |
| `django_celery_beat_*` | rows | Celery Beat scheduled tasks |
| `django_celery_results_taskresult` | 296 | Celery task results |
| `django_content_type` | rows | Django content types |
| `django_migrations` | rows | Migration history |
| `django_session` | rows | User sessions |
| `silk_*` | rows | Django Silk profiling |
| `logging_manager_log` | 3,973 | Application logging |
| `reports_report` | 44 | Generated reports |
| `sites_config_jwttoken` | rows | JWT tokens |
| `unergy_odoo_django_odoocredentials` | rows | Odoo integration credentials |
| `proxied_links_proxiedlink` | rows | Proxied/shortened links |
| `admin_interface_theme` | rows | Admin UI theme |
| `legal_validation_*` | rows | Legal keyword validation settings |

### Document Template System

| Table | Rows | Purpose |
|-------|------|---------|
| `termsheet_docxdocument` | 75 | Generated DOCX files |
| `termsheet_docxtemplate` | 19 | DOCX templates |
| `termsheet_docxtemplatevariable` | rows | Template variables |
| `termsheet_htmltemplate` | 6 | HTML templates |

### ZapSign Integration

| Table | Rows | Purpose |
|-------|------|---------|
| `termsheet_signerzapsign` | 502 | ZapSign signer records |
| `termsheet_zapsignwebhookresponses` | 1,175 | ZapSign webhook payloads |
| `termsheet_accesscode` | 24 | Access codes for signing |

---

## Entity Relationship Map

```
                         ┌──────────────────────────┐
                         │  termsheet_originator(34) │
                         └────────────┬─────────────┘
                                      │ sources
                         ┌────────────▼─────────────┐
                         │  termsheet_terrain(6330)  │◄──── prospecting_contact(13295)
                         │  (land parcels)           │◄──── prospecting_pre_validation(2161)
                         └──┬───────┬────────┬───────┘
                            │       │        │
              ┌─────────────┘       │        └──────────────┐
              │                     │                       │
    ┌─────────▼──────────┐  ┌──────▼────────┐   ┌─────────▼───────────┐
    │ landlord_terrain    │  │ easement(190) │   │ validation_field     │
    │ (2059 links)        │  └───────────────┘   │ (1,147,520)         │
    └─────────┬──────────┘                       └─────────────────────┘
              │
    ┌─────────▼──────────┐
    │ termsheet_landlord  │
    │ (2423 owners)       │
    └─────────┬──────────┘
              │ signs
    ┌─────────▼──────────┐        ┌──────────────────────┐
    │ termsheet_termsheet │        │ termsheet_clause      │
    │ (672 termsheets)    │◄───────┤ contract_termsheet... │
    └───┬─────────────┬───┘        │ (1512 clauses)       │
        │             │            └──────────────────────┘
        │             │
   ┌────▼───┐    ┌────▼──────────────┐
   │contract│    │ leasing_contract   │
   │(30)    │    │ (141)              │
   └────┬───┘    └────┬──────────────┘
        │             │
        └──────┬──────┘
               │
    ┌──────────▼─────────────┐          ┌────────────────────────┐
    │  minifarm_project      │◄─────────┤ timeline_timeline(418) │
    │  (3084 projects)       │          │   └─ activity(15466)   │
    │  CENTRAL TABLE         │          └────────────────────────┘
    └───┬───┬───┬────┬───────┘
        │   │   │    │
        │   │   │    └────────────────────────────────────────────┐
        │   │   │                                                 │
   ┌────▼───┘   └──────┐                               ┌────────▼──────────┐
   │                    │                               │ epc_projectepc    │
   │                    │                               │ (526)             │
┌──▼──────────────┐  ┌──▼───────────────────┐           └───────────────────┘
│ project_stage   │  │ investment_minifarm   │
│ change(9497)    │  │ (3084, 1:1 w/project) │
└─────────────────┘  └──┬──────────────────┘
                        │
              ┌─────────▼──────────┐      ┌──────────────────┐
              │ portfolio_minifarm │      │ investment(78)   │
              │ (247 links)        │      │ (investors/funds) │
              └─────────┬──────────┘      └──────┬───────────┘
                        │                        │
              ┌─────────▼──────────┐      ┌──────▼───────────┐
              │ portfolio(114)     │◄─────┤ portfolio_invest │
              │ (DE/EQ financing)  │      │ (138 links)      │
              └─────────┬──────────┘      └──────────────────┘
                        │
              ┌─────────▼──────────┐      ┌──────────────────┐
              │ ppa_portfolios     │      │ offtaker(16)     │
              └─────────┬──────────┘      └──────┬───────────┘
                        │                        │
              ┌─────────▼──────────┐             │
              │ ppa(22)            │◄────────────┘
              │ (power purchase)   │
              └────────────────────┘

    ┌──────────────────────┐
    │ termsheet_payment    │──── paid to ────► termsheet_paymentreceiver(136)
    │ (3221 payments)      │──── for ────────► termsheet_termsheet
    │                      │──── landlord ──► termsheet_landlord
    └──────────────────────┘

    ┌──────────────────────────────────┐
    │ territorial_city(1169)           │
    │ ├── territorial_region(57)       │◄──── grid_operator mapping
    │ ├── territorial_subregion(1346)  │      (territorial_or* tables)
    │ ├── territorial_locality(5586)   │
    │ └── territorial_neighborhood    │
    │     (20238)                      │
    └──────────────────────────────────┘
```

---

## Data Volume Summary

### Top Tables by Size

| Table | Total Size | Data Size | Rows |
|-------|-----------|-----------|------|
| django_tracker_auditlog | 15 GB | 10 GB | 20,533,878 |
| easyaudit_crudevent | 14 GB | 12 GB | (large) |
| validation_field | 1,012 MB | 534 MB | 1,147,520 |
| validation_weightfield | 166 MB | 80 MB | 1,164,214 |
| django_celery_results | 86 MB | 2 MB | 296 |
| investment_dataroomfolder_fields | 25 MB | 8 MB | 131,082 |
| prospecting_chattigoreport | 21 MB | 17 MB | 61,488 |
| investment_dataroomfolder | 13 MB | 7 MB | 72,796 |

### Key Business Metrics

| Metric | Value |
|--------|-------|
| Active projects (not dead/prospect) | 399 |
| Operational projects | 30 |
| Under construction | 27 |
| Signed contracts | 28 |
| Total payments made (paid) | 2,746 |
| Standard project size | 996 kW AC / 1,320 kW DC / 2,016 panels |
| Dominant contract type | Rental (92%) |
| Top grid operator | Afinia (1,060 projects) |
| Total investors tracked | 78 |
| Total offtakers/PPAs | 16 / 22 |
| Land parcels evaluated | 6,330 terrains |
| Landowners registered | 2,423 |
| Contacts in prospecting | 13,295 |
| WhatsApp messages | 14,172 |
| Data room files | 21,719 |
| Chatbot conversations | 61,488 |

### Key Observations

1. **No database-level FK constraints** -- all relationships enforced at Django ORM level (`db_constraint=False`). Columns named `*_id` are logical FKs.
2. **Dual audit systems** -- `django_tracker_auditlog` (15 GB) + `easyaudit_crudevent` (14 GB) = 29 GB of audit data (97% of DB). Consider archiving.
3. **Validation engine is massive** -- 1.1M field instances + 1.1M weight records. This is the checklist/scoring engine for all projects and terrains.
4. **Standard minifarm template** -- Nearly all projects are 996 kW AC / 1,320 kW DC / 2,016 panels (Huawei SUN2000-249KTL-H1 inverter).
5. **ZapSign integration** -- Electronic signatures for termsheets and contracts via ZapSign API.
6. **Odoo integration** -- Accounting (expenses, HR) syncs to Odoo ERP via `id_odoo` / `odoo_analytic_account_id`.
7. **ClickUp integration** -- Projects and tasks tracked in ClickUp via `clickup_task_id`.
8. **Google Drive integration** -- Dataroom files synced from Google Drive (`google_id`, `web_view_link`).
9. **Chattigo chatbot** -- 61K conversation records for landowner prospecting campaigns.
10. **Dual city systems** -- `cities_light_*` (legacy) being migrated to `territorial_*` (new). Both FK patterns coexist (`city_prev_id` vs `city_id`).
11. **Kill rate is high** -- 84% of projects (2,602/3,084) are `dead`. 89% of terrains (5,660/6,330) are `dead`. This is normal for solar origination.
12. **Grid operator concentration** -- Afinia (34%), Aire (17%), ESSA (10%), Celsia (9%) cover 70% of projects. All Caribbean/Santander coast.
