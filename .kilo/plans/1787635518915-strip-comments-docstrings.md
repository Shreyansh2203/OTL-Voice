# Plan: Remove Comments and Docstrings from Entire Repository

## Objective
Remove all comments and docstrings from source files in the repository root, excluding:
- `node_modules/` (third-party code)
- `.venv/` (virtual environment)
- `__pycache__/` (compiled Python)
- Build artifacts and generated files
- Configuration files (package.json, pyproject.toml, etc.)

## Target Files

### Python (.py) - 32 files
**Backend source:**
- `backend/__init__.py`
- `backend/main.py`
- `backend/models.py`
- `backend/core/auth.py`
- `backend/core/oci_ai_speech_realtime/__init__.py`
- `backend/core/oci_ai_speech_realtime/ai_service_speech_realtime_client.py`
- `backend/services/otl_client.py`
- `backend/services/oci_speech.py`
- `backend/services/oci_gemini.py`
- `backend/services/fusion_catalogue.py`
- `backend/services/chat.py`

**Backend tests (may preserve):**
- `backend/tests/*.py` (7 files)
- `backend/scripts/*.py` (5 files)

**Root scripts (likely disposable):**
- `scripts/explore_fusion.py`
- `scripts/build_person_centric_catalogue.py`
- `recover*.py` (2 files)
- `patch*.py` (16 files)

### TypeScript/JavaScript (.ts, .tsx, .js) - 30 files
**Frontend source:**
- `frontend/src/main.tsx`
- `frontend/src/App.tsx`
- `frontend/src/types.ts`
- `frontend/src/vite-env.d.ts`
- `frontend/src/api/client.ts`
- `frontend/src/lib/voice.ts`, `sse.ts`, `entries.ts`, `chat.ts`, `audio.ts`
- `frontend/src/components/*.tsx` (12 component files)

**Frontend tests (may preserve):**
- `frontend/tests/*.ts` (5 files)
- `frontend/tests/unit/*.ts` (1 file)
- `frontend/src/**/*.test.tsx` (12 test files)

**Config (preserve comments):**
- `frontend/vite.config.ts`
- `frontend/playwright.config.ts`
- `frontend/eslint.config.js`
- `frontend/tsconfig*.json`

## Approach

### Python: Use `ast` module for safe docstring removal
- Parse AST, remove docstring nodes (module, class, function)
- Remove `#` comments while preserving string literals
- Write custom script using Python's `tokenize` module for accuracy

### TypeScript/JavaScript: Use regex-based approach
- Remove `/* ... */` multi-line comments (not in strings)
- Remove `// ...` single-line comments (not in strings)
- Preserve JSDoc-style `/** ... */` if needed for type hints

## Implementation Steps

1. **Create Python stripper script** - Uses `tokenize` to accurately remove comments/docstrings
2. **Create TypeScript stripper script** - Uses regex with string literal awareness
3. **Run on backend source files** (excluding tests if desired)
4. **Run on frontend source files** (excluding tests if desired)
5. **Verify syntax validity** - Run `mypy` on Python, `tsc` on TypeScript
6. **Run tests** - Ensure functionality preserved

## Safety Checks
- Backup files before modification
- Run type checkers after stripping
- Run test suite to verify no regressions
- Git diff to review changes

## Open Questions
- Should test files be processed? (Currently: exclude tests to preserve documentation)
- Should root patch/recover scripts be processed? (Currently: yes, they're disposable)
- Should config files be processed? (Currently: no, preserve comments in configs)