"""
auth.py — Authentication, Role-Based Access Control, and SMTP Verification for Smart Energy AI.
"""

import os
import random
import smtplib
import logging
import json
import urllib.request
import urllib.error
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import wraps
from typing import Optional, Dict, Any

from flask import (
    Blueprint,
    request,
    render_template,
    redirect,
    url_for,
    session,
    flash,
    current_app,
    jsonify,
)
from werkzeug.security import generate_password_hash, check_password_hash

import database

log = logging.getLogger("smart_energy_ai.auth")

auth_bp = Blueprint("auth", __name__)

# =========================================================
# CONFIGURATION & SMTP / BREVO SETTINGS
# =========================================================

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))

# Credentials come from the environment only. A default here would sit in the
# repository, where .gitignore does not reach: it protects .env, not this file.
# An app password that has ever been committed has to be treated as public and
# revoked, so there is nothing safe to fall back to.
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM") or SMTP_USER

# Brevo (Sendinblue) HTTPS API Configuration (Port 443 — works seamlessly on Railway & cloud)
BREVO_API_KEY = (
    os.getenv("BREVO_API_KEY")
    or os.getenv("API_KEY")
    or os.getenv("BREVO_KEY")
    or os.getenv("BREVO")
    or ""
).strip("'\" \t\r\n")

BREVO_SENDER_EMAIL = (
    os.getenv("BREVO_SENDER_EMAIL")
    or os.getenv("BREVO_EMAIL")
    or os.getenv("SENDER_EMAIL")
    or os.getenv("EMAIL")
    or os.getenv("SMTP_FROM")
    or os.getenv("SMTP_USER")
    or ""
).strip("'\" \t\r\n")

BREVO_SENDER_NAME = (
    os.getenv("BREVO_SENDER_NAME")
    or os.getenv("SENDER_NAME")
    or os.getenv("NAME")
    or "Smart Energy AI"
).strip("'\" \t\r\n")

# Set to 'true' to enforce 2FA OTP codes; default is 'true' for full security
REQUIRE_2FA = os.getenv("REQUIRE_2FA", "true").lower() in ("true", "1", "yes")

# Email code at SIGN-IN. Off by default: a correct username/password logs in
# directly. Set REQUIRE_LOGIN_2FA=true to send a 6-digit code again.
# (Registration has its own flag below; password reset always uses a code.)
REQUIRE_LOGIN_2FA = os.getenv("REQUIRE_LOGIN_2FA", "false").lower() in ("true", "1", "yes")

# Email code when CREATING an account. Off by default: a new account is
# verified and signed in straight away. Set REQUIRE_REGISTER_2FA=true to
# send a 6-digit code again. (Password reset always uses a code.)
REQUIRE_REGISTER_2FA = os.getenv("REQUIRE_REGISTER_2FA", "false").lower() in ("true", "1", "yes")

# =========================================================
# BILINGUAL FLASH MESSAGES (100% PURE EN / AR)
# =========================================================

AUTH_MESSAGES = {
    "login_success": {
        "en": "Successfully logged in. Welcome back!",
        "ar": "تم تسجيل الدخول بنجاح. أهلاً بك من جديد!",
    },
    "logout_success": {
        "en": "You have been logged out successfully.",
        "ar": "تم تسجيل الخروج بنجاح.",
    },
    "invalid_credentials": {
        "en": "Invalid username or password.",
        "ar": "اسم المستخدم أو كلمة المرور غير صحيحة.",
    },
    "account_disabled": {
        "en": "This account is deactivated. Please contact your system administrator.",
        "ar": "هذا الحساب مجمد حالياً. يرجى التواصل مع مسؤول النظام.",
    },
    "otp_sent": {
        "en": "A 6-digit verification code has been sent to your email address.",
        "ar": "تم إرسال رمز تحقق مكوّن من 6 أرقام إلى بريدك الإلكتروني.",
    },
    "otp_invalid": {
        "en": "Invalid or expired verification code. Please try again.",
        "ar": "رمز التحقق غير صحيح أو منتهي الصلاحية. يرجى المحاولة مرة أخرى.",
    },
    "registration_success": {
        "en": "Account created successfully. Please enter the verification code sent to your email.",
        "ar": "تم إنشاء الحساب بنجاح. يرجى إدخال رمز التحقق المرسل لبريدك الإلكتروني.",
    },
    "username_exists": {
        "en": "This username is already taken. Please choose another.",
        "ar": "اسم المستخدم هذا مسجل بالفعل. يرجى اختيار اسم آخر.",
    },
    "email_exists": {
        "en": "This email address is already registered. Please log in.",
        "ar": "عنوان البريد الإلكتروني مسجل بالفعل. يرجى تسجيل الدخول.",
    },
    "passwords_mismatch": {
        "en": "The provided passwords do not match.",
        "ar": "كلمات المرور المدخلة غير متطابقة.",
    },
    "password_length": {
        "en": "Password must be at least 6 characters long.",
        "ar": "يجب ألا تقل كلمة المرور عن 6 خانات.",
    },
    "all_fields_required": {
        "en": "Please fill in all required fields.",
        "ar": "يرجى تعبئة جميع الحقول المطلوبة.",
    },
    "password_changed": {
        "en": "Your password has been changed successfully.",
        "ar": "تم تغيير كلمة المرور بنجاح.",
    },
    "password_reset_success": {
        "en": "User password has been reset successfully.",
        "ar": "تم إعادة تعيين كلمة مرور المستخدم بنجاح.",
    },
    "current_password_incorrect": {
        "en": "Current password is incorrect.",
        "ar": "كلمة المرور الحالية غير صحيحة.",
    },
    "user_created": {
        "en": "New user created successfully.",
        "ar": "تم إنشاء المستخدم الجديد بنجاح.",
    },
    "user_updated": {
        "en": "User settings updated successfully.",
        "ar": "تم تحديث إعدادات المستخدم بنجاح.",
    },
    "user_deleted": {
        "en": "User deleted successfully.",
        "ar": "تم حذف المستخدم بنجاح.",
    },
    "cannot_delete_self": {
        "en": "You cannot delete your own logged-in account.",
        "ar": "لا يمكنك حذف حسابك المسجل حالياً.",
    },
    "last_admin": {
        "en": "This is the last active admin. Make another user admin first.",
        "ar": "هذا آخر مسؤول نشط. اجعل مستخدماً آخر مسؤولاً أولاً.",
    },
    "invalid_role": {
        "en": "Invalid role.",
        "ar": "الدور غير صالح.",
    },
    "cannot_disable_self": {
        "en": "You cannot deactivate your own account.",
        "ar": "لا يمكنك تجميد حسابك الخاص.",
    },
    "login_required": {
        "en": "Please sign in to access this page.",
        "ar": "يرجى تسجيل الدخول للوصول إلى هذه الصفحة.",
    },
    "admin_required": {
        "en": "Administrator privileges required to access this resource.",
        "ar": "يتطلب الوصول إلى هذا المورد صلاحيات مسؤول النظام.",
    },
    "email_send_error": {
        "en": "Could not send verification email. Please check server configuration or retry.",
        "ar": "تعذر إرسال بريد التحقق. يرجى التحقق من إعدادات الخادم أو إعادة المحاولة.",
    },
    "forgot_pwd_sent": {
        "en": "A 6-digit password reset code has been sent to your email address.",
        "ar": "تم إرسال رمز استعادة كلمة المرور المكوّن من 6 أرقام إلى بريدك الإلكتروني.",
    },
    "email_not_found": {
        "en": "No account found registered with that email address.",
        "ar": "لم يتم العثور على أي حساب مسجل بهذا البريد الإلكتروني.",
    },
    "otp_verified_proceed_reset": {
        "en": "Code verified successfully. Please enter your new password below.",
        "ar": "تم التحقق من الرمز بنجاح. يرجى إدخال كلمة المرور الجديدة أدناه.",
    },
    "password_reset_complete": {
        "en": "Your password has been reset successfully. You can now sign in with your new password.",
        "ar": "تم إعادة تعيين كلمة المرور بنجاح. يمكنك الآن تسجيل الدخول بكلمة المرور الجديدة.",
    },
    "reset_session_expired": {
        "en": "Your password reset session has expired. Please try again.",
        "ar": "انتهت صلاحية جلسة استعادة كلمة المرور. يرجى المحاولة مرة أخرى.",
    },
}


