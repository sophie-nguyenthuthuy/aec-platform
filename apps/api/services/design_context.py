"""Design Context Generator service.

Builds a Vietnamese architectural design brief through a multi-turn
follow-up question loop, then generates a site context diagram (SVG)
once enough information has been collected.

Wire format (SSE):
  event: token     → {"delta": "..."}        incremental answer text
  event: questions → {"questions": [...]}    follow-up question chips
  event: svg       → {"svg": "..."}          site context SVG diagram
  event: done      → DesignContextDone JSON
  event: error     → {"message": "..."}
"""

from __future__ import annotations

import json
import logging
import os
from typing import AsyncGenerator

from core.config import get_settings  # noqa: F401 — kept for future per-tenant tuning
from schemas.design_context import ChatTurn, DesignContextRequest

logger = logging.getLogger(__name__)

# ---------- System prompt ----------

_SYSTEM_PROMPT = """\
Bạn là kiến trúc sư AI chuyên về kiến trúc Việt Nam. Nhiệm vụ của bạn là:
1. Thu thập thông tin về dự án thông qua các câu hỏi làm rõ (follow-up questions)
2. Khi đã có đủ thông tin, tạo ra bản tóm tắt thiết kế và bản vẽ context (sơ đồ vị trí) dạng SVG

## Bối cảnh kiến trúc Việt Nam
- Khí hậu nhiệt đới gió mùa: nóng ẩm, cần thông gió tự nhiên và che nắng hướng Tây
- Hướng tốt nhất: Nam, Đông Nam (đón gió mát, tránh nắng chiều)
- Quy chuẩn áp dụng: QCVN 03:2012/BXD, QCVN 06:2022/BXD, TCVN 9386:2012
- Loại hình phổ biến: nhà ống (tube house), biệt thự, nhà phố, chung cư, nhà xưởng
- Mật độ xây dựng tuân theo quy hoạch địa phương (thường 60–80% trong khu dân cư)

## Thông tin cần thu thập
Để tạo bản vẽ context hoàn chỉnh, cần biết:
- **Loại công trình**: nhà ở, thương mại, công nghiệp, v.v.
- **Vị trí / địa chỉ**: tỉnh/thành, quận/huyện, đặc điểm khu vực
- **Diện tích lô đất** và kích thước (mặt tiền × chiều sâu)
- **Hướng mặt tiền** (tiếp giáp đường hướng nào)
- **Số tầng** dự kiến
- **Phong cách kiến trúc** mong muốn
- **Ngân sách** (không bắt buộc)

## Quy trình
- Nếu thông tin còn thiếu: trả lời và đề xuất 2–4 câu hỏi làm rõ quan trọng nhất
- Nếu đã đủ thông tin cơ bản (loại công trình + diện tích + hướng): chuyển sang tạo bản vẽ

## Định dạng JSON đầu ra (BẮT BUỘC gọi tool `design_output`)
Luôn gọi tool `design_output` ở cuối mỗi phản hồi để cung cấp dữ liệu có cấu trúc.

## Hướng dẫn tạo SVG bản vẽ context
Khi stage="generating", tạo SVG site context đơn giản (viewBox="0 0 500 500"):
- Nền màu trắng/xám nhạt
- Đường phố/hẻm (màu xám, stroke)
- Lô đất (đường viền đứt, fill màu vàng nhạt)
- Footprint công trình (fill màu cam nhạt)
- Mũi tên hướng Bắc (góc trên phải)
- Nhãn tên đường, kích thước, hướng
- Chú thích tiếng Việt (tên công trình, diện tích, số tầng)
Style: sạch, chuyên nghiệp, kiến trúc kỹ thuật
"""

# ---------- Tool definition ----------

