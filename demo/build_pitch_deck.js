// Vietnamese investor pitch deck for AEC Platform.
//
// Target audience: VN angel investors, early-stage VCs (Genesia,
// VinaCapital Ventures, ThinkZone, 500 Startups VN), accelerators.
//
// Design system:
//   Primary  : 0A2540 deep navy
//   Secondary: 3E5C76 slate blue
//   Accent   : F77F00 construction-safety orange
//   Bg light : F8FAFC off-white
//   Muted    : 64748B
//   Text-on-dark: F8FAFC
//
// Visual motif: thin orange vertical bar (0.06" wide, 0.6" tall) at
// the left edge of headers on content slides — single repeated cue
// that ties the deck together without slipping into "decorative bar"
// AI-slop territory.
//
// Font pairing: Cambria headers + Calibri body. Both ship with VN
// diacritic support on Windows + macOS PowerPoint.

const pptxgen = require("pptxgenjs");

const COLOR = {
  navy:    "0A2540",
  slate:   "3E5C76",
  orange:  "F77F00",
  bg:      "F8FAFC",
  muted:   "64748B",
  light:   "F8FAFC",
  white:   "FFFFFF",
  emerald: "10B981",
  rose:    "E11D48",
};

const FONT = {
  head: "Cambria",
  body: "Calibri",
};

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9"; // 10" x 5.625"
pres.author = "Sophie Nguyễn Thị Thúy";
pres.title = "AEC Platform — Pitch Deck";
pres.subject = "Investor pitch — VN-first construction SaaS";

const W = 10;
const H = 5.625;

// ---------- Helpers ----------

function addAccentBar(slide) {
  // Thin orange marker at the left edge of every content-slide header.
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.5,
    y: 0.55,
    w: 0.06,
    h: 0.55,
    fill: { color: COLOR.orange },
    line: { color: COLOR.orange, width: 0 },
  });
}

function addHeader(slide, title, subtitle) {
  addAccentBar(slide);
  slide.addText(title, {
    x: 0.7,
    y: 0.4,
    w: W - 1.4,
    h: 0.5,
    fontFace: FONT.head,
    fontSize: 28,
    bold: true,
    color: COLOR.navy,
    margin: 0,
  });
  if (subtitle) {
    slide.addText(subtitle, {
      x: 0.7,
      y: 0.92,
      w: W - 1.4,
      h: 0.3,
      fontFace: FONT.body,
      fontSize: 12,
      color: COLOR.muted,
      margin: 0,
    });
  }
}

function addPageNumber(slide, n, total) {
  slide.addText(`${n} / ${total}`, {
    x: W - 1.2,
    y: H - 0.4,
    w: 0.7,
    h: 0.25,
    fontFace: FONT.body,
    fontSize: 9,
    color: COLOR.muted,
    align: "right",
    margin: 0,
  });
}

function addFooter(slide) {
  slide.addText("AEC Platform · Confidential", {
    x: 0.5,
    y: H - 0.4,
    w: 4,
    h: 0.25,
    fontFace: FONT.body,
    fontSize: 9,
    color: COLOR.muted,
    margin: 0,
  });
}

const TOTAL = 14;
let slideNum = 0;
function newSlide(opts = {}) {
  slideNum++;
  const s = pres.addSlide();
  s.background = { color: opts.dark ? COLOR.navy : COLOR.bg };
  if (!opts.dark && !opts.noFooter) {
    addFooter(s);
    addPageNumber(s, slideNum, TOTAL);
  }
  return s;
}

// ============================================================
// Slide 1 — Cover
// ============================================================

{
  const s = newSlide({ dark: true, noFooter: true });

  // Orange band on the left edge — visual signature
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0,
    y: 0,
    w: 0.4,
    h: H,
    fill: { color: COLOR.orange },
    line: { color: COLOR.orange, width: 0 },
  });

  // Top-right small label
  s.addText("VC · Angel pitch · 2026", {
    x: W - 3.7,
    y: 0.5,
    w: 3.2,
    h: 0.3,
    fontFace: FONT.body,
    fontSize: 10,
    color: COLOR.orange,
    align: "right",
    charSpacing: 4,
    margin: 0,
  });

  // Big title
  s.addText("AEC Platform", {
    x: 1.0,
    y: 1.8,
    w: W - 1.5,
    h: 1.0,
    fontFace: FONT.head,
    fontSize: 60,
    bold: true,
    color: COLOR.white,
    margin: 0,
  });

  // Tagline
  s.addText(
    "Nền tảng AI quản lý dự án xây dựng — dành riêng cho Việt Nam",
    {
      x: 1.0,
      y: 2.85,
      w: W - 1.5,
      h: 0.5,
      fontFace: FONT.body,
      fontSize: 20,
      color: "CADCFC",
      margin: 0,
    },
  );

  // Stats row
  const stats = [
    { num: "20", label: "module tích hợp" },
    { num: "1.128", label: "test xanh" },
    { num: "$30B", label: "thị trường VN/năm" },
  ];
  stats.forEach((stat, i) => {
    const x = 1.0 + i * 2.7;
    s.addText(stat.num, {
      x,
      y: 3.85,
      w: 2.5,
      h: 0.55,
      fontFace: FONT.head,
      fontSize: 36,
      bold: true,
      color: COLOR.orange,
      margin: 0,
    });
    s.addText(stat.label, {
      x,
      y: 4.4,
      w: 2.5,
      h: 0.3,
      fontFace: FONT.body,
      fontSize: 11,
      color: "CADCFC",
      margin: 0,
    });
  });

  // Footer presenter info
  s.addText("Sophie Nguyễn Thị Thúy · Founder & CEO", {
    x: 1.0,
    y: H - 0.7,
    w: 6,
    h: 0.25,
    fontFace: FONT.body,
    fontSize: 11,
    color: "CADCFC",
    margin: 0,
  });
  s.addText("github.com/sophie-nguyenthuthuy/aec-platform", {
    x: W - 5.2,
    y: H - 0.7,
    w: 4.7,
    h: 0.25,
    fontFace: FONT.body,
    fontSize: 10,
    color: COLOR.orange,
    align: "right",
    margin: 0,
  });
}

// ============================================================
// Slide 2 — Vấn đề (Problem)
// ============================================================