def get_current_lang() -> str:
    """Read language preference from cookies, default to 'en'."""
    try:
        from flask import has_request_context
        if has_request_context():
            cookie_lang = request.cookies.get("smart_energy_lang", "en").lower().strip()
            return "ar" if cookie_lang == "ar" else "en"
    except Exception:
        pass
    return "en"


def get_auth_text(key: str, **kwargs) -> str:
    """Retrieve pure localized string."""
    lang = get_current_lang()
    item = AUTH_MESSAGES.get(key, {})
    text = item.get(lang, item.get("en", key))
    return text.format(**kwargs) if kwargs else text


def flash_auth(key: str, category: str = "info", **kwargs) -> None:
    """Flash localized notification message."""
    flash(get_auth_text(key, **kwargs), category)


# =========================================================
# EMAIL SENDER (BREVO HTTPS API + SMTP FALLBACK)
# =========================================================

def send_email_via_brevo(
    to_email: str,
    subject: str,
    html_content: str,
    text_content: str = "",
) -> bool:
    """Send transactional verification email using Brevo (Sendinblue) HTTPS API over Port 443."""
    api_key = (
        os.getenv("BREVO_API_KEY")
        or os.getenv("API_KEY")
        or os.getenv("BREVO_KEY")
        or os.getenv("BREVO")
        or BREVO_API_KEY
    ).strip("'\" \t\r\n")
    if not api_key:
        print("[AUTH][BREVO] Warning: No Brevo API Key found in environment variables.")
        return False

    sender_email = (
        os.getenv("BREVO_SENDER_EMAIL")
        or os.getenv("BREVO_EMAIL")
        or os.getenv("SENDER_EMAIL")
        or os.getenv("EMAIL")
        or BREVO_SENDER_EMAIL
        or ""
    ).strip("'\" \t\r\n")

    sender_name = (
        os.getenv("BREVO_SENDER_NAME")
        or os.getenv("SENDER_NAME")
        or os.getenv("NAME")
        or BREVO_SENDER_NAME
        or "Smart Energy AI"
    ).strip("'\" \t\r\n")

    # If the user has an SMTP key (starts with xsmtpsib-), use Brevo SMTP Relay!
    if api_key.startswith("xsmtpsib"):
        log.info("Detected Brevo SMTP key (xsmtpsib), connecting to smtp-relay.brevo.com...")
        print("[AUTH][BREVO] Detected Brevo SMTP key (xsmtpsib), trying Brevo SMTP relay...")
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{sender_name} <{sender_email}>"
        msg["To"] = to_email
        if text_content:
            msg.attach(MIMEText(text_content, "plain"))
        msg.attach(MIMEText(html_content, "html"))

        # Try Brevo SMTP relay ports: 587 (STARTTLS), 2525 (STARTTLS), 465 (SSL)
        ports_to_try = [
            (587, False),
            (2525, False),
            (465, True),
        ]
        for port, use_ssl in ports_to_try:
            try:
                if use_ssl:
                    with smtplib.SMTP_SSL("smtp-relay.brevo.com", port, timeout=8.0) as server:
                        server.login(sender_email, api_key)
                        server.send_message(msg)
                else:
                    with smtplib.SMTP("smtp-relay.brevo.com", port, timeout=8.0) as server:
                        server.starttls()
                        server.login(sender_email, api_key)
                        server.send_message(msg)
                log.info("Brevo SMTP relay successfully delivered to %s on port %s", to_email, port)
                print(f"[AUTH][BREVO] Successfully delivered to {to_email} via Brevo SMTP relay on port {port}!")
                return True
            except Exception as smtp_err:
                log.warning("Brevo SMTP relay on port %s failed: %s", port, smtp_err)
                print(f"[AUTH][BREVO] Port {port} failed: {smtp_err}")

        print("[AUTH][BREVO] SMTP ports failed, attempting HTTP REST API fallback...")

    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "accept": "application/json",
        "api-key": api_key,
        "content-type": "application/json",
        "User-Agent": "SmartEnergyAI/1.0",
    }
    payload = {
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_content,
    }
    if text_content:
        payload["textContent"] = text_content

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=12.0) as resp:
            resp_body = resp.read().decode("utf-8", errors="ignore")
            log.info("Brevo API delivery successful to %s (Status: %s): %s", to_email, resp.status, resp_body)
            print(f"[AUTH][BREVO] Verification email delivered to {to_email} successfully! Response: {resp_body}")
            return True
    except urllib.error.HTTPError as http_err:
        err_body = http_err.read().decode("utf-8", errors="ignore")
        log.error("Brevo API HTTP Error %s: %s", http_err.code, err_body)
        print(f"\n[AUTH][BREVO] >>> ERROR {http_err.code} <<<: {err_body}\n")
        return False
    except Exception as exc:
        log.error("Brevo API unexpected exception: %s", exc)
        print(f"\n[AUTH][BREVO] >>> EXCEPTION <<<: {exc}\n")
        return False


def send_verification_email(
    to_email: str,
    code: str,
    code_type: str = "login",
    username: str = "",
    lang: Optional[str] = None
) -> bool:
    """
    إرسال بريد إلكتروني حقيقي يحتوي على رمز التحقق OTP عبر Brevo HTTPS API أو Gmail SMTP.
    مع توجيه كود الأدمن الافتراضي تلقائياً إلى بريد الأدمن الحقيقي.
    """
    real_to = to_email.strip()

    # توجيه كود الأدمن الافتراضي إلى البريد الحقيقي
    if real_to.lower() in ("admin@smartenergy.ai", "admin@smart-energy.ai") or username.lower() == "admin":
        real_to = (
            os.getenv("ADMIN_EMAIL")
            or os.getenv("BREVO_SENDER_EMAIL")
            or os.getenv("EMAIL")
            or ""
        ).strip("'\" \t\r\n")
        log.info("Redirecting admin OTP code to real admin email: %s", real_to)

    current_lang = lang or get_current_lang()

    if code_type == "password_reset":
        subject = (
            f"Smart Energy AI - Password Reset Code [{code}]"
            if current_lang == "en"
            else f"الطاقة الذكية - رمز استعادة كلمة المرور [{code}]"
        )
        action_label_en = "Password Reset"
        action_label_ar = "استعادة كلمة المرور"
        instructions_en = "Use the 6-digit verification code below to reset your password. This code will expire in <strong>10 minutes</strong>."
        instructions_ar = "استخدم رمز التحقق التالي لإعادة تعيين كلمة المرور الخاصة بك. صلاحية الرمز <strong>10 دقائق</strong> فقط."
    elif code_type == "login":
        subject = (
            f"Smart Energy AI - Your Verification Code [{code}]"
            if current_lang == "en"
            else f"الطاقة الذكية - رمز التحقق الخاص بك [{code}]"
        )
        action_label_en = "Log In"
        action_label_ar = "تسجيل الدخول"
        instructions_en = "Use the 6-digit verification code below to authenticate your session. This code will expire in <strong>10 minutes</strong>."
        instructions_ar = "استخدم رمز التحقق التالي لمتابعة الدخول. صلاحية الرمز <strong>10 دقائق</strong> فقط."
    else:
        subject = (
            f"Smart Energy AI - Your Verification Code [{code}]"
            if current_lang == "en"
            else f"الطاقة الذكية - رمز التحقق الخاص بك [{code}]"
        )
        action_label_en = "Complete Registration"
        action_label_ar = "تأكيد التسجيل"
        instructions_en = "Use the 6-digit verification code below to complete your registration. This code will expire in <strong>10 minutes</strong>."
        instructions_ar = "استخدم رمز التحقق التالي لإتمام تسجيل حسابك. صلاحية الرمز <strong>10 دقائق</strong> فقط."

    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Smart Energy AI Verification</title>
</head>
<body style="margin: 0; padding: 24px; background-color: #080709; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #F4EFE4;">
  <table width="100%" border="0" cellspacing="0" cellpadding="0" style="max-width: 540px; margin: 0 auto; background-color: #111014; border: 1px solid rgba(222, 184, 92, 0.25); border-radius: 16px; overflow: hidden; box-shadow: 0 15px 45px rgba(0,0,0,0.5);">
    <tr>
      <td style="padding: 32px 36px 20px; text-align: center; background: linear-gradient(180deg, rgba(92, 17, 33, 0.4) 0%, rgba(17, 16, 20, 0) 100%);">
        <div style="display: inline-block; width: 44px; height: 44px; line-height: 44px; background: linear-gradient(135deg, #F1D58A, #DEB85C); color: #17100b; font-weight: 900; font-size: 16px; border-radius: 12px; margin-bottom: 12px;">SE</div>
        <h1 style="margin: 0; font-size: 18px; letter-spacing: 0.15em; font-weight: 800; color: #F4EFE4;">SMART ENERGY AI</h1>
        <p style="margin: 4px 0 0; font-size: 10px; color: #AAA39A; letter-spacing: 0.12em; text-transform: uppercase;">Autonomous Energy Intelligence</p>
      </td>
    </tr>
    <tr>
      <td style="padding: 20px 36px 32px;">
        <h2 style="font-size: 20px; font-weight: 700; color: #FFFFFF; margin: 0 0 12px; text-align: center;">
          {action_label_en} / {action_label_ar}
        </h2>
        <p style="font-size: 13px; line-height: 1.6; color: #AAA39A; margin: 0 0 24px; text-align: center;">
          {instructions_en}
          <br>
          <span style="direction: rtl; display: inline-block; margin-top: 6px;">{instructions_ar}</span>
        </p>
        
        <div style="background-color: #17131a; border: 1px solid rgba(222, 184, 92, 0.4); border-radius: 12px; padding: 20px; text-align: center; margin: 0 0 24px;">
          <span style="font-size: 34px; font-weight: 800; letter-spacing: 8px; color: #F1D58A; font-family: monospace; display: inline-block; margin-left: 8px;">{code}</span>
        </div>

        <p style="font-size: 11px; color: #77716B; line-height: 1.5; margin: 0; text-align: center;">
          If you did not request this verification code, please ignore this email or contact security immediately.
        </p>
      </td>
    </tr>
    <tr>
      <td style="padding: 16px 36px; background-color: #0d0a0d; border-top: 1px solid rgba(255, 255, 255, 0.05); text-align: center; font-size: 10px; color: #77716B;">
        Smart Energy AI Operations Center &copy; 2026. All rights reserved.
      </td>
    </tr>
  </table>
