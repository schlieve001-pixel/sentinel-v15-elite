# VeriFuse Incident Response

## Rollback Steps

### API code rollback
```bash
git log --oneline -10        # find last good commit
git checkout COMMIT_HASH -- verifuse_v2/server/api.py
bin/vf api-restart
bin/vf gauntlet
```

### Full DB rollback
```bash
bin/vf api-stop
bin/vf logs-scraper          # confirm no scraper is running
cp "${VERIFUSE_DB_PATH}.bak.TIMESTAMP" "${VERIFUSE_DB_PATH}"
bin/vf api-start
bin/vf gauntlet
```

## Disable Timer (Emergency Stop Ingestion)

```bash
systemctl stop verifuse-scrapers.timer
systemctl disable verifuse-scrapers.timer
# Confirm no active scraper:
journalctl -u verifuse-scrapers --since "1 hour ago" | tail -20
```

Re-enable when safe:
```bash
systemctl enable --now verifuse-scrapers.timer
```

## Restore DB from Backup

1. Stop the API: `bin/vf api-stop`
2. Confirm no scraper running (check journalctl)
3. Copy backup: `cp "${VERIFUSE_DB_PATH}.bak.TIMESTAMP" "${VERIFUSE_DB_PATH}"`
4. Re-run migrations (safe — idempotent): `bin/vf migrate`
5. Start API: `bin/vf api-start`
6. Verify: `bin/vf gauntlet`

## Revoke User Access

```bash
bin/vf db-shell
sqlite> UPDATE users SET is_active=0 WHERE user_id='...';
# Active sessions will fail on next request (role read from DB, not JWT)
```

To revoke admin:
```bash
sqlite> UPDATE users SET role='public', is_admin=0 WHERE user_id='...';
```

## Quarantine Ingested Data

To block a case from appearing in the API while investigation proceeds:
```bash
bin/vf db-shell
sqlite> UPDATE leads SET data_grade='QUARANTINE' WHERE county='jefferson' AND case_number='J2400300';
# Alternatively, remove from asset_registry or mark processing_status='NEEDS_REVIEW'
```

## Suspicious Evidence File

If a vault file is suspected to be malformed or harmful:
```bash
# Move out of vault
mv /var/lib/verifuse/vault/govsoft/jefferson/J2400300/original/suspicious.pdf \
   /var/lib/verifuse/quarantine/

# Remove DB reference
bin/vf db-shell
sqlite> DELETE FROM evidence_documents WHERE file_path LIKE '%suspicious.pdf%';
```

## Contact Escalation

1. DB integrity issues → check `PRAGMA integrity_check` and restore from backup
2. Stripe webhook anomalies → check `stripe_events` table + Stripe dashboard
3. GovSoft auth failure → rotate credentials in `/etc/verifuse/verifuse.env`, restart
4. JWT secret compromise → rotate `VERIFUSE_JWT_SECRET`, all sessions invalidated immediately (DB re-auth on next request)
