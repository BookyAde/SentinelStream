"""
SentinelStream Email Service
Sends verification codes and notifications via Resend.
"""

import os
import secrets
import resend
from app.core.logging import get_logger

logger = get_logger(__name__)

resend.api_key = os.environ.get("RESEND_API_KEY", "")
FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL", "onboarding@resend.dev")
APP_NAME   = "SentinelStream"


def generate_verification_code() -> str:
    """Generate a 6-digit numeric verification code."""
    return str(secrets.randbelow(900000) + 100000)


async def send_verification_email(to_email: str, full_name: str, code: str) -> bool:
    """Send email verification code. Returns True on success."""
    if not resend.api_key:
        logger.warning("RESEND_API_KEY not set — skipping email, code: " + code)
        return True  # Don't block registration if email not configured

    html = f"""
    <div style="font-family: 'Courier New', monospace; background: #020508; color: #b0c8e8; padding: 40px; max-width: 480px; margin: 0 auto; border: 1px solid #0f2540; border-radius: 4px;">
      <div style="font-size: 20px; font-weight: 800; letter-spacing: 4px; text-transform: uppercase; color: white; margin-bottom: 4px;">
        SENTINEL<span style="color: #00f0ff;">STREAM</span>
      </div>
      <div style="font-size: 10px; color: #4a6a8a; letter-spacing: 2px; text-transform: uppercase; margin-bottom: 32px;">
        Real-time event pipeline
      </div>
      <div style="font-size: 14px; color: #b0c8e8; margin-bottom: 24px;">
        Hi {full_name},<br><br>
        Your verification code is:
      </div>
      <div style="font-size: 40px; font-weight: 800; letter-spacing: 12px; color: #00f0ff; background: #091422; border: 1px solid #163450; padding: 20px; text-align: center; border-radius: 2px; margin-bottom: 24px;">
        {code}
      </div>
      <div style="font-size: 12px; color: #4a6a8a;">
        This code expires in <strong style="color: #ffaa00;">15 minutes</strong>.<br>
        If you didn't create a SentinelStream account, ignore this email.
      </div>
    </div>
    """

    try:
        resend.Emails.send({
            "from":    FROM_EMAIL,
            "to":      [to_email],
            "subject": f"[{APP_NAME}] Your verification code: {code}",
            "html":    html,
        })
        logger.info(f"Verification email sent to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send verification email: {e}")
        return False


async def send_welcome_email(to_email: str, full_name: str, workspace_slug: str) -> None:
    """Send welcome email after successful verification."""
    if not resend.api_key:
        return

    html = f"""
    <div style="font-family: 'Courier New', monospace; background: #020508; color: #b0c8e8; padding: 40px; max-width: 480px; margin: 0 auto; border: 1px solid #0f2540; border-radius: 4px;">
      <div style="font-size: 20px; font-weight: 800; letter-spacing: 4px; text-transform: uppercase; color: white; margin-bottom: 4px;">
        SENTINEL<span style="color: #00f0ff;">STREAM</span>
      </div>
      <div style="font-size: 10px; color: #4a6a8a; letter-spacing: 2px; text-transform: uppercase; margin-bottom: 32px;">
        Welcome aboard
      </div>
      <div style="font-size: 14px; color: #b0c8e8; margin-bottom: 24px;">
        Hi {full_name} — your account is verified and ready.<br><br>
        Your workspace <strong style="color: #00f0ff;">{workspace_slug}</strong> is live.
        Start sending events using the <strong>X-API-Key</strong> header.
      </div>
      <div style="font-size: 12px; color: #4a6a8a; border-top: 1px solid #0f2540; padding-top: 16px;">
        Need help? Reply to this email anytime.
      </div>
    </div>
    """

    try:
        resend.Emails.send({
            "from":    FROM_EMAIL,
            "to":      [to_email],
            "subject": f"Welcome to {APP_NAME} — {workspace_slug} is ready",
            "html":    html,
        })
    except Exception as e:
        logger.error(f"Failed to send welcome email: {e}")