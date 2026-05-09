/* eslint-disable */
/**
 * Auto-generated. DO NOT EDIT — re-run `pnpm --filter @aec/sdk run generate`
 * after backend deploys.
 *
 * Source: AEC Platform OpenAPI snapshot
 * API title: AEC Platform API
 * API version: (unknown)
 */

import type { AecClientCore } from "./client";

export interface Operations {
  /** Get Activity Feed */
  get_activity_feed_api_v1_activity_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Stream Activity */
  stream_activity_api_v1_activity_stream_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Mint Stream Ticket */
  mint_stream_ticket_api_v1_activity_stream_ticket_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Admin Top Api Keys */
  admin_top_api_keys_api_v1_admin_api_keys_top_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Admin Api Key Usage */
  admin_api_key_usage_api_v1_admin_api_keys__key_id__usage_get: { params: { key_id: string | number }; method: "GET"; path: string };
  /** List Crons */
  list_crons_api_v1_admin_crons_get: { params: Record<string, never>; method: "GET"; path: string };
  /** List Cron Runs */
  list_cron_runs_api_v1_admin_crons__cron_name__runs_get: { params: { cron_name: string | number }; method: "GET"; path: string };
  /** List Normalizer Rules */
  list_normalizer_rules_api_v1_admin_normalizer_rules_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Create Normalizer Rule */
  create_normalizer_rule_api_v1_admin_normalizer_rules_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Update Normalizer Rule */
  update_normalizer_rule_api_v1_admin_normalizer_rules__rule_id__patch: { params: { rule_id: string | number }; method: "PATCH"; path: string };
  /** Delete Normalizer Rule */
  delete_normalizer_rule_api_v1_admin_normalizer_rules__rule_id__delete: { params: { rule_id: string | number }; method: "DELETE"; path: string };
  /** Retention Run Now */
  retention_run_now_api_v1_admin_retention_run_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Retention Status */
  retention_status_api_v1_admin_retention_status_get: { params: Record<string, never>; method: "GET"; path: string };
  /** List Scraper Runs */
  list_scraper_runs_api_v1_admin_scraper_runs_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Scraper Runs Summary */
  scraper_runs_summary_api_v1_admin_scraper_runs_summary_get: { params: Record<string, never>; method: "GET"; path: string };
  /** List Slack Deliveries */
  list_slack_deliveries_api_v1_admin_slack_deliveries_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Slack Deliveries Summary */
  slack_deliveries_summary_api_v1_admin_slack_deliveries_summary_get: { params: Record<string, never>; method: "GET"; path: string };
  /** List Webhook Deliveries */
  list_webhook_deliveries_api_v1_admin_webhook_deliveries_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Webhook Deliveries Summary */
  webhook_deliveries_summary_api_v1_admin_webhook_deliveries_summary_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Get Webhook Delivery Detail */
  get_webhook_delivery_detail_api_v1_admin_webhook_deliveries__delivery_id__get: { params: { delivery_id: string | number }; method: "GET"; path: string };
  /** List Api Keys */
  list_api_keys_api_v1_api_keys_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Create Api Key */
  create_api_key_api_v1_api_keys_post: { params: Record<string, never>; method: "POST"; path: string };
  /** List Scopes */
  list_scopes_api_v1_api_keys_scopes_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Revoke Api Key */
  revoke_api_key_api_v1_api_keys__key_id__revoke_post: { params: { key_id: string | number }; method: "POST"; path: string };
  /** Ask About Project */
  ask_about_project_api_v1_assistant_projects__project_id__ask_post: { params: { project_id: string | number }; method: "POST"; path: string };
  /** Ask About Project Stream */
  ask_about_project_stream_api_v1_assistant_projects__project_id__ask_stream_post: { params: { project_id: string | number }; method: "POST"; path: string };
  /** List Threads */
  list_threads_api_v1_assistant_projects__project_id__threads_get: { params: { project_id: string | number }; method: "GET"; path: string };
  /** Get Thread */
  get_thread_api_v1_assistant_threads__thread_id__get: { params: { thread_id: string | number }; method: "GET"; path: string };
  /** Delete Thread */
  delete_thread_api_v1_assistant_threads__thread_id__delete: { params: { thread_id: string | number }; method: "DELETE"; path: string };
  /** List Audit Events */
  list_audit_events_api_v1_audit_events_get: { params: Record<string, never>; method: "GET"; path: string };
  /** List Digests */
  list_digests_api_v1_bidradar_digests_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Send Digest */
  send_digest_api_v1_bidradar_digests_send_post: { params: Record<string, never>; method: "POST"; path: string };
  /** List Matches */
  list_matches_api_v1_bidradar_matches_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Get Match */
  get_match_api_v1_bidradar_matches__match_id__get: { params: { match_id: string | number }; method: "GET"; path: string };
  /** Create Proposal */
  create_proposal_api_v1_bidradar_matches__match_id__create_proposal_post: { params: { match_id: string | number }; method: "POST"; path: string };
  /** Update Match Status */
  update_match_status_api_v1_bidradar_matches__match_id__status_patch: { params: { match_id: string | number }; method: "PATCH"; path: string };
  /** Get Firm Profile */
  get_firm_profile_api_v1_bidradar_profile_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Upsert Firm Profile */
  upsert_firm_profile_api_v1_bidradar_profile_put: { params: Record<string, never>; method: "PUT"; path: string };
  /** Score Matches */
  score_matches_api_v1_bidradar_score_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Trigger Scrape */
  trigger_scrape_api_v1_bidradar_scrape_post: { params: Record<string, never>; method: "POST"; path: string };
  /** List Tenders */
  list_tenders_api_v1_bidradar_tenders_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Get Tender */
  get_tender_api_v1_bidradar_tenders__tender_id__get: { params: { tender_id: string | number }; method: "GET"; path: string };
  /** Accept Candidate */
  accept_candidate_api_v1_changeorder_candidates__cand_id__accept_post: { params: { cand_id: string | number }; method: "POST"; path: string };
  /** Reject Candidate */
  reject_candidate_api_v1_changeorder_candidates__cand_id__reject_post: { params: { cand_id: string | number }; method: "POST"; path: string };
  /** List Change Orders */
  list_change_orders_api_v1_changeorder_cos_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Create Change Order */
  create_change_order_api_v1_changeorder_cos_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Get Change Order */
  get_change_order_api_v1_changeorder_cos__co_id__get: { params: { co_id: string | number }; method: "GET"; path: string };
  /** Update Change Order */
  update_change_order_api_v1_changeorder_cos__co_id__patch: { params: { co_id: string | number }; method: "PATCH"; path: string };
  /** Analyze Impact Endpoint */
  analyze_impact_endpoint_api_v1_changeorder_cos__co_id__analyze_post: { params: { co_id: string | number }; method: "POST"; path: string };
  /** Record Approval */
  record_approval_api_v1_changeorder_cos__co_id__approvals_post: { params: { co_id: string | number }; method: "POST"; path: string };
  /** Add Line Item */
  add_line_item_api_v1_changeorder_cos__co_id__line_items_post: { params: { co_id: string | number }; method: "POST"; path: string };
  /** Add Source */
  add_source_api_v1_changeorder_cos__co_id__sources_post: { params: { co_id: string | number }; method: "POST"; path: string };
  /** Extract Candidates Endpoint */
  extract_candidates_endpoint_api_v1_changeorder_extract_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Update Line Item */
  update_line_item_api_v1_changeorder_line_items__li_id__patch: { params: { li_id: string | number }; method: "PATCH"; path: string };
  /** Price Suggestions */
  price_suggestions_api_v1_changeorder_price_suggestions_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Mark Checklist Item */
  mark_checklist_item_api_v1_codeguard_checks__check_id__mark_item_post: { params: { check_id: string | number }; method: "POST"; path: string };
  /** List Project Checks */
  list_project_checks_api_v1_codeguard_checks__project_id__get: { params: { project_id: string | number }; method: "GET"; path: string };
  /** Codeguard Health */
  codeguard_health_api_v1_codeguard_health_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Create Permit Checklist */
  create_permit_checklist_api_v1_codeguard_permit_checklist_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Codeguard Permit Checklist Stream */
  codeguard_permit_checklist_stream_api_v1_codeguard_permit_checklist_stream_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Export Permit Checklist Pdf */
  export_permit_checklist_pdf_api_v1_codeguard_permit_checklist__checklist_id__pdf_get: { params: { checklist_id: string | number }; method: "GET"; path: string };
  /** Codeguard Query */
  codeguard_query_api_v1_codeguard_query_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Codeguard Query Stream */
  codeguard_query_stream_api_v1_codeguard_query_stream_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Get Codeguard Quota */
  get_codeguard_quota_api_v1_codeguard_quota_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Get Codeguard Quota Audit */
  get_codeguard_quota_audit_api_v1_codeguard_quota_audit_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Get Codeguard Quota History */
  get_codeguard_quota_history_api_v1_codeguard_quota_history_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Get Codeguard Quota Top Users */
  get_codeguard_quota_top_users_api_v1_codeguard_quota_top_users_get: { params: Record<string, never>; method: "GET"; path: string };
  /** List Regulations */
  list_regulations_api_v1_codeguard_regulations_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Get Regulation */
  get_regulation_api_v1_codeguard_regulations__regulation_id__get: { params: { regulation_id: string | number }; method: "GET"; path: string };
  /** Codeguard Scan */
  codeguard_scan_api_v1_codeguard_scan_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Codeguard Scan Stream */
  codeguard_scan_stream_api_v1_codeguard_scan_stream_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Cost Benchmark */
  cost_benchmark_api_v1_costpulse_analytics_cost_benchmark_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Estimate From Brief */
  estimate_from_brief_api_v1_costpulse_estimate_from_brief_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Estimate From Drawings */
  estimate_from_drawings_api_v1_costpulse_estimate_from_drawings_post: { params: Record<string, never>; method: "POST"; path: string };
  /** List Estimates */
  list_estimates_api_v1_costpulse_estimates_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Create Estimate */
  create_estimate_api_v1_costpulse_estimates_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Get Estimate */
  get_estimate_api_v1_costpulse_estimates__estimate_id__get: { params: { estimate_id: string | number }; method: "GET"; path: string };
  /** Approve Estimate */
  approve_estimate_api_v1_costpulse_estimates__estimate_id__approve_post: { params: { estimate_id: string | number }; method: "POST"; path: string };
  /** Update Boq */
  update_boq_api_v1_costpulse_estimates__estimate_id__boq_put: { params: { estimate_id: string | number }; method: "PUT"; path: string };
  /** Export Boq Pdf */
  export_boq_pdf_api_v1_costpulse_estimates__estimate_id__boq_export_pdf_get: { params: { estimate_id: string | number }; method: "GET"; path: string };
  /** Export Boq Xlsx */
  export_boq_xlsx_api_v1_costpulse_estimates__estimate_id__boq_export_xlsx_get: { params: { estimate_id: string | number }; method: "GET"; path: string };
  /** Import Boq Xlsx */
  import_boq_xlsx_api_v1_costpulse_estimates__estimate_id__boq_import_post: { params: { estimate_id: string | number }; method: "POST"; path: string };
  /** Diff Estimate Versions */
  diff_estimate_versions_api_v1_costpulse_estimates__estimate_id__diff_get: { params: { estimate_id: string | number }; method: "GET"; path: string };
  /** List Estimate Versions */
  list_estimate_versions_api_v1_costpulse_estimates__estimate_id__versions_get: { params: { estimate_id: string | number }; method: "GET"; path: string };
  /** Create Price Alert */
  create_price_alert_api_v1_costpulse_price_alerts_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Lookup Prices */
  lookup_prices_api_v1_costpulse_prices_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Price History */
  price_history_api_v1_costpulse_prices_history__material_code__get: { params: { material_code: string | number }; method: "GET"; path: string };
  /** Override Price */
  override_price_api_v1_costpulse_prices_override_post: { params: Record<string, never>; method: "POST"; path: string };
  /** List Rfq */
  list_rfq_api_v1_costpulse_rfq_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Create Rfq */
  create_rfq_api_v1_costpulse_rfq_post: { params: Record<string, never>; method: "POST"; path: string };
  /** List Suppliers */
  list_suppliers_api_v1_costpulse_suppliers_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Create Supplier */
  create_supplier_api_v1_costpulse_suppliers_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Export Suppliers Csv */
  export_suppliers_csv_api_v1_costpulse_suppliers_export_csv_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Export Suppliers Xlsx */
  export_suppliers_xlsx_api_v1_costpulse_suppliers_export_xlsx_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Import Suppliers */
  import_suppliers_api_v1_costpulse_suppliers_import_post: { params: Record<string, never>; method: "POST"; path: string };
  /** List Logs */
  list_logs_api_v1_dailylog_logs_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Create Log */
  create_log_api_v1_dailylog_logs_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Get Log */
  get_log_api_v1_dailylog_logs__log_id__get: { params: { log_id: string | number }; method: "GET"; path: string };
  /** Update Log */
  update_log_api_v1_dailylog_logs__log_id__patch: { params: { log_id: string | number }; method: "PATCH"; path: string };
  /** Trigger Extract */
  trigger_extract_api_v1_dailylog_logs__log_id__extract_post: { params: { log_id: string | number }; method: "POST"; path: string };
  /** Create Observation */
  create_observation_api_v1_dailylog_logs__log_id__observations_post: { params: { log_id: string | number }; method: "POST"; path: string };
  /** Update Observation */
  update_observation_api_v1_dailylog_observations__obs_id__patch: { params: { obs_id: string | number }; method: "PATCH"; path: string };
  /** Get Patterns */
  get_patterns_api_v1_dailylog_projects__project_id__patterns_get: { params: { project_id: string | number }; method: "GET"; path: string };
  /** Conflict Scan */
  conflict_scan_api_v1_drawbridge_conflict_scan_post: { params: Record<string, never>; method: "POST"; path: string };
  /** List Conflicts */
  list_conflicts_api_v1_drawbridge_conflicts_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Get Conflict */
  get_conflict_api_v1_drawbridge_conflicts__conflict_id__get: { params: { conflict_id: string | number }; method: "GET"; path: string };
  /** Update Conflict */
  update_conflict_api_v1_drawbridge_conflicts__conflict_id__patch: { params: { conflict_id: string | number }; method: "PATCH"; path: string };
  /** List Document Sets */
  list_document_sets_api_v1_drawbridge_document_sets_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Create Document Set */
  create_document_set_api_v1_drawbridge_document_sets_post: { params: Record<string, never>; method: "POST"; path: string };
  /** List Documents */
  list_documents_api_v1_drawbridge_documents_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Upload Document */
  upload_document_api_v1_drawbridge_documents_upload_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Get Document */
  get_document_api_v1_drawbridge_documents__document_id__get: { params: { document_id: string | number }; method: "GET"; path: string };
  /** Delete Document */
  delete_document_api_v1_drawbridge_documents__document_id__delete: { params: { document_id: string | number }; method: "DELETE"; path: string };
  /** Get Document File */
  get_document_file_api_v1_drawbridge_documents__document_id__file_get: { params: { document_id: string | number }; method: "GET"; path: string };
  /** Extract From Document */
  extract_from_document_api_v1_drawbridge_extract_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Drawbridge Query */
  drawbridge_query_api_v1_drawbridge_query_post: { params: Record<string, never>; method: "POST"; path: string };
  /** List Rfis */
  list_rfis_api_v1_drawbridge_rfis_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Create Rfi */
  create_rfi_api_v1_drawbridge_rfis_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Generate Rfi From Conflict */
  generate_rfi_from_conflict_api_v1_drawbridge_rfis_generate_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Update Rfi */
  update_rfi_api_v1_drawbridge_rfis__rfi_id__patch: { params: { rfi_id: string | number }; method: "PATCH"; path: string };
  /** Answer Rfi */
  answer_rfi_api_v1_drawbridge_rfis__rfi_id__answer_post: { params: { rfi_id: string | number }; method: "POST"; path: string };
  /** Export Entity */
  export_entity_api_v1_export__entity__get: { params: { entity: string | number }; method: "GET"; path: string };
  /** Upload File */
  upload_file_api_v1_files_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Register As Built */
  register_as_built_api_v1_handover_as_builts_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Update Closeout Item */
  update_closeout_item_api_v1_handover_closeout_items__item_id__patch: { params: { item_id: string | number }; method: "PATCH"; path: string };
  /** List Defects */
  list_defects_api_v1_handover_defects_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Create Defect */
  create_defect_api_v1_handover_defects_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Update Defect */
  update_defect_api_v1_handover_defects__defect_id__patch: { params: { defect_id: string | number }; method: "PATCH"; path: string };
  /** Generate Om Manual */
  generate_om_manual_api_v1_handover_om_manuals_generate_post: { params: Record<string, never>; method: "POST"; path: string };
  /** List Packages */
  list_packages_api_v1_handover_packages_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Create Package */
  create_package_api_v1_handover_packages_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Get Package */
  get_package_api_v1_handover_packages__package_id__get: { params: { package_id: string | number }; method: "GET"; path: string };
  /** Update Package */
  update_package_api_v1_handover_packages__package_id__patch: { params: { package_id: string | number }; method: "PATCH"; path: string };
  /** Add Closeout Item */
  add_closeout_item_api_v1_handover_packages__package_id__closeout_items_post: { params: { package_id: string | number }; method: "POST"; path: string };
  /** List Om Manuals */
  list_om_manuals_api_v1_handover_packages__package_id__om_manuals_get: { params: { package_id: string | number }; method: "GET"; path: string };
  /** Package Preconditions */
  package_preconditions_api_v1_handover_packages__package_id__preconditions_get: { params: { package_id: string | number }; method: "GET"; path: string };
  /** Promote Drawings From Drawbridge */
  promote_drawings_from_drawbridge_api_v1_handover_packages__package_id__promote_drawings_post: { params: { package_id: string | number }; method: "POST"; path: string };
  /** List As Builts */
  list_as_builts_api_v1_handover_projects__project_id__as_builts_get: { params: { project_id: string | number }; method: "GET"; path: string };
  /** List Warranties */
  list_warranties_api_v1_handover_warranties_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Create Warranty */
  create_warranty_api_v1_handover_warranties_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Extract Warranty */
  extract_warranty_api_v1_handover_warranties_extract_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Update Warranty */
  update_warranty_api_v1_handover_warranties__warranty_id__patch: { params: { warranty_id: string | number }; method: "PATCH"; path: string };
  /** Get Import Job */
  get_import_job_api_v1_import_jobs__job_id__get: { params: { job_id: string | number }; method: "GET"; path: string };
  /** Commit Import Job */
  commit_import_job_api_v1_import_jobs__job_id__commit_post: { params: { job_id: string | number }; method: "POST"; path: string };
  /** Preview Import */
  preview_import_api_v1_import__entity__preview_post: { params: { entity: string | number }; method: "POST"; path: string };
  /** Get Invitation */
  get_invitation_api_v1_invitations__token__get: { params: { token: string | number }; method: "GET"; path: string };
  /** Accept Invitation */
  accept_invitation_api_v1_invitations__token__accept_post: { params: { token: string | number }; method: "POST"; path: string };
  /** My Inbox */
  my_inbox_api_v1_me_inbox_get: { params: Record<string, never>; method: "GET"; path: string };
  /** List My Orgs */
  list_my_orgs_api_v1_me_orgs_get: { params: Record<string, never>; method: "GET"; path: string };
  /** List Preferences */
  list_preferences_api_v1_notifications_preferences_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Upsert Preference */
  upsert_preference_api_v1_notifications_preferences__key__put: { params: { key: string | number }; method: "PUT"; path: string };
  /** List My Watches */
  list_my_watches_api_v1_notifications_watches_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Create Watch */
  create_watch_api_v1_notifications_watches_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Delete Watch */
  delete_watch_api_v1_notifications_watches__project_id__delete: { params: { project_id: string | number }; method: "DELETE"; path: string };
  /** Seed Demo Into Caller Org */
  seed_demo_into_caller_org_api_v1_onboarding_seed_demo_post: { params: Record<string, never>; method: "POST"; path: string };
  /** List Members */
  list_members_api_v1_org_members_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Invite Member */
  invite_member_api_v1_org_members_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Update Member Role */
  update_member_role_api_v1_org_members__user_id__patch: { params: { user_id: string | number }; method: "PATCH"; path: string };
  /** Remove Member */
  remove_member_api_v1_org_members__user_id__delete: { params: { user_id: string | number }; method: "DELETE"; path: string };
  /** Create Org */
  create_org_api_v1_orgs_post: { params: Record<string, never>; method: "POST"; path: string };
  /** List Invitations */
  list_invitations_api_v1_orgs__org_id__invitations_get: { params: { org_id: string | number }; method: "GET"; path: string };
  /** Create Invitation */
  create_invitation_api_v1_orgs__org_id__invitations_post: { params: { org_id: string | number }; method: "POST"; path: string };
  /** Revoke Invitation */
  revoke_invitation_api_v1_orgs__org_id__invitations__invitation_id__delete: { params: { org_id: string | number; invitation_id: string | number }; method: "DELETE"; path: string };
  /** List Projects */
  list_projects_api_v1_projects_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Get Project Detail */
  get_project_detail_api_v1_projects__project_id__get: { params: { project_id: string | number }; method: "GET"; path: string };
  /** Get Rfq Context */
  get_rfq_context_api_v1_public_rfq_context_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Submit Rfq Response */
  submit_rfq_response_api_v1_public_rfq_respond_post: { params: Record<string, never>; method: "POST"; path: string };
  /** List Change Orders */
  list_change_orders_api_v1_pulse_change_orders_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Create Change Order */
  create_change_order_api_v1_pulse_change_orders_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Analyze Change Order */
  analyze_change_order_api_v1_pulse_change_orders__co_id__analyze_post: { params: { co_id: string | number }; method: "POST"; path: string };
  /** Approve Change Order */
  approve_change_order_api_v1_pulse_change_orders__co_id__approve_patch: { params: { co_id: string | number }; method: "PATCH"; path: string };
  /** Generate Client Report */
  generate_client_report_api_v1_pulse_client_reports_generate_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Send Client Report */
  send_client_report_api_v1_pulse_client_reports__report_id__send_post: { params: { report_id: string | number }; method: "POST"; path: string };
  /** Create Meeting Note */
  create_meeting_note_api_v1_pulse_meeting_notes_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Structure Meeting Notes */
  structure_meeting_notes_api_v1_pulse_meeting_notes_structure_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Project Dashboard */
  project_dashboard_api_v1_pulse_projects__project_id__dashboard_get: { params: { project_id: string | number }; method: "GET"; path: string };
  /** List Tasks */
  list_tasks_api_v1_pulse_tasks_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Create Task */
  create_task_api_v1_pulse_tasks_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Bulk Update Tasks */
  bulk_update_tasks_api_v1_pulse_tasks_bulk_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Update Task */
  update_task_api_v1_pulse_tasks__task_id__patch: { params: { task_id: string | number }; method: "PATCH"; path: string };
  /** Update Item */
  update_item_api_v1_punchlist_items__item_id__patch: { params: { item_id: string | number }; method: "PATCH"; path: string };
  /** Delete Item */
  delete_item_api_v1_punchlist_items__item_id__delete: { params: { item_id: string | number }; method: "DELETE"; path: string };
  /** List Lists */
  list_lists_api_v1_punchlist_lists_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Create List */
  create_list_api_v1_punchlist_lists_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Get List */
  get_list_api_v1_punchlist_lists__list_id__get: { params: { list_id: string | number }; method: "GET"; path: string };
  /** Update List */
  update_list_api_v1_punchlist_lists__list_id__patch: { params: { list_id: string | number }; method: "PATCH"; path: string };
  /** Add Item */
  add_item_api_v1_punchlist_lists__list_id__items_post: { params: { list_id: string | number }; method: "POST"; path: string };
  /** Photo Hints */
  photo_hints_api_v1_punchlist_lists__list_id__photo_hints_get: { params: { list_id: string | number }; method: "GET"; path: string };
  /** Sign Off */
  sign_off_api_v1_punchlist_lists__list_id__sign_off_post: { params: { list_id: string | number }; method: "POST"; path: string };
  /** Update Activity */
  update_activity_api_v1_schedule_activities__activity_id__patch: { params: { activity_id: string | number }; method: "PATCH"; path: string };
  /** Delete Activity */
  delete_activity_api_v1_schedule_activities__activity_id__delete: { params: { activity_id: string | number }; method: "DELETE"; path: string };
  /** Create Dependency */
  create_dependency_api_v1_schedule_dependencies_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Delete Dependency */
  delete_dependency_api_v1_schedule_dependencies__dep_id__delete: { params: { dep_id: string | number }; method: "DELETE"; path: string };
  /** List Schedules */
  list_schedules_api_v1_schedule_schedules_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Create Schedule */
  create_schedule_api_v1_schedule_schedules_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Get Schedule */
  get_schedule_api_v1_schedule_schedules__schedule_id__get: { params: { schedule_id: string | number }; method: "GET"; path: string };
  /** Update Schedule */
  update_schedule_api_v1_schedule_schedules__schedule_id__patch: { params: { schedule_id: string | number }; method: "PATCH"; path: string };
  /** Create Activity */
  create_activity_api_v1_schedule_schedules__schedule_id__activities_post: { params: { schedule_id: string | number }; method: "POST"; path: string };
  /** Baseline Schedule */
  baseline_schedule_api_v1_schedule_schedules__schedule_id__baseline_post: { params: { schedule_id: string | number }; method: "POST"; path: string };
  /** Run Risk Assessment */
  run_risk_assessment_api_v1_schedule_schedules__schedule_id__risk_assessment_post: { params: { schedule_id: string | number }; method: "POST"; path: string };
  /** List Risk Assessments */
  list_risk_assessments_api_v1_schedule_schedules__schedule_id__risk_assessments_get: { params: { schedule_id: string | number }; method: "GET"; path: string };
  /** Search Endpoint */
  search_endpoint_api_v1_search_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Search Analytics Endpoint */
  search_analytics_endpoint_api_v1_search_analytics_get: { params: Record<string, never>; method: "GET"; path: string };
  /** List Photos */
  list_photos_api_v1_siteeye_photos_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Upload Photos */
  upload_photos_api_v1_siteeye_photos_upload_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Progress Timeline */
  progress_timeline_api_v1_siteeye_progress_get: { params: Record<string, never>; method: "GET"; path: string };
  /** List Reports */
  list_reports_api_v1_siteeye_reports_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Generate Report */
  generate_report_api_v1_siteeye_reports_generate_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Send Report */
  send_report_api_v1_siteeye_reports__report_id__send_post: { params: { report_id: string | number }; method: "POST"; path: string };
  /** List Safety Incidents */
  list_safety_incidents_api_v1_siteeye_safety_incidents_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Acknowledge Incident */
  acknowledge_incident_api_v1_siteeye_safety_incidents__incident_id__ack_patch: { params: { incident_id: string | number }; method: "PATCH"; path: string };
  /** List Visits */
  list_visits_api_v1_siteeye_visits_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Create Visit */
  create_visit_api_v1_siteeye_visits_post: { params: Record<string, never>; method: "POST"; path: string };
  /** List Submittals */
  list_submittals_api_v1_submittals_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Create Submittal */
  create_submittal_api_v1_submittals_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Accept Draft */
  accept_draft_api_v1_submittals_drafts__draft_id__accept_post: { params: { draft_id: string | number }; method: "POST"; path: string };
  /** Review Revision */
  review_revision_api_v1_submittals_revisions__revision_id__review_post: { params: { revision_id: string | number }; method: "POST"; path: string };
  /** Draft Rfi Response Endpoint */
  draft_rfi_response_endpoint_api_v1_submittals_rfis__rfi_id__draft_post: { params: { rfi_id: string | number }; method: "POST"; path: string };
  /** Embed Rfi Endpoint */
  embed_rfi_endpoint_api_v1_submittals_rfis__rfi_id__embed_post: { params: { rfi_id: string | number }; method: "POST"; path: string };
  /** Find Similar Rfis Endpoint */
  find_similar_rfis_endpoint_api_v1_submittals_rfis__rfi_id__similar_post: { params: { rfi_id: string | number }; method: "POST"; path: string };
  /** Get Submittal */
  get_submittal_api_v1_submittals__submittal_id__get: { params: { submittal_id: string | number }; method: "GET"; path: string };
  /** Update Submittal */
  update_submittal_api_v1_submittals__submittal_id__patch: { params: { submittal_id: string | number }; method: "PATCH"; path: string };
  /** Create Revision */
  create_revision_api_v1_submittals__submittal_id__revisions_post: { params: { submittal_id: string | number }; method: "POST"; path: string };
  /** List Webhooks */
  list_webhooks_api_v1_webhooks_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Create Webhook */
  create_webhook_api_v1_webhooks_post: { params: Record<string, never>; method: "POST"; path: string };
  /** List Dead Letter */
  list_dead_letter_api_v1_webhooks_deliveries_dead_letter_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Redeliver */
  redeliver_api_v1_webhooks_deliveries__delivery_id__redeliver_post: { params: { delivery_id: string | number }; method: "POST"; path: string };
  /** List Event Types */
  list_event_types_api_v1_webhooks_event_types_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Update Webhook */
  update_webhook_api_v1_webhooks__webhook_id__patch: { params: { webhook_id: string | number }; method: "PATCH"; path: string };
  /** Delete Webhook */
  delete_webhook_api_v1_webhooks__webhook_id__delete: { params: { webhook_id: string | number }; method: "DELETE"; path: string };
  /** List Deliveries */
  list_deliveries_api_v1_webhooks__webhook_id__deliveries_get: { params: { webhook_id: string | number }; method: "GET"; path: string };
  /** Deliveries Histogram */
  deliveries_histogram_api_v1_webhooks__webhook_id__deliveries_histogram_get: { params: { webhook_id: string | number }; method: "GET"; path: string };
  /** Test Webhook */
  test_webhook_api_v1_webhooks__webhook_id__test_post: { params: { webhook_id: string | number }; method: "POST"; path: string };
  /** Win Rate Route */
  win_rate_route_api_v1_winwork_analytics_win_rate_get: { params: Record<string, never>; method: "GET"; path: string };
  /** List Benchmarks */
  list_benchmarks_api_v1_winwork_benchmarks_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Fee Estimate */
  fee_estimate_api_v1_winwork_fee_estimate_post: { params: Record<string, never>; method: "POST"; path: string };
  /** List Proposals Route */
  list_proposals_route_api_v1_winwork_proposals_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Create Proposal Route */
  create_proposal_route_api_v1_winwork_proposals_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Generate Proposal Route */
  generate_proposal_route_api_v1_winwork_proposals_generate_post: { params: Record<string, never>; method: "POST"; path: string };
  /** Get Proposal Route */
  get_proposal_route_api_v1_winwork_proposals__proposal_id__get: { params: { proposal_id: string | number }; method: "GET"; path: string };
  /** Update Proposal Route */
  update_proposal_route_api_v1_winwork_proposals__proposal_id__patch: { params: { proposal_id: string | number }; method: "PATCH"; path: string };
  /** Mark Outcome Route */
  mark_outcome_route_api_v1_winwork_proposals__proposal_id__outcome_patch: { params: { proposal_id: string | number }; method: "PATCH"; path: string };
  /** Send Proposal Route */
  send_proposal_route_api_v1_winwork_proposals__proposal_id__send_post: { params: { proposal_id: string | number }; method: "POST"; path: string };
  /** Health */
  health_health_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Health Ready */
  health_ready_health_ready_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Healthz */
  healthz_healthz_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Metrics */
  metrics_metrics_get: { params: Record<string, never>; method: "GET"; path: string };
  /** Readyz */
  readyz_readyz_get: { params: Record<string, never>; method: "GET"; path: string };
}

