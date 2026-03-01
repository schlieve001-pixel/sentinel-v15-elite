-- 010_surplus_streams.sql
-- Adds surplus stream classification and estate case support.
--
-- surplus_stream values: FORECLOSURE_OVERBID | TAX_LIEN | TAX_DEED | HOA | UNCLAIMED_PROPERTY
-- has_deceased_indicator: 1 if owner appears in probate index or deceased indicator found
-- owner_mailing_address: pulled from county assessor public records

-- ── leads.surplus_stream ──────────────────────────────────────────────────────
-- SQLite does not support ALTER TABLE ADD COLUMN IF NOT EXISTS, so this is
-- handled idempotently in run_migrations.py (column check before ALTER).

-- ── asset_registry columns ────────────────────────────────────────────────────
-- Added idempotently in run_migrations.py apply_phase13().

-- ── county_profiles: seed GovSoft Pattern A counties ─────────────────────────
INSERT OR IGNORE INTO county_profiles
    (county, platform_type, captcha_mode, requires_accept_terms,
     base_url, search_path, detail_path)
VALUES
    -- Pattern A GovSoft (no CAPTCHA, accept-terms required)
    ('adams',      'govsoft', 'none',  1,
     'https://apps.adcogov.org/PTForeclosureSearch/',
     '/SearchDetails.aspx', '/CaseDetails.aspx'),
    ('douglas',    'govsoft', 'none',  1,
     'https://apps.douglas.co.us/PublicTrusteeForeclosureSearch/',
     '/SearchDetails.aspx', '/CaseDetails.aspx'),
    ('boulder',    'govsoft', 'none',  1,
     'https://apps.bouldercounty.org/PublicTrusteeSearch/',
     '/SearchDetails.aspx', '/CaseDetails.aspx'),
    ('broomfield', 'govsoft', 'none',  1,
     'https://apps.broomfield.org/PublicTrusteeForeclosureSearch/',
     '/SearchDetails.aspx', '/CaseDetails.aspx'),
    ('gilpin',     'govsoft', 'none',  1,
     'https://apps.co.gilpin.co.us/PublicTrusteeSearch/',
     '/SearchDetails.aspx', '/CaseDetails.aspx'),
    ('weld',       'govsoft', 'none',  1,
     'https://apps.weldgov.com/PublicTrusteeForeclosureSearch/',
     '/SearchDetails.aspx', '/CaseDetails.aspx'),
    -- Pattern B GovSoft (CAPTCHA on detail page)
    ('mesa',       'govsoft', 'detail', 1,
     'https://apps.mesacounty.us/PublicTrusteeSearch/',
     '/SearchDetails.aspx', '/CaseDetails.aspx'),
    ('eagle',      'govsoft', 'detail', 1,
     'https://apps.eaglecounty.us/PublicTrusteeForeclosureSearch/',
     '/SearchDetails.aspx', '/CaseDetails.aspx');

-- ── govsoft_county_configs: mirror Pattern A counties ────────────────────────
INSERT OR IGNORE INTO govsoft_county_configs
    (county, base_url, requires_accept_terms, captcha_mode, documents_enabled, active)
VALUES
    ('adams',      'https://apps.adcogov.org/PTForeclosureSearch/',                        1, 'none',   1, 1),
    ('douglas',    'https://apps.douglas.co.us/PublicTrusteeForeclosureSearch/',           1, 'none',   1, 1),
    ('boulder',    'https://apps.bouldercounty.org/PublicTrusteeSearch/',                  1, 'none',   1, 1),
    ('broomfield', 'https://apps.broomfield.org/PublicTrusteeForeclosureSearch/',          1, 'none',   1, 1),
    ('gilpin',     'https://apps.co.gilpin.co.us/PublicTrusteeSearch/',                    1, 'none',   1, 1),
    ('weld',       'https://apps.weldgov.com/PublicTrusteeForeclosureSearch/',             1, 'none',   1, 1),
    ('mesa',       'https://apps.mesacounty.us/PublicTrusteeSearch/',                      1, 'detail', 1, 1),
    ('eagle',      'https://apps.eaglecounty.us/PublicTrusteeForeclosureSearch/',          1, 'detail', 1, 1);

-- ── el_paso update (realforeclose platform, not govsoft) ─────────────────────
INSERT OR IGNORE INTO county_profiles
    (county, platform_type, captcha_mode, requires_accept_terms,
     base_url, search_path, detail_path)
VALUES
    ('el_paso',    'realforeclose', 'none', 0,
     'https://elpaso.realforeclose.com',
     '/default.aspx', '/details.aspx');

-- ── larimer (custom MVC) ─────────────────────────────────────────────────────
INSERT OR IGNORE INTO county_profiles
    (county, platform_type, captcha_mode, requires_accept_terms,
     base_url, search_path, detail_path)
VALUES
    ('larimer',    'realforeclose', 'none', 0,
     'https://larimer.realforeclose.com',
     '/default.aspx', '/details.aspx');
