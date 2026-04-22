-- ────────────────────────────────────────────────────────────────────────────
-- Per-domain evaluation report for the Regulatory Watch pipeline.
--
-- Usage:
--   docker compose exec -T db psql -U regwatch -d regwatch \
--     -v domain="'cbp.gov'" -f /tmp/domain_report.sql
--
-- (or copy-paste one section at a time if you prefer interactive psql)
-- ────────────────────────────────────────────────────────────────────────────

\echo
\echo ==================================================================
\echo  DOMAIN REPORT :: :domain
\echo ==================================================================

-- ─ 1. Ingested documents: count, languages, sizes, S3 archival
\echo
\echo ── raw_documents ──────────────────────────────────────────────────
SELECT
    source_type,
    language,
    count(*)                                  AS docs,
    pg_size_pretty(sum(length(raw_text))::bigint) AS text_bytes,
    count(*) FILTER (WHERE artifact_uri IS NOT NULL) AS archived_s3
FROM raw_documents
WHERE source_url LIKE '%' || :domain || '%'
GROUP BY source_type, language
ORDER BY source_type, language;

-- ─ 2. Version history
\echo
\echo ── source_versions (immutable history) ────────────────────────────
SELECT
    source_type,
    count(DISTINCT source_url) AS unique_urls,
    count(*)                   AS versions_total,
    count(*) FILTER (WHERE first_seen_at > now() - interval '1 hour')
                               AS versions_last_hour
FROM source_versions
WHERE source_url LIKE '%' || :domain || '%'
GROUP BY source_type;

-- ─ 3. Change events with scoring status
\echo
\echo ── change_events (+scoring breakdown) ─────────────────────────────
SELECT
    diff_kind                                                      AS kind,
    change_type                                                    AS llm_type,
    count(*)                                                       AS events,
    count(*) FILTER (WHERE significance_score IS NOT NULL)         AS scored,
    count(*) FILTER (WHERE llm_error IS NOT NULL)                  AS errored,
    count(*) FILTER (WHERE significance_score IS NULL
                       AND llm_error IS NULL)                      AS unscored,
    round(avg(significance_score)::numeric, 2)                     AS avg_score
FROM change_events
WHERE source_url LIKE '%' || :domain || '%'
GROUP BY diff_kind, change_type
ORDER BY diff_kind, llm_type NULLS LAST;

-- ─ 4. Top-scored events (what an alert would surface)
\echo
\echo ── top-scored change events ───────────────────────────────────────
SELECT
    to_char(detected_at, 'YYYY-MM-DD HH24:MI')  AS when,
    diff_kind,
    round(significance_score::numeric, 2)       AS score,
    change_type,
    topic,
    left(regexp_replace(source_url, '^https?://', ''), 60) AS url,
    left(coalesce(summary, '(no summary)'), 90) AS summary
FROM change_events
WHERE source_url LIKE '%' || :domain || '%'
  AND significance_score IS NOT NULL
ORDER BY significance_score DESC NULLS LAST, detected_at DESC
LIMIT 10;

-- ─ 5. Topic distribution (M4)
\echo
\echo ── topic distribution ─────────────────────────────────────────────
SELECT
    coalesce(topic, '(unscored)')       AS topic,
    count(*)                            AS events,
    round(avg(significance_score)::numeric, 2) AS avg_score
FROM change_events
WHERE source_url LIKE '%' || :domain || '%'
GROUP BY topic
ORDER BY events DESC;

-- ─ 6. Top entities mentioned (M4)
\echo
\echo ── top entities (last 30d) ────────────────────────────────────────
SELECT
    e.entity_type,
    e.display_name,
    count(*) AS mentions
FROM entities e
JOIN change_event_entities x ON x.entity_id = e.id
JOIN change_events         c ON c.id       = x.change_event_id
WHERE c.source_url LIKE '%' || :domain || '%'
  AND c.detected_at > now() - interval '30 days'
GROUP BY e.id, e.entity_type, e.display_name
ORDER BY mentions DESC, e.display_name
LIMIT 15;

-- ─ 7. Extracted obligations (M4)
\echo
\echo ── obligations (recent) ───────────────────────────────────────────
SELECT
    o.obligation_type                           AS type,
    coalesce(o.deadline_date::text,
             left(o.deadline_text, 20), '-')    AS deadline,
    left(o.actor, 30)                           AS actor,
    left(o.action, 80)                          AS action
FROM obligations o
JOIN change_events c ON c.id = o.change_event_id
WHERE c.source_url LIKE '%' || :domain || '%'
ORDER BY o.extracted_at DESC
LIMIT 10;

-- ─ 8. Latest raw sample (what the extractor actually captured)
\echo
\echo ── latest extracted sample ────────────────────────────────────────
SELECT
    source_type,
    language,
    left(title, 60)          AS title,
    length(raw_text)         AS chars,
    left(raw_text, 200)      AS preview
FROM raw_documents
WHERE source_url LIKE '%' || :domain || '%'
ORDER BY fetched_at DESC
LIMIT 3;