_DESIGN_OUTPUT_TOOL = {
    "name": "design_output",
    "description": (
        "Cung cấp dữ liệu có cấu trúc cho bản vẽ context. "
        "Luôn gọi tool này ở cuối mỗi phản hồi."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "stage": {
                "type": "string",
                "enum": ["gathering", "generating"],
                "description": "'gathering' khi còn đang thu thập thông tin, 'generating' khi đã đủ dữ liệu để tạo bản vẽ",
            },
            "follow_up_questions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "2–4 câu hỏi làm rõ quan trọng nhất (chỉ khi stage=gathering)",
                "maxItems": 4,
            },
            "brief": {
                "type": "object",
                "description": "Tóm tắt thông tin dự án đã thu thập được",
                "properties": {
                    "project_type": {"type": "string"},
                    "location": {"type": "string"},
                    "site_area": {"type": "string"},
                    "site_dimensions": {"type": "string"},
                    "orientation": {"type": "string"},
                    "floors": {"type": "integer"},
                    "style": {"type": "string"},
                    "budget": {"type": "string"},
                    "special_requirements": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
            "svg_diagram": {
                "type": "string",
                "description": "SVG đầy đủ của bản vẽ context (chỉ khi stage=generating)",
            },
        },
        "required": ["stage"],
    },
}

# ---------- SSE helper ----------


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ---------- Stub SVG for no-key dev path ----------

_STUB_SVG = """\
<svg viewBox="0 0 500 500" xmlns="http://www.w3.org/2000/svg" font-family="sans-serif">
  <rect width="500" height="500" fill="#f8f8f8"/>
  <rect x="50" y="200" width="400" height="30" fill="#d0d0d0" rx="2"/>
  <text x="250" y="221" text-anchor="middle" font-size="11" fill="#666">Đường / Street</text>
  <rect x="150" y="80" width="200" height="120" fill="#fef9c3" stroke="#b45309" stroke-width="1.5" stroke-dasharray="6,3"/>
  <text x="250" y="73" text-anchor="middle" font-size="10" fill="#92400e">Lô đất (200 m²)</text>
  <rect x="175" y="100" width="150" height="80" fill="#fed7aa" stroke="#ea580c" stroke-width="1.5" rx="2"/>
  <text x="250" y="145" text-anchor="middle" font-size="11" fill="#9a3412" font-weight="bold">Công trình</text>
  <text x="250" y="160" text-anchor="middle" font-size="10" fill="#9a3412">4 tầng · 120 m²</text>
  <g transform="translate(440,50)">
    <circle cx="0" cy="0" r="18" fill="white" stroke="#334155" stroke-width="1.5"/>
    <polygon points="0,-14 4,6 0,2 -4,6" fill="#1e293b"/>
    <text x="0" y="30" text-anchor="middle" font-size="10" fill="#334155" font-weight="bold">N</text>
  </g>
  <text x="250" y="460" text-anchor="middle" font-size="9" fill="#94a3b8">[Bản vẽ mẫu — đảm bảo OSS LLM (Ollama/vLLM) đang chạy tại LLM_BASE_URL để tạo sơ đồ thực tế]</text>
</svg>"""


# ---------- Main streaming function ----------


