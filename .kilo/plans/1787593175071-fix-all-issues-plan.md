# Fix All Issues Plan

## Overview
Fix 33 issues across backend, frontend, security, testing, and config. Grouped by priority: Critical (5 runtime crashes) → High (6 reliability/security) → Medium (12) → Low (10).

---

## Phase 1: Critical - Missing Imports (Runtime Crashes)

### 1.1 Add `logging` import to `backend/main.py`
- **File**: `backend/main.py`
- **Lines**: Add `import logging` at top (after `import time as time_module`)
- **Fix**: `logger = logging.getLogger(__name__)` before first use (line ~57)

### 1.2 Add `logging` import to `backend/services/otl_client.py`
- **File**: `backend/services/otl_client.py`
- **Lines**: Add `import logging` at top; `logger = logging.getLogger(__name__)` before CircuitBreaker class

### 1.3 Add `asyncio` import to `backend/core/auth.py`
- **File**: `backend/core/auth.py`
- **Lines**: Add `import asyncio` at top (after `import secrets`)

### 1.4 Add `logging` import to `backend/services/fusion_catalogue.py`
- **File**: `backend/services/fusion_catalogue.py`
- **Lines**: Add `import logging` at top (already has `logger = logging.getLogger(__name__)` at line 28 but missing import)

---

## Phase 2: High - Concurrency & Resource Management

### 2.1 Fix token blocklist singleton race condition
- **File**: `backend/core/auth.py` lines 49-65
- **Issue**: `__new__` uses `threading.Lock` but `_init_lock` is `asyncio.Lock`
- **Fix**: Use `threading.Lock` consistently for sync singleton init; remove async lock from class var

### 2.2 Fix `destroy()` event loop handling
- **File**: `backend/core/auth.py` lines 186-195
- **Issue**: `asyncio.run()` in sync context breaks if called from async
- **Fix**: Use `asyncio.get_event_loop().create_task()` when loop running; only `asyncio.run()` when no loop

### 2.3 Fix STT WebSocket connection error handling
- **File**: `frontend/src/lib/voice.ts` lines 111-178
- **Issue**: No handling for connection failure before `onopen`
- **Fix**: Add connection timeout; handle `ws.onerror` for pre-connection failures

### 2.4 Fix STT WebSocket cleanup race conditions
- **File**: `frontend/src/lib/voice.ts` lines 167-178
- **Issue**: Multiple cleanup paths can double-cleanup
- **Fix**: Add `isCleaningUp` flag; guard all cleanup paths

### 2.5 Fix AudioWorklet blob URL memory leak
- **File**: `frontend/src/lib/voice.ts` line 116
- **Issue**: `URL.createObjectURL()` never revoked
- **Fix**: Store URL in ref; revoke in `cleanup()`

### 2.6 Add request validation to `/api/chat`
- **File**: `backend/main.py` lines 600-647
- **Issue**: No limits on message count, length, role validation
- **Fix**: Add Pydantic model with constraints (max 50 messages, max 10k chars each, valid roles)

### 2.7 Fix circuit breaker to ignore 4xx errors
- **File**: `backend/services/otl_client.py` lines 130-145
- **Issue**: Opens circuit for client errors (4xx)
- **Fix**: Only count 5xx and network errors as failures

---

## Phase 3: Medium - Logic & UX Fixes

### 3.1 Fix ReviewPanel auto-submit race condition
- **File**: `frontend/src/components/ReviewPanel.tsx` lines 55-74
- **Fix**: Use `useRef` for submitted flag; clear countdown immediately on submit start

### 3.2 Add backpressure to TTS queue
- **File**: `frontend/src/components/ChatView.tsx` lines 134-148
- **Fix**: When queue full, pause SSE processing (signal backpressure) instead of dropping

### 3.3 Fix ChatView barge-in handling
- **File**: `frontend/src/components/ChatView.tsx` lines 114-121, 182-198
- **Fix**: Don't stop mic at `runAssistant` start; only stop on explicit barge-in

### 3.4 Improve `useAudioPlayer` autoplay error handling
- **File**: `frontend/src/lib/voice.ts` lines 205-237
- **Fix**: Distinguish autoplay block (DOMException name='NotAllowedError') from other errors

