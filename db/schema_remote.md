# Schema remoto do VOLTA

> Relat?rio gerado por inspe??o somente leitura do PostgreSQL remoto. Nenhum registro de neg?cio foi exportado.

Tabelas encontradas: **18**

## Tabelas e campos

### `public.ai_report`

| Campo | Tipo | Nulo | Padr?o |
|---|---|---|---|
| `id` | `uuid` | `NO` | `gen_random_uuid()` |
| `incident_id` | `uuid` | `NO` | `` |
| `detected_waste_type` | `character varying(100)` | `YES` | `` |
| `ai_contamination_level` | `character varying(50)` | `YES` | `` |
| `recommendations` | `text` | `YES` | `` |
| `report_text` | `text` | `YES` | `` |
| `generated_at` | `timestamp without time zone` | `NO` | `CURRENT_TIMESTAMP` |

### `public.area`

| Campo | Tipo | Nulo | Padr?o |
|---|---|---|---|
| `id` | `uuid` | `NO` | `gen_random_uuid()` |
| `company_id` | `uuid` | `NO` | `` |
| `sector_name` | `character varying(100)` | `NO` | `` |
| `location_description` | `character varying(255)` | `YES` | `` |

### `public.attachment`

| Campo | Tipo | Nulo | Padr?o |
|---|---|---|---|
| `id` | `uuid` | `NO` | `gen_random_uuid()` |
| `incident_id` | `uuid` | `NO` | `` |
| `file_url` | `character varying(500)` | `NO` | `` |
| `file_type` | `character varying(100)` | `NO` | `` |

### `public.collection`

| Campo | Tipo | Nulo | Padr?o |
|---|---|---|---|
| `id` | `uuid` | `NO` | `gen_random_uuid()` |
| `incident_id` | `uuid` | `NO` | `` |
| `cooperative_id` | `uuid` | `NO` | `` |
| `requested_at` | `timestamp without time zone` | `NO` | `CURRENT_TIMESTAMP` |
| `scheduled_at` | `timestamp without time zone` | `YES` | `` |
| `current_status` | `character varying(50)` | `NO` | `` |
| `collection_type` | `character varying(50)` | `NO` | `` |
| `urgent` | `boolean` | `NO` | `false` |

### `public.collection_status`

| Campo | Tipo | Nulo | Padr?o |
|---|---|---|---|
| `id` | `uuid` | `NO` | `gen_random_uuid()` |
| `collection_id` | `uuid` | `NO` | `` |
| `status` | `character varying(50)` | `NO` | `` |
| `changed_at` | `timestamp without time zone` | `NO` | `CURRENT_TIMESTAMP` |
| `observation` | `text` | `YES` | `` |

### `public.company`

| Campo | Tipo | Nulo | Padr?o |
|---|---|---|---|
| `id` | `uuid` | `NO` | `gen_random_uuid()` |
| `name` | `character varying(150)` | `NO` | `` |
| `cnpj` | `character varying(18)` | `NO` | `` |
| `address` | `character varying(255)` | `NO` | `` |

### `public.conversation`

| Campo | Tipo | Nulo | Padr?o |
|---|---|---|---|
| `id` | `uuid` | `NO` | `gen_random_uuid()` |
| `company_id` | `uuid` | `NO` | `` |
| `cooperative_id` | `uuid` | `NO` | `` |
| `collection_id` | `uuid` | `NO` | `` |
| `created_at` | `timestamp without time zone` | `NO` | `CURRENT_TIMESTAMP` |

### `public.cooperative`

| Campo | Tipo | Nulo | Padr?o |
|---|---|---|---|
| `id` | `uuid` | `NO` | `gen_random_uuid()` |
| `name` | `character varying(150)` | `NO` | `` |
| `cnpj` | `character varying(18)` | `NO` | `` |
| `latitude` | `numeric(9,6)` | `NO` | `` |
| `longitude` | `numeric(9,6)` | `NO` | `` |
| `average_rating` | `numeric(3,2)` | `YES` | `0` |
| `specialties` | `character varying(500)` | `YES` | `` |

### `public.esg_metric`