async def generate_design_context_stream(
    request: DesignContextRequest,
) -> AsyncGenerator[str, None]:
    """Stream SSE events for one turn of the design-context conversation."""
    messages = _build_messages(request)

    if os.environ.get("AEC_PIPELINE_DEV_STUB") == "1":
        yield _sse("token", {"delta": _stub_answer(request)})
        yield _sse("questions", {"questions": _stub_questions(request)})
        yield _sse("svg", {"svg": _STUB_SVG})
        yield _sse(
            "done",
            {
                "stage": "generating",
                "brief": {
                    "project_type": "Nhà ở",
                    "site_area": "200 m²",
                    "floors": 4,
                    "orientation": "Nam",
                },
                "follow_up_questions": [],
                "svg_diagram": _STUB_SVG,
            },
        )
        return

    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from ml.llm import chat_model  # type: ignore[import-not-found]
    except ImportError:
        yield _sse("error", {"message": "langchain-openai not installed"})
        return

    # Convert Anthropic tool schema → OpenAI tool schema for bind_tools().
    openai_tool = {
        "type": "function",
        "function": {
            "name": _DESIGN_OUTPUT_TOOL["name"],
            "description": _DESIGN_OUTPUT_TOOL["description"],
            "parameters": _DESIGN_OUTPUT_TOOL["input_schema"],
        },
    }

    lc_messages: list = [SystemMessage(content=_SYSTEM_PROMPT)]
    for m in messages:
        # langchain HumanMessage handles 'user' role; treat all turns as user
        # since the OSS LLM gets the assistant context via the system prompt.
        content = m.get("content") if isinstance(m, dict) else None
        if isinstance(content, str):
            lc_messages.append(HumanMessage(content=content))

    llm = chat_model(temperature=0.2, max_tokens=4096).bind_tools([openai_tool])
    tool_input: dict | None = None
    try:
        async for chunk in llm.astream(lc_messages):
            piece = chunk.content if isinstance(chunk.content, str) else ""
            if piece:
                yield _sse("token", {"delta": piece})
            # Tool-call arguments arrive incrementally on `additional_kwargs`
            # once the stream completes the call. We don't ship deltas of the
            # JSON args to the client — they're internal.
            calls = getattr(chunk, "tool_calls", None) or []
            for call in calls:
                if call.get("name") == _DESIGN_OUTPUT_TOOL["name"]:
                    args = call.get("args")
                    if isinstance(args, dict) and args:
                        tool_input = args
    except Exception as exc:
        logger.exception("design_context stream failed")
        yield _sse("error", {"message": f"AI error: {type(exc).__name__}: {exc}"})
        return

    if not tool_input:
        # Model chose not to call the tool — emit empty done.
        yield _sse("done", {"stage": "gathering", "follow_up_questions": [], "brief": None})
        return

    stage = tool_input.get("stage", "gathering")
    questions = tool_input.get("follow_up_questions") or []
    brief = tool_input.get("brief")
    svg = tool_input.get("svg_diagram")

    if questions:
        yield _sse("questions", {"questions": questions})

    if svg:
        yield _sse("svg", {"svg": svg})

    yield _sse(
        "done",
        {
            "stage": stage,
            "follow_up_questions": questions,
            "brief": brief,
            "svg_diagram": None,  # don't repeat the large SVG in done
        },
    )


# ---------- Helpers ----------


def _build_messages(request: DesignContextRequest) -> list[dict]:
    messages: list[dict] = []
    for turn in request.history:
        messages.append({"role": turn.role.value, "content": turn.content})
    messages.append({"role": "user", "content": request.message})
    return messages


def _stub_answer(request: DesignContextRequest) -> str:
    return (
        "Chào bạn! Tôi là kiến trúc sư AI chuyên về thiết kế kiến trúc Việt Nam.\n\n"
        f"Tôi đã nhận được yêu cầu: **{request.message[:120]}**\n\n"
        "Để tạo bản vẽ context chính xác, tôi cần thêm một vài thông tin. "
        "Bạn có thể trả lời các câu hỏi dưới đây:\n\n"
        "*(Đây là phản hồi mẫu — AEC_PIPELINE_DEV_STUB đang bật)*"
    )


def _stub_questions(request: DesignContextRequest) -> list[str]:
    if not request.history:
        return [
            "Diện tích lô đất và kích thước mặt tiền × chiều sâu là bao nhiêu?",
            "Hướng mặt tiền tiếp giáp đường nào (Nam, Đông, Tây, Bắc)?",
            "Số tầng dự kiến là bao nhiêu?",
            "Phong cách kiến trúc mong muốn (hiện đại, tân cổ điển, nhiệt đới...)?",
        ]
    return [
        "Ngân sách dự kiến cho dự án là bao nhiêu?",
        "Có yêu cầu đặc biệt nào về không gian sử dụng không?",
    ]
