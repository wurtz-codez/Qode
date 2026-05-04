---
name: qode-refactoring
description: Plan safe refactors using blast radius and dependency mapping
---

# Refactoring with Qode

## When to Use
- "Rename this function safely"
- "Extract this into a module"
- "Split this service"
- "Move this to a new file"
- Any task involving renaming, extracting, splitting, or restructuring code

## Workflow

```
1. qode_impact({target: "X", direction: "upstream"})  → Map all dependents
2. qode_query({query: "X"})                            → Find execution flows involving X
3. qode_context({name: "X"})                           → See all incoming/outgoing refs
4. Plan update order: interfaces → implementations → callers → tests
```

> If "Index is stale" → run `npx qode analyze` in terminal.

## Checklists

### Rename Symbol
```
- [ ] qode_rename({symbol_name: "oldName", new_name: "newName", dry_run: true}) — preview all edits
- [ ] Review graph edits (high confidence) and ast_search edits (review carefully)
- [ ] If satisfied: qode_rename({..., dry_run: false}) — apply edits
- [ ] qode_detect_changes() — verify only expected files changed
- [ ] Run tests for affected processes
```

### Extract Module
```
- [ ] qode_context({name: target}) — see all incoming/outgoing refs
- [ ] qode_impact({target, direction: "upstream"}) — find all external callers
- [ ] Define new module interface
- [ ] Extract code, update imports
- [ ] qode_detect_changes() — verify affected scope
- [ ] Run tests for affected processes
```

### Split Function/Service
```
- [ ] qode_context({name: target}) — understand all callees
- [ ] Group callees by responsibility
- [ ] qode_impact({target, direction: "upstream"}) — map callers to update
- [ ] Create new functions/services
- [ ] Update callers
- [ ] qode_detect_changes() — verify affected scope
- [ ] Run tests for affected processes
```

## Tools

**qode_rename** — automated multi-file rename:
```
qode_rename({symbol_name: "validateUser", new_name: "authenticateUser", dry_run: true})
→ 12 edits across 8 files
→ 10 graph edits (high confidence), 2 ast_search edits (review)
→ Changes: [{file_path, edits: [{line, old_text, new_text, confidence}]}]
```

**qode_impact** — map all dependents first:
```
qode_impact({target: "validateUser", direction: "upstream"})
→ d=1: loginHandler, apiMiddleware, testUtils
→ Affected Processes: LoginFlow, TokenRefresh
```

**qode_detect_changes** — verify your changes after refactoring:
```
qode_detect_changes({scope: "all"})
→ Changed: 8 files, 12 symbols
→ Affected processes: LoginFlow, TokenRefresh
→ Risk: MEDIUM
```

**qode_cypher** — custom reference queries:
```cypher
MATCH (caller)-[:CodeRelation {type: 'CALLS'}]->(f:Function {name: "validateUser"})
RETURN caller.name, caller.filePath ORDER BY caller.filePath
```

## Risk Rules

| Risk Factor | Mitigation |
|-------------|------------|
| Many callers (>5) | Use qode_rename for automated updates |
| Cross-area refs | Use detect_changes after to verify scope |
| String/dynamic refs | qode_query to find them |
| External/public API | Version and deprecate properly |

## Example: Rename `validateUser` to `authenticateUser`

```
1. qode_rename({symbol_name: "validateUser", new_name: "authenticateUser", dry_run: true})
   → 12 edits: 10 graph (safe), 2 ast_search (review)
   → Files: validator.ts, login.ts, middleware.ts, config.json...

2. Review ast_search edits (config.json: dynamic reference!)

3. qode_rename({symbol_name: "validateUser", new_name: "authenticateUser", dry_run: false})
   → Applied 12 edits across 8 files

4. qode_detect_changes({scope: "all"})
   → Affected: LoginFlow, TokenRefresh
   → Risk: MEDIUM — run tests for these flows
```
