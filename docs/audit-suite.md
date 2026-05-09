# Ratchet audit suite

<!-- GENERATED FILE — do not edit by hand. Regenerate via `python -m scripts.generate_audit_index` from `apps/api/`. Source of truth is each `tests/test_*_audit.py` docstring + its `BASELINE_*` constants. -->

Each entry below is a ratchet test in `apps/api/tests/`. The audit walks a chunk of the codebase, counts a specific bug-shape, and asserts the count hasn't grown beyond a pinned baseline. Reductions ALSO fail (with a 🎉) so a baseline drop is captured in the same PR as the fix.

Run all of them with `make audit` (~5s). They also run as a pre-commit hook (`ratchet-audits`) scoped to files any audit scans, and inside the broader `pytest` CI job.

## Index

- [Admin routes role gate](#admin-routes-role-gate)
- [Admin session factory usage](#admin-session-factory-usage)
- [Alembic chain integrity](#alembic-chain-integrity)
- [Assert in production](#assert-in-production)
- [Audit action callsite](#audit-action-callsite)
- [Audit completeness](#audit-completeness)
- [Audit index freshness](#audit-index-freshness)
- [Bare except](#bare-except)
- [Ci precommit drift](#ci-precommit-drift)
- [Complexity budget](#complexity-budget)
- [Concurrency safety](#concurrency-safety)
- [Cron mutex](#cron-mutex)
- [Dep parity](#dep-parity)
- [Dependency direction](#dependency-direction)
- [Dunder all consistency](#dunder-all-consistency)
- [Every router mounted in main](#every-router-mounted-in-main)
- [Fixture duplication](#fixture-duplication)
- [Fk index coverage](#fk-index-coverage)
- [Fk ondelete](#fk-ondelete)
- [Fromtimestamp naive](#fromtimestamp-naive)
- [Frontend bundle composition](#frontend-bundle-composition)
- [Future annotations import](#future-annotations-import)
- [Http status constants](#http-status-constants)
- [Idempotency contract](#idempotency-contract)
- [Input schemas no organization id](#input-schemas-no-organization-id)
- [Logger exception outside except](#logger-exception-outside-except)
- [Logging structure](#logging-structure)
- [Migration safety](#migration-safety)
- [Migration upgrade downgrade symmetry](#migration-upgrade-downgrade-symmetry)
- [Mutable default args](#mutable-default-args)
- [N plus one](#n-plus-one)
- [Naive datetime](#naive-datetime)
- [Noqa specificity](#noqa-specificity)
- [Openapi route docs](#openapi-route-docs)
- [Openapi tags](#openapi-tags)
- [Optional without default](#optional-without-default)
- [Orm tables organization id](#orm-tables-organization-id)
- [Output schemas no secret fields](#output-schemas-no-secret-fields)
- [Print in production](#print-in-production)
- [Pydantic field constraint](#pydantic-field-constraint)
- [Pydantic strictness](#pydantic-strictness)
- [Rate limit](#rate-limit)
- [Rls policy coverage](#rls-policy-coverage)
- [Router commit](#router-commit)
- [Router docstring](#router-docstring)
- [Router handlers are async](#router-handlers-are-async)
- [Secret access](#secret-access)
- [Shell injection](#shell-injection)
- [Singleton comparison](#singleton-comparison)
- [Stale init export](#stale-init-export)
- [Sync open in async](#sync-open-in-async)
- [Sync requests in async](#sync-requests-in-async)
- [Tenant predicate](#tenant-predicate)
- [Todo aging](#todo-aging)
- [Type ignore specificity](#type-ignore-specificity)
- [Untyped function](#untyped-function)
- [Worker retry policy](#worker-retry-policy)

## Admin routes role gate <a id="admin-routes-role-gate"></a>
_File:_ `apps/api/tests/test_admin_routes_role_gate_audit.py`

Audit: every `/api/v1/admin/*` route MUST have an admin-role dep in its dependency tree.

**Tests**: `test_every_admin_route_has_admin_role_gate`, `test_admin_route_audit_catches_at_least_one_route`, `test_public_admin_allowlist_is_minimal`

## Admin session factory usage <a id="admin-session-factory-usage"></a>
_File:_ `apps/api/tests/test_admin_session_factory_usage_audit.py`

Audit: `AdminSessionFactory` (BYPASSRLS) MUST only be used by the curated allowlist of routers that have a legitimate cross-tenant reason for it.

**Tests**: `test_routers_using_admin_session_factory_match_allowlist`, `test_allowlist_entries_have_rationale`, `test_allowlist_size_does_not_grow_silently`

## Alembic chain integrity <a id="alembic-chain-integrity"></a>
_File:_ `apps/api/tests/test_alembic_chain_integrity_audit.py`

Audit: alembic migration chain integrity.

**Tests**: `test_audit_finds_migration_files`, `test_revision_ids_are_unique`, `test_down_revisions_resolve_to_known_revisions`, `test_exactly_one_root_revision`, `test_at_most_one_head_revision_or_explicit_multi_head`, `test_no_cycle_in_migration_chain`, `test_filename_prefix_matches_revision_id`

## Assert in production <a id="assert-in-production"></a>
_File:_ `apps/api/tests/test_assert_in_production_audit.py`

`assert` in production code audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_PRODUCTION_ASSERTS` | `8` |

**Tests**: `test_no_assert_statements_in_production_code`, `test_audit_recognises_documented_shapes`, `test_allowlist_entries_actually_correspond_to_real_asserts`

## Audit action callsite <a id="audit-action-callsite"></a>
_File:_ `apps/api/tests/test_audit_action_callsite_audit.py`

Audit: every `audit.record(action="...")` call site MUST pass an `action` string that's in the canonical `AuditAction` Literal.

**Tests**: `test_every_audit_record_action_in_literal`, `test_audit_actually_finds_call_sites`, `test_canonical_audit_action_set_size_floor`, `test_dynamic_call_sites_allowlist_is_minimal`

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

## Bare except <a id="bare-except"></a>
_File:_ `apps/api/tests/test_bare_except_audit.py`

Bare `except:` audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_BARE_EXCEPT` | `0` |

**Tests**: `test_no_bare_except_clauses`, `test_audit_recognises_documented_shapes`

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

## Dunder all consistency <a id="dunder-all-consistency"></a>
_File:_ `apps/api/tests/test_dunder_all_consistency_audit.py`

Audit: every name in a module's `__all__` MUST exist as a top-level symbol in that module.

**Tests**: `test_every_name_in_dunder_all_resolves_to_a_top_level_symbol`, `test_no_underscore_names_in_dunder_all`, `test_audit_finds_at_least_one_dunder_all`

## Every router mounted in main <a id="every-router-mounted-in-main"></a>
_File:_ `apps/api/tests/test_every_router_mounted_in_main_audit.py`

Audit: every router module under `apps/api/routers/` is imported AND mounted by `main.py::create_app()`.

**Tests**: `test_every_router_module_is_imported_in_main`, `test_every_imported_router_is_mounted`, `test_audit_finds_at_least_one_router`, `test_deliberately_unmounted_allowlist_entries_have_rationale`, `test_deliberately_unmounted_allowlist_is_minimal`

## Fixture duplication <a id="fixture-duplication"></a>
_File:_ `apps/api/tests/test_fixture_duplication_audit.py`

Test-fixture duplication audit.

**Tests**: `test_fixture_pattern_duplication_does_not_grow`, `test_baselines_cover_every_recognised_pattern`, `test_pattern_regex_actually_matches_documented_shape`, `test_per_pattern_baseline_breakdown_is_visible_on_fail`

## Fk index coverage <a id="fk-index-coverage"></a>
_File:_ `apps/api/tests/test_fk_index_coverage_audit.py`

Foreign-key index coverage audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_UNCOVERED_FKS` | `125` |

**Tests**: `test_every_fk_column_has_a_leading_index`, `test_audit_recognises_documented_shapes`, `test_allowlist_entries_actually_correspond_to_real_fks`

## Fk ondelete <a id="fk-ondelete"></a>
_File:_ `apps/api/tests/test_fk_ondelete_audit.py`

Foreign-key ON DELETE behaviour audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_FK_NO_ONDELETE` | `0` |

**Tests**: `test_every_foreign_key_has_explicit_ondelete`, `test_audit_recognises_documented_fk_call_shapes`

## Fromtimestamp naive <a id="fromtimestamp-naive"></a>
_File:_ `apps/api/tests/test_fromtimestamp_naive_audit.py`

`datetime.fromtimestamp(x)` without `tz=` audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_NAIVE_FROMTIMESTAMP` | `0` |

**Tests**: `test_no_naive_fromtimestamp_calls`, `test_audit_recognises_documented_shapes`

## Frontend bundle composition <a id="frontend-bundle-composition"></a>
_File:_ `apps/api/tests/test_frontend_bundle_composition_audit.py`

Frontend bundle composition tracker.

**Tests**: `test_no_unreviewed_packages_enter_the_bundle`, `test_no_server_only_imports_in_client_source`, `test_allowlist_entries_correspond_to_real_files`, `test_audit_recognises_documented_import_shapes`

## Future annotations import <a id="future-annotations-import"></a>
_File:_ `apps/api/tests/test_future_annotations_import_audit.py`

Audit: every Python file under `apps/api/` has `from __future__ import annotations` near the top.

**Tests**: `test_every_python_file_has_future_annotations`, `test_audit_finds_python_files`

## Http status constants <a id="http-status-constants"></a>
_File:_ `apps/api/tests/test_http_status_constants_audit.py`

HTTP status-code constants audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_LITERAL_STATUS_CODES` | `43` |

**Tests**: `test_no_literal_http_status_codes`, `test_audit_recognises_documented_call_shapes`, `test_allowlist_entries_actually_exist_in_source`

## Idempotency contract <a id="idempotency-contract"></a>
_File:_ `apps/api/tests/test_idempotency_contract_audit.py`

Idempotency-key contract audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_NON_IDEMPOTENT_CREATES` | `33` |

**Tests**: `test_every_creation_post_uses_idempotent_route`, `test_create_pattern_matches_at_least_some_routes`, `test_idempotent_route_class_is_importable`

## Input schemas no organization id <a id="input-schemas-no-organization-id"></a>
_File:_ `apps/api/tests/test_input_schemas_no_organization_id_audit.py`

Audit: Pydantic *input* schemas (Create / Update / Patch / Payload) MUST NOT accept `organization_id` from the client.

**Tests**: `test_no_input_schema_accepts_organization_id`, `test_audit_actually_walks_input_schemas`, `test_output_schema_classifier_correct`, `test_input_schemas_with_org_id_allowlist_is_minimal`

## Logger exception outside except <a id="logger-exception-outside-except"></a>
_File:_ `apps/api/tests/test_logger_exception_outside_except_audit.py`

`logger.exception(...)` outside an `except` block audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_LOGGER_EXCEPTION_OUTSIDE_EXCEPT` | `0` |

**Tests**: `test_no_logger_exception_outside_except`, `test_audit_recognises_documented_shapes`

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

## Migration upgrade downgrade symmetry <a id="migration-upgrade-downgrade-symmetry"></a>
_File:_ `apps/api/tests/test_migration_upgrade_downgrade_symmetry_audit.py`

Audit: every alembic migration's `upgrade()` has a non-trivial `downgrade()` covering the same DDL (or is explicitly allowlisted as one-way).

**Tests**: `test_every_migration_has_upgrade_and_downgrade`, `test_downgrade_non_empty_when_upgrade_has_ddl`, `test_audit_finds_migration_files`, `test_one_way_allowlist_entries_have_rationale`, `test_one_way_allowlist_size_is_minimal`

## Mutable default args <a id="mutable-default-args"></a>
_File:_ `apps/api/tests/test_mutable_default_args_audit.py`

Audit: no mutable default arguments in function signatures.

**Tests**: `test_no_mutable_default_arguments`, `test_mutable_default_allowlist_entries_have_rationale`, `test_audit_finds_python_files`

## N plus one <a id="n-plus-one"></a>
_File:_ `apps/api/tests/test_n_plus_one_audit.py`

N+1 query detection audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_N_PLUS_ONE_CALLS` | `22` |

**Tests**: `test_no_db_query_inside_loop_body`, `test_audit_recognises_documented_patterns`

## Naive datetime <a id="naive-datetime"></a>
_File:_ `apps/api/tests/test_naive_datetime_audit.py`

Naive-datetime audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_NAIVE_DATETIMES` | `0` |

**Tests**: `test_no_new_naive_datetime_call_sites`, `test_audit_recognises_documented_naive_shapes`, `test_allowlist_entries_actually_correspond_to_real_lines`

## Noqa specificity <a id="noqa-specificity"></a>
_File:_ `apps/api/tests/test_noqa_specificity_audit.py`

`# noqa` specificity audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_BARE_NOQA` | `0` |

**Tests**: `test_no_bare_noqa_comments`, `test_audit_recognises_documented_shapes`

## Openapi route docs <a id="openapi-route-docs"></a>
_File:_ `apps/api/tests/test_openapi_route_docs_audit.py`

OpenAPI route documentation completeness audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_UNDOCUMENTED_NAME` | `131` |
| `BASELINE_NO_RESPONSE_MODEL` | `90` |

**Tests**: `test_every_route_has_summary_or_docstring`, `test_every_route_has_response_model_or_is_allowlisted`, `test_response_model_allowlist_entries_actually_match_routes`

## Openapi tags <a id="openapi-tags"></a>
_File:_ `apps/api/tests/test_openapi_tags_audit.py`

Per-route OpenAPI tags audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_UNTAGGED_ROUTES` | `0` |

**Tests**: `test_every_route_has_at_least_one_tag`, `test_allowlist_entries_actually_match_routes`

## Optional without default <a id="optional-without-default"></a>
_File:_ `apps/api/tests/test_optional_without_default_audit.py`

`Optional` field without `= None` default audit (Pydantic).

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_OPTIONAL_NO_DEFAULT` | `30` |

**Tests**: `test_every_optional_pydantic_field_has_a_none_default`, `test_allowlist_entries_actually_correspond_to_real_fields`

## Orm tables organization id <a id="orm-tables-organization-id"></a>
_File:_ `apps/api/tests/test_orm_tables_organization_id_audit.py`

Audit: every ORM table is either tenant-bearing (has an `organization_id` column) OR explicitly allowlisted as global.

**Tests**: `test_audit_walks_orm_models`, `test_every_table_has_org_id_or_is_explicitly_global`, `test_global_table_entries_have_rationale`, `test_global_table_set_size_does_not_grow_silently`, `test_known_tenant_tables_actually_have_org_id`

## Output schemas no secret fields <a id="output-schemas-no-secret-fields"></a>
_File:_ `apps/api/tests/test_output_schemas_no_secret_fields_audit.py`

Audit: Pydantic *output* schemas (Out / Detail / Response / Read / Summary / Row / View / Returned) MUST NOT carry secret-shaped fields.

**Tests**: `test_no_output_schema_carries_secret_field`, `test_audit_actually_walks_output_schemas`, `test_classifier_exempts_create_response_shapes`, `test_secret_field_name_set_is_conservative`, `test_output_schemas_with_secret_allowlist_is_minimal`

## Print in production <a id="print-in-production"></a>
_File:_ `apps/api/tests/test_print_in_production_audit.py`

`print(...)` in production code audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_PRODUCTION_PRINTS` | `4` |

**Tests**: `test_no_print_calls_in_production_code`, `test_audit_recognises_documented_shapes`, `test_allowlist_entries_actually_correspond_to_real_prints`

## Pydantic field constraint <a id="pydantic-field-constraint"></a>
_File:_ `apps/api/tests/test_pydantic_field_constraint_audit.py`

Pydantic field-level constraint audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_UNCONSTRAINED_STR` | `506` |
| `BASELINE_UNCONSTRAINED_NUMERIC` | `266` |

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

## Rls policy coverage <a id="rls-policy-coverage"></a>
_File:_ `apps/api/tests/test_rls_policy_coverage_audit.py`

Audit: every tenant-bearing ORM table has at least one `CREATE POLICY` declared in the alembic migrations.

**Tests**: `test_every_tenant_bearing_table_has_an_rls_policy`, `test_audit_finds_tenant_bearing_tables`, `test_audit_finds_create_policy_statements`, `test_allowlist_entries_have_rationale`, `test_allowlist_size_is_minimal`

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

## Router handlers are async <a id="router-handlers-are-async"></a>
_File:_ `apps/api/tests/test_router_handlers_are_async_audit.py`

Audit: every FastAPI route handler is `async def`, not `def`.

**Tests**: `test_every_router_handler_is_async`, `test_audit_finds_router_handlers`, `test_legitimate_sync_handler_allowlist_is_minimal`, `test_legitimate_sync_handler_entries_have_rationale`

## Secret access <a id="secret-access"></a>
_File:_ `apps/api/tests/test_secret_access_audit.py`

Secret/env-var access audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_DIRECT_ENV_ACCESS` | `0` |

**Tests**: `test_no_direct_env_access_outside_settings`, `test_audit_recognises_documented_access_shapes`, `test_file_allowlist_entries_actually_correspond_to_real_files`

## Shell injection <a id="shell-injection"></a>
_File:_ `apps/api/tests/test_shell_injection_audit.py`

Shell-injection guard audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_SHELL_INJECTIONS` | `0` |

**Tests**: `test_no_shell_injection_call_sites`, `test_audit_recognises_documented_shapes`, `test_allowlist_entries_actually_correspond_to_real_calls`

## Singleton comparison <a id="singleton-comparison"></a>
_File:_ `apps/api/tests/test_singleton_comparison_audit.py`

`==` against None/True/False audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_SINGLETON_EQ` | `0` |

**Tests**: `test_no_eq_against_singletons`, `test_audit_recognises_documented_shapes`

## Stale init export <a id="stale-init-export"></a>
_File:_ `apps/api/tests/test_stale_init_export_audit.py`

Stale `__init__.py` re-export audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_STALE_INIT_EXPORTS` | `0` |

**Tests**: `test_no_stale_init_reexports`, `test_audit_recognises_documented_shapes`, `test_allowlist_entries_actually_correspond_to_real_imports`

## Sync open in async <a id="sync-open-in-async"></a>
_File:_ `apps/api/tests/test_sync_open_in_async_audit.py`

Sync `open()` inside `async def` audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_SYNC_OPEN_IN_ASYNC` | `2` |

**Tests**: `test_no_sync_open_in_async_function`, `test_audit_recognises_documented_patterns`, `test_allowlist_entries_actually_correspond_to_real_calls`

## Sync requests in async <a id="sync-requests-in-async"></a>
_File:_ `apps/api/tests/test_sync_requests_in_async_audit.py`

`requests.<verb>(...)` (or other sync HTTP) in async function audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_SYNC_HTTP_IN_ASYNC` | `0` |

**Tests**: `test_no_sync_http_in_async_function`, `test_audit_recognises_documented_patterns`

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

## Type ignore specificity <a id="type-ignore-specificity"></a>
_File:_ `apps/api/tests/test_type_ignore_specificity_audit.py`

`# type: ignore` specificity audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_BARE_TYPE_IGNORE` | `0` |

**Tests**: `test_no_bare_type_ignore_comments`, `test_audit_recognises_documented_shapes`

## Untyped function <a id="untyped-function"></a>
_File:_ `apps/api/tests/test_untyped_function_audit.py`

Untyped function-signature audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_UNTYPED_SLOTS` | `78` |

**Tests**: `test_untyped_function_slot_count_does_not_grow`, `test_audit_recognises_documented_shapes`, `test_allowlist_entries_actually_correspond_to_real_functions`

## Worker retry policy <a id="worker-retry-policy"></a>
_File:_ `apps/api/tests/test_worker_retry_policy_audit.py`

Worker job retry-policy audit.

**Baselines**:

| Constant | Value |
|---|---|
| `BASELINE_ARQ_RETRY_GAPS` | `2` |
| `BASELINE_CELERY_TASKS_NO_MAX_RETRIES` | `3` |

**Tests**: `test_arq_worker_settings_declares_retry_policy`, `test_every_celery_task_declares_max_retries`, `test_audit_recognises_documented_decorator_shapes`