{
  const s = newSlide();
  addHeader(s, "Vấn đề", "Nhà thầu xây dựng Việt Nam đang quản lý dự án bằng Excel + Zalo");

  // Left column: stat callouts
  const stats = [
    {
      num: "70%",
      label: "dự án trễ tiến độ",
      detail: "do thiếu công cụ tracking + AI rủi ro",
    },
    {
      num: "2-3 lần",
      label: "thẩm tra trả về mỗi hồ sơ",
      detail: "không có công cụ đối chiếu QCVN trước khi nộp",
    },
    {
      num: "5-15M ₫",
      label: "phạt mỗi lần thiếu hồ sơ BHLĐ",
      detail: "Nghị định 06/2021 + Thông tư 04/2017",
    },
  ];

  stats.forEach((stat, i) => {
    const y = 1.5 + i * 1.15;
    // Number — wider column so "5-15M ₫" doesn't wrap
    s.addText(stat.num, {
      x: 0.7,
      y,
      w: 2.3,
      h: 0.6,
      fontFace: FONT.head,
      fontSize: 36,
      bold: true,
      color: COLOR.rose,
      margin: 0,
    });
    // Label + detail (shifted right to accommodate wider number column)
    s.addText(stat.label, {
      x: 3.1,
      y: y + 0.05,
      w: 2.9,
      h: 0.35,
      fontFace: FONT.body,
      fontSize: 15,
      bold: true,
      color: COLOR.navy,
      margin: 0,
    });
    s.addText(stat.detail, {
      x: 3.1,
      y: y + 0.5,
      w: 2.9,
      h: 0.35,
      fontFace: FONT.body,
      fontSize: 11,
      color: COLOR.muted,
      margin: 0,
    });
  });

  // Right side panel — "Why this happens"
  s.addShape(pres.shapes.RECTANGLE, {
    x: 6.3,
    y: 1.4,
    w: 3.2,
    h: 3.4,
    fill: { color: COLOR.navy },
    line: { color: COLOR.navy, width: 0 },
  });
  s.addText("Tại sao?", {
    x: 6.5,
    y: 1.6,
    w: 2.8,
    h: 0.35,
    fontFace: FONT.head,
    fontSize: 16,
    bold: true,
    color: COLOR.orange,
    margin: 0,
  });
  const reasons = [
    "Procore + Autodesk ACC — không hiểu QCVN, không có VietQR",
    "Phần mềm nội địa (Coffee Cup, Eta) — thiếu AI, kiến trúc cũ",
    "Tự build — 18 tháng, 5-10 tỷ, không tận dụng AI",
  ];
  s.addText(
    reasons.map((r, i) => ({
      text: r,
      options: { bullet: { code: "25A0" }, breakLine: i < reasons.length - 1 },
    })),
    {
      x: 6.5,
      y: 2.05,
      w: 2.85,
      h: 2.7,
      fontFace: FONT.body,
      fontSize: 11,
      color: "CADCFC",
      paraSpaceAfter: 8,
      margin: 0,
    },
  );
}

// ============================================================
// Slide 3 — Giải pháp (Solution)
// ============================================================

{
  const s = newSlide();
  addHeader(
    s,
    "Giải pháp",
    "Một nền tảng. 20 module tích hợp. AI + QCVN built-in.",
  );

  // Big statement
  s.addText(
    "AEC Platform = Procore + AI tiếng Việt + ingest QCVN sẵn",
    {
      x: 0.7,
      y: 1.4,
      w: W - 1.4,
      h: 0.5,
      fontFace: FONT.head,
      fontSize: 22,
      bold: true,
      color: COLOR.navy,
      italic: true,
      margin: 0,
    },
  );

  // Three differentiator cards
  const cards = [
    {
      title: "AI tích hợp sâu",
      body: "CodeGuard biết QCVN. Drawbridge đọc bản vẽ Việt. WinWork hiểu mẫu BXD. AI làm việc với dữ liệu của khách hàng — không phải dán PDF vào ChatGPT.",
      color: COLOR.orange,
    },
    {
      title: "Data sovereignty",
      body: "Lưu trữ tại Supabase Singapore, MinIO on-prem cho Enterprise. Không gửi PII / bản vẽ sang Mỹ — phù hợp khách SOE + bộ ngành.",
      color: COLOR.emerald,
    },
    {
      title: "Việt Nam-first",
      body: "QCVN/TCVN ingest sẵn (PCCC, kết cấu, tiếp cận, năng lượng, quy hoạch). VietQR thanh toán. Biên bản bàn giao đúng mẫu BXD.",
      color: COLOR.slate,
    },
  ];

  cards.forEach((c, i) => {
    const x = 0.7 + i * 3.0;
    // Card background
    s.addShape(pres.shapes.RECTANGLE, {
      x,
      y: 2.2,
      w: 2.8,
      h: 2.7,
      fill: { color: COLOR.white },
      line: { color: "E2E8F0", width: 1 },
      shadow: {
        type: "outer",
        color: "000000",
        blur: 6,
        offset: 2,
        angle: 90,
        opacity: 0.08,
      },
    });
    // Top accent
    s.addShape(pres.shapes.RECTANGLE, {
      x,
      y: 2.2,
      w: 2.8,
      h: 0.08,
      fill: { color: c.color },
      line: { color: c.color, width: 0 },
    });
    s.addText(c.title, {
      x: x + 0.2,
      y: 2.4,
      w: 2.5,
      h: 0.4,
      fontFace: FONT.head,
      fontSize: 17,
      bold: true,
      color: COLOR.navy,
      margin: 0,
    });
    s.addText(c.body, {
      x: x + 0.2,
      y: 2.85,
      w: 2.5,
      h: 1.9,
      fontFace: FONT.body,
      fontSize: 11,
      color: COLOR.slate,
      margin: 0,
      paraSpaceAfter: 0,
    });
  });
}

// ============================================================
// Slide 4 — Thị trường (Market opportunity)
// ============================================================

