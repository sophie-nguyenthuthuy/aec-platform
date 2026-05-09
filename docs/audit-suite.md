# Ratchet audit suite

<!-- GENERATED FILE — do not edit by hand. Regenerate via `python -m scripts.generate_audit_index` from `apps/api/`. Source of truth is each `tests/test_*_audit.py` docstring + its `BASELINE_*` constants. -->

Each entry below is a ratchet test in `apps/api/tests/`. The audit walks a chunk of the codebase, counts a specific bug-shape, and asserts the count hasn't grown beyond a pinned baseline. Reductions ALSO fail (with a 🎉) so a baseline drop is captured in the same PR as the fix.

Run all of them with `make audit` (~5s). They also run as a pre-commit hook (`ratchet-audits`) scoped to files any audit scans, and inside the broader `pytest` CI job.

## Index

- [Audit completeness](#audit-completeness)
- [Audit index freshness](#audit-index-freshness)
- [Ci precommit drift](#ci-precommit-drift)
- [Complexity budget](#complexity-budget)
- [Concurrency safety](#concurrency-safety)
- [Cron mutex](#cron-mutex)
- [Dep parity](#dep-parity)
- [Dependency direction](#dependency-direction)
- [Fixture duplication](#fixture-duplication)
- [Fk ondelete](#fk-ondelete)
- [Frontend bundle composition](#frontend-bundle-composition)
- [Idempotency contract](#idempotency-contract)
- [Logging structure](#logging-structure)
- [Migration safety](#migration-safety)
- [Naive datetime](#naive-datetime)
- [Openapi route docs](#openapi-route-docs)
- [Openapi tags](#openapi-tags)
- [Pydantic field constraint](#pydantic-field-constraint)
- [Pydantic strictness](#pydantic-strictness)
- [Rate limit](#rate-limit)
- [Router commit](#router-commit)
- [Router docstring](#router-docstring)
- [Secret access](#secret-access)
- [Tenant predicate](#tenant-predicate)
- [Todo aging](#todo-aging)
- [Worker retry policy](#worker-retry-policy)

## Audit completeness <a id="audit-completeness"></a>
_File:_ `apps/api/tests/test_audit_completeness_audit.py`

Audit-trail completeness audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_MISSING_AUDIT` | `124` |

**Tests**: `test_state_changing_routes_emit_audit_events_or_are_allowlisted`, `test_allowlist_entries_actually_match_routes`, `test_audit_patterns_recognise_documented_aliases`

## Audit index freshness <a id="audit-index-freshness"></a>
_File:_ `apps/api/tests/test_audit_index_freshness_audit.py`

Audit-index freshness audit.

**Tests**: `test_audit_index_doc_matches_generator_output`

## Ci precommit drift <a id="ci-precommit-drift"></a>
_File:_ `apps/api/tests/test_ci_precommit_drift_audit.py`

CI ↔ pre-commit drift audit.

**Tests**: `test_ruff_version_pin_matches_between_precommit_and_requirements`, `test_every_precommit_hook_runs_in_ci_or_is_allowlisted`, `test_ci_only_allowlist_entries_actually_appear_in_ci`, `test_pre_commit_config_is_well_formed`

## Complexity budget <a id="complexity-budget"></a>
_File:_ `apps/api/tests/test_complexity_budget_audit.py`

Per-file / per-function complexity budget audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_MAX_FILE_LOC` | `1480` |
| `BASELINE_MAX_FUNCTION_LOC` | `456` |

**Tests**: `test_no_file_exceeds_size_budget`, `test_no_function_exceeds_size_budget`, `test_allowlist_entries_correspond_to_real_targets`

## Concurrency safety <a id="concurrency-safety"></a>
_File:_ `apps/api/tests/test_concurrency_safety_audit.py`

Concurrency-safety audit (`await` inside loop bodies).

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_AWAITS_IN_LOOPS` | `60` |

**Tests**: `test_no_unsuppressed_await_inside_loop_bodies`, `test_audit_recognises_documented_patterns`

## Cron mutex <a id="cron-mutex"></a>
_File:_ `apps/api/tests/test_cron_mutex_audit.py`

Cron mutual-exclusion audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_UNSAFE_CRONS` | `8` |

**Tests**: `test_every_cron_handler_has_a_mutex_mechanism`, `test_recognised_mutex_patterns_cover_the_documented_helpers`

## Dep parity <a id="dep-parity"></a>
_File:_ `apps/api/tests/test_dep_parity_audit.py`

Cross-service Python dependency parity audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_DIVERGENT_PINS` | `2` |

**Tests**: `test_every_shared_package_pins_the_same_version_across_services`, `test_allowlist_entries_actually_appear_somewhere`, `test_pin_regex_handles_documented_formats`

## Dependency direction <a id="dependency-direction"></a>
_File:_ `apps/api/tests/test_dependency_direction_audit.py`

Dependency-direction audit (layered-architecture pin).

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_UPWARD_EDGES` | `5` |

**Tests**: `test_no_upward_layer_imports`, `test_allowlist_entries_correspond_to_real_files`, `test_layer_lookup_is_consistent`, `test_audit_recognises_documented_import_shapes`

## Fixture duplication <a id="fixture-duplication"></a>
_File:_ `apps/api/tests/test_fixture_duplication_audit.py`

Test-fixture duplication audit.

**Tests**: `test_fixture_pattern_duplication_does_not_grow`, `test_baselines_cover_every_recognised_pattern`, `test_pattern_regex_actually_matches_documented_shape`, `test_per_pattern_baseline_breakdown_is_visible_on_fail`

## Fk ondelete <a id="fk-ondelete"></a>
_File:_ `apps/api/tests/test_fk_ondelete_audit.py`

Foreign-key ON DELETE behaviour audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_FK_NO_ONDELETE` | `0` |

**Tests**: `test_every_foreign_key_has_explicit_ondelete`, `test_audit_recognises_documented_fk_call_shapes`

## Frontend bundle composition <a id="frontend-bundle-composition"></a>
_File:_ `apps/api/tests/test_frontend_bundle_composition_audit.py`

Frontend bundle composition tracker.

**Tests**: `test_no_unreviewed_packages_enter_the_bundle`, `test_no_server_only_imports_in_client_source`, `test_allowlist_entries_correspond_to_real_files`, `test_audit_recognises_documented_import_shapes`

## Idempotency contract <a id="idempotency-contract"></a>
_File:_ `apps/api/tests/test_idempotency_contract_audit.py`

Idempotency-key contract audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_NON_IDEMPOTENT_CREATES` | `33` |

**Tests**: `test_every_creation_post_uses_idempotent_route`, `test_create_pattern_matches_at_least_some_routes`, `test_idempotent_route_class_is_importable`

## Logging structure <a id="logging-structure"></a>
_File:_ `apps/api/tests/test_logging_structure_audit.py`

Logging structure contract audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_BAD_LOGGER_MSG` | `0` |

**Tests**: `test_no_logger_messages_use_f_strings_or_format`, `test_audit_recognises_documented_bad_shapes`

## Migration safety <a id="migration-safety"></a>
_File:_ `apps/api/tests/test_migration_safety_audit.py`

Alembic migration safety audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_UNSAFE_INDEX` | `9` |
| `BASELINE_UNSAFE_NOT_NULL` | `0` |

**Tests**: `test_no_locking_index_creation_on_pre_existing_tables`, `test_no_set_not_null_without_backfill_annotation`, `test_audit_recognises_documented_safety_patterns`

## Naive datetime <a id="naive-datetime"></a>
_File:_ `apps/api/tests/test_naive_datetime_audit.py`

Naive-datetime audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_NAIVE_DATETIMES` | `0` |

**Tests**: `test_no_new_naive_datetime_call_sites`, `test_audit_recognises_documented_naive_shapes`, `test_allowlist_entries_actually_correspond_to_real_lines`

## Openapi route docs <a id="openapi-route-docs"></a>
_File:_ `apps/api/tests/test_openapi_route_docs_audit.py`

OpenAPI route documentation completeness audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_UNDOCUMENTED_NAME` | `131` |
| `BASELINE_NO_RESPONSE_MODEL` | `170` |

**Tests**: `test_every_route_has_summary_or_docstring`, `test_every_route_has_response_model_or_is_allowlisted`, `test_response_model_allowlist_entries_actually_match_routes`

## Openapi tags <a id="openapi-tags"></a>
_File:_ `apps/api/tests/test_openapi_tags_audit.py`

Per-route OpenAPI tags audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_UNTAGGED_ROUTES` | `0` |

**Tests**: `test_every_route_has_at_least_one_tag`, `test_allowlist_entries_actually_match_routes`

## Pydantic field constraint <a id="pydantic-field-constraint"></a>
_File:_ `apps/api/tests/test_pydantic_field_constraint_audit.py`

Pydantic field-level constraint audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_UNCONSTRAINED_STR` | `506` |
| `BASELINE_UNCONSTRAINED_NUMERIC` | `264` |

**Tests**: `test_every_str_field_has_a_length_constraint`, `test_every_numeric_field_has_a_range_constraint`, `test_allowlist_entries_actually_correspond_to_real_fields`

## Pydantic strictness <a id="pydantic-strictness"></a>
_File:_ `apps/api/tests/test_pydantic_strictness_audit.py`

Pydantic strictness audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_NON_STRICT_COUNT` | `320` |

**Tests**: `test_every_pydantic_schema_forbids_extra_fields`, `test_allowlist_entries_actually_correspond_to_real_schemas`

## Rate limit <a id="rate-limit"></a>
_File:_ `apps/api/tests/test_rate_limit_audit.py`

Per-tenant rate-limit audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_UNGUARDED_EXPENSIVE` | `34` |

**Tests**: `test_every_expensive_route_has_a_rate_limit`, `test_allowlist_entries_actually_match_routes`, `test_expensive_path_patterns_match_at_least_one_route_each`

## Router commit <a id="router-commit"></a>
_File:_ `apps/api/tests/test_router_commit_audit.py`

Database transaction-commit audit (routers).

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_INLINE_COMMITS` | `182` |

**Tests**: `test_no_inline_commit_in_routers`, `test_audit_recognises_session_commit_shapes`

## Router docstring <a id="router-docstring"></a>
_File:_ `apps/api/tests/test_router_docstring_audit.py`

Per-router docstring completeness audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_MODULES_NO_DOCSTRING` | `1` |
| `BASELINE_HANDLERS_NO_DOCSTRING` | `133` |

**Tests**: `test_every_router_module_has_a_docstring`, `test_every_router_handler_has_a_docstring`, `test_audit_recognises_router_decorator_shapes`

## Secret access <a id="secret-access"></a>
_File:_ `apps/api/tests/test_secret_access_audit.py`

Secret/env-var access audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_DIRECT_ENV_ACCESS` | `0` |

**Tests**: `test_no_direct_env_access_outside_settings`, `test_audit_recognises_documented_access_shapes`, `test_file_allowlist_entries_actually_correspond_to_real_files`

## Tenant predicate <a id="tenant-predicate"></a>
_File:_ `apps/api/tests/test_tenant_predicate_audit.py`

Cross-tenant data-leak audit (raw SQL).

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_TENANT_LEAK` | `113` |

**Tests**: `test_no_raw_sql_query_misses_the_tenant_predicate`, `test_audit_recognises_documented_predicate_shapes`, `test_global_tables_recognised_for_unscoped_queries`, `test_allowlist_entries_actually_exist`

## Todo aging <a id="todo-aging"></a>
_File:_ `apps/api/tests/test_todo_aging_audit.py`

TODO / FIXME aging audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_UNANNOTATED_TODOS` | `3` |
| `BASELINE_STALE_TODOS` | `0` |

**Tests**: `test_unannotated_todo_count_does_not_grow`, `test_stale_todo_count_does_not_grow`, `test_audit_recognises_documented_annotation_shapes`

## Worker retry policy <a id="worker-retry-policy"></a>
_File:_ `apps/api/tests/test_worker_retry_policy_audit.py`

Worker job retry-policy audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_ARQ_RETRY_GAPS` | `2` |
| `BASELINE_CELERY_TASKS_NO_MAX_RETRIES` | `3` |

**Tests**: `test_arq_worker_settings_declares_retry_policy`, `test_every_celery_task_declares_max_retries`, `test_audit_recognises_documented_decorator_shapes`