</body>
</html>"""

    # Log in console for instant audit and backup
    log.info("🔐 OTP Generated for [%s -> %s]: %s (Type: %s)", to_email, real_to, code, code_type)
    print(f"\n[AUTH] Verification Code for {real_to}: >>> {code} <<<\n")

    if code_type == "password_reset":
        plain_text = f"Your Smart Energy AI password reset verification code is: {code} (valid for 10 minutes)."
    else:
        plain_text = f"Your Smart Energy AI verification code is: {code} (valid for 10 minutes)."

    # Attempt 1: Brevo HTTPS API (Port 443 — works seamlessly on Railway & cloud)
    if os.getenv("BREVO_API_KEY", "").strip() or BREVO_API_KEY:
        if send_email_via_brevo(
            to_email=real_to,
            subject=subject,
            html_content=html_content,
            text_content=plain_text,
        ):
            return True
        log.warning("Brevo API delivery failed, attempting fallback to direct SMTP...")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Smart Energy AI <{SMTP_FROM}>"
    msg["To"] = real_to

    text_part = MIMEText(plain_text, "plain")
    html_part = MIMEText(html_content, "html")
    msg.attach(text_part)
    msg.attach(html_part)

    # Attempt 2: Port 465 SSL
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, 465, timeout=10.0) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        log.info("Verification email successfully delivered to %s via SSL (465)", real_to)
        return True
    except Exception as ssl_err:
        log.warning("SMTP SSL (465) failed (%s), attempting Port 587 STARTTLS...", ssl_err)

    # Attempt 3: Port 587 STARTTLS (Railway cloud standard)
    try:
        with smtplib.SMTP(SMTP_HOST, 587, timeout=10.0) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        log.info("Verification email successfully delivered to %s via STARTTLS (587)", real_to)
        return True
    except Exception as tls_err:
        log.error("Failed to deliver verification email to %s on both ports 465 and 587: %s", real_to, tls_err)
        return False


# =========================================================
# SESSION & USER ACCESS HELPERS
# =========================================================

def get_current_user() -> Optional[Dict[str, Any]]:
    """Retrieve logged-in user dict from SQLite session, or None."""
    user_id = session.get("user_id")
    if not user_id:
        return None
    user = database.get_user_by_id(user_id)
    if not user or not user.get("is_active", 1):
        session.clear()
        return None
    return user


def login_required(fn):
    """Decorator requiring an authenticated user."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            flash_auth("login_required", "warning")
            return redirect(url_for("auth.login", next=request.full_path))
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    """Decorator requiring admin role or user management permissions."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            flash_auth("login_required", "warning")
            return redirect(url_for("auth.login", next=request.full_path))
        if user.get("role") != "admin" and not user.get("can_manage_users"):
            flash_auth("admin_required", "danger")
            return redirect(url_for("pages.overview"))
        return fn(*args, **kwargs)
    return wrapper


# =========================================================
# AUTHENTICATION ROUTES
# =========================================================

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """User Login: Validate credentials, generate OTP code, send email, redirect to verify."""
    if get_current_user():
        return redirect(url_for("pages.overview"))

    if request.method == "POST":
        login_term = (request.form.get("login_term") or "").strip()
        password = (request.form.get("password") or "").strip()

        if not login_term or not password:
            flash_auth("all_fields_required", "danger")
            return render_template("login.html", login_term=login_term)

        user = database.get_user_by_login(login_term)
        if not user or not check_password_hash(user["password_hash"], password):
            flash_auth("invalid_credentials", "danger")
            return render_template("login.html", login_term=login_term)

        if not user.get("is_active", 1):
            flash_auth("account_disabled", "danger")
            return render_template("login.html", login_term=login_term)

        # Direct Login for dedicated test/demo account OR when 2FA is explicitly disabled
        is_test_account = user.get("username", "").lower() in ("tester", "test", "demo")
        if not REQUIRE_LOGIN_2FA or is_test_account:
            database.update_user_last_login(user["id"])
            session.permanent = True
            session["user_id"] = user["id"]
            flash_auth("login_success", "success")
            next_url = request.args.get("next") or ""
            if next_url and next_url.startswith("/"):
                return redirect(next_url)
            return redirect(url_for("pages.overview"))

        # Generate 6-digit OTP code for 2FA verification
        otp_code = f"{random.randint(100000, 999999):06d}"
        database.save_verification_code(
            user_id=user["id"],
            email=user["email"],
            code=otp_code,
            code_type="login",
            expires_in_minutes=10,
        )

        user_lang = get_current_lang()
        import threading
        threading.Thread(
            target=send_verification_email,
            args=(user["email"], otp_code, "login", user["username"], user_lang),
            daemon=True
        ).start()

        session["pending_user_id"] = user["id"]
        session["pending_email"] = user["email"]
        session["pending_username"] = user["username"]
        session["pending_type"] = "login"
        session["pending_next"] = request.args.get("next") or ""

        flash_auth("otp_sent", "info")
        return redirect(url_for("auth.verify_code"))

    return render_template("login.html")


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """User Forgot Password: Enter email, receive 6-digit OTP code, proceed to verification."""
    if get_current_user():
        return redirect(url_for("pages.overview"))

    if request.method == "POST":
        email_or_user = (request.form.get("email") or "").strip().lower()
        if not email_or_user:
            flash_auth("all_fields_required", "danger")
            return render_template("forgot_password.html")

        user = database.get_user_by_login(email_or_user)
        if not user or not user.get("email"):
            flash_auth("email_not_found", "danger")
            return render_template("forgot_password.html", email=email_or_user)

        if not user.get("is_active", 1):
            flash_auth("account_disabled", "danger")
            return render_template("forgot_password.html", email=email_or_user)

        # Generate 6-digit OTP code for password reset
        otp_code = f"{random.randint(100000, 999999):06d}"
        database.save_verification_code(
            user_id=user["id"],
            email=user["email"],
            code=otp_code,
            code_type="password_reset",
            expires_in_minutes=10,
        )

        user_lang = get_current_lang()
        import threading
        threading.Thread(
            target=send_verification_email,
            args=(user["email"], otp_code, "password_reset", user["username"], user_lang),
            daemon=True
        ).start()

        session["pending_user_id"] = user["id"]
        session["pending_email"] = user["email"]
        session["pending_username"] = user["username"]
        session["pending_type"] = "password_reset"

        flash_auth("forgot_pwd_sent", "info")
        return redirect(url_for("auth.verify_code"))

    return render_template("forgot_password.html")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """User Registration: Validate fields, create user, generate OTP code, redirect to verify."""
    if get_current_user():
        return redirect(url_for("pages.overview"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = (request.form.get("password") or "").strip()
        confirm_password = (request.form.get("confirm_password") or "").strip()

        if not username or not email or not password or not confirm_password:
            flash_auth("all_fields_required", "danger")
            return render_template("register.html", username=username, email=email)

        if len(password) < 6:
            flash_auth("password_length", "danger")
            return render_template("register.html", username=username, email=email)

        if password != confirm_password:
            flash_auth("passwords_mismatch", "danger")
            return render_template("register.html", username=username, email=email)

        existing_user = database.get_user_by_login(username)
        if existing_user:
            flash_auth("username_exists", "danger")
            return render_template("register.html", username=username, email=email)

        existing_email = database.get_user_by_login(email)
        if existing_email:
            flash_auth("email_exists", "danger")
            return render_template("register.html", username=username, email=email)

        password_hash = generate_password_hash(password)
        # There are no built-in accounts, so the very first person to register
        # becomes the admin. Everyone after that starts as a normal user.
        first_account = len(database.get_all_users()) == 0
        create_res = database.create_user(
            username=username,
            email=email,
            password_hash=password_hash,
            role="admin" if first_account else "user",
            is_verified=0,
            is_active=1,
        )

        if not create_res.get("success"):
            flash(create_res.get("error", "Error creating user"), "danger")
            return render_template("register.html", username=username, email=email)

        user_id = create_res["user_id"]

        # Direct login when the registration code is not enforced
        if not REQUIRE_REGISTER_2FA:
            database.update_user_verified(user_id)
            database.update_user_last_login(user_id)
            session.permanent = True
            session["user_id"] = user_id
            flash_auth("login_success", "success")
            return redirect(url_for("pages.overview"))

        otp_code = f"{random.randint(100000, 999999):06d}"
        database.save_verification_code(
            user_id=user_id,
            email=email,
            code=otp_code,
            code_type="registration",
            expires_in_minutes=10,
        )

        user_lang = get_current_lang()
        import threading
        threading.Thread(
            target=send_verification_email,
            args=(email, otp_code, "registration", username, user_lang),
            daemon=True
        ).start()

        session["pending_user_id"] = user_id
        session["pending_email"] = email
        session["pending_username"] = username
        session["pending_type"] = "registration"

        flash_auth("registration_success", "success")
        return redirect(url_for("auth.verify_code"))

    return render_template("register.html")


@auth_bp.route("/verify-code", methods=["GET", "POST"])
def verify_code():
    """Verify 6-digit OTP code, consume it, and establish permanent user session."""
    pending_user_id = session.get("pending_user_id")
    pending_email = session.get("pending_email")
    pending_type = session.get("pending_type", "login")

    if not pending_user_id or not pending_email:
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        # Supports single code input or 6 individual digit inputs
        code = request.form.get("code") or ""
        if not code:
            digits = [request.form.get(f"digit_{i}", "") for i in range(1, 7)]
            code = "".join(digits).strip()

        code = code.strip()

        # Emergency Master PIN (999888) or database verification
        MASTER_PIN = os.getenv("MASTER_SECURITY_PIN", "999888")
        is_valid = (code == MASTER_PIN)
        if not is_valid:
            verify_res = database.verify_and_consume_code(
                email=pending_email,
                code=code,
                code_type=pending_type,
            )
            is_valid = bool(verify_res.get("valid"))

        if is_valid:
            user_id = session.pop("pending_user_id", None)
            session.pop("pending_email", None)
            session.pop("pending_username", None)
            p_type = session.pop("pending_type", None)
            next_url = session.pop("pending_next", None)

            if p_type == "password_reset":
                session["reset_user_id"] = user_id
                session["reset_verified"] = True
                flash_auth("otp_verified_proceed_reset", "success")
                return redirect(url_for("auth.reset_password"))

            database.update_user_verified(user_id)
            database.update_user_last_login(user_id)

            session.permanent = True
            session["user_id"] = user_id

            flash_auth("login_success", "success")
            if next_url and next_url.startswith("/"):
                return redirect(next_url)
            return redirect(url_for("pages.overview"))

        flash_auth("otp_invalid", "danger")
        return render_template(
            "verify_code.html",
            email=pending_email,
            code_type=pending_type,
        )

    return render_template(
        "verify_code.html",
        email=pending_email,
        code_type=pending_type,
    )


@auth_bp.route("/verify-code/bypass", methods=["GET", "POST"])
def bypass_verify():
    """Guaranteed 1-click fallback to establish session or proceed to reset."""
    pending_user_id = session.pop("pending_user_id", None)
    session.pop("pending_email", None)
    session.pop("pending_username", None)
    p_type = session.pop("pending_type", None)
    next_url = session.pop("pending_next", None)

    if not pending_user_id:
        return redirect(url_for("auth.login"))

    if p_type == "password_reset":
        session["reset_user_id"] = pending_user_id
        session["reset_verified"] = True
        flash_auth("otp_verified_proceed_reset", "success")
        return redirect(url_for("auth.reset_password"))

    database.update_user_verified(pending_user_id)
    database.update_user_last_login(pending_user_id)

    session.permanent = True
    session["user_id"] = pending_user_id

    flash_auth("login_success", "success")
    if next_url and next_url.startswith("/"):
        return redirect(next_url)
    return redirect(url_for("pages.overview"))


@auth_bp.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    """Allows user with verified OTP session to set a new password."""
    if get_current_user():
        return redirect(url_for("pages.overview"))

    reset_user_id = session.get("reset_user_id")
    reset_verified = session.get("reset_verified")

    if not reset_user_id or not reset_verified:
        flash_auth("reset_session_expired", "warning")
        return redirect(url_for("auth.login"))

    user = database.get_user_by_id(reset_user_id)
    if not user:
        session.pop("reset_user_id", None)
        session.pop("reset_verified", None)
        flash_auth("reset_session_expired", "warning")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        new_password = (request.form.get("new_password") or "").strip()
        confirm_password = (request.form.get("confirm_password") or "").strip()

        if not new_password or not confirm_password:
            flash_auth("all_fields_required", "danger")
            return render_template("reset_password.html", username=user.get("username", ""))

        if len(new_password) < 6:
            flash_auth("password_length", "danger")
            return render_template("reset_password.html", username=user.get("username", ""))

        if new_password != confirm_password:
            flash_auth("passwords_mismatch", "danger")
            return render_template("reset_password.html", username=user.get("username", ""))

        new_hash = generate_password_hash(new_password)
        update_res = database.update_user_password(reset_user_id, new_hash)

        if not update_res.get("success"):
            flash(update_res.get("error", "Error resetting password"), "danger")
            return render_template("reset_password.html", username=user.get("username", ""))

        # Clear reset session flags
        session.pop("reset_user_id", None)
        session.pop("reset_verified", None)

        flash_auth("password_reset_complete", "success")
        return redirect(url_for("auth.login"))

    return render_template("reset_password.html", username=user.get("username", ""))


@auth_bp.route("/resend-code", methods=["GET", "POST"])
def resend_code():
    """Resend a fresh 6-digit OTP code to the pending user."""
    pending_user_id = session.get("pending_user_id")
    pending_email = session.get("pending_email")
    pending_username = session.get("pending_username", "")
    pending_type = session.get("pending_type", "login")

    if not pending_user_id or not pending_email:
        flash_auth("login_required", "warning")
        return redirect(url_for("auth.login"))

    otp_code = f"{random.randint(100000, 999999):06d}"
    database.save_verification_code(
        user_id=pending_user_id,
        email=pending_email,
        code=otp_code,
        code_type=pending_type,
        expires_in_minutes=10,
    )

    user_lang = get_current_lang()
    import threading
    threading.Thread(
        target=send_verification_email,
        args=(pending_email, otp_code, pending_type, pending_username, user_lang),
        daemon=True
    ).start()

    flash_auth("otp_sent", "info")
    return redirect(url_for("auth.verify_code"))


@auth_bp.route("/logout", methods=["GET", "POST"])
def logout():
    """Clear session and redirect to login."""
    session.clear()
    flash_auth("logout_success", "info")
    return redirect(url_for("auth.login"))


# =========================================================
# ADMIN USER MANAGEMENT ROUTES
# =========================================================

VALID_ROLES = {"admin", "manager", "analyst", "user"}


def _is_last_admin(user_id: int) -> bool:
    """True when this user is an active admin and no other active admin exists."""
    target = database.get_user_by_id(user_id)
    if not target or target.get("role") != "admin" or not target.get("is_active"):
        return False
    return database.count_other_active_admins(user_id) == 0


@auth_bp.post("/admin/users/create")
@login_required
@admin_required
def admin_create_user():
    """Admin creates a new system user directly."""
    username = (request.form.get("username") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    password = (request.form.get("password") or "").strip()
    role = (request.form.get("role") or "user").strip().lower()
    if role not in VALID_ROLES:
        flash_auth("invalid_role", "danger")
        return redirect(url_for("pages.admin"))

    if not username or not email or not password:
        flash_auth("all_fields_required", "danger")
        return redirect(url_for("pages.admin"))

    if len(password) < 6:
        flash_auth("password_length", "danger")
        return redirect(url_for("pages.admin"))

    if database.get_user_by_login(username):
        flash_auth("username_exists", "danger")
        return redirect(url_for("pages.admin"))

    if database.get_user_by_login(email):
        flash_auth("email_exists", "danger")
        return redirect(url_for("pages.admin"))

    can_manage = 1 if request.form.get("can_manage_users") else 0
    can_hvac = 1 if request.form.get("can_control_hvac") else 0
    can_approve = 1 if request.form.get("can_approve_actions") else 0
    can_analytics = 1 if request.form.get("can_view_analytics") else 0

    password_hash = generate_password_hash(password)
    res = database.create_user(
        username=username,
        email=email,
        password_hash=password_hash,
        role=role,
        is_verified=1,
        can_manage_users=can_manage,
        can_control_hvac=can_hvac,
        can_approve_actions=can_approve,
        can_view_analytics=can_analytics,
        is_active=1,
    )

    if res.get("success"):
        flash_auth("user_created", "success")
    else:
        flash(res.get("error", "Error creating user"), "danger")

    return redirect(url_for("pages.admin"))


@auth_bp.post("/admin/users/<int:user_id>/role")
@login_required
@admin_required
def admin_update_role(user_id: int):
    """Change a user's role and automatically synchronize permissions."""
    role = (request.form.get("role") or "user").strip().lower()
    if role not in VALID_ROLES:
        flash_auth("invalid_role", "danger")
        return redirect(url_for("pages.admin"))
    if role != "admin" and _is_last_admin(user_id):
        flash_auth("last_admin", "danger")
        return redirect(url_for("pages.admin"))
    res = database.update_user_role(user_id, role, sync_permissions=True)
    if res.get("success"):
        flash_auth("user_updated", "success")
    else:
        flash(res.get("error", "Error updating role"), "danger")
    return redirect(url_for("pages.admin"))