| Campo | Tipo | Nulo | Padr?o |
|---|---|---|---|
| `id` | `uuid` | `NO` | `gen_random_uuid()` |
| `company_id` | `uuid` | `NO` | `` |
| `period` | `character varying(20)` | `NO` | `` |
| `total_waste_kg` | `numeric(14,2)` | `NO` | `0` |
| `total_recycled_kg` | `numeric(14,2)` | `NO` | `0` |
| `recycling_percentage` | `numeric(5,2)` | `NO` | `0` |
| `calculated_at` | `timestamp without time zone` | `NO` | `CURRENT_TIMESTAMP` |

### `public.flyway_schema_history`

| Campo | Tipo | Nulo | Padr?o |
|---|---|---|---|
| `installed_rank` | `integer` | `NO` | `` |
| `version` | `character varying(50)` | `YES` | `` |
| `description` | `character varying(200)` | `NO` | `` |
| `type` | `character varying(20)` | `NO` | `` |
| `script` | `character varying(1000)` | `NO` | `` |
| `checksum` | `integer` | `YES` | `` |
| `installed_by` | `character varying(100)` | `NO` | `` |
| `installed_on` | `timestamp without time zone` | `NO` | `now()` |
| `execution_time` | `integer` | `NO` | `` |
| `success` | `boolean` | `NO` | `` |

### `public.incident`

| Campo | Tipo | Nulo | Padr?o |
|---|---|---|---|
| `id` | `uuid` | `NO` | `gen_random_uuid()` |
| `company_id` | `uuid` | `NO` | `` |
| `user_id` | `uuid` | `NO` | `` |
| `area_id` | `uuid` | `NO` | `` |
| `waste_type_id` | `uuid` | `YES` | `` |
| `photo_url` | `character varying(500)` | `YES` | `` |
| `employee_description` | `text` | `NO` | `` |
| `contamination_level` | `character varying(50)` | `YES` | `` |
| `estimated_quantity` | `numeric(12,2)` | `YES` | `` |
| `priority` | `character varying(30)` | `NO` | `` |
| `status` | `character varying(50)` | `NO` | `` |
| `registered_at` | `timestamp without time zone` | `NO` | `CURRENT_TIMESTAMP` |

### `public.message`

| Campo | Tipo | Nulo | Padr?o |
|---|---|---|---|
| `id` | `uuid` | `NO` | `gen_random_uuid()` |
| `conversation_id` | `uuid` | `NO` | `` |
| `user_id` | `uuid` | `NO` | `` |
| `text` | `text` | `NO` | `` |
| `reported` | `boolean` | `NO` | `false` |
| `sent_at` | `timestamp without time zone` | `NO` | `CURRENT_TIMESTAMP` |

### `public.message_attachment`

| Campo | Tipo | Nulo | Padr?o |
|---|---|---|---|
| `id` | `uuid` | `NO` | `gen_random_uuid()` |
| `message_id` | `uuid` | `NO` | `` |
| `file_url` | `character varying(500)` | `NO` | `` |
| `file_type` | `character varying(100)` | `NO` | `` |

### `public.notification`

| Campo | Tipo | Nulo | Padr?o |
|---|---|---|---|
| `id` | `uuid` | `NO` | `gen_random_uuid()` |
| `user_id` | `uuid` | `NO` | `` |
| `type` | `character varying(50)` | `NO` | `` |
| `title` | `character varying(150)` | `NO` | `` |
| `message` | `text` | `NO` | `` |
| `read` | `boolean` | `NO` | `false` |
| `created_at` | `timestamp without time zone` | `NO` | `CURRENT_TIMESTAMP` |

### `public.review`

| Campo | Tipo | Nulo | Padr?o |
|---|---|---|---|
| `id` | `uuid` | `NO` | `gen_random_uuid()` |
| `cooperative_id` | `uuid` | `NO` | `` |
| `user_id` | `uuid` | `NO` | `` |
| `collection_id` | `uuid` | `NO` | `` |
| `stars` | `integer` | `NO` | `` |
| `comment` | `text` | `YES` | `` |
| `reviewed_at` | `timestamp without time zone` | `NO` | `CURRENT_TIMESTAMP` |

### `public.role`

| Campo | Tipo | Nulo | Padr?o |
|---|---|---|---|
| `id` | `uuid` | `NO` | `gen_random_uuid()` |
| `type` | `character varying(50)` | `NO` | `` |

### `public.users`

| Campo | Tipo | Nulo | Padr?o |
|---|---|---|---|
| `id` | `uuid` | `NO` | `gen_random_uuid()` |
| `company_id` | `uuid` | `NO` | `` |
| `role_id` | `uuid` | `NO` | `` |
| `name` | `character varying(150)` | `NO` | `` |
| `email` | `character varying(150)` | `NO` | `` |
| `password_hash` | `character varying(255)` | `NO` | `` |
| `position` | `character varying(100)` | `YES` | `` |

### `public.waste_type`

| Campo | Tipo | Nulo | Padr?o |
|---|---|---|---|
| `id` | `uuid` | `NO` | `gen_random_uuid()` |
| `category` | `character varying(100)` | `NO` | `` |
| `description` | `character varying(255)` | `YES` | `` |
| `default_risk_level` | `character varying(50)` | `NO` | `` |

## Relacionamentos e constraints

- **CHECK** `public.ai_report.` (`ai_report_generated_at_not_null`)
- **CHECK** `public.ai_report.` (`ai_report_id_not_null`)
- **CHECK** `public.ai_report.` (`ai_report_incident_id_not_null`)
- **PRIMARY KEY** `public.ai_report.id` (`ai_report_pkey`)
- **FK** `public.ai_report.incident_id` ? `public.incident.id` (`fk_ai_report_incident`)
- **CHECK** `public.area.` (`area_company_id_not_null`)
- **CHECK** `public.area.` (`area_id_not_null`)
- **PRIMARY KEY** `public.area.id` (`area_pkey`)
- **CHECK** `public.area.` (`area_sector_name_not_null`)
- **FK** `public.area.company_id` ? `public.company.id` (`fk_area_company`)
- **CHECK** `public.attachment.` (`attachment_file_type_not_null`)
- **CHECK** `public.attachment.` (`attachment_file_url_not_null`)
- **CHECK** `public.attachment.` (`attachment_id_not_null`)
- **CHECK** `public.attachment.` (`attachment_incident_id_not_null`)
- **PRIMARY KEY** `public.attachment.id` (`attachment_pkey`)
- **FK** `public.attachment.incident_id` ? `public.incident.id` (`fk_attachment_incident`)
- **CHECK** `public.collection.` (`chk_collection_dates`)
- **CHECK** `public.collection.` (`chk_collection_dates`)
- **CHECK** `public.collection.` (`collection_collection_type_not_null`)
- **CHECK** `public.collection.` (`collection_cooperative_id_not_null`)
- **CHECK** `public.collection.` (`collection_current_status_not_null`)
- **CHECK** `public.collection.` (`collection_id_not_null`)
- **CHECK** `public.collection.` (`collection_incident_id_not_null`)
- **PRIMARY KEY** `public.collection.id` (`collection_pkey`)
- **CHECK** `public.collection.` (`collection_requested_at_not_null`)
- **CHECK** `public.collection.` (`collection_urgent_not_null`)
- **FK** `public.collection.cooperative_id` ? `public.cooperative.id` (`fk_collection_cooperative`)
- **FK** `public.collection.incident_id` ? `public.incident.id` (`fk_collection_incident`)
- **CHECK** `public.collection_status.` (`collection_status_changed_at_not_null`)
- **CHECK** `public.collection_status.` (`collection_status_collection_id_not_null`)
- **CHECK** `public.collection_status.` (`collection_status_id_not_null`)
- **PRIMARY KEY** `public.collection_status.id` (`collection_status_pkey`)
- **CHECK** `public.collection_status.` (`collection_status_status_not_null`)
- **FK** `public.collection_status.collection_id` ? `public.collection.id` (`fk_collection_status_collection`)
- **CHECK** `public.company.` (`company_address_not_null`)
- **UNIQUE** `public.company.cnpj` (`company_cnpj_key`)
- **CHECK** `public.company.` (`company_cnpj_not_null`)
- **CHECK** `public.company.` (`company_id_not_null`)
- **CHECK** `public.company.` (`company_name_not_null`)
- **PRIMARY KEY** `public.company.id` (`company_pkey`)
- **CHECK** `public.conversation.` (`conversation_collection_id_not_null`)
- **CHECK** `public.conversation.` (`conversation_company_id_not_null`)
- **CHECK** `public.conversation.` (`conversation_cooperative_id_not_null`)
- **CHECK** `public.conversation.` (`conversation_created_at_not_null`)
- **CHECK** `public.conversation.` (`conversation_id_not_null`)
- **PRIMARY KEY** `public.conversation.id` (`conversation_pkey`)
- **FK** `public.conversation.collection_id` ? `public.collection.id` (`fk_conversation_collection`)
- **FK** `public.conversation.company_id` ? `public.company.id` (`fk_conversation_company`)
- **FK** `public.conversation.cooperative_id` ? `public.cooperative.id` (`fk_conversation_cooperative`)
- **CHECK** `public.cooperative.` (`chk_cooperative_latitude`)
- **CHECK** `public.cooperative.` (`chk_cooperative_longitude`)
- **CHECK** `public.cooperative.` (`chk_cooperative_rating`)
- **UNIQUE** `public.cooperative.cnpj` (`cooperative_cnpj_key`)
- **CHECK** `public.cooperative.` (`cooperative_cnpj_not_null`)
- **CHECK** `public.cooperative.` (`cooperative_id_not_null`)
- **CHECK** `public.cooperative.` (`cooperative_latitude_not_null`)
- **CHECK** `public.cooperative.` (`cooperative_longitude_not_null`)
- **CHECK** `public.cooperative.` (`cooperative_name_not_null`)
- **PRIMARY KEY** `public.cooperative.id` (`cooperative_pkey`)
- **CHECK** `public.esg_metric.` (`chk_esg_percentage`)
- **CHECK** `public.esg_metric.` (`chk_esg_recycled_not_greater`)
- **CHECK** `public.esg_metric.` (`chk_esg_recycled_not_greater`)
- **CHECK** `public.esg_metric.` (`chk_esg_total_recycled`)
- **CHECK** `public.esg_metric.` (`chk_esg_total_waste`)
- **CHECK** `public.esg_metric.` (`esg_metric_calculated_at_not_null`)
- **CHECK** `public.esg_metric.` (`esg_metric_company_id_not_null`)
- **CHECK** `public.esg_metric.` (`esg_metric_id_not_null`)
- **CHECK** `public.esg_metric.` (`esg_metric_period_not_null`)
- **PRIMARY KEY** `public.esg_metric.id` (`esg_metric_pkey`)
- **CHECK** `public.esg_metric.` (`esg_metric_recycling_percentage_not_null`)
- **CHECK** `public.esg_metric.` (`esg_metric_total_recycled_kg_not_null`)
- **CHECK** `public.esg_metric.` (`esg_metric_total_waste_kg_not_null`)
- **FK** `public.esg_metric.company_id` ? `public.company.id` (`fk_esg_metric_company`)
- **CHECK** `public.flyway_schema_history.` (`flyway_schema_history_description_not_null`)
- **CHECK** `public.flyway_schema_history.` (`flyway_schema_history_execution_time_not_null`)
- **CHECK** `public.flyway_schema_history.` (`flyway_schema_history_installed_by_not_null`)
- **CHECK** `public.flyway_schema_history.` (`flyway_schema_history_installed_on_not_null`)
- **CHECK** `public.flyway_schema_history.` (`flyway_schema_history_installed_rank_not_null`)
- **PRIMARY KEY** `public.flyway_schema_history.installed_rank` (`flyway_schema_history_pk`)
- **CHECK** `public.flyway_schema_history.` (`flyway_schema_history_script_not_null`)
- **CHECK** `public.flyway_schema_history.` (`flyway_schema_history_success_not_null`)
- **CHECK** `public.flyway_schema_history.` (`flyway_schema_history_type_not_null`)
- **CHECK** `public.incident.` (`chk_incident_quantity`)
- **FK** `public.incident.area_id` ? `public.area.id` (`fk_incident_area`)
- **FK** `public.incident.company_id` ? `public.company.id` (`fk_incident_company`)
- **FK** `public.incident.user_id` ? `public.users.id` (`fk_incident_user`)
- **FK** `public.incident.waste_type_id` ? `public.waste_type.id` (`fk_incident_waste_type`)
- **CHECK** `public.incident.` (`incident_area_id_not_null`)
- **CHECK** `public.incident.` (`incident_company_id_not_null`)
- **CHECK** `public.incident.` (`incident_employee_description_not_null`)
- **CHECK** `public.incident.` (`incident_id_not_null`)
- **PRIMARY KEY** `public.incident.id` (`incident_pkey`)
- **CHECK** `public.incident.` (`incident_priority_not_null`)
- **CHECK** `public.incident.` (`incident_registered_at_not_null`)
- **CHECK** `public.incident.` (`incident_status_not_null`)
- **CHECK** `public.incident.` (`incident_user_id_not_null`)
- **FK** `public.message.conversation_id` ? `public.conversation.id` (`fk_message_conversation`)
- **FK** `public.message.user_id` ? `public.users.id` (`fk_message_user`)
- **CHECK** `public.message.` (`message_conversation_id_not_null`)
- **CHECK** `public.message.` (`message_id_not_null`)
- **PRIMARY KEY** `public.message.id` (`message_pkey`)
- **CHECK** `public.message.` (`message_reported_not_null`)
- **CHECK** `public.message.` (`message_sent_at_not_null`)
- **CHECK** `public.message.` (`message_text_not_null`)
- **CHECK** `public.message.` (`message_user_id_not_null`)
- **FK** `public.message_attachment.message_id` ? `public.message.id` (`fk_message_attachment_message`)
- **CHECK** `public.message_attachment.` (`message_attachment_file_type_not_null`)
- **CHECK** `public.message_attachment.` (`message_attachment_file_url_not_null`)
- **CHECK** `public.message_attachment.` (`message_attachment_id_not_null`)
- **CHECK** `public.message_attachment.` (`message_attachment_message_id_not_null`)
- **PRIMARY KEY** `public.message_attachment.id` (`message_attachment_pkey`)
- **FK** `public.notification.user_id` ? `public.users.id` (`fk_notification_user`)
- **CHECK** `public.notification.` (`notification_created_at_not_null`)
- **CHECK** `public.notification.` (`notification_id_not_null`)
- **CHECK** `public.notification.` (`notification_message_not_null`)
- **PRIMARY KEY** `public.notification.id` (`notification_pkey`)
- **CHECK** `public.notification.` (`notification_read_not_null`)
- **CHECK** `public.notification.` (`notification_title_not_null`)
- **CHECK** `public.notification.` (`notification_type_not_null`)
- **CHECK** `public.notification.` (`notification_user_id_not_null`)
- **CHECK** `public.review.` (`chk_review_stars`)
- **FK** `public.review.collection_id` ? `public.collection.id` (`fk_review_collection`)
- **FK** `public.review.cooperative_id` ? `public.cooperative.id` (`fk_review_cooperative`)
- **FK** `public.review.user_id` ? `public.users.id` (`fk_review_user`)
- **CHECK** `public.review.` (`review_collection_id_not_null`)
- **CHECK** `public.review.` (`review_cooperative_id_not_null`)
- **CHECK** `public.review.` (`review_id_not_null`)
- **PRIMARY KEY** `public.review.id` (`review_pkey`)
- **CHECK** `public.review.` (`review_reviewed_at_not_null`)
- **CHECK** `public.review.` (`review_stars_not_null`)
- **CHECK** `public.review.` (`review_user_id_not_null`)
- **CHECK** `public.role.` (`role_id_not_null`)
- **PRIMARY KEY** `public.role.id` (`role_pkey`)
- **UNIQUE** `public.role.type` (`role_type_key`)
- **CHECK** `public.role.` (`role_type_not_null`)
- **FK** `public.users.company_id` ? `public.company.id` (`fk_users_company`)
- **FK** `public.users.role_id` ? `public.role.id` (`fk_users_role`)
- **CHECK** `public.users.` (`users_company_id_not_null`)
- **UNIQUE** `public.users.email` (`users_email_key`)
- **CHECK** `public.users.` (`users_email_not_null`)
- **CHECK** `public.users.` (`users_id_not_null`)
- **CHECK** `public.users.` (`users_name_not_null`)
- **CHECK** `public.users.` (`users_password_hash_not_null`)
- **PRIMARY KEY** `public.users.id` (`users_pkey`)
- **CHECK** `public.users.` (`users_role_id_not_null`)
- **CHECK** `public.waste_type.` (`waste_type_category_not_null`)
- **CHECK** `public.waste_type.` (`waste_type_default_risk_level_not_null`)
- **CHECK** `public.waste_type.` (`waste_type_id_not_null`)
- **PRIMARY KEY** `public.waste_type.id` (`waste_type_pkey`)

## ?ndices

- `public.ai_report.ai_report_pkey`: `CREATE UNIQUE INDEX ai_report_pkey ON public.ai_report USING btree (id)`
- `public.area.area_pkey`: `CREATE UNIQUE INDEX area_pkey ON public.area USING btree (id)`
- `public.attachment.attachment_pkey`: `CREATE UNIQUE INDEX attachment_pkey ON public.attachment USING btree (id)`
- `public.collection.collection_pkey`: `CREATE UNIQUE INDEX collection_pkey ON public.collection USING btree (id)`
- `public.collection_status.collection_status_pkey`: `CREATE UNIQUE INDEX collection_status_pkey ON public.collection_status USING btree (id)`
- `public.company.company_cnpj_key`: `CREATE UNIQUE INDEX company_cnpj_key ON public.company USING btree (cnpj)`
- `public.company.company_pkey`: `CREATE UNIQUE INDEX company_pkey ON public.company USING btree (id)`
- `public.conversation.conversation_pkey`: `CREATE UNIQUE INDEX conversation_pkey ON public.conversation USING btree (id)`
- `public.cooperative.cooperative_cnpj_key`: `CREATE UNIQUE INDEX cooperative_cnpj_key ON public.cooperative USING btree (cnpj)`
- `public.cooperative.cooperative_pkey`: `CREATE UNIQUE INDEX cooperative_pkey ON public.cooperative USING btree (id)`
- `public.esg_metric.esg_metric_pkey`: `CREATE UNIQUE INDEX esg_metric_pkey ON public.esg_metric USING btree (id)`
- `public.flyway_schema_history.flyway_schema_history_pk`: `CREATE UNIQUE INDEX flyway_schema_history_pk ON public.flyway_schema_history USING btree (installed_rank)`
- `public.flyway_schema_history.flyway_schema_history_s_idx`: `CREATE INDEX flyway_schema_history_s_idx ON public.flyway_schema_history USING btree (success)`
- `public.incident.incident_pkey`: `CREATE UNIQUE INDEX incident_pkey ON public.incident USING btree (id)`
- `public.message.message_pkey`: `CREATE UNIQUE INDEX message_pkey ON public.message USING btree (id)`
- `public.message_attachment.message_attachment_pkey`: `CREATE UNIQUE INDEX message_attachment_pkey ON public.message_attachment USING btree (id)`
- `public.notification.notification_pkey`: `CREATE UNIQUE INDEX notification_pkey ON public.notification USING btree (id)`
- `public.review.review_pkey`: `CREATE UNIQUE INDEX review_pkey ON public.review USING btree (id)`
- `public.role.role_pkey`: `CREATE UNIQUE INDEX role_pkey ON public.role USING btree (id)`
- `public.role.role_type_key`: `CREATE UNIQUE INDEX role_type_key ON public.role USING btree (type)`
- `public.users.users_email_key`: `CREATE UNIQUE INDEX users_email_key ON public.users USING btree (email)`
- `public.users.users_pkey`: `CREATE UNIQUE INDEX users_pkey ON public.users USING btree (id)`
- `public.waste_type.waste_type_pkey`: `CREATE UNIQUE INDEX waste_type_pkey ON public.waste_type USING btree (id)`
