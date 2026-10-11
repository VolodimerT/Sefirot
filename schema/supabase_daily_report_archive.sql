-- SEFIROT private append-only day-end archive v1.
-- Standalone from original CORE/Policy/predictions, manual tickets, chat job queue and seals.
-- Access only through the explicitly connected privileged Supabase tool.
CREATE TABLE IF NOT EXISTS sefirot.daily_report_archive (
    report_day date NOT NULL,
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    saved_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (report_day, sha256)
);
COMMENT ON TABLE sefirot.daily_report_archive IS
'PRIVATE user day-end report snapshots; unverified, versioned, no wager permissions. Not a source of original CORE forecasts.';

ALTER TABLE sefirot.daily_report_archive ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE sefirot.daily_report_archive FROM PUBLIC, anon, authenticated, service_role;

CREATE OR REPLACE FUNCTION sefirot.block_daily_report_changes()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, sefirot
AS $$
BEGIN
    RAISE EXCEPTION 'IMMUTABLE_DAILY_ARCHIVE' USING ERRCODE = '23514';
END;
$$;
REVOKE ALL ON FUNCTION sefirot.block_daily_report_changes()
    FROM PUBLIC, anon, authenticated, service_role;
DROP TRIGGER IF EXISTS daily_report_immutable_row ON sefirot.daily_report_archive;
CREATE TRIGGER daily_report_immutable_row
    BEFORE UPDATE OR DELETE ON sefirot.daily_report_archive
    FOR EACH ROW EXECUTE FUNCTION sefirot.block_daily_report_changes();
DROP TRIGGER IF EXISTS daily_report_immutable_truncate ON sefirot.daily_report_archive;
CREATE TRIGGER daily_report_immutable_truncate
    BEFORE TRUNCATE ON sefirot.daily_report_archive
    FOR EACH STATEMENT EXECUTE FUNCTION sefirot.block_daily_report_changes();

CREATE OR REPLACE FUNCTION sefirot.save_daily_report(p_payload jsonb)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, sefirot
AS $$
DECLARE
    v_day date;
    v_hash text;
    v_rows integer;
    v_count integer;
    v_ref jsonb;
    v_existing jsonb;
    v_saved_at timestamptz;