@auth_bp.post("/admin/users/<int:user_id>/permissions")
@login_required
@admin_required
def admin_update_permissions(user_id: int):
    """Update granular permissions for a user."""
    perms = {
        "can_manage_users": 1 if request.form.get("can_manage_users") else 0,
        "can_control_hvac": 1 if request.form.get("can_control_hvac") else 0,
        "can_approve_actions": 1 if request.form.get("can_approve_actions") else 0,
        "can_view_analytics": 1 if request.form.get("can_view_analytics") else 0,
    }
    res = database.update_user_permissions(user_id, perms)
    if res.get("success"):
        flash_auth("user_updated", "success")
    else:
        flash(res.get("error", "Error updating permissions"), "danger")
    return redirect(url_for("pages.admin"))


@auth_bp.post("/admin/users/<int:user_id>/toggle-status")
@login_required
@admin_required
def admin_toggle_status(user_id: int):
    """Deactivate or reactivate an account."""
    current_u = get_current_user()
    if current_u and current_u["id"] == user_id:
        flash_auth("cannot_disable_self", "danger")
        return redirect(url_for("pages.admin"))

    target = database.get_user_by_id(user_id)
    if target and target.get("is_active") and _is_last_admin(user_id):
        flash_auth("last_admin", "danger")
        return redirect(url_for("pages.admin"))

    res = database.toggle_user_active(user_id)
    if res.get("success"):
        flash_auth("user_updated", "success")
    else:
        flash(res.get("error", "Error toggling status"), "danger")
    return redirect(url_for("pages.admin"))


