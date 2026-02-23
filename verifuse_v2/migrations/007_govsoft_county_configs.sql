-- 007_govsoft_county_configs.sql
CREATE TABLE IF NOT EXISTS govsoft_county_configs (
    county                TEXT    PRIMARY KEY,
    base_url              TEXT    NOT NULL,
    requires_accept_terms INTEGER NOT NULL DEFAULT 1,
    captcha_mode          TEXT    NOT NULL
                          CHECK(captcha_mode IN ('none','entry','detail'))
                          DEFAULT 'none',
    documents_enabled     INTEGER NOT NULL DEFAULT 1,
    page_limit            INTEGER NOT NULL DEFAULT 90,
    active                INTEGER NOT NULL DEFAULT 1,
    search_path           TEXT    NOT NULL DEFAULT '/SearchDetails.aspx',
    selectors_json        TEXT,
    last_verified_ts      INTEGER
);

-- Seed from existing county_profiles (idempotent)
INSERT OR IGNORE INTO govsoft_county_configs
    (county, base_url, requires_accept_terms, captcha_mode,
     documents_enabled, active)
SELECT county, base_url, requires_accept_terms, captcha_mode, 1, 1
FROM county_profiles
WHERE platform_type = 'govsoft';