BEGIN
    IF p_payload IS NULL OR jsonb_typeof(p_payload) <> 'object' OR
       (SELECT count(*) FROM jsonb_object_keys(p_payload)) <> 7 OR
       NOT (p_payload ?& ARRAY['schema','day','timezone','origin','status','source_refs','report']) THEN
        RAISE EXCEPTION 'INVALID_DAILY_REPORT_FIELDS' USING ERRCODE = '22023';
    END IF;
    IF (p_payload->>'schema') IS DISTINCT FROM 'sefirot-daily-report-v1'
        OR (p_payload->>'timezone') IS DISTINCT FROM 'Europe/Kyiv'
        OR (p_payload->>'status') IS DISTINCT FROM 'REPORTED_UNVERIFIED'
        OR coalesce(p_payload->>'origin','') NOT IN ('CHAT_DAILY','TICKET_AUDIT') THEN
        RAISE EXCEPTION 'INVALID_DAILY_REPORT_CONTRACT' USING ERRCODE = '22023';
    END IF;
    IF jsonb_typeof(p_payload->'day') <> 'string'
       OR p_payload->>'day' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN
        RAISE EXCEPTION 'INVALID_DAILY_REPORT_DAY' USING ERRCODE = '22023';
    END IF;
    v_day := (p_payload->>'day')::date;
    IF v_day::text <> p_payload->>'day' THEN
        RAISE EXCEPTION 'NONCANONICAL_REPORT_DAY' USING ERRCODE = '22023';
    END IF;
    IF jsonb_typeof(p_payload->'source_refs') <> 'array' THEN
        RAISE EXCEPTION 'INVALID_SOURCE_REFS' USING ERRCODE = '22023';
    END IF;
    IF jsonb_array_length(p_payload->'source_refs') > 100 THEN
        RAISE EXCEPTION 'TOO_MANY_SOURCE_REFS' USING ERRCODE = '22023';
    END IF;
    FOR v_ref IN SELECT value FROM jsonb_array_elements(p_payload->'source_refs')
    LOOP
        IF jsonb_typeof(v_ref) <> 'string'
           OR length(v_ref #>> '{}') NOT BETWEEN 1 AND 300 THEN
            RAISE EXCEPTION 'INVALID_SOURCE_REF_VALUE' USING ERRCODE = '22023';
        END IF;
    END LOOP;
    IF p_payload->>'origin' = 'CHAT_DAILY' THEN
        IF jsonb_typeof(p_payload->'report') <> 'string'
           OR btrim(p_payload->>'report') = '' THEN
            RAISE EXCEPTION 'EMPTY_DAILY_CHAT_REPORT' USING ERRCODE = '22023';
        END IF;
    ELSE
        IF jsonb_typeof(p_payload->'report') <> 'object'
           OR (p_payload->'report'->>'schema') IS DISTINCT FROM 'ticket-audit-v1'
           OR (p_payload->'report'->>'status') IS DISTINCT FROM 'REPORTED_UNVERIFIED'
           OR (p_payload->'report'->'monetary_permission') IS DISTINCT FROM 'false'::jsonb THEN
            RAISE EXCEPTION 'INVALID_TICKET_AUDIT' USING ERRCODE = '22023';
        END IF;
        IF jsonb_typeof(p_payload->'report'->'days') IS DISTINCT FROM 'array' THEN
            RAISE EXCEPTION 'INVALID_TICKET_AUDIT_DAYS' USING ERRCODE = '22023';
        END IF;
        IF jsonb_array_length(p_payload->'report'->'days') <> 1
           OR (p_payload->'report'->'days'->0->>'day') IS DISTINCT FROM v_day::text
           OR (p_payload->'report'->>'timezone') IS DISTINCT FROM 'Europe/Kyiv' THEN
            RAISE EXCEPTION 'MIXED_OR_DIFFERENT_REPORT_DAYS' USING ERRCODE = '22023';
        END IF;
    END IF;
    IF octet_length(convert_to(p_payload::text, 'UTF8')) > 512000 THEN
        RAISE EXCEPTION 'DAILY_REPORT_TOO_LARGE' USING ERRCODE = '22023';
    END IF;

    -- PostgreSQL jsonb::text canonical serialization is the CLOUD hash contract.
    -- It is NOT the same byte representation as Python's local canonical encoder.
    v_hash := encode(sha256(convert_to(p_payload::text, 'UTF8')), 'hex');
    INSERT INTO sefirot.daily_report_archive(report_day, sha256, payload)
    VALUES (v_day, v_hash, p_payload)
    ON CONFLICT (report_day, sha256) DO NOTHING;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    SELECT payload, saved_at INTO STRICT v_existing, v_saved_at
      FROM sefirot.daily_report_archive
      WHERE report_day = v_day AND sha256 = v_hash;
    IF v_existing IS DISTINCT FROM p_payload OR
       encode(sha256(convert_to(v_existing::text, 'UTF8')), 'hex') <> v_hash THEN
        RAISE EXCEPTION 'DAILY_REPORT_READBACK_MISMATCH' USING ERRCODE = '23514';
    END IF;
    SELECT count(*) INTO v_count FROM sefirot.daily_report_archive WHERE report_day = v_day;
    RETURN jsonb_build_object(
        'saved', true,
        'backend', 'PRIVATE_SUPABASE',
        'new_version', v_rows = 1,
        'day', v_day::text,
        'sha256', v_hash,
        'versions_for_day', v_count,
        'saved_at', v_saved_at,
        'status', 'REPORTED_UNVERIFIED'
    );
END;
$$;
REVOKE ALL ON FUNCTION sefirot.save_daily_report(jsonb)
    FROM PUBLIC, anon, authenticated, service_role;