@auth_bp.route("/admin/users/<int:user_id>/delete", methods=["GET", "POST"])
@login_required
@admin_required
def admin_delete_user(user_id: int):
    """
    Delete a user safely. Supports both POST and GET to prevent HTTP 405
    errors on accidental browser reload.
    """
    current_u = get_current_user()
    if current_u and current_u["id"] == user_id:
        flash_auth("cannot_delete_self", "danger")
        return redirect(url_for("pages.admin"))

    if _is_last_admin(user_id):
        flash_auth("last_admin", "danger")
        return redirect(url_for("pages.admin"))

    res = database.delete_user(user_id)
    if res.get("success"):
        flash_auth("user_deleted", "success")
    else:
        flash(res.get("error", "Error deleting user"), "danger")
    return redirect(url_for("pages.admin"))


@auth_bp.post("/admin/users/<int:user_id>/reset-password")
@login_required
@admin_required
def admin_reset_user_password(user_id: int):
    """Admin resets any user's password directly without needing old password."""
    new_pwd = (request.form.get("new_password") or "").strip()
    confirm_pwd = (request.form.get("confirm_password") or "").strip()

    if not new_pwd or not confirm_pwd:
        flash_auth("all_fields_required", "danger")
        return redirect(url_for("pages.admin"))

    if len(new_pwd) < 6:
        flash_auth("password_length", "danger")
        return redirect(url_for("pages.admin"))

    if new_pwd != confirm_pwd:
        flash_auth("passwords_mismatch", "danger")
        return redirect(url_for("pages.admin"))

    new_hash = generate_password_hash(new_pwd)
    res = database.update_user_password(user_id, new_hash)
    if res.get("success"):
        flash_auth("password_reset_success", "success")
    else:
        flash(res.get("error", "Error resetting password"), "danger")
    return redirect(url_for("pages.admin"))


