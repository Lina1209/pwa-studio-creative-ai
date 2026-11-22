[object Object]

## 13. IndexedDB recovery mirror and user-managed backups

Added `movie-storage.js` and integrated it with Mini Movie Studio:

- Account-scoped IndexedDB mirror for project drafts and deletion tombstones, while retaining synchronous localStorage compatibility and fallback.
- Startup/account-switch recovery merges IndexedDB and localStorage by project ID and latest timestamp; scope checks prevent one signed-in account from restoring another account's records.
- JSON export/import controls validate the backup schema, file size, project identity fields, and account/guest scope. Import merges rather than blindly overwriting newer local projects.
- Backups exclude credentials and session tokens.

Limitations: IndexedDB is still browser-local and can be cleared or lost with the device; it is not an off-device backup. Import does not reapply deletion tombstones, and complete multi-device conflict resolution is not implemented. Keep downloaded backups in a separate safe location. No production deployment, Supabase migration, or live device validation was performed.
