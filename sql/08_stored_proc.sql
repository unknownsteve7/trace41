CREATE OR REPLACE PROCEDURE sp_refresh_matviews()
LANGUAGE plpgsql AS $$
BEGIN
    REFRESH MATERIALIZED VIEW mv_hourly_headway;
END;
$$;
CREATE OR REPLACE PROCEDURE sp_load_realtime_day(
    p_date        DATE,
    p_rows_loaded INT,
    p_rows_quar   INT,
    p_status      VARCHAR DEFAULT 'ok',
    p_message     TEXT    DEFAULT NULL
)
LANGUAGE plpgsql AS $$
DECLARE
    v_run_id INT;
BEGIN
    INSERT INTO etl_run_log (script_name, target_date, rows_loaded,
                              rows_quarantined, status, message)
    VALUES ('load_facts.actual', p_date, p_rows_loaded,
            p_rows_quar, p_status, p_message)
    RETURNING id INTO v_run_id;
    IF p_status = 'ok' AND p_rows_loaded > 0 THEN
        CALL sp_refresh_matviews();
        UPDATE etl_run_log
           SET message = COALESCE(message,'') || ' | matviews refreshed'
         WHERE id = v_run_id;
    END IF;
    COMMIT;
EXCEPTION WHEN OTHERS THEN
    INSERT INTO etl_run_log (script_name, target_date, status, message)
    VALUES ('sp_load_realtime_day', p_date, 'error', SQLERRM);
    COMMIT;
    RAISE;
END;
$$;