{
  const s = newSlide();
  addHeader(s, "Thị trường", "Thị trường xây dựng VN — TAM / SAM / SOM");

  // Three concentric numbers
  const market = [
    {
      label: "TAM",
      value: "$30 tỷ",
      sub: "Thị trường xây dựng VN/năm",
      detail: "~700 nghìn tỷ VNĐ chi tiêu xây dựng quốc gia. 17M lao động.",
      color: COLOR.slate,
    },
    {
      label: "SAM",
      value: "$3,5 tỷ",
      sub: "Phần mềm + AI ngành xây dựng",
      detail: "~83 nghìn tỷ VNĐ — tổng thầu, tư vấn TVTK, chủ đầu tư BĐS, FDI manufacturing.",
      color: COLOR.navy,
    },
    {
      label: "SOM",
      value: "$120M",
      sub: "Mục tiêu 5 năm (3% SAM)",
      detail: "~2.800 tỷ VNĐ — 5.000 SOE customer + 2.500 nhà thầu tư nhân.",
      color: COLOR.orange,
    },
  ];

  market.forEach((m, i) => {
    const y = 1.45 + i * 1.15;
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.7,
      y,
      w: 0.8,
      h: 0.95,
      fill: { color: m.color },
      line: { color: m.color, width: 0 },
    });
    s.addText(m.label, {
      x: 0.7,
      y,
      w: 0.8,
      h: 0.95,
      fontFace: FONT.head,
      fontSize: 16,
      bold: true,
      color: COLOR.white,
      align: "center",
      valign: "middle",
      margin: 0,
    });
    s.addText(m.value, {
      x: 1.7,
      y: y - 0.05,
      w: 2.0,
      h: 0.55,
      fontFace: FONT.head,
      fontSize: 32,
      bold: true,
      color: COLOR.navy,
      margin: 0,
    });
    s.addText(m.sub, {
      x: 3.7,
      y,
      w: 5.6,
      h: 0.35,
      fontFace: FONT.body,
      fontSize: 13,
      bold: true,
      color: COLOR.navy,
      margin: 0,
    });
    s.addText(m.detail, {
      x: 3.7,
      y: y + 0.4,
      w: 5.6,
      h: 0.6,
      fontFace: FONT.body,
      fontSize: 11,
      color: COLOR.muted,
      margin: 0,
    });
  });

  // Source line at bottom
  s.addText(
    "Nguồn: Tổng cục Thống kê 2024, Hiệp hội Xây dựng VN, BXD báo cáo ngành Q4/2024",
    {
      x: 0.7,
      y: 4.95,
      w: 8.5,
      h: 0.3,
      fontFace: FONT.body,
      fontSize: 9,
      italic: true,
      color: COLOR.muted,
      margin: 0,
    },
  );
}

// ============================================================
// Slide 5 — Sản phẩm: 20 module
// ============================================================

{
  const s = newSlide();
  addHeader(
    s,
    "Sản phẩm",
    "20 module phủ toàn vòng đời dự án — từ săn gói thầu đến bàn giao",
  );

  // Group by lifecycle phase
  const phases = [
    {
      name: "Pháp lý",
      color: COLOR.rose,
      modules: ["PermitFlow", "PCCC"],
    },
    {
      name: "Thiết kế",
      color: "8B5CF6",
      modules: ["CodeGuard", "Drawbridge"],
    },
    {
      name: "Đấu thầu",
      color: "0EA5E9",
      modules: ["BidRadar", "WinWork", "CostPulse", "MaterialPrice"],
    },
    {
      name: "Thi công",
      color: COLOR.emerald,
      modules: [
        "Pulse",
        "SiteEye",
        "SchedulePilot",
        "Nhật ký",
        "Change orders",
        "Safety Toolbox",
        "Equipment",
        "Subcontractors",
      ],
    },
    {
      name: "Bàn giao",
      color: COLOR.orange,
      modules: ["Handover", "Punch list", "WarrantyTracker", "CashFlow"],
    },
  ];

  // Phase lifecycle bar at top
  const barY = 1.45;
  const barH = 0.4;
  const totalWidth = W - 1.4;
  const counts = phases.map((p) => p.modules.length);
  const totalCount = counts.reduce((a, b) => a + b, 0);
  let cursorX = 0.7;
  phases.forEach((p, i) => {
    const w = (p.modules.length / totalCount) * totalWidth;
    s.addShape(pres.shapes.RECTANGLE, {
      x: cursorX,
      y: barY,
      w,
      h: barH,
      fill: { color: p.color },
      line: { color: p.color, width: 0 },
    });
    s.addText(p.name, {
      x: cursorX,
      y: barY,
      w,
      h: barH,
      fontFace: FONT.body,
      fontSize: 11,
      bold: true,
      color: COLOR.white,
      align: "center",
      valign: "middle",
      margin: 0,
    });
    cursorX += w;
  });

  // Modules grid below
  const gridY = 2.1;
  const gridX = 0.7;
  const moduleW = 1.5;
  const moduleH = 0.55;
  const colsPerRow = 5;
  let col = 0,
    row = 0;
  const flatModules = phases.flatMap((p) =>
    p.modules.map((m) => ({ name: m, color: p.color })),
  );
  flatModules.forEach((mod) => {
    const x = gridX + col * (moduleW + 0.14);
    const y = gridY + row * (moduleH + 0.14);
    s.addShape(pres.shapes.RECTANGLE, {
      x,
      y,
      w: moduleW,
      h: moduleH,
      fill: { color: COLOR.white },
      line: { color: "E2E8F0", width: 0.5 },
    });
    // Left accent stripe
    s.addShape(pres.shapes.RECTANGLE, {
      x,
      y,
      w: 0.08,
      h: moduleH,
      fill: { color: mod.color },
      line: { color: mod.color, width: 0 },
    });
    s.addText(mod.name, {
      x: x + 0.12,
      y,
      w: moduleW - 0.18,
      h: moduleH,
      fontFace: FONT.body,
      fontSize: 11,
      bold: true,
      color: COLOR.navy,
      valign: "middle",
      margin: 0,
    });
    col++;
    if (col === colsPerRow) {
      col = 0;
      row++;
    }
  });
}

// ============================================================
// Slide 6 — AI integration
// ============================================================

{
  const s = newSlide();
  addHeader(s, "AI tích hợp", "Gemini + Claude làm việc với dữ liệu khách hàng");

  // Big stat — total LLM calls processed
  s.addText("3 luồng AI cốt lõi, mỗi luồng có audit trail riêng", {
    x: 0.7,
    y: 1.4,
    w: W - 1.4,
    h: 0.4,
    fontFace: FONT.body,
    fontSize: 14,
    italic: true,
    color: COLOR.muted,
    margin: 0,
  });

  const aiFlows = [
    {
      module: "CodeGuard",
      title: "Đối chiếu QCVN tự động",
      detail:
        "Quét thông số dự án → AI tìm vi phạm QCVN với trích dẫn nguyên văn. 83 chunk QCVN đã ingest.",
      stack: "Gemini embedding + Claude Sonnet 4.6",
    },
    {
      module: "Drawbridge",
      title: "Hỏi-đáp bản vẽ kỹ thuật",
      detail:
        "Upload bộ bản vẽ + thuyết minh → AI trả lời câu hỏi engineer, có citation về drawing number + page.",
      stack: "Gemini embedding 768-dim + BAAI bge-reranker-v2",
    },
    {
      module: "SiteEye",
      title: "Giám sát công trường",
      detail:
        "Chụp ảnh từ điện thoại → YOLOv8m phát hiện PPE + incident. Báo cáo tuần PDF tự động.",
      stack: "YOLOv8m fine-tuned VN + Ray Serve",
    },
  ];

  aiFlows.forEach((flow, i) => {
    const y = 2.0 + i * 1.05;
    // Module name badge
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.7,
      y,
      w: 1.6,
      h: 0.9,
      fill: { color: COLOR.navy },
      line: { color: COLOR.navy, width: 0 },
    });
    s.addText(flow.module, {
      x: 0.7,
      y,
      w: 1.6,
      h: 0.9,
      fontFace: FONT.head,
      fontSize: 14,
      bold: true,
      color: COLOR.orange,
      align: "center",
      valign: "middle",
      margin: 0,
    });
    s.addText(flow.title, {
      x: 2.5,
      y: y + 0.03,
      w: 6.8,
      h: 0.32,
      fontFace: FONT.body,
      fontSize: 14,
      bold: true,
      color: COLOR.navy,
      margin: 0,
    });
    s.addText(flow.detail, {
      x: 2.5,
      y: y + 0.36,
      w: 6.8,
      h: 0.35,
      fontFace: FONT.body,
      fontSize: 11,
      color: COLOR.slate,
      margin: 0,
    });
    s.addText(`Stack: ${flow.stack}`, {
      x: 2.5,
      y: y + 0.7,
      w: 6.8,
      h: 0.22,
      fontFace: FONT.body,
      fontSize: 9.5,
      italic: true,
      color: COLOR.muted,
      margin: 0,
    });
  });
}

