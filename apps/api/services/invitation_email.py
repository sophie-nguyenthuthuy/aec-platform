"""Send the invitation accept-link to the invitee.

Best-effort: if SMTP isn't configured the create-invitation endpoint
still returns the accept_url and the admin shares it manually. The
email here is a UX nicety for once SMTP is wired up.

Templates are inlined — Vietnamese first (the platform's primary
audience) with an English fallback. Once we have proper i18n on the
api side this moves to a Jinja template.
"""

from __future__ import annotations

import logging

from services.mailer import Delivery, send_mail

logger = logging.getLogger(__name__)


async def send_invitation_email(
    *,
    to: str,
    organization_name: str,
    role: str,
    accept_url: str,
    invited_by_name: str | None,
) -> Delivery:
    """Send the invitation email. Returns the mailer Delivery record so
    the caller can decide whether to surface "email sent" or "copy the
    link" to the admin.
    """
    inviter_phrase = invited_by_name or "Quản trị viên"
    subject = f"[AEC Platform] {inviter_phrase} mời bạn tham gia {organization_name}"

    text_body = (
        f"Chào bạn,\n\n"
        f'{inviter_phrase} đã mời bạn tham gia tổ chức "{organization_name}" '
        f"trên AEC Platform với vai trò {role}.\n\n"
        f"Mở liên kết sau, đặt mật khẩu, và bạn có thể bắt đầu sử dụng ngay:\n\n"
        f"  {accept_url}\n\n"
        f"Liên kết này dùng được một lần và sẽ hết hạn sau 7 ngày.\n\n"
        f"Nếu bạn không yêu cầu lời mời này, bỏ qua email này một cách an toàn.\n\n"
        f"— AEC Platform"
    )

    html_body = f"""<!DOCTYPE html>
<html lang="vi">
<head><meta charset="utf-8"><title>{subject}</title></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 560px; margin: 24px auto; color: #1e293b;">
  <h1 style="font-size: 18px; color: #0f172a;">Lời mời tham gia {organization_name}</h1>
  <p>Chào bạn,</p>
  <p>
    <strong>{inviter_phrase}</strong> đã mời bạn tham gia tổ chức
    <strong>{organization_name}</strong> trên AEC Platform với vai trò
    <strong>{role}</strong>.
  </p>
  <p style="margin: 24px 0;">
    <a href="{accept_url}"
       style="display: inline-block; padding: 10px 18px; background: #0f172a; color: white; text-decoration: none; border-radius: 6px; font-weight: 600;">
      Chấp nhận lời mời
    </a>
  </p>
  <p style="font-size: 13px; color: #475569;">
    Hoặc dán liên kết này vào trình duyệt:<br>
    <code style="font-size: 12px; color: #334155;">{accept_url}</code>
  </p>
  <p style="font-size: 12px; color: #64748b; margin-top: 32px;">
    Liên kết dùng được một lần và hết hạn sau 7 ngày. Nếu bạn không yêu cầu
    lời mời này, bỏ qua email một cách an toàn.
  </p>
</body>
</html>"""

    return await send_mail(to=to, subject=subject, text_body=text_body, html_body=html_body)
