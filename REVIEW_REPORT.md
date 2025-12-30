# Review Report: Table.vue + Database/File Operations

## Scope
- Frontend detection table UI and actions: `frontend/src/views/Table.vue`, `frontend/src/composables/useTableData.js`, `frontend/src/components/DetectionActions.vue`, `frontend/src/services/media.js`.
- Database modification logic (insert/delete) and related API endpoints: `backend/core/db.py`, `backend/core/api.py`.
- File operations for recording processing, cleanup, and serving: `backend/core/main.py`, `backend/core/storage_manager.py`, `backend/core/api_utils.py`, `backend/core/utils.py`, `backend/core/audio_manager.py`.

## Findings
### High
- Recording data loss on BirdNET service errors. `process_audio_file()` collapses all BirdNET errors into an empty list, and `process_audio_files()` deletes the source `.wav` unconditionally after the call. This means transient HTTP/timeout/connection failures permanently drop recordings and prevent reprocessing. This is particularly risky during service warmup or network hiccups. References: `backend/core/main.py:311`, `backend/core/main.py:322`, `backend/core/main.py:364`, `backend/core/main.py:372`.

### Medium
- Filename generation assumes ISO timestamps always contain `T`. `build_detection_filenames()` splits `timestamp` on `T` without guarding for legacy or malformed formats; a non-ISO timestamp (e.g., `YYYY-MM-DD HH:MM:SS`) will raise and break API responses, deletions, and cleanup flows that depend on filenames. This can surface when working with older DBs or imported data. References: `backend/core/utils.py:49`, `backend/core/utils.py:51`, `backend/core/db.py:842`.

### Low
- Selection persists across page/filter changes without clear UI visibility, which can lead to unintended batch deletes of items not currently visible. `selectedIds` is global across pagination and is not cleared on `setFilters()`/`clearFilters()`, so batch delete can target records from previous pages or filters. References: `frontend/src/composables/useTableData.js:36`, `frontend/src/composables/useTableData.js:275`, `frontend/src/composables/useTableData.js:288`.

## Notes
- I did not find SQL injection issues in the DB modification paths; sort fields and order are validated before query interpolation in the paginated query path. References: `backend/core/db.py:768`, `backend/core/db.py:773`.
- File-serving endpoints reject path traversal in filenames (`/`, `\\`, `..`). Reference: `backend/core/api_utils.py:52`.