// ============================================================
// Slide 7 — Khác biệt (Competition)
// ============================================================

{
  const s = newSlide();
  addHeader(
    s,
    "Khác biệt với competitor",
    "Đối thủ thiếu 1 trong 3 điều cốt lõi cho khách VN",
  );

  // Comparison table
  const headers = ["", "AEC Platform", "Procore (US)", "Coffee Cup (VN)", "Tự build"];
  const rows = [
    ["QCVN/TCVN ingest sẵn", "✓", "✗", "✗", "6 tháng"],
    ["AI built-in", "✓", "Add-on $$", "✗", "12 tháng"],
    ["Multi-tenant SaaS", "✓", "✓", "✗", "12 tháng"],
    ["VietQR + e-invoice VN", "✓", "✗", "✓", "3 tháng"],
    ["Data sovereignty (on-prem)", "✓ Enterprise", "✗", "Tự host", "Tự build"],
    ["Cost", "Free / 4.9M VNĐ-tháng", "$1000+/user/yr", "Custom", "5-10 tỷ"],
  ];

  const tx = 0.7;
  const ty = 1.5;
  const cellH = 0.42;
  const widths = [2.2, 1.7, 1.7, 1.7, 1.3]; // total = 8.6"

  // Header row
  let cx = tx;
  headers.forEach((h, i) => {
    s.addShape(pres.shapes.RECTANGLE, {
      x: cx,
      y: ty,
      w: widths[i],
      h: cellH,
      fill: { color: i === 1 ? COLOR.navy : COLOR.slate },
      line: { color: "FFFFFF", width: 1 },
    });
    s.addText(h, {
      x: cx,
      y: ty,
      w: widths[i],
      h: cellH,
      fontFace: FONT.body,
      fontSize: 11,
      bold: true,
      color: COLOR.white,
      align: i === 0 ? "left" : "center",
      valign: "middle",
      margin: 0.05,
    });
    cx += widths[i];
  });

  // Data rows
  rows.forEach((row, ri) => {
    const ry = ty + cellH + ri * cellH;
    cx = tx;
    row.forEach((cell, ci) => {
      const isAec = ci === 1;
      s.addShape(pres.shapes.RECTANGLE, {
        x: cx,
        y: ry,
        w: widths[ci],
        h: cellH,
        fill: { color: isAec ? "FFF7ED" : COLOR.white },
        line: { color: "E2E8F0", width: 0.5 },
      });
      let color = COLOR.slate;
      let bold = false;
      if (cell === "✓") {
        color = COLOR.emerald;
        bold = true;
      } else if (cell === "✗") {
        color = COLOR.rose;
        bold = true;
      } else if (isAec) {
        color = COLOR.navy;
        bold = true;
      }
      s.addText(cell, {
        x: cx,
        y: ry,
        w: widths[ci],
        h: cellH,
        fontFace: FONT.body,
        fontSize: 11,
        bold,
        color,
        align: ci === 0 ? "left" : "center",
        valign: "middle",
        margin: 0.05,
      });
      cx += widths[ci];
    });
  });
}

// ============================================================
// Slide 8 — Mô hình kinh doanh (Business model)
// ============================================================

{
  const s = newSlide();
  addHeader(s, "Mô hình kinh doanh", "SaaS subscription · VietQR + Stripe · 3 tier");

  // 3 pricing tiles
  const tiers = [
    {
      name: "Khởi đầu",
      price: "Miễn phí",
      sub: "Cho team đang đánh giá",
      features: [
        "1 dự án · 3 thành viên",
        "2 GB lưu trữ bản vẽ",
        "200 lượt CodeGuard/tháng",
        "Tất cả 20 module",
      ],
      color: COLOR.slate,
      featured: false,
    },
    {
      name: "Chuyên nghiệp",
      price: "4,9M ₫",
      priceSub: "/ tháng · chưa VAT",
      sub: "Nhà thầu vừa, 5-25 người",
      features: [
        "10 dự án · 25 thành viên",
        "50 GB lưu trữ bản vẽ",
        "1.000 lượt CodeGuard/tháng",
        "PDF báo cáo + KTNN export",
        "Email hỗ trợ trong ngày",
      ],
      color: COLOR.orange,
      featured: true,
    },
    {
      name: "Doanh nghiệp",
      price: "Liên hệ",
      sub: "SOE, tổng thầu lớn, FDI",
      features: [
        "Không giới hạn",
        "On-prem MinIO",
        "SSO Microsoft + Google",
        "SLA 99.9% hợp đồng",
        "Custom QCVN ingest",
      ],
      color: COLOR.navy,
      featured: false,
    },
  ];

  tiers.forEach((t, i) => {
    const x = 0.7 + i * 3.0;
    const y = 1.4;
    const cardH = 3.8;
    // Card
    s.addShape(pres.shapes.RECTANGLE, {
      x,
      y,
      w: 2.8,
      h: cardH,
      fill: { color: t.featured ? COLOR.navy : COLOR.white },
      line: { color: t.featured ? COLOR.orange : "E2E8F0", width: t.featured ? 2 : 1 },
      shadow: t.featured
        ? {
            type: "outer",
            color: "000000",
            blur: 10,
            offset: 3,
            angle: 90,
            opacity: 0.15,
          }
        : undefined,
    });
    // Featured badge
    if (t.featured) {
      s.addShape(pres.shapes.RECTANGLE, {
        x: x + 0.7,
        y: y - 0.18,
        w: 1.4,
        h: 0.3,
        fill: { color: COLOR.orange },
        line: { color: COLOR.orange, width: 0 },
      });
      s.addText("PHỔ BIẾN", {
        x: x + 0.7,
        y: y - 0.18,
        w: 1.4,
        h: 0.3,
        fontFace: FONT.body,
        fontSize: 9,
        bold: true,
        color: COLOR.white,
        align: "center",
        valign: "middle",
        charSpacing: 3,
        margin: 0,
      });
    }
    s.addText(t.name, {
      x: x + 0.25,
      y: y + 0.25,
      w: 2.3,
      h: 0.4,
      fontFace: FONT.head,
      fontSize: 18,
      bold: true,
      color: t.featured ? COLOR.orange : COLOR.navy,
      margin: 0,
    });
    s.addText(t.price, {
      x: x + 0.25,
      y: y + 0.7,
      w: 2.3,
      h: 0.5,
      fontFace: FONT.head,
      fontSize: 28,
      bold: true,
      color: t.featured ? COLOR.white : COLOR.navy,
      margin: 0,
    });
    if (t.priceSub) {
      s.addText(t.priceSub, {
        x: x + 0.25,
        y: y + 1.22,
        w: 2.3,
        h: 0.25,
        fontFace: FONT.body,
        fontSize: 10,
        color: t.featured ? "CADCFC" : COLOR.muted,
        margin: 0,
      });
    }
    s.addText(t.sub, {
      x: x + 0.25,
      y: y + 1.5,
      w: 2.3,
      h: 0.32,
      fontFace: FONT.body,
      fontSize: 10.5,
      italic: true,
      color: t.featured ? "CADCFC" : COLOR.muted,
      margin: 0,
    });
    // Features
    s.addText(
      t.features.map((f, idx) => ({
        text: f,
        options: {
          bullet: { code: "2713" },
          breakLine: idx < t.features.length - 1,
        },
      })),
      {
        x: x + 0.25,
        y: y + 1.95,
        w: 2.3,
        h: 1.65,
        fontFace: FONT.body,
        fontSize: 10.5,
        color: t.featured ? "CADCFC" : COLOR.slate,
        paraSpaceAfter: 4,
        margin: 0,
      },
    );
  });

  // Unit economics callout — keep clear of the footer at y=5.225
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.7,
    y: 4.65,
    w: W - 1.4,
    h: 0.45,
    fill: { color: "FFF7ED" },
    line: { color: COLOR.orange, width: 1 },
  });
  s.addText(
    [
      { text: "Unit economics: ", options: { bold: true, color: COLOR.navy } },
      { text: "ARPU 60M ₫/năm · CAC 5M ₫ · payback 2 tháng · gross margin 78% · NRR 115% (target)", options: { color: COLOR.slate } },
    ],
    {
      x: 0.85,
      y: 4.65,
      w: W - 1.7,
      h: 0.45,
      fontFace: FONT.body,
      fontSize: 11,
      valign: "middle",
      margin: 0,
    },
  );
}

// ============================================================
// Slide 9 — Go-to-market
// ============================================================

{
  const s = newSlide();
  addHeader(
    s,
    "Go-to-market",
    "5 ICP archetype · outbound + content + partnerships",
  );

  // Funnel diagram on left
  const funnelX = 0.7;
  const funnelW = 4.0;
  const funnel = [
    { label: "200 cold email/tháng", value: "8-15% open", w: 4.0, color: COLOR.slate },
    { label: "20 discovery call", value: "60% → demo", w: 3.3, color: "0EA5E9" },
    { label: "12 product demo", value: "40% → POC", w: 2.6, color: "8B5CF6" },
    { label: "5 POC paid", value: "50% → close", w: 1.9, color: COLOR.orange },
    { label: "2-3 close/tháng", value: "Avg ACV 80M ₫", w: 1.3, color: COLOR.emerald },
  ];

  funnel.forEach((f, i) => {
    const y = 1.5 + i * 0.55;
    const offset = (funnelW - f.w) / 2;
    s.addShape(pres.shapes.RECTANGLE, {
      x: funnelX + offset,
      y,
      w: f.w,
      h: 0.45,
      fill: { color: f.color },
      line: { color: f.color, width: 0 },
    });
    s.addText(f.label, {
      x: funnelX + offset,
      y,
      w: f.w,
      h: 0.45,
      fontFace: FONT.body,
      fontSize: 11,
      bold: true,
      color: COLOR.white,
      align: "center",
      valign: "middle",
      margin: 0,
    });
    s.addText(f.value, {
      x: funnelX + offset + f.w + 0.15,
      y,
      w: 1.5,
      h: 0.45,
      fontFace: FONT.body,
      fontSize: 10,
      color: COLOR.muted,
      valign: "middle",
      margin: 0,
    });
  });

  // ICP archetypes on right
  s.addText("5 ICP target", {
    x: 6.3,
    y: 1.4,
    w: 3.2,
    h: 0.3,
    fontFace: FONT.head,
    fontSize: 16,
    bold: true,
    color: COLOR.navy,
    margin: 0,
  });
  const icps = [
    { name: "Tổng thầu SOE", example: "Vinaconex, Cienco4, Sông Đà" },
    { name: "TVTK / consulting", example: "VNCC, TEDI, AA Corp" },
    { name: "Nhà thầu thi công", example: "Coteccons sub, Hòa Bình" },
    { name: "Chủ đầu tư BĐS", example: "Sun Group, VinHomes" },
    { name: "FDI manufacturer", example: "Samsung, LG, Foxconn" },
  ];
  icps.forEach((icp, i) => {
    const y = 1.85 + i * 0.55;
    s.addText(icp.name, {
      x: 6.3,
      y,
      w: 3.2,
      h: 0.25,
      fontFace: FONT.body,
      fontSize: 12,
      bold: true,
      color: COLOR.navy,
      margin: 0,
    });
    s.addText(icp.example, {
      x: 6.3,
      y: y + 0.27,
      w: 3.2,
      h: 0.22,
      fontFace: FONT.body,
      fontSize: 9.5,
      italic: true,
      color: COLOR.muted,
      margin: 0,
    });
  });

  // Partnership callout — moved up to clear footer
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.7,
    y: 4.7,
    w: W - 1.4,
    h: 0.45,
    fill: { color: "F1F5F9" },
    line: { color: "E2E8F0", width: 0.5 },
  });
  s.addText(
    [
      { text: "Channel + partnership: ", options: { bold: true, color: COLOR.navy } },
      {
        text: "Hiệp hội Nhà thầu VN (VACA), Hội Tư vấn Xây dựng (VECAS) — sponsorship + co-marketing. Stripe + VietQR đối tác thanh toán.",
        options: { color: COLOR.slate },
      },
    ],
    {
      x: 0.85,
      y: 4.7,
      w: W - 1.7,
      h: 0.45,
      fontFace: FONT.body,
      fontSize: 11,
      valign: "middle",
      margin: 0,
    },
  );
}

// ============================================================
// Slide 10 — Traction
// ============================================================

{
  const s = newSlide();
  addHeader(s, "Traction", "Pre-revenue · platform shipped · sẵn sàng go-to-market");

  // Big stats row
  const stats = [
    { num: "20", label: "module shipped", sub: "production-ready" },
    { num: "1.128", label: "test xanh", sub: "100% pass rate" },
    { num: "78%", label: "code coverage", sub: "API + worker + web" },
    { num: "55", label: "alembic migration", sub: "RLS + multi-tenant" },
  ];
  stats.forEach((stat, i) => {
    const x = 0.7 + i * 2.2;
    s.addShape(pres.shapes.RECTANGLE, {
      x,
      y: 1.5,
      w: 2.0,
      h: 1.4,
      fill: { color: COLOR.navy },
      line: { color: COLOR.navy, width: 0 },
    });
    s.addText(stat.num, {
      x,
      y: 1.55,
      w: 2.0,
      h: 0.7,
      fontFace: FONT.head,
      fontSize: 36,
      bold: true,
      color: COLOR.orange,
      align: "center",
      valign: "middle",
      margin: 0,
    });
    s.addText(stat.label, {
      x,
      y: 2.3,
      w: 2.0,
      h: 0.3,
      fontFace: FONT.body,
      fontSize: 11,
      bold: true,
      color: COLOR.white,
      align: "center",
      margin: 0,
    });
    s.addText(stat.sub, {
      x,
      y: 2.6,
      w: 2.0,
      h: 0.25,
      fontFace: FONT.body,
      fontSize: 9,
      italic: true,
      color: "CADCFC",
      align: "center",
      margin: 0,
    });
  });

  // Milestone timeline
  s.addText("Milestones đã hoàn thành", {
    x: 0.7,
    y: 3.2,
    w: 8.5,
    h: 0.3,
    fontFace: FONT.head,
    fontSize: 14,
    bold: true,
    color: COLOR.navy,
    margin: 0,
  });

  const milestones = [
    {
      date: "Q4/2025",
      title: "MVP — 14 module cốt lõi",
      detail: "WinWork, CostPulse, Pulse, SiteEye, BidRadar, CodeGuard, Drawbridge, Handover…",
    },
    {
      date: "Q1/2026",
      title: "Multi-tenant + RLS + SSO",
      detail: "Postgres RLS isolation, Google + Microsoft SSO, KTNN audit export",
    },
    {
      date: "Q2/2026",
      title: "20 module + production deploy",
      detail: "+6 module mới, Railway + Vercel + Supabase Singapore, public GitHub repo",
    },
  ];

  milestones.forEach((m, i) => {
    const y = 3.6 + i * 0.55;
    s.addShape(pres.shapes.OVAL, {
      x: 0.75,
      y: y + 0.1,
      w: 0.12,
      h: 0.12,
      fill: { color: COLOR.orange },
      line: { color: COLOR.orange, width: 0 },
    });
    s.addText(m.date, {
      x: 1.0,
      y,
      w: 1.2,
      h: 0.3,
      fontFace: FONT.body,
      fontSize: 11,
      bold: true,
      color: COLOR.orange,
      margin: 0,
    });
    s.addText(m.title, {
      x: 2.2,
      y,
      w: 3.5,
      h: 0.3,
      fontFace: FONT.body,
      fontSize: 12,
      bold: true,
      color: COLOR.navy,
      margin: 0,
    });
    s.addText(m.detail, {
      x: 2.2,
      y: y + 0.28,
      w: 7.0,
      h: 0.22,
      fontFace: FONT.body,
      fontSize: 10,
      color: COLOR.muted,
      margin: 0,
    });
  });
}

// ============================================================
// Slide 11 — Roadmap 12 tháng
// ============================================================

{
  const s = newSlide();
  addHeader(s, "Roadmap 12 tháng", "Customer-led roadmap · key bets per quarter");

  // 4-quarter timeline
  const quarters = [
    {
      q: "Q3/2026",
      goal: "First 10 paying customer",
      bets: [
        "5 POC paid (gói Pro)",
        "Eval harness > 85% accuracy",
        "Mobile Capacitor iOS + Android",
      ],
      kpi: "ARR ~600M ₫",
    },
    {
      q: "Q4/2026",
      goal: "Product-market fit signal",
      bets: [
        "First MSA Doanh nghiệp",
        "Real-time presence + collab",
        "Mở rộng QCVN ingest (đầy đủ)",
      ],
      kpi: "ARR ~2 tỷ ₫",
    },
    {
      q: "Q1/2027",
      goal: "Scale + hire core team",
      bets: [
        "Hire VP Sales + 2 AE",
        "SOC 2 Type II audit",
        "Multi-region failover live",
      ],
      kpi: "ARR ~5 tỷ ₫",
    },
    {
      q: "Q2/2027",
      goal: "Series A readiness",
      bets: [
        "30+ paying customer",
        "20% MoM growth sustained",
        "Khám phá thị trường Lào, Campuchia",
      ],
      kpi: "ARR ~12 tỷ ₫",
    },
  ];

  quarters.forEach((q, i) => {
    const x = 0.7 + i * 2.2;
    const y = 1.5;
    s.addShape(pres.shapes.RECTANGLE, {
      x,
      y,
      w: 2.0,
      h: 3.5,
      fill: { color: COLOR.white },
      line: { color: "E2E8F0", width: 1 },
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x,
      y,
      w: 2.0,
      h: 0.45,
      fill: { color: COLOR.navy },
      line: { color: COLOR.navy, width: 0 },
    });
    s.addText(q.q, {
      x,
      y,
      w: 2.0,
      h: 0.45,
      fontFace: FONT.head,
      fontSize: 13,
      bold: true,
      color: COLOR.orange,
      align: "center",
      valign: "middle",
      margin: 0,
    });
    s.addText(q.goal, {
      x: x + 0.15,
      y: y + 0.55,
      w: 1.7,
      h: 0.6,
      fontFace: FONT.body,
      fontSize: 11,
      bold: true,
      color: COLOR.navy,
      margin: 0,
    });
    s.addText(
      q.bets.map((b, j) => ({
        text: b,
        options: {
          bullet: { code: "2022" },
          breakLine: j < q.bets.length - 1,
        },
      })),
      {
        x: x + 0.15,
        y: y + 1.3,
        w: 1.7,
        h: 1.55,
        fontFace: FONT.body,
        fontSize: 9.5,
        color: COLOR.slate,
        paraSpaceAfter: 4,
        margin: 0,
      },
    );
    // KPI footer
    s.addShape(pres.shapes.RECTANGLE, {
      x,
      y: y + 2.95,
      w: 2.0,
      h: 0.55,
      fill: { color: "FFF7ED" },
      line: { color: "FFF7ED", width: 0 },
    });
    s.addText(q.kpi, {
      x,
      y: y + 2.95,
      w: 2.0,
      h: 0.55,
      fontFace: FONT.head,
      fontSize: 12,
      bold: true,
      color: COLOR.orange,
      align: "center",
      valign: "middle",
      margin: 0,
    });
  });

  s.addText(
    "Roadmap có thể thay đổi theo customer feedback. Đây không phải commitment cứng.",
    {
      x: 0.7,
      y: 5.1,
      w: W - 1.4,
      h: 0.25,
      fontFace: FONT.body,
      fontSize: 9,
      italic: true,
      color: COLOR.muted,
      align: "center",
      margin: 0,
    },
  );
}