export function bindOperations(core: AecClientCore) {
  return {
    /** Get Activity Feed */
    get_activity_feed_api_v1_activity_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/activity", query),
    /** Stream Activity */
    stream_activity_api_v1_activity_stream_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/activity/stream", query),
    /** Mint Stream Ticket */
    mint_stream_ticket_api_v1_activity_stream_ticket_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/activity/stream/ticket", query, body),
    /** Admin Top Api Keys */
    admin_top_api_keys_api_v1_admin_api_keys_top_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/admin/api-keys/top", query),
    /** Admin Api Key Usage */
    admin_api_key_usage_api_v1_admin_api_keys__key_id__usage_get: (params: { key_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/admin/api-keys/${params.key_id}/usage`, query),
    /** List Crons */
    list_crons_api_v1_admin_crons_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/admin/crons", query),
    /** List Cron Runs */
    list_cron_runs_api_v1_admin_crons__cron_name__runs_get: (params: { cron_name: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/admin/crons/${params.cron_name}/runs`, query),
    /** List Normalizer Rules */
    list_normalizer_rules_api_v1_admin_normalizer_rules_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/admin/normalizer-rules", query),
    /** Create Normalizer Rule */
    create_normalizer_rule_api_v1_admin_normalizer_rules_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/admin/normalizer-rules", query, body),
    /** Update Normalizer Rule */
    update_normalizer_rule_api_v1_admin_normalizer_rules__rule_id__patch: (params: { rule_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("PATCH", `/api/v1/admin/normalizer-rules/${params.rule_id}`, query, body),
    /** Delete Normalizer Rule */
    delete_normalizer_rule_api_v1_admin_normalizer_rules__rule_id__delete: (params: { rule_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("DELETE", `/api/v1/admin/normalizer-rules/${params.rule_id}`, query),
    /** Retention Run Now */
    retention_run_now_api_v1_admin_retention_run_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/admin/retention/run", query, body),
    /** Retention Status */
    retention_status_api_v1_admin_retention_status_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/admin/retention/status", query),
    /** List Scraper Runs */
    list_scraper_runs_api_v1_admin_scraper_runs_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/admin/scraper-runs", query),
    /** Scraper Runs Summary */
    scraper_runs_summary_api_v1_admin_scraper_runs_summary_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/admin/scraper-runs/summary", query),
    /** List Slack Deliveries */
    list_slack_deliveries_api_v1_admin_slack_deliveries_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/admin/slack-deliveries", query),
    /** Slack Deliveries Summary */
    slack_deliveries_summary_api_v1_admin_slack_deliveries_summary_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/admin/slack-deliveries/summary", query),
    /** List Webhook Deliveries */
    list_webhook_deliveries_api_v1_admin_webhook_deliveries_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/admin/webhook-deliveries", query),
    /** Webhook Deliveries Summary */
    webhook_deliveries_summary_api_v1_admin_webhook_deliveries_summary_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/admin/webhook-deliveries/summary", query),
    /** Get Webhook Delivery Detail */
    get_webhook_delivery_detail_api_v1_admin_webhook_deliveries__delivery_id__get: (params: { delivery_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/admin/webhook-deliveries/${params.delivery_id}`, query),
    /** List Api Keys */
    list_api_keys_api_v1_api_keys_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/api-keys", query),
    /** Create Api Key */
    create_api_key_api_v1_api_keys_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/api-keys", query, body),
    /** List Scopes */
    list_scopes_api_v1_api_keys_scopes_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/api-keys/scopes", query),
    /** Revoke Api Key */
    revoke_api_key_api_v1_api_keys__key_id__revoke_post: (params: { key_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/api-keys/${params.key_id}/revoke`, query, body),
    /** Ask About Project */
    ask_about_project_api_v1_assistant_projects__project_id__ask_post: (params: { project_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/assistant/projects/${params.project_id}/ask`, query, body),
    /** Ask About Project Stream */
    ask_about_project_stream_api_v1_assistant_projects__project_id__ask_stream_post: (params: { project_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/assistant/projects/${params.project_id}/ask/stream`, query, body),
    /** List Threads */
    list_threads_api_v1_assistant_projects__project_id__threads_get: (params: { project_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/assistant/projects/${params.project_id}/threads`, query),
    /** Get Thread */
    get_thread_api_v1_assistant_threads__thread_id__get: (params: { thread_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/assistant/threads/${params.thread_id}`, query),
    /** Delete Thread */
    delete_thread_api_v1_assistant_threads__thread_id__delete: (params: { thread_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("DELETE", `/api/v1/assistant/threads/${params.thread_id}`, query),
    /** List Audit Events */
    list_audit_events_api_v1_audit_events_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/audit/events", query),
    /** List Digests */
    list_digests_api_v1_bidradar_digests_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/bidradar/digests", query),
    /** Send Digest */
    send_digest_api_v1_bidradar_digests_send_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/bidradar/digests/send", query, body),
    /** List Matches */
    list_matches_api_v1_bidradar_matches_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/bidradar/matches", query),
    /** Get Match */
    get_match_api_v1_bidradar_matches__match_id__get: (params: { match_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/bidradar/matches/${params.match_id}`, query),
    /** Create Proposal */
    create_proposal_api_v1_bidradar_matches__match_id__create_proposal_post: (params: { match_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/bidradar/matches/${params.match_id}/create-proposal`, query, body),
    /** Update Match Status */
    update_match_status_api_v1_bidradar_matches__match_id__status_patch: (params: { match_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("PATCH", `/api/v1/bidradar/matches/${params.match_id}/status`, query, body),
    /** Get Firm Profile */
    get_firm_profile_api_v1_bidradar_profile_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/bidradar/profile", query),
    /** Upsert Firm Profile */
    upsert_firm_profile_api_v1_bidradar_profile_put: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("PUT", "/api/v1/bidradar/profile", query, body),
    /** Score Matches */
    score_matches_api_v1_bidradar_score_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/bidradar/score", query, body),
    /** Trigger Scrape */
    trigger_scrape_api_v1_bidradar_scrape_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/bidradar/scrape", query, body),
    /** List Tenders */
    list_tenders_api_v1_bidradar_tenders_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/bidradar/tenders", query),
    /** Get Tender */
    get_tender_api_v1_bidradar_tenders__tender_id__get: (params: { tender_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/bidradar/tenders/${params.tender_id}`, query),
    /** Accept Candidate */
    accept_candidate_api_v1_changeorder_candidates__cand_id__accept_post: (params: { cand_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/changeorder/candidates/${params.cand_id}/accept`, query, body),
    /** Reject Candidate */
    reject_candidate_api_v1_changeorder_candidates__cand_id__reject_post: (params: { cand_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/changeorder/candidates/${params.cand_id}/reject`, query, body),
    /** List Change Orders */
    list_change_orders_api_v1_changeorder_cos_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/changeorder/cos", query),
    /** Create Change Order */
    create_change_order_api_v1_changeorder_cos_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/changeorder/cos", query, body),
    /** Get Change Order */
    get_change_order_api_v1_changeorder_cos__co_id__get: (params: { co_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/changeorder/cos/${params.co_id}`, query),
    /** Update Change Order */
    update_change_order_api_v1_changeorder_cos__co_id__patch: (params: { co_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("PATCH", `/api/v1/changeorder/cos/${params.co_id}`, query, body),
    /** Analyze Impact Endpoint */
    analyze_impact_endpoint_api_v1_changeorder_cos__co_id__analyze_post: (params: { co_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/changeorder/cos/${params.co_id}/analyze`, query, body),
    /** Record Approval */
    record_approval_api_v1_changeorder_cos__co_id__approvals_post: (params: { co_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/changeorder/cos/${params.co_id}/approvals`, query, body),
    /** Add Line Item */
    add_line_item_api_v1_changeorder_cos__co_id__line_items_post: (params: { co_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/changeorder/cos/${params.co_id}/line-items`, query, body),
    /** Add Source */
    add_source_api_v1_changeorder_cos__co_id__sources_post: (params: { co_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/changeorder/cos/${params.co_id}/sources`, query, body),
    /** Extract Candidates Endpoint */
    extract_candidates_endpoint_api_v1_changeorder_extract_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/changeorder/extract", query, body),
    /** Update Line Item */
    update_line_item_api_v1_changeorder_line_items__li_id__patch: (params: { li_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("PATCH", `/api/v1/changeorder/line-items/${params.li_id}`, query, body),
    /** Price Suggestions */
    price_suggestions_api_v1_changeorder_price_suggestions_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/changeorder/price-suggestions", query),
    /** Mark Checklist Item */
    mark_checklist_item_api_v1_codeguard_checks__check_id__mark_item_post: (params: { check_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/codeguard/checks/${params.check_id}/mark-item`, query, body),
    /** List Project Checks */
    list_project_checks_api_v1_codeguard_checks__project_id__get: (params: { project_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/codeguard/checks/${params.project_id}`, query),
    /** Codeguard Health */
    codeguard_health_api_v1_codeguard_health_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/codeguard/health", query),
    /** Create Permit Checklist */
    create_permit_checklist_api_v1_codeguard_permit_checklist_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/codeguard/permit-checklist", query, body),
    /** Codeguard Permit Checklist Stream */
    codeguard_permit_checklist_stream_api_v1_codeguard_permit_checklist_stream_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/codeguard/permit-checklist/stream", query, body),
    /** Export Permit Checklist Pdf */
    export_permit_checklist_pdf_api_v1_codeguard_permit_checklist__checklist_id__pdf_get: (params: { checklist_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/codeguard/permit-checklist/${params.checklist_id}/pdf`, query),
    /** Codeguard Query */
    codeguard_query_api_v1_codeguard_query_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/codeguard/query", query, body),
    /** Codeguard Query Stream */
    codeguard_query_stream_api_v1_codeguard_query_stream_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/codeguard/query/stream", query, body),
    /** Get Codeguard Quota */
    get_codeguard_quota_api_v1_codeguard_quota_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/codeguard/quota", query),
    /** Get Codeguard Quota Audit */
    get_codeguard_quota_audit_api_v1_codeguard_quota_audit_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/codeguard/quota/audit", query),
    /** Get Codeguard Quota History */
    get_codeguard_quota_history_api_v1_codeguard_quota_history_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/codeguard/quota/history", query),
    /** Get Codeguard Quota Top Users */
    get_codeguard_quota_top_users_api_v1_codeguard_quota_top_users_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/codeguard/quota/top-users", query),
    /** List Regulations */
    list_regulations_api_v1_codeguard_regulations_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/codeguard/regulations", query),
    /** Get Regulation */
    get_regulation_api_v1_codeguard_regulations__regulation_id__get: (params: { regulation_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/codeguard/regulations/${params.regulation_id}`, query),
    /** Codeguard Scan */
    codeguard_scan_api_v1_codeguard_scan_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/codeguard/scan", query, body),
    /** Codeguard Scan Stream */
    codeguard_scan_stream_api_v1_codeguard_scan_stream_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/codeguard/scan/stream", query, body),
    /** Cost Benchmark */
    cost_benchmark_api_v1_costpulse_analytics_cost_benchmark_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/costpulse/analytics/cost-benchmark", query),
    /** Estimate From Brief */
    estimate_from_brief_api_v1_costpulse_estimate_from_brief_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/costpulse/estimate/from-brief", query, body),
    /** Estimate From Drawings */
    estimate_from_drawings_api_v1_costpulse_estimate_from_drawings_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/costpulse/estimate/from-drawings", query, body),
    /** List Estimates */
    list_estimates_api_v1_costpulse_estimates_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/costpulse/estimates", query),
    /** Create Estimate */
    create_estimate_api_v1_costpulse_estimates_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/costpulse/estimates", query, body),
    /** Get Estimate */
    get_estimate_api_v1_costpulse_estimates__estimate_id__get: (params: { estimate_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/costpulse/estimates/${params.estimate_id}`, query),
    /** Approve Estimate */
    approve_estimate_api_v1_costpulse_estimates__estimate_id__approve_post: (params: { estimate_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/costpulse/estimates/${params.estimate_id}/approve`, query, body),
    /** Update Boq */
    update_boq_api_v1_costpulse_estimates__estimate_id__boq_put: (params: { estimate_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("PUT", `/api/v1/costpulse/estimates/${params.estimate_id}/boq`, query, body),
    /** Export Boq Pdf */
    export_boq_pdf_api_v1_costpulse_estimates__estimate_id__boq_export_pdf_get: (params: { estimate_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/costpulse/estimates/${params.estimate_id}/boq/export.pdf`, query),
    /** Export Boq Xlsx */
    export_boq_xlsx_api_v1_costpulse_estimates__estimate_id__boq_export_xlsx_get: (params: { estimate_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/costpulse/estimates/${params.estimate_id}/boq/export.xlsx`, query),
    /** Import Boq Xlsx */
    import_boq_xlsx_api_v1_costpulse_estimates__estimate_id__boq_import_post: (params: { estimate_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/costpulse/estimates/${params.estimate_id}/boq/import`, query, body),
    /** Diff Estimate Versions */
    diff_estimate_versions_api_v1_costpulse_estimates__estimate_id__diff_get: (params: { estimate_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/costpulse/estimates/${params.estimate_id}/diff`, query),
    /** List Estimate Versions */
    list_estimate_versions_api_v1_costpulse_estimates__estimate_id__versions_get: (params: { estimate_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/costpulse/estimates/${params.estimate_id}/versions`, query),
    /** Create Price Alert */
    create_price_alert_api_v1_costpulse_price_alerts_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/costpulse/price-alerts", query, body),
    /** Lookup Prices */
    lookup_prices_api_v1_costpulse_prices_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/costpulse/prices", query),
    /** Price History */
    price_history_api_v1_costpulse_prices_history__material_code__get: (params: { material_code: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/costpulse/prices/history/${params.material_code}`, query),
    /** Override Price */
    override_price_api_v1_costpulse_prices_override_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/costpulse/prices/override", query, body),
    /** List Rfq */
    list_rfq_api_v1_costpulse_rfq_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/costpulse/rfq", query),
    /** Create Rfq */
    create_rfq_api_v1_costpulse_rfq_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/costpulse/rfq", query, body),
    /** List Suppliers */
    list_suppliers_api_v1_costpulse_suppliers_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/costpulse/suppliers", query),
    /** Create Supplier */
    create_supplier_api_v1_costpulse_suppliers_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/costpulse/suppliers", query, body),
    /** Export Suppliers Csv */
    export_suppliers_csv_api_v1_costpulse_suppliers_export_csv_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/costpulse/suppliers/export.csv", query),
    /** Export Suppliers Xlsx */
    export_suppliers_xlsx_api_v1_costpulse_suppliers_export_xlsx_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/costpulse/suppliers/export.xlsx", query),
    /** Import Suppliers */
    import_suppliers_api_v1_costpulse_suppliers_import_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/costpulse/suppliers/import", query, body),
    /** List Logs */
    list_logs_api_v1_dailylog_logs_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/dailylog/logs", query),
    /** Create Log */
    create_log_api_v1_dailylog_logs_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/dailylog/logs", query, body),
    /** Get Log */
    get_log_api_v1_dailylog_logs__log_id__get: (params: { log_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/dailylog/logs/${params.log_id}`, query),
    /** Update Log */
    update_log_api_v1_dailylog_logs__log_id__patch: (params: { log_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("PATCH", `/api/v1/dailylog/logs/${params.log_id}`, query, body),
    /** Trigger Extract */
    trigger_extract_api_v1_dailylog_logs__log_id__extract_post: (params: { log_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/dailylog/logs/${params.log_id}/extract`, query, body),
    /** Create Observation */
    create_observation_api_v1_dailylog_logs__log_id__observations_post: (params: { log_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/dailylog/logs/${params.log_id}/observations`, query, body),
    /** Update Observation */
    update_observation_api_v1_dailylog_observations__obs_id__patch: (params: { obs_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("PATCH", `/api/v1/dailylog/observations/${params.obs_id}`, query, body),
    /** Get Patterns */
    get_patterns_api_v1_dailylog_projects__project_id__patterns_get: (params: { project_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/dailylog/projects/${params.project_id}/patterns`, query),
    /** Conflict Scan */
    conflict_scan_api_v1_drawbridge_conflict_scan_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/drawbridge/conflict-scan", query, body),
    /** List Conflicts */
    list_conflicts_api_v1_drawbridge_conflicts_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/drawbridge/conflicts", query),
    /** Get Conflict */
    get_conflict_api_v1_drawbridge_conflicts__conflict_id__get: (params: { conflict_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/drawbridge/conflicts/${params.conflict_id}`, query),
    /** Update Conflict */
    update_conflict_api_v1_drawbridge_conflicts__conflict_id__patch: (params: { conflict_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("PATCH", `/api/v1/drawbridge/conflicts/${params.conflict_id}`, query, body),
    /** List Document Sets */
    list_document_sets_api_v1_drawbridge_document_sets_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/drawbridge/document-sets", query),
    /** Create Document Set */
    create_document_set_api_v1_drawbridge_document_sets_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/drawbridge/document-sets", query, body),
    /** List Documents */
    list_documents_api_v1_drawbridge_documents_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/drawbridge/documents", query),
    /** Upload Document */
    upload_document_api_v1_drawbridge_documents_upload_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/drawbridge/documents/upload", query, body),
    /** Get Document */
    get_document_api_v1_drawbridge_documents__document_id__get: (params: { document_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/drawbridge/documents/${params.document_id}`, query),
    /** Delete Document */
    delete_document_api_v1_drawbridge_documents__document_id__delete: (params: { document_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("DELETE", `/api/v1/drawbridge/documents/${params.document_id}`, query),
    /** Get Document File */
    get_document_file_api_v1_drawbridge_documents__document_id__file_get: (params: { document_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/drawbridge/documents/${params.document_id}/file`, query),
    /** Extract From Document */
    extract_from_document_api_v1_drawbridge_extract_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/drawbridge/extract", query, body),
    /** Drawbridge Query */
    drawbridge_query_api_v1_drawbridge_query_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/drawbridge/query", query, body),
    /** List Rfis */
    list_rfis_api_v1_drawbridge_rfis_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/drawbridge/rfis", query),
    /** Create Rfi */
    create_rfi_api_v1_drawbridge_rfis_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/drawbridge/rfis", query, body),
    /** Generate Rfi From Conflict */
    generate_rfi_from_conflict_api_v1_drawbridge_rfis_generate_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/drawbridge/rfis/generate", query, body),
    /** Update Rfi */
    update_rfi_api_v1_drawbridge_rfis__rfi_id__patch: (params: { rfi_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("PATCH", `/api/v1/drawbridge/rfis/${params.rfi_id}`, query, body),
    /** Answer Rfi */
    answer_rfi_api_v1_drawbridge_rfis__rfi_id__answer_post: (params: { rfi_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/drawbridge/rfis/${params.rfi_id}/answer`, query, body),
    /** Export Entity */
    export_entity_api_v1_export__entity__get: (params: { entity: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/export/${params.entity}`, query),
    /** Upload File */
    upload_file_api_v1_files_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/files", query, body),
    /** Register As Built */
    register_as_built_api_v1_handover_as_builts_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/handover/as-builts", query, body),
    /** Update Closeout Item */
    update_closeout_item_api_v1_handover_closeout_items__item_id__patch: (params: { item_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("PATCH", `/api/v1/handover/closeout-items/${params.item_id}`, query, body),
    /** List Defects */
    list_defects_api_v1_handover_defects_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/handover/defects", query),
    /** Create Defect */
    create_defect_api_v1_handover_defects_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/handover/defects", query, body),
    /** Update Defect */
    update_defect_api_v1_handover_defects__defect_id__patch: (params: { defect_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("PATCH", `/api/v1/handover/defects/${params.defect_id}`, query, body),
    /** Generate Om Manual */
    generate_om_manual_api_v1_handover_om_manuals_generate_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/handover/om-manuals/generate", query, body),
    /** List Packages */
    list_packages_api_v1_handover_packages_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/handover/packages", query),
    /** Create Package */
    create_package_api_v1_handover_packages_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/handover/packages", query, body),
    /** Get Package */
    get_package_api_v1_handover_packages__package_id__get: (params: { package_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/handover/packages/${params.package_id}`, query),
    /** Update Package */
    update_package_api_v1_handover_packages__package_id__patch: (params: { package_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("PATCH", `/api/v1/handover/packages/${params.package_id}`, query, body),
    /** Add Closeout Item */
    add_closeout_item_api_v1_handover_packages__package_id__closeout_items_post: (params: { package_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/handover/packages/${params.package_id}/closeout-items`, query, body),
    /** List Om Manuals */
    list_om_manuals_api_v1_handover_packages__package_id__om_manuals_get: (params: { package_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/handover/packages/${params.package_id}/om-manuals`, query),
    /** Package Preconditions */
    package_preconditions_api_v1_handover_packages__package_id__preconditions_get: (params: { package_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/handover/packages/${params.package_id}/preconditions`, query),
    /** Promote Drawings From Drawbridge */
    promote_drawings_from_drawbridge_api_v1_handover_packages__package_id__promote_drawings_post: (params: { package_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/handover/packages/${params.package_id}/promote-drawings`, query, body),
    /** List As Builts */
    list_as_builts_api_v1_handover_projects__project_id__as_builts_get: (params: { project_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/handover/projects/${params.project_id}/as-builts`, query),
    /** List Warranties */
    list_warranties_api_v1_handover_warranties_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/handover/warranties", query),
    /** Create Warranty */
    create_warranty_api_v1_handover_warranties_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/handover/warranties", query, body),
    /** Extract Warranty */
    extract_warranty_api_v1_handover_warranties_extract_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/handover/warranties/extract", query, body),
    /** Update Warranty */
    update_warranty_api_v1_handover_warranties__warranty_id__patch: (params: { warranty_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("PATCH", `/api/v1/handover/warranties/${params.warranty_id}`, query, body),
    /** Get Import Job */
    get_import_job_api_v1_import_jobs__job_id__get: (params: { job_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/import/jobs/${params.job_id}`, query),
    /** Commit Import Job */
    commit_import_job_api_v1_import_jobs__job_id__commit_post: (params: { job_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/import/jobs/${params.job_id}/commit`, query, body),
    /** Preview Import */
    preview_import_api_v1_import__entity__preview_post: (params: { entity: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/import/${params.entity}/preview`, query, body),
    /** Get Invitation */
    get_invitation_api_v1_invitations__token__get: (params: { token: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/invitations/${params.token}`, query),
    /** Accept Invitation */
    accept_invitation_api_v1_invitations__token__accept_post: (params: { token: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/invitations/${params.token}/accept`, query, body),
    /** My Inbox */
    my_inbox_api_v1_me_inbox_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/me/inbox", query),
    /** List My Orgs */
    list_my_orgs_api_v1_me_orgs_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/me/orgs", query),
    /** List Preferences */
    list_preferences_api_v1_notifications_preferences_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/notifications/preferences", query),
    /** Upsert Preference */
    upsert_preference_api_v1_notifications_preferences__key__put: (params: { key: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("PUT", `/api/v1/notifications/preferences/${params.key}`, query, body),
    /** List My Watches */
    list_my_watches_api_v1_notifications_watches_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/notifications/watches", query),
    /** Create Watch */
    create_watch_api_v1_notifications_watches_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/notifications/watches", query, body),
    /** Delete Watch */
    delete_watch_api_v1_notifications_watches__project_id__delete: (params: { project_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("DELETE", `/api/v1/notifications/watches/${params.project_id}`, query),
    /** Seed Demo Into Caller Org */
    seed_demo_into_caller_org_api_v1_onboarding_seed_demo_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/onboarding/seed-demo", query, body),
    /** List Members */
    list_members_api_v1_org_members_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/org/members", query),
    /** Invite Member */
    invite_member_api_v1_org_members_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/org/members", query, body),
    /** Update Member Role */
    update_member_role_api_v1_org_members__user_id__patch: (params: { user_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("PATCH", `/api/v1/org/members/${params.user_id}`, query, body),
    /** Remove Member */
    remove_member_api_v1_org_members__user_id__delete: (params: { user_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("DELETE", `/api/v1/org/members/${params.user_id}`, query),
    /** Create Org */
    create_org_api_v1_orgs_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/orgs", query, body),
    /** List Invitations */
    list_invitations_api_v1_orgs__org_id__invitations_get: (params: { org_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/orgs/${params.org_id}/invitations`, query),
    /** Create Invitation */
    create_invitation_api_v1_orgs__org_id__invitations_post: (params: { org_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/orgs/${params.org_id}/invitations`, query, body),
    /** Revoke Invitation */
    revoke_invitation_api_v1_orgs__org_id__invitations__invitation_id__delete: (params: { org_id: string | number; invitation_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("DELETE", `/api/v1/orgs/${params.org_id}/invitations/${params.invitation_id}`, query),
    /** List Projects */
    list_projects_api_v1_projects_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/projects", query),
    /** Get Project Detail */
    get_project_detail_api_v1_projects__project_id__get: (params: { project_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/projects/${params.project_id}`, query),
    /** Get Rfq Context */
    get_rfq_context_api_v1_public_rfq_context_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/public/rfq/context", query),
    /** Submit Rfq Response */
    submit_rfq_response_api_v1_public_rfq_respond_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/public/rfq/respond", query, body),
    /** List Change Orders */
    list_change_orders_api_v1_pulse_change_orders_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/pulse/change-orders", query),
    /** Create Change Order */
    create_change_order_api_v1_pulse_change_orders_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/pulse/change-orders", query, body),
    /** Analyze Change Order */
    analyze_change_order_api_v1_pulse_change_orders__co_id__analyze_post: (params: { co_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/pulse/change-orders/${params.co_id}/analyze`, query, body),
    /** Approve Change Order */
    approve_change_order_api_v1_pulse_change_orders__co_id__approve_patch: (params: { co_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("PATCH", `/api/v1/pulse/change-orders/${params.co_id}/approve`, query, body),
    /** Generate Client Report */
    generate_client_report_api_v1_pulse_client_reports_generate_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/pulse/client-reports/generate", query, body),
    /** Send Client Report */
    send_client_report_api_v1_pulse_client_reports__report_id__send_post: (params: { report_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/pulse/client-reports/${params.report_id}/send`, query, body),
    /** Create Meeting Note */
    create_meeting_note_api_v1_pulse_meeting_notes_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/pulse/meeting-notes", query, body),
    /** Structure Meeting Notes */
    structure_meeting_notes_api_v1_pulse_meeting_notes_structure_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/pulse/meeting-notes/structure", query, body),
    /** Project Dashboard */
    project_dashboard_api_v1_pulse_projects__project_id__dashboard_get: (params: { project_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/pulse/projects/${params.project_id}/dashboard`, query),
    /** List Tasks */
    list_tasks_api_v1_pulse_tasks_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/pulse/tasks", query),
    /** Create Task */
    create_task_api_v1_pulse_tasks_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/pulse/tasks", query, body),
    /** Bulk Update Tasks */
    bulk_update_tasks_api_v1_pulse_tasks_bulk_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/pulse/tasks/bulk", query, body),
    /** Update Task */
    update_task_api_v1_pulse_tasks__task_id__patch: (params: { task_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("PATCH", `/api/v1/pulse/tasks/${params.task_id}`, query, body),
    /** Update Item */
    update_item_api_v1_punchlist_items__item_id__patch: (params: { item_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("PATCH", `/api/v1/punchlist/items/${params.item_id}`, query, body),
    /** Delete Item */
    delete_item_api_v1_punchlist_items__item_id__delete: (params: { item_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("DELETE", `/api/v1/punchlist/items/${params.item_id}`, query),
    /** List Lists */
    list_lists_api_v1_punchlist_lists_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/punchlist/lists", query),
    /** Create List */
    create_list_api_v1_punchlist_lists_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/punchlist/lists", query, body),
    /** Get List */
    get_list_api_v1_punchlist_lists__list_id__get: (params: { list_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/punchlist/lists/${params.list_id}`, query),
    /** Update List */
    update_list_api_v1_punchlist_lists__list_id__patch: (params: { list_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("PATCH", `/api/v1/punchlist/lists/${params.list_id}`, query, body),
    /** Add Item */
    add_item_api_v1_punchlist_lists__list_id__items_post: (params: { list_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/punchlist/lists/${params.list_id}/items`, query, body),
    /** Photo Hints */
    photo_hints_api_v1_punchlist_lists__list_id__photo_hints_get: (params: { list_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/punchlist/lists/${params.list_id}/photo-hints`, query),
    /** Sign Off */
    sign_off_api_v1_punchlist_lists__list_id__sign_off_post: (params: { list_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/punchlist/lists/${params.list_id}/sign-off`, query, body),
    /** Update Activity */
    update_activity_api_v1_schedule_activities__activity_id__patch: (params: { activity_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("PATCH", `/api/v1/schedule/activities/${params.activity_id}`, query, body),
    /** Delete Activity */
    delete_activity_api_v1_schedule_activities__activity_id__delete: (params: { activity_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("DELETE", `/api/v1/schedule/activities/${params.activity_id}`, query),
    /** Create Dependency */
    create_dependency_api_v1_schedule_dependencies_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/schedule/dependencies", query, body),
    /** Delete Dependency */
    delete_dependency_api_v1_schedule_dependencies__dep_id__delete: (params: { dep_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("DELETE", `/api/v1/schedule/dependencies/${params.dep_id}`, query),
    /** List Schedules */
    list_schedules_api_v1_schedule_schedules_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/schedule/schedules", query),
    /** Create Schedule */
    create_schedule_api_v1_schedule_schedules_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/schedule/schedules", query, body),
    /** Get Schedule */
    get_schedule_api_v1_schedule_schedules__schedule_id__get: (params: { schedule_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/schedule/schedules/${params.schedule_id}`, query),
    /** Update Schedule */
    update_schedule_api_v1_schedule_schedules__schedule_id__patch: (params: { schedule_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("PATCH", `/api/v1/schedule/schedules/${params.schedule_id}`, query, body),
    /** Create Activity */
    create_activity_api_v1_schedule_schedules__schedule_id__activities_post: (params: { schedule_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/schedule/schedules/${params.schedule_id}/activities`, query, body),
    /** Baseline Schedule */
    baseline_schedule_api_v1_schedule_schedules__schedule_id__baseline_post: (params: { schedule_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/schedule/schedules/${params.schedule_id}/baseline`, query, body),
    /** Run Risk Assessment */
    run_risk_assessment_api_v1_schedule_schedules__schedule_id__risk_assessment_post: (params: { schedule_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/schedule/schedules/${params.schedule_id}/risk-assessment`, query, body),
    /** List Risk Assessments */
    list_risk_assessments_api_v1_schedule_schedules__schedule_id__risk_assessments_get: (params: { schedule_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/schedule/schedules/${params.schedule_id}/risk-assessments`, query),
    /** Search Endpoint */
    search_endpoint_api_v1_search_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/search", query, body),
    /** Search Analytics Endpoint */
    search_analytics_endpoint_api_v1_search_analytics_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/search/analytics", query),
    /** List Photos */
    list_photos_api_v1_siteeye_photos_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/siteeye/photos", query),
    /** Upload Photos */
    upload_photos_api_v1_siteeye_photos_upload_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/siteeye/photos/upload", query, body),
    /** Progress Timeline */
    progress_timeline_api_v1_siteeye_progress_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/siteeye/progress", query),
    /** List Reports */
    list_reports_api_v1_siteeye_reports_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/siteeye/reports", query),
    /** Generate Report */
    generate_report_api_v1_siteeye_reports_generate_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/siteeye/reports/generate", query, body),
    /** Send Report */
    send_report_api_v1_siteeye_reports__report_id__send_post: (params: { report_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/siteeye/reports/${params.report_id}/send`, query, body),
    /** List Safety Incidents */
    list_safety_incidents_api_v1_siteeye_safety_incidents_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/siteeye/safety-incidents", query),
    /** Acknowledge Incident */
    acknowledge_incident_api_v1_siteeye_safety_incidents__incident_id__ack_patch: (params: { incident_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("PATCH", `/api/v1/siteeye/safety-incidents/${params.incident_id}/ack`, query, body),
    /** List Visits */
    list_visits_api_v1_siteeye_visits_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/siteeye/visits", query),
    /** Create Visit */
    create_visit_api_v1_siteeye_visits_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/siteeye/visits", query, body),
    /** List Submittals */
    list_submittals_api_v1_submittals_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/submittals", query),
    /** Create Submittal */
    create_submittal_api_v1_submittals_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/submittals", query, body),
    /** Accept Draft */
    accept_draft_api_v1_submittals_drafts__draft_id__accept_post: (params: { draft_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/submittals/drafts/${params.draft_id}/accept`, query, body),
    /** Review Revision */
    review_revision_api_v1_submittals_revisions__revision_id__review_post: (params: { revision_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/submittals/revisions/${params.revision_id}/review`, query, body),
    /** Draft Rfi Response Endpoint */
    draft_rfi_response_endpoint_api_v1_submittals_rfis__rfi_id__draft_post: (params: { rfi_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/submittals/rfis/${params.rfi_id}/draft`, query, body),
    /** Embed Rfi Endpoint */
    embed_rfi_endpoint_api_v1_submittals_rfis__rfi_id__embed_post: (params: { rfi_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/submittals/rfis/${params.rfi_id}/embed`, query, body),
    /** Find Similar Rfis Endpoint */
    find_similar_rfis_endpoint_api_v1_submittals_rfis__rfi_id__similar_post: (params: { rfi_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/submittals/rfis/${params.rfi_id}/similar`, query, body),
    /** Get Submittal */
    get_submittal_api_v1_submittals__submittal_id__get: (params: { submittal_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/submittals/${params.submittal_id}`, query),
    /** Update Submittal */
    update_submittal_api_v1_submittals__submittal_id__patch: (params: { submittal_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("PATCH", `/api/v1/submittals/${params.submittal_id}`, query, body),
    /** Create Revision */
    create_revision_api_v1_submittals__submittal_id__revisions_post: (params: { submittal_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/submittals/${params.submittal_id}/revisions`, query, body),
    /** List Webhooks */
    list_webhooks_api_v1_webhooks_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/webhooks", query),
    /** Create Webhook */
    create_webhook_api_v1_webhooks_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/webhooks", query, body),
    /** List Dead Letter */
    list_dead_letter_api_v1_webhooks_deliveries_dead_letter_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/webhooks/deliveries/dead-letter", query),
    /** Redeliver */
    redeliver_api_v1_webhooks_deliveries__delivery_id__redeliver_post: (params: { delivery_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/webhooks/deliveries/${params.delivery_id}/redeliver`, query, body),
    /** List Event Types */
    list_event_types_api_v1_webhooks_event_types_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/webhooks/event-types", query),
    /** Update Webhook */
    update_webhook_api_v1_webhooks__webhook_id__patch: (params: { webhook_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("PATCH", `/api/v1/webhooks/${params.webhook_id}`, query, body),
    /** Delete Webhook */
    delete_webhook_api_v1_webhooks__webhook_id__delete: (params: { webhook_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("DELETE", `/api/v1/webhooks/${params.webhook_id}`, query),
    /** List Deliveries */
    list_deliveries_api_v1_webhooks__webhook_id__deliveries_get: (params: { webhook_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/webhooks/${params.webhook_id}/deliveries`, query),
    /** Deliveries Histogram */
    deliveries_histogram_api_v1_webhooks__webhook_id__deliveries_histogram_get: (params: { webhook_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/webhooks/${params.webhook_id}/deliveries/histogram`, query),
    /** Test Webhook */
    test_webhook_api_v1_webhooks__webhook_id__test_post: (params: { webhook_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/webhooks/${params.webhook_id}/test`, query, body),
    /** Win Rate Route */
    win_rate_route_api_v1_winwork_analytics_win_rate_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/winwork/analytics/win-rate", query),
    /** List Benchmarks */
    list_benchmarks_api_v1_winwork_benchmarks_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/winwork/benchmarks", query),
    /** Fee Estimate */
    fee_estimate_api_v1_winwork_fee_estimate_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/winwork/fee-estimate", query, body),
    /** List Proposals Route */
    list_proposals_route_api_v1_winwork_proposals_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/api/v1/winwork/proposals", query),
    /** Create Proposal Route */
    create_proposal_route_api_v1_winwork_proposals_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/winwork/proposals", query, body),
    /** Generate Proposal Route */
    generate_proposal_route_api_v1_winwork_proposals_generate_post: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", "/api/v1/winwork/proposals/generate", query, body),
    /** Get Proposal Route */
    get_proposal_route_api_v1_winwork_proposals__proposal_id__get: (params: { proposal_id: string | number }, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", `/api/v1/winwork/proposals/${params.proposal_id}`, query),
    /** Update Proposal Route */
    update_proposal_route_api_v1_winwork_proposals__proposal_id__patch: (params: { proposal_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("PATCH", `/api/v1/winwork/proposals/${params.proposal_id}`, query, body),
    /** Mark Outcome Route */
    mark_outcome_route_api_v1_winwork_proposals__proposal_id__outcome_patch: (params: { proposal_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("PATCH", `/api/v1/winwork/proposals/${params.proposal_id}/outcome`, query, body),
    /** Send Proposal Route */
    send_proposal_route_api_v1_winwork_proposals__proposal_id__send_post: (params: { proposal_id: string | number }, query?: Record<string, string | number | boolean | undefined>, body?: unknown) =>
      core.request<unknown>("POST", `/api/v1/winwork/proposals/${params.proposal_id}/send`, query, body),
    /** Health */
    health_health_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/health", query),
    /** Health Ready */
    health_ready_health_ready_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/health/ready", query),
    /** Healthz */
    healthz_healthz_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/healthz", query),
    /** Metrics */
    metrics_metrics_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/metrics", query),
    /** Readyz */
    readyz_readyz_get: (params: Record<string, never>, query?: Record<string, string | number | boolean | undefined>) =>
      core.request<unknown>("GET", "/readyz", query),
  };
}

export const OPERATION_COUNT = 248;