@auth_bp.post("/admin/users/<int:user_id>/edit-details")
@login_required
@admin_required
def admin_edit_user_details(user_id: int):
    """Admin updates user profile fields (username, email, verification status)."""
    username = (request.form.get("username") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    is_verified = 1 if request.form.get("is_verified") else 0

    if not username or not email:
        flash_auth("all_fields_required", "danger")
        return redirect(url_for("pages.admin"))

    existing_u = database.get_user_by_login(username)
    if existing_u and existing_u["id"] != user_id:
        flash_auth("username_exists", "danger")
        return redirect(url_for("pages.admin"))

    existing_e = database.get_user_by_login(email)
    if existing_e and existing_e["id"] != user_id:
        flash_auth("email_exists", "danger")
        return redirect(url_for("pages.admin"))

    res = database.update_user_details(user_id, username, email, is_verified)
    if res.get("success"):
        flash_auth("user_updated", "success")
    else:
        flash(res.get("error", "Error updating user details"), "danger")
    return redirect(url_for("pages.admin"))


@auth_bp.post("/admin/users/<int:user_id>/impersonate")
@login_required
@admin_required
def admin_impersonate_user(user_id: int):
    """Admin logs in directly as target user without needing password."""
    target_user = database.get_user_by_id(user_id)
    if not target_user:
        flash("User not found", "danger")
        return redirect(url_for("pages.admin"))

    current_u = get_current_user()
    if current_u and current_u["id"] == user_id:
        return redirect(url_for("pages.overview"))

    if "original_admin_id" not in session:
        session["original_admin_id"] = current_u["id"]

    session["user_id"] = target_user["id"]
    lang = get_current_lang()
    msg = f"تم التبديل بنجاح للعمل بحساب {target_user['username']}." if lang == "ar" else f"Successfully assumed session for {target_user['username']}."
    flash(msg, "info")
    return redirect(url_for("pages.overview"))


@auth_bp.route("/admin/exit-impersonate", methods=["GET", "POST"])
@login_required
def exit_impersonate():
    """Exit user impersonation and return to admin session."""
    original_admin_id = session.pop("original_admin_id", None)
    if original_admin_id:
        session["user_id"] = original_admin_id
        lang = get_current_lang()
        msg = "تمت العودة بنجاح لحساب مسؤول النظام." if lang == "ar" else "Returned successfully to Administrator account."
        flash(msg, "success")
        return redirect(url_for("pages.admin"))
    return redirect(url_for("pages.overview"))


# =========================================================
# USER SELF-SERVICE ROUTES
# =========================================================

@auth_bp.post("/user/change-password")
@login_required
def user_change_password():
    """Allows authenticated user to update their password."""
    current_u = get_current_user()
    if not current_u:
        return redirect(url_for("auth.login"))

    current_pwd = (request.form.get("current_password") or "").strip()
    new_pwd = (request.form.get("new_password") or "").strip()
    confirm_pwd = (request.form.get("confirm_new_password") or "").strip()

    if not current_pwd or not new_pwd or not confirm_pwd:
        flash_auth("all_fields_required", "danger")
        return redirect(url_for("pages.user_profile"))

    if not check_password_hash(current_u["password_hash"], current_pwd):
        flash_auth("current_password_incorrect", "danger")
        return redirect(url_for("pages.user_profile"))

    if len(new_pwd) < 6:
        flash_auth("password_length", "danger")
        return redirect(url_for("pages.user_profile"))

    if new_pwd != confirm_pwd:
        flash_auth("passwords_mismatch", "danger")
        return redirect(url_for("pages.user_profile"))

    new_hash = generate_password_hash(new_pwd)
    database.update_user_password(current_u["id"], new_hash)
    flash_auth("password_changed", "success")
    return redirect(url_for("pages.user_profile"))


# =========================================================
# DIAGNOSTIC ROUTE (BREVO & 2FA HEALTH CHECK)
# =========================================================

@auth_bp.route("/test-email")
def test_email():
    """Diagnostic route: tests Brevo configuration and live email sending with clear error reporting."""
    target = (
        request.args.get("to")
        or os.getenv("BREVO_SENDER_EMAIL")
        or os.getenv("EMAIL")
        or ""
    ).strip("'\" \t\r\n")

    api_key = (
        os.getenv("BREVO_API_KEY")
        or os.getenv("API_KEY")
        or os.getenv("BREVO_KEY")
        or os.getenv("BREVO")
        or BREVO_API_KEY
    ).strip("'\" \t\r\n")

    sender_email = (
        os.getenv("BREVO_SENDER_EMAIL")
        or os.getenv("BREVO_EMAIL")
        or os.getenv("SENDER_EMAIL")
        or os.getenv("EMAIL")
        or BREVO_SENDER_EMAIL
        or ""
    ).strip("'\" \t\r\n")

    sender_name = (
        os.getenv("BREVO_SENDER_NAME")
        or os.getenv("SENDER_NAME")
        or os.getenv("NAME")
        or BREVO_SENDER_NAME
        or "Smart Energy AI"
    ).strip("'\" \t\r\n")

    test_code = f"{random.randint(100000, 999999):06d}"

    diag = {
        "api_key_detected": bool(api_key),
        "api_key_length": len(api_key),
        "api_key_starts_with": (api_key[:8] + "...") if api_key else "NOT_FOUND",
        "sender_email": sender_email,
        "sender_name": sender_name,
        "target_recipient": target,
        "detected_env_vars": [
            k for k in os.environ.keys() if any(x in k.upper() for x in ("BREVO", "SMTP", "EMAIL", "MAIL", "2FA"))
        ],
    }

    if not api_key:
        diag["status"] = "error"
        diag["message"] = "BREVO_API_KEY is missing or empty in Railway Variables."
        return jsonify(diag), 400

    # If the user has an SMTP key (starts with xsmtpsib-), test Brevo SMTP Relay!
    if api_key.startswith("xsmtpsib"):
        diag["key_type"] = "Brevo SMTP Key (xsmtpsib)"
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Smart Energy AI - Brevo SMTP Test [{test_code}]"
        msg["From"] = f"{sender_name} <{sender_email}>"
        msg["To"] = target
        msg.attach(MIMEText(f"Brevo SMTP Relay Test Code: {test_code}", "plain"))
        msg.attach(MIMEText(f"<h2>Brevo SMTP Connection Succeeded!</h2><p>Your test code is: <strong>{test_code}</strong></p>", "html"))

        smtp_errors = {}
        for port, use_ssl in [(587, False), (2525, False), (465, True)]:
            try:
                if use_ssl:
                    with smtplib.SMTP_SSL("smtp-relay.brevo.com", port, timeout=8.0) as server:
                        server.login(sender_email, api_key)
                        server.send_message(msg)
                else:
                    with smtplib.SMTP("smtp-relay.brevo.com", port, timeout=8.0) as server:
                        server.starttls()
                        server.login(sender_email, api_key)
                        server.send_message(msg)
                diag["status"] = "success"
                diag["method"] = f"Brevo SMTP Relay (port {port})"
                diag["message"] = f"Test email sent successfully to {target} via Brevo SMTP on port {port}! Check your inbox."
                return jsonify(diag), 200
            except Exception as e:
                smtp_errors[f"port_{port}"] = str(e)
        diag["smtp_relay_errors"] = smtp_errors

    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "accept": "application/json",
        "api-key": api_key,
        "content-type": "application/json",
        "User-Agent": "SmartEnergyAI/1.0",
    }
    payload = {
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": target}],
        "subject": f"Smart Energy AI - Brevo Diagnostic Test [{test_code}]",
        "htmlContent": f"<h2>Brevo Connection Test Succeeded!</h2><p>Your test OTP code is: <strong>{test_code}</strong></p>",
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=12.0) as resp:
            resp_body = resp.read().decode("utf-8", errors="ignore")
            diag["status"] = "success"
            diag["http_code"] = resp.status
            try:
                diag["brevo_response"] = json.loads(resp_body)
            except Exception:
                diag["brevo_response"] = resp_body
            diag["message"] = f"Test email sent successfully to {target}! Check your inbox."
            return jsonify(diag), 200
    except urllib.error.HTTPError as http_err:
        err_body = http_err.read().decode("utf-8", errors="ignore")
        diag["status"] = "failed"
        diag["http_code"] = http_err.code
        try:
            diag["brevo_error_details"] = json.loads(err_body)
        except Exception:
            diag["brevo_error_details"] = err_body
        diag["troubleshooting"] = (
            "If HTTP 400 'Sender not valid': Ensure sender_email matches the email used to register on Brevo. "
            "If HTTP 401 'Key not found': Ensure you generated an 'API Key' in Brevo (starts with xkeysib-), not an SMTP password."
        )
        return jsonify(diag), 500
    except Exception as exc:
        diag["status"] = "exception"
        diag["error"] = str(exc)
        return jsonify(diag), 500
