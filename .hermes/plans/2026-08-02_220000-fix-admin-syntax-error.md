# Fix SyntaxError in Admin HTML - Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Fix SyntaxError "Invalid or unexpected token" at admin.html:1886:19 and any remaining template literal issues in the admin HTML file.

**Architecture:** The admin.html is a single-file SPA with embedded JavaScript. The issue is in template literals that were partially fixed by sed but may have residual escaping issues. The error at line 1886 suggests a template literal syntax problem in the renderAvailabilityTab function.

**Tech Stack:** Vanilla JS SPA embedded in HTML, FastAPI backend.

---

## Current State Analysis

### What Works
- All Python tests pass (67 passed)
- Mypy/Ruff clean on Python files
- Backend API endpoints working
- HTML serves correctly

### What's Broken
- **SyntaxError at admin:1886:19** - "Invalid or unexpected token" in browser console
- Multiple Bitwarden extension errors (noise, not related to app)
- The error occurs in `renderAvailabilityTab` function around line 1886

### Root Cause
Previous sed commands to fix template literals (`sed -i 's/\\\\`/`/g'`) may have missed some occurrences or created new issues. The template literals in JavaScript embedded in HTML have complex escaping due to:
1. HTML escaping
2. JavaScript template literal syntax (backticks)
3. String interpolation with `${}`
4. Escaped backticks `\\`` and escaped `${}` in the original code

---

## Plan

### Task 1: Locate and Analyze the SyntaxError at Line 1886

**Objective:** Identify the exact syntax error at admin.html:1886:19

**Files:**
- Read: `src/otelms/api/static/admin.html:1880-1895`

**Step 1: Examine the exact line 1886 and surrounding context**
```bash
sed -n '1880,1895p' src/otelms/api/static/admin.html
```

**Step 2: Identify the specific token causing the error at column 19**

**Step 3: Determine if it's a template literal, string escaping, or character encoding issue**

---

### Task 2: Fix the SyntaxError in renderAvailabilityTab

**Objective:** Correct the template literal syntax error at line 1886

**Files:**
- Modify: `src/otelms/api/static/admin.html:1881-1890`

**Step 1: Create a test to verify the error exists**
```bash
# Open in browser dev tools to confirm SyntaxError at line 1886
```

**Step 2: Fix the template literal syntax**
The issue is likely in the ternary operator within the template literal. The fix may involve:
- Ensuring proper backtick usage (not escaped)
- Fixing any remaining `\\${` to `${` 
- Fixing any remaining `\\`` to `` ` ``
- Properly escaping quotes within template literals

**Step 3: Verify the fix**
```bash
# Reload page in browser, check console for SyntaxError
```

---

### Task 3: Scan and Fix All Remaining Template Literal Issues

**Objective:** Ensure no other SyntaxError exists in the admin.html

**Files:**
- Read: `src/otelms/api/static/admin.html` (full scan)
- Modify: Any remaining problematic template literals

**Step 1: Search for remaining escaped backticks**
```bash
grep -n '\\\\`' src/otelms/api/static/admin.html
```

**Step 2: Search for remaining escaped template expressions**
```bash
grep -n '\\\\$' src/otelms/api/static/admin.html
```

**Step 3: Fix all occurrences**
Use sed or manual patches to fix all remaining issues.

---

### Task 4: Verify All JavaScript Loads Without Syntax Errors

**Objective:** Confirm the admin page loads without any SyntaxError in browser console

**Files:**
- Test: Browser console check

**Step 1: Reload admin page**
```bash
curl -s http://127.0.0.1:8010/admin | head -5
```

**Step 2: Check browser console for any SyntaxError**
- Open http://127.0.0.1:8010/admin in browser
- Open DevTools Console
- Verify no "SyntaxError: Invalid or unexpected token" errors

**Step 3: Test all tabs load**
- Click through all 6 main tabs
- Click through all 6 sub-tabs in Tasks tab
- Verify no JavaScript errors

---

### Task 5: Run Full Test Suite to Ensure No Regressions

**Objective:** Ensure all tests still pass after HTML fixes

**Files:**
- Test: `tests/unit/`

**Step 1: Run full test suite**
```bash
env -u PYTHONPATH .venv/Scripts/python.exe -m pytest tests/unit/ -v
```

**Step 2: Run mypy and ruff on modified files**
```bash
env -u PYTHONPATH .venv/Scripts/python.exe -m mypy src/otelms/api/routes/admin.py
env -u PYTHONPATH uvx ruff check src/otelms/api/static/admin.html
```

---

## Verification Steps

1. **Browser Console**: Zero SyntaxError entries
2. **All 6 main tabs load**: Dashboard, Hoteles, Sync Logs, Config, Tablas, Tareas
3. **All 6 sub-tabs in Tareas**: Close/Open, Availability, Guests, Reservations, Move, Notifications
4. **All API endpoints respond**: 200 OK for tasks endpoints
5. **Tests pass**: 67 passed, 2 skipped
4. **Mypy/Ruff**: Clean

---

## Risks & Tradeoffs

| Risk | Mitigation |
|------|------------|
| Multiple template literal fixes may introduce new errors | Test after each fix, use browser console |
| HTML file is large (2261 lines) | Fix in small batches, verify incrementally |
| Bitwarden extension noise in console | Filter console to show only app errors |

---

## Open Questions

1. Are there any other browser-specific JavaScript features that might cause issues?
2. Should we consider extracting JavaScript to a separate .js file for better maintainability?

---

*Plan saved to `.hermes/plans/2026-08-02_220000-fix-admin-syntax-error.md`*