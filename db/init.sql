-- Schema local alinhado ao PostgreSQL remoto (Neon).
-- Fonte de verdade: schema_remote.md gerado por inspe??o somente leitura.
-- Este arquivo n?o cont?m dados de neg?cio.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS "public"."ai_report" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "incident_id" uuid NOT NULL,
    "detected_waste_type" character varying(100),
    "ai_contamination_level" character varying(50),
    "recommendations" text,
    "report_text" text,
    "generated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS "public"."area" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "company_id" uuid NOT NULL,
    "sector_name" character varying(100) NOT NULL,
    "location_description" character varying(255)
);

CREATE TABLE IF NOT EXISTS "public"."attachment" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "incident_id" uuid NOT NULL,
    "file_url" character varying(500) NOT NULL,
    "file_type" character varying(100) NOT NULL
);

CREATE TABLE IF NOT EXISTS "public"."collection" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "incident_id" uuid NOT NULL,
    "cooperative_id" uuid NOT NULL,
    "requested_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "scheduled_at" timestamp without time zone,
    "current_status" character varying(50) NOT NULL,
    "collection_type" character varying(50) NOT NULL,
    "urgent" boolean DEFAULT false NOT NULL
);

CREATE TABLE IF NOT EXISTS "public"."collection_status" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "collection_id" uuid NOT NULL,
    "status" character varying(50) NOT NULL,
    "changed_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "observation" text
);

CREATE TABLE IF NOT EXISTS "public"."company" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "name" character varying(150) NOT NULL,
    "cnpj" character varying(18) NOT NULL,
    "address" character varying(255) NOT NULL
);

CREATE TABLE IF NOT EXISTS "public"."conversation" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "company_id" uuid NOT NULL,
    "cooperative_id" uuid NOT NULL,
    "collection_id" uuid NOT NULL,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS "public"."cooperative" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "name" character varying(150) NOT NULL,
    "cnpj" character varying(18) NOT NULL,
    "latitude" numeric(9,6) NOT NULL,
    "longitude" numeric(9,6) NOT NULL,
    "average_rating" numeric(3,2) DEFAULT 0,
    "specialties" character varying(500)
);

CREATE TABLE IF NOT EXISTS "public"."esg_metric" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "company_id" uuid NOT NULL,
    "period" character varying(20) NOT NULL,
    "total_waste_kg" numeric(14,2) DEFAULT 0 NOT NULL,
    "total_recycled_kg" numeric(14,2) DEFAULT 0 NOT NULL,
    "recycling_percentage" numeric(5,2) DEFAULT 0 NOT NULL,
    "calculated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS "public"."flyway_schema_history" (
    "installed_rank" integer NOT NULL,
    "version" character varying(50),
    "description" character varying(200) NOT NULL,
    "type" character varying(20) NOT NULL,
    "script" character varying(1000) NOT NULL,
    "checksum" integer,
    "installed_by" character varying(100) NOT NULL,
    "installed_on" timestamp without time zone DEFAULT now() NOT NULL,
    "execution_time" integer NOT NULL,
    "success" boolean NOT NULL
);

CREATE TABLE IF NOT EXISTS "public"."incident" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "company_id" uuid NOT NULL,
    "user_id" uuid NOT NULL,
    "area_id" uuid NOT NULL,
    "waste_type_id" uuid,
    "photo_url" character varying(500),
    "employee_description" text NOT NULL,
    "contamination_level" character varying(50),
    "estimated_quantity" numeric(12,2),
    "priority" character varying(30) NOT NULL,
    "status" character varying(50) NOT NULL,
    "registered_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS "public"."message" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "conversation_id" uuid NOT NULL,
    "user_id" uuid NOT NULL,
    "text" text NOT NULL,
    "reported" boolean DEFAULT false NOT NULL,
    "sent_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS "public"."message_attachment" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "message_id" uuid NOT NULL,
    "file_url" character varying(500) NOT NULL,
    "file_type" character varying(100) NOT NULL
);

CREATE TABLE IF NOT EXISTS "public"."notification" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "user_id" uuid NOT NULL,
    "type" character varying(50) NOT NULL,
    "title" character varying(150) NOT NULL,
    "message" text NOT NULL,
    "read" boolean DEFAULT false NOT NULL,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS "public"."review" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "cooperative_id" uuid NOT NULL,
    "user_id" uuid NOT NULL,
    "collection_id" uuid NOT NULL,
    "stars" integer NOT NULL,
    "comment" text,
    "reviewed_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS "public"."role" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "type" character varying(50) NOT NULL
);

CREATE TABLE IF NOT EXISTS "public"."users" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "company_id" uuid NOT NULL,
    "role_id" uuid NOT NULL,
    "name" character varying(150) NOT NULL,
    "email" character varying(150) NOT NULL,
    "password_hash" character varying(255) NOT NULL,
    "position" character varying(100)
);

CREATE TABLE IF NOT EXISTS "public"."waste_type" (
    "id" uuid DEFAULT gen_random_uuid() NOT NULL,
    "category" character varying(100) NOT NULL,
    "description" character varying(255),
    "default_risk_level" character varying(50) NOT NULL
);

ALTER TABLE "public"."ai_report" ADD CONSTRAINT "ai_report_pkey" PRIMARY KEY (id);
ALTER TABLE "public"."ai_report" ADD CONSTRAINT "fk_ai_report_incident" FOREIGN KEY (incident_id) REFERENCES incident(id);
ALTER TABLE "public"."area" ADD CONSTRAINT "area_pkey" PRIMARY KEY (id);
ALTER TABLE "public"."area" ADD CONSTRAINT "fk_area_company" FOREIGN KEY (company_id) REFERENCES company(id);
ALTER TABLE "public"."attachment" ADD CONSTRAINT "attachment_pkey" PRIMARY KEY (id);
ALTER TABLE "public"."attachment" ADD CONSTRAINT "fk_attachment_incident" FOREIGN KEY (incident_id) REFERENCES incident(id);
ALTER TABLE "public"."collection" ADD CONSTRAINT "chk_collection_dates" CHECK (((scheduled_at IS NULL) OR (scheduled_at >= requested_at)));
ALTER TABLE "public"."collection" ADD CONSTRAINT "collection_pkey" PRIMARY KEY (id);
ALTER TABLE "public"."collection" ADD CONSTRAINT "fk_collection_cooperative" FOREIGN KEY (cooperative_id) REFERENCES cooperative(id);
ALTER TABLE "public"."collection" ADD CONSTRAINT "fk_collection_incident" FOREIGN KEY (incident_id) REFERENCES incident(id);
ALTER TABLE "public"."collection_status" ADD CONSTRAINT "collection_status_pkey" PRIMARY KEY (id);
ALTER TABLE "public"."collection_status" ADD CONSTRAINT "fk_collection_status_collection" FOREIGN KEY (collection_id) REFERENCES collection(id);
ALTER TABLE "public"."company" ADD CONSTRAINT "company_cnpj_key" UNIQUE (cnpj);
ALTER TABLE "public"."company" ADD CONSTRAINT "company_pkey" PRIMARY KEY (id);
ALTER TABLE "public"."conversation" ADD CONSTRAINT "conversation_pkey" PRIMARY KEY (id);
ALTER TABLE "public"."conversation" ADD CONSTRAINT "fk_conversation_collection" FOREIGN KEY (collection_id) REFERENCES collection(id);
ALTER TABLE "public"."conversation" ADD CONSTRAINT "fk_conversation_company" FOREIGN KEY (company_id) REFERENCES company(id);
ALTER TABLE "public"."conversation" ADD CONSTRAINT "fk_conversation_cooperative" FOREIGN KEY (cooperative_id) REFERENCES cooperative(id);
ALTER TABLE "public"."cooperative" ADD CONSTRAINT "chk_cooperative_latitude" CHECK (((latitude >= ('-90'::integer)::numeric) AND (latitude <= (90)::numeric)));
ALTER TABLE "public"."cooperative" ADD CONSTRAINT "chk_cooperative_longitude" CHECK (((longitude >= ('-180'::integer)::numeric) AND (longitude <= (180)::numeric)));
ALTER TABLE "public"."cooperative" ADD CONSTRAINT "chk_cooperative_rating" CHECK (((average_rating >= (0)::numeric) AND (average_rating <= (5)::numeric)));
ALTER TABLE "public"."cooperative" ADD CONSTRAINT "cooperative_cnpj_key" UNIQUE (cnpj);
ALTER TABLE "public"."cooperative" ADD CONSTRAINT "cooperative_pkey" PRIMARY KEY (id);
ALTER TABLE "public"."esg_metric" ADD CONSTRAINT "chk_esg_percentage" CHECK (((recycling_percentage >= (0)::numeric) AND (recycling_percentage <= (100)::numeric)));
ALTER TABLE "public"."esg_metric" ADD CONSTRAINT "chk_esg_recycled_not_greater" CHECK ((total_recycled_kg <= total_waste_kg));
ALTER TABLE "public"."esg_metric" ADD CONSTRAINT "chk_esg_total_recycled" CHECK ((total_recycled_kg >= (0)::numeric));
ALTER TABLE "public"."esg_metric" ADD CONSTRAINT "chk_esg_total_waste" CHECK ((total_waste_kg >= (0)::numeric));
ALTER TABLE "public"."esg_metric" ADD CONSTRAINT "esg_metric_pkey" PRIMARY KEY (id);
ALTER TABLE "public"."esg_metric" ADD CONSTRAINT "fk_esg_metric_company" FOREIGN KEY (company_id) REFERENCES company(id);
ALTER TABLE "public"."flyway_schema_history" ADD CONSTRAINT "flyway_schema_history_pk" PRIMARY KEY (installed_rank);
ALTER TABLE "public"."incident" ADD CONSTRAINT "chk_incident_quantity" CHECK (((estimated_quantity IS NULL) OR (estimated_quantity >= (0)::numeric)));
ALTER TABLE "public"."incident" ADD CONSTRAINT "fk_incident_area" FOREIGN KEY (area_id) REFERENCES area(id);
ALTER TABLE "public"."incident" ADD CONSTRAINT "fk_incident_company" FOREIGN KEY (company_id) REFERENCES company(id);
ALTER TABLE "public"."incident" ADD CONSTRAINT "fk_incident_user" FOREIGN KEY (user_id) REFERENCES users(id);
ALTER TABLE "public"."incident" ADD CONSTRAINT "fk_incident_waste_type" FOREIGN KEY (waste_type_id) REFERENCES waste_type(id);
ALTER TABLE "public"."incident" ADD CONSTRAINT "incident_pkey" PRIMARY KEY (id);
ALTER TABLE "public"."message" ADD CONSTRAINT "fk_message_conversation" FOREIGN KEY (conversation_id) REFERENCES conversation(id);
ALTER TABLE "public"."message" ADD CONSTRAINT "fk_message_user" FOREIGN KEY (user_id) REFERENCES users(id);
ALTER TABLE "public"."message" ADD CONSTRAINT "message_pkey" PRIMARY KEY (id);
ALTER TABLE "public"."message_attachment" ADD CONSTRAINT "fk_message_attachment_message" FOREIGN KEY (message_id) REFERENCES message(id);
ALTER TABLE "public"."message_attachment" ADD CONSTRAINT "message_attachment_pkey" PRIMARY KEY (id);
ALTER TABLE "public"."notification" ADD CONSTRAINT "fk_notification_user" FOREIGN KEY (user_id) REFERENCES users(id);
ALTER TABLE "public"."notification" ADD CONSTRAINT "notification_pkey" PRIMARY KEY (id);
ALTER TABLE "public"."review" ADD CONSTRAINT "chk_review_stars" CHECK (((stars >= 1) AND (stars <= 5)));
ALTER TABLE "public"."review" ADD CONSTRAINT "fk_review_collection" FOREIGN KEY (collection_id) REFERENCES collection(id);
ALTER TABLE "public"."review" ADD CONSTRAINT "fk_review_cooperative" FOREIGN KEY (cooperative_id) REFERENCES cooperative(id);
ALTER TABLE "public"."review" ADD CONSTRAINT "fk_review_user" FOREIGN KEY (user_id) REFERENCES users(id);
ALTER TABLE "public"."review" ADD CONSTRAINT "review_pkey" PRIMARY KEY (id);
ALTER TABLE "public"."role" ADD CONSTRAINT "role_pkey" PRIMARY KEY (id);
ALTER TABLE "public"."role" ADD CONSTRAINT "role_type_key" UNIQUE (type);
ALTER TABLE "public"."users" ADD CONSTRAINT "fk_users_company" FOREIGN KEY (company_id) REFERENCES company(id);
ALTER TABLE "public"."users" ADD CONSTRAINT "fk_users_role" FOREIGN KEY (role_id) REFERENCES role(id);
ALTER TABLE "public"."users" ADD CONSTRAINT "users_email_key" UNIQUE (email);
ALTER TABLE "public"."users" ADD CONSTRAINT "users_pkey" PRIMARY KEY (id);
ALTER TABLE "public"."waste_type" ADD CONSTRAINT "waste_type_pkey" PRIMARY KEY (id);

CREATE INDEX flyway_schema_history_s_idx ON public.flyway_schema_history USING btree (success);