// ============================================================
// Slide 12 — Team
// ============================================================

{
  const s = newSlide();
  addHeader(s, "Team", "Solo founder + advisor network · hiring sau Series Seed");

  // Founder block
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.7,
    y: 1.4,
    w: W - 1.4,
    h: 1.4,
    fill: { color: COLOR.navy },
    line: { color: COLOR.navy, width: 0 },
  });
  s.addShape(pres.shapes.OVAL, {
    x: 0.95,
    y: 1.65,
    w: 0.95,
    h: 0.95,
    fill: { color: COLOR.orange },
    line: { color: COLOR.orange, width: 0 },
  });
  s.addText("S", {
    x: 0.95,
    y: 1.65,
    w: 0.95,
    h: 0.95,
    fontFace: FONT.head,
    fontSize: 36,
    bold: true,
    color: COLOR.white,
    align: "center",
    valign: "middle",
    margin: 0,
  });
  s.addText("Sophie Nguyễn Thị Thúy", {
    x: 2.1,
    y: 1.55,
    w: 5,
    h: 0.4,
    fontFace: FONT.head,
    fontSize: 20,
    bold: true,
    color: COLOR.white,
    margin: 0,
  });
  s.addText("Founder & CEO · Full-stack engineer", {
    x: 2.1,
    y: 1.95,
    w: 5,
    h: 0.3,
    fontFace: FONT.body,
    fontSize: 12,
    color: COLOR.orange,
    margin: 0,
  });
  s.addText(
    "Built AEC Platform end-to-end (20 module · backend FastAPI + frontend Next.js · ML/AI pipelines · deploy). Trước đó: 5+ năm engineering ở fintech + proptech VN.",
    {
      x: 2.1,
      y: 2.3,
      w: 7.0,
      h: 0.5,
      fontFace: FONT.body,
      fontSize: 10.5,
      color: "CADCFC",
      margin: 0,
    },
  );

  // What we'll hire — Q3 + Q4
  s.addText("Hire plan (sau seed close)", {
    x: 0.7,
    y: 3.05,
    w: 8,
    h: 0.3,
    fontFace: FONT.head,
    fontSize: 14,
    bold: true,
    color: COLOR.navy,
    margin: 0,
  });

  const hires = [
    {
      role: "VP Sales",
      when: "Q3/2026",
      desc: "10+ năm B2B SaaS sales ở VN; chốt 2-3 deal/tháng",
    },
    {
      role: "Senior Full-stack",
      when: "Q3/2026",
      desc: "Mở rộng module + maintain 1.128 test xanh",
    },
    {
      role: "Account Executive ×2",
      when: "Q4/2026",
      desc: "Outbound 200+ email/người/tháng cho 5 ICP archetype",
    },
    {
      role: "Customer Success",
      when: "Q4/2026",
      desc: "Onboarding + đào tạo on-site cho gói Doanh nghiệp",
    },
  ];

  hires.forEach((h, i) => {
    const x = 0.7 + (i % 2) * 4.4;
    const y = 3.5 + Math.floor(i / 2) * 0.85;
    s.addShape(pres.shapes.RECTANGLE, {
      x,
      y,
      w: 4.1,
      h: 0.7,
      fill: { color: COLOR.white },
      line: { color: "E2E8F0", width: 1 },
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x,
      y,
      w: 0.08,
      h: 0.7,
      fill: { color: COLOR.orange },
      line: { color: COLOR.orange, width: 0 },
    });
    s.addText(h.role, {
      x: x + 0.18,
      y: y + 0.05,
      w: 2.6,
      h: 0.3,
      fontFace: FONT.body,
      fontSize: 12,
      bold: true,
      color: COLOR.navy,
      margin: 0,
    });
    s.addText(h.when, {
      x: x + 2.8,
      y: y + 0.05,
      w: 1.2,
      h: 0.3,
      fontFace: FONT.body,
      fontSize: 10,
      bold: true,
      color: COLOR.orange,
      align: "right",
      margin: 0,
    });
    s.addText(h.desc, {
      x: x + 0.18,
      y: y + 0.36,
      w: 3.85,
      h: 0.3,
      fontFace: FONT.body,
      fontSize: 9.5,
      color: COLOR.muted,
      margin: 0,
    });
  });
}

// ============================================================
// Slide 13 — Ask + use of funds
// ============================================================

{
  const s = newSlide();
  addHeader(s, "Tài chính", "Pre-seed: 500.000 USD · runway 18 tháng");

  // Big ask number on left
  s.addText("Đang gọi vốn", {
    x: 0.7,
    y: 1.5,
    w: 4.5,
    h: 0.4,
    fontFace: FONT.body,
    fontSize: 14,
    color: COLOR.muted,
    margin: 0,
  });
  s.addText("$500K USD", {
    x: 0.7,
    y: 1.9,
    w: 4.5,
    h: 1.0,
    fontFace: FONT.head,
    fontSize: 56,
    bold: true,
    color: COLOR.navy,
    margin: 0,
  });
  s.addText("~12 tỷ VNĐ · pre-seed convertible note", {
    x: 0.7,
    y: 2.95,
    w: 4.5,
    h: 0.35,
    fontFace: FONT.body,
    fontSize: 14,
    italic: true,
    color: COLOR.orange,
    margin: 0,
  });
  s.addText("Runway: 18 tháng · Valuation cap: $4M · Discount 20%", {
    x: 0.7,
    y: 3.35,
    w: 4.5,
    h: 0.3,
    fontFace: FONT.body,
    fontSize: 11,
    color: COLOR.slate,
    margin: 0,
  });

  // Use-of-funds pie on right (simplified to bars)
  s.addText("Phân bổ vốn", {
    x: 5.6,
    y: 1.5,
    w: 4,
    h: 0.35,
    fontFace: FONT.head,
    fontSize: 14,
    bold: true,
    color: COLOR.navy,
    margin: 0,
  });
  const allocation = [
    { name: "Sales + Marketing", pct: 40, color: COLOR.orange },
    { name: "Engineering hires", pct: 30, color: COLOR.navy },
    { name: "Infra + AI cost", pct: 15, color: COLOR.slate },
    { name: "Compliance (SOC 2, KTNN)", pct: 10, color: COLOR.emerald },
    { name: "Working capital", pct: 5, color: COLOR.muted },
  ];
  allocation.forEach((a, i) => {
    const y = 2.0 + i * 0.55;
    s.addText(a.name, {
      x: 5.6,
      y,
      w: 2.3,
      h: 0.3,
      fontFace: FONT.body,
      fontSize: 11,
      color: COLOR.navy,
      margin: 0,
    });
    s.addText(`${a.pct}%`, {
      x: W - 1.0,
      y,
      w: 0.5,
      h: 0.3,
      fontFace: FONT.body,
      fontSize: 11,
      bold: true,
      color: COLOR.navy,
      align: "right",
      margin: 0,
    });
    // Bar background
    s.addShape(pres.shapes.RECTANGLE, {
      x: 5.6,
      y: y + 0.3,
      w: 3.9,
      h: 0.12,
      fill: { color: "F1F5F9" },
      line: { color: "F1F5F9", width: 0 },
    });
    // Bar fill
    s.addShape(pres.shapes.RECTANGLE, {
      x: 5.6,
      y: y + 0.3,
      w: 3.9 * (a.pct / 40),
      h: 0.12,
      fill: { color: a.color },
      line: { color: a.color, width: 0 },
    });
  });

  // Bottom: why this round, why now — moved up to clear footer at y=5.225
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.7,
    y: 4.45,
    w: W - 1.4,
    h: 0.65,
    fill: { color: COLOR.navy },
    line: { color: COLOR.navy, width: 0 },
  });
  s.addText(
    [
      { text: "Why this round, why now: ", options: { bold: true, color: COLOR.orange } },
      {
        text: "Platform shipped + production-ready. Cần vốn để chuyển từ engineering-mode sang go-to-market mode. Hire VP Sales + 2 AE + scale outbound 600 email/tháng = 5-8 close/tháng đầu Q4.",
        options: { color: "CADCFC" },
      },
    ],
    {
      x: 0.85,
      y: 4.45,
      w: W - 1.7,
      h: 0.65,
      fontFace: FONT.body,
      fontSize: 11,
      valign: "middle",
      margin: 0,
    },
  );
}

// ============================================================
// Slide 14 — Closing CTA
// ============================================================

{
  const s = newSlide({ dark: true, noFooter: true });

  // Orange left band like cover
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0,
    y: 0,
    w: 0.4,
    h: H,
    fill: { color: COLOR.orange },
    line: { color: COLOR.orange, width: 0 },
  });

  s.addText("Cảm ơn anh/chị đã lắng nghe", {
    x: 1.0,
    y: 1.4,
    w: 8.5,
    h: 0.5,
    fontFace: FONT.body,
    fontSize: 14,
    color: "CADCFC",
    margin: 0,
  });

  s.addText("Bước tiếp theo", {
    x: 1.0,
    y: 1.95,
    w: 8.5,
    h: 0.8,
    fontFace: FONT.head,
    fontSize: 48,
    bold: true,
    color: COLOR.white,
    margin: 0,
  });

  // Three next-step options
  const steps = [
    {
      title: "Đặt lịch deep-dive",
      detail: "60 phút demo + tour code + Q&A kỹ thuật",
    },
    {
      title: "Khám phá platform thật",
      detail: "github.com/sophie-nguyenthuthuy/aec-platform — code public",
    },
    {
      title: "Term sheet conversation",
      detail: "Pre-seed $500K · cap $4M · discount 20%",
    },
  ];

  steps.forEach((step, i) => {
    const y = 3.0 + i * 0.55;
    s.addShape(pres.shapes.OVAL, {
      x: 1.0,
      y: y + 0.05,
      w: 0.3,
      h: 0.3,
      fill: { color: COLOR.orange },
      line: { color: COLOR.orange, width: 0 },
    });
    s.addText(String(i + 1), {
      x: 1.0,
      y: y + 0.05,
      w: 0.3,
      h: 0.3,
      fontFace: FONT.head,
      fontSize: 14,
      bold: true,
      color: COLOR.white,
      align: "center",
      valign: "middle",
      margin: 0,
    });
    s.addText(step.title, {
      x: 1.5,
      y,
      w: 5,
      h: 0.32,
      fontFace: FONT.body,
      fontSize: 14,
      bold: true,
      color: COLOR.white,
      margin: 0,
    });
    s.addText(step.detail, {
      x: 1.5,
      y: y + 0.27,
      w: 7.5,
      h: 0.22,
      fontFace: FONT.body,
      fontSize: 10,
      color: "CADCFC",
      margin: 0,
    });
  });

  // Contact footer — divider aligned with text content (starts at x=1.5
  // where the numbered list text sits, not at x=1.0 under the badges)
  s.addShape(pres.shapes.RECTANGLE, {
    x: 1.5,
    y: H - 1.0,
    w: 7.5,
    h: 0.04,
    fill: { color: COLOR.orange },
    line: { color: COLOR.orange, width: 0 },
  });
  s.addText("Sophie Nguyễn Thị Thúy · Founder & CEO", {
    x: 1.0,
    y: H - 0.85,
    w: 6,
    h: 0.3,
    fontFace: FONT.body,
    fontSize: 12,
    bold: true,
    color: COLOR.white,
    margin: 0,
  });
  s.addText("sophie@aec-platform.vn · +84 ... · github.com/sophie-nguyenthuthuy", {
    x: 1.0,
    y: H - 0.55,
    w: 8.5,
    h: 0.25,
    fontFace: FONT.body,
    fontSize: 10,
    color: COLOR.orange,
    margin: 0,
  });
}

// ---------- Write ----------

pres
  .writeFile({ fileName: __dirname + "/AEC-Platform-Pitch-Deck-VN.pptx" })
  .then((f) => console.log(`Wrote ${f}`));
