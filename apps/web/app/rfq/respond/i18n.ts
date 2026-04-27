/**
 * Self-contained i18n for the supplier RFQ-response page.
 *
 * The dashboard uses `next-intl` driven by `i18n/request.ts`, which
 * hard-codes the locale to "vi". The supplier portal sits outside
 * that flow — suppliers have no session, no cookie, no login. We
 * keep the messages here rather than going through `next-intl` so
 * the page can self-determine locale from `?lang=`/browser without
 * needing server-side resolution.
 *
 * The keys mirror the `rfq_respond.*` namespace in
 * `apps/web/i18n/messages/{vi,en}.json` so a future migration to
 * next-intl-driven public locale would be a string-key swap rather
 * than a copy rewrite.
 */

export type SupplierLocale = "vi" | "en";

export const SUPPLIER_LOCALES: SupplierLocale[] = ["vi", "en"];


// Vietnamese is the default — the actual user base. EN is a courtesy
// for international suppliers / when the buyer wants to share the link
// in an English-speaking thread. We keep both objects flat so a `t(key)`
// lookup is a single property access.
export const SUPPLIER_MESSAGES: Record<SupplierLocale, Record<string, string>> = {
  vi: {
    loading: "Đang tải yêu cầu báo giá…",
    missing_token_title: "Liên kết không hợp lệ",
    missing_token_body:
      "Trang này cần liên kết bảo mật trong email yêu cầu báo giá. Nếu bạn đã sao chép URL bằng tay, vui lòng dùng đúng liên kết gốc trong email — phần token sau dấu ?t= là bắt buộc.",
    expired_title: "Liên kết đã hết hạn hoặc không hợp lệ",
    expired_body:
      "Liên kết trong email của bạn có thể đã hết hạn hoặc bị thay thế bởi liên kết mới hơn. Vui lòng phản hồi email gốc để yêu cầu liên kết mới.",
    unavailable_title: "Yêu cầu báo giá không khả dụng",
    header_label: "Yêu cầu báo giá",
    field_project: "Dự án",
    field_estimate: "Dự toán",
    field_deadline: "Hạn phản hồi",
    scope_heading: "Phạm vi tham khảo",
    col_description: "Mô tả",
    col_code: "Mã",
    col_quantity: "Khối lượng",
    col_unit: "Đơn vị",
    col_unit_price: "Đơn giá (VND)",
    submitted_banner:
      "Báo giá của bạn đã được tiếp nhận. Cảm ơn — bên mua sẽ liên hệ nếu cần thêm thông tin. Bạn có thể đóng trang này.",
    submitted_heading: "Nội dung bạn đã gửi",
    field_total_vnd: "Tổng (VND)",
    field_lead_time: "Thời gian giao hàng",
    lead_time_days_suffix: "ngày",
    field_valid_until: "Báo giá có hiệu lực đến",
    form_heading: "Gửi báo giá của bạn",
    form_subheading:
      "Bạn có thể điền tổng giá ở đầu hoặc đơn giá theo từng dòng — hoặc cả hai. Tất cả các trường đều không bắt buộc.",
    label_total: "Tổng báo giá (VND)",
    label_lead_time: "Thời gian giao hàng (ngày)",
    label_valid_until: "Báo giá có hiệu lực đến",
    label_notes: "Ghi chú (điều khoản giao nhận, thanh toán, loại trừ…)",
    line_items_heading: "Đơn giá theo từng hạng mục",
    submit_button: "Gửi báo giá",
    submitting: "Đang gửi…",
    placeholder_total_vnd: "vd. 12500000",
    placeholder_unit_price: "0",
    no_value: "—",
    language_label: "Ngôn ngữ",
    language_vi: "Tiếng Việt",
    language_en: "English",
  },
  en: {
    loading: "Loading your RFQ…",
    missing_token_title: "Missing link token",
    missing_token_body:
      "This page expects a secure link from your RFQ email. If you copied the URL by hand, please use the original link from the email instead — the token after ?t= is required.",
    expired_title: "Link expired or invalid",
    expired_body:
      "The link in your email may have expired or been replaced by a newer one. Please reply to the original email asking for a fresh link.",
    unavailable_title: "RFQ unavailable",
    header_label: "Request for Quotation",
    field_project: "Project",
    field_estimate: "Estimate",
    field_deadline: "Response deadline",
    scope_heading: "Indicative scope",
    col_description: "Description",
    col_code: "Code",
    col_quantity: "Quantity",
    col_unit: "Unit",
    col_unit_price: "Unit price (VND)",
    submitted_banner:
      "Your quote has been received. Thanks — the buyer will reach out if they need follow-up. You can close this page.",
    submitted_heading: "What you submitted",
    field_total_vnd: "Total (VND)",
    field_lead_time: "Lead time",
    lead_time_days_suffix: "days",
    field_valid_until: "Valid until",
    form_heading: "Submit your quote",
    form_subheading:
      "Fill in either a top-line total or per-line prices below — both is fine too. All fields are optional.",
    label_total: "Total quote (VND)",
    label_lead_time: "Lead time (days)",
    label_valid_until: "Quote valid until",
    label_notes: "Notes (delivery terms, payment terms, exclusions…)",
    line_items_heading: "Line-item pricing",
    submit_button: "Submit quote",
    submitting: "Sending…",
    placeholder_total_vnd: "e.g. 12500000",
    placeholder_unit_price: "0",
    no_value: "—",
    language_label: "Language",
    language_vi: "Tiếng Việt",
    language_en: "English",
  },
};


/**
 * Pick a supplier-portal locale from `?lang=` first, falling back to a
 * sensible default of Vietnamese (the primary user base).
 *
 * Doesn't sniff `Accept-Language` because the page is rendered on the
 * client and most suppliers come straight from an email link — the
 * email tells us nothing about the supplier's browser locale, so any
 * sniffing would be guesswork. An explicit `?lang=en` override stays
 * stable across reloads.
 */
export function resolveSupplierLocale(searchParam: string | null): SupplierLocale {
  if (searchParam === "en" || searchParam === "vi") {
    return searchParam;
  }
  return "vi";
}