### 3.5 Verify production CSP allows WebSocket
- **File**: `backend/main.py` lines 286-298
- **Fix**: Ensure `connect-src` includes nginx proxy origin for wss

### 3.6 Enable OTL healthcheck in Docker
- **File**: `deploy/docker-compose.yml` lines 39-45
- **Fix**: Uncomment `healthcheck_otl` block; adjust intervals

### 3.7 Add timecard validation during chat
- **File**: `backend/main.py` lines 931-967 (or new validation helper)
- **Fix**: Validate entry structure before queuing for submit; return user-friendly errors

### 3.8 Add rate limiting to STT WebSocket
- **File**: `backend/main.py` lines 688-794
- **Fix**: Track WebSocket connections per IP; reject if over limit

---

## Phase 4: Low - Code Quality & Config

### 4.1 Align sync/async validation in otl_client
- **File**: `backend/services/otl_client.py` lines 386-422
- **Fix**: Either both use circuit breaker or neither; recommend adding to sync version

### 4.2 Convert catalogue refresh to async
- **File**: `backend/services/fusion_catalogue.py` lines 241-400
- **Fix**: Replace `threading.Thread` with `asyncio.create_task()` + async HTTP client

### 4.3 Validate SESSION_COOKIE_SAMESITE='none' requires SECURE
- **File**: `backend/main.py` lines 518-520, 582-584
- **Fix**: Add validation: if `samesite == 'none'` and not `cookie_secure()`, error

### 4.4 Enable security middleware in tests
- **File**: `backend/tests/conftest.py` line 15
- **Fix**: Remove `TEST_MODE=true` or set to `false` for security tests; add separate test for middleware

### 4.5 Refactor frontend tests to not mock hooks
- **File**: `frontend/src/components/ChatView.test.tsx` lines 8-32
- **Fix**: Mock API layer only; test component behavior through user interactions

### 4.6 Add SESSION_SECRET_KEY generation script
- **File**: New script or update `.env.example`
- **Fix**: Add `python -c "import secrets; print(secrets.token_urlsafe(32))"` as executable command in docs

### 4.7 Align FRONTEND_DIST paths
- **File**: `Containerfile` line 21 vs `backend/main.py` line 1084
- **Fix**: Use same default path; prefer `/app/frontend/dist` in both

### 4.8 Make KICKOFF message configurable
- **File**: `frontend/src/components/ChatView.tsx` line 14
- **Fix**: Move to config/env or pass as prop

### 4.9 Clean up mockMic test flag
- **File**: `frontend/src/components/Composer.tsx` lines 77-80
- **Fix**: Remove after test or guard with `process.env.NODE_ENV === 'test'`

### 4.10 Optimize catalogue fuzzy match
- **File**: `backend/services/fusion_catalogue.py` lines 437-445
- **Fix**: Add SQL `LIKE` query for fuzzy match; limit results

---

## Validation Plan

### Automated Checks
- `uv run ruff check backend` - lint
- `uv run mypy backend` - type check
- `uv run pytest backend/tests` - unit tests
- `cd frontend && npm run lint && npm run typecheck && npm run test:unit` - frontend checks

### Manual Verification
1. Start app with `docker compose -f deploy/docker-compose.yml up --build`
2. Verify login flow works (CSRF, rate limiting active)
3. Test STT WebSocket connection (mic button)
4. Test TTS playback (voice toggle)
5. Submit timecard end-to-end
6. Verify catalogue refresh works
7. Check health endpoints: `/api/health`, `/api/health/otl`

---

## Dependencies & Order

```
Phase 1 (Critical) → Phase 2 (High) → Phase 3 (Medium) → Phase 4 (Low)
```

Within each phase, tasks can run in parallel except:
- 2.1 before 2.2 (both auth.py)
- 2.3 before 2.4 (both voice.ts)
- 3.6 requires 1.1-1.4 working

---

## Open Questions

1. **STT WebSocket rate limit**: What limit per IP? (Recommend: 5 concurrent)
2. **Chat message limits**: Max 50 messages, 10k chars each - adjust?
3. **Catalogue async conversion**: Accept breaking change to sync callers (`list_assignments_for_worker`)?
4. **TEST_MODE**: Keep disabled for all tests or enable for specific security tests?