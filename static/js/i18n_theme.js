/**
 * i18n_theme.js — Pure bilingual (English / Arabic) engine and Light / Dark theme system for Smart Energy AI.
 * 
 * Features:
 *  1. Zero Flash (synchronous execution on parse).
 *  2. 100% Pure language separation (No mixed brackets or hybrid words).
 *  3. Full RTL support for Arabic, LTR for English.
 *  4. Syncs with localStorage and cookie 'smart_energy_lang' for server flashes.
 */

// =========================================================
// 1. IMMEDIATE SYNCHRONOUS RUNNER (ZERO FLASH)
// =========================================================
(function initThemeAndLanguage() {
  try {
    // Theme setup
    const savedTheme = localStorage.getItem("smart_energy_theme") || "dark";
    document.documentElement.setAttribute("data-theme", savedTheme);
    // Colour theme (palette). "luxury" is the original look: no attribute.
    const savedPalette = localStorage.getItem("smart_energy_palette") || "luxury";
    if (savedPalette !== "luxury") document.documentElement.setAttribute("data-palette", savedPalette);

    // Language setup: localStorage or cookie or browser default
    let savedLang = localStorage.getItem("smart_energy_lang");
    if (!savedLang) {
      const match = document.cookie.match(/(?:^|; )smart_energy_lang=([^;]*)/);
      savedLang = match ? decodeURIComponent(match[1]) : "en";
    }
    savedLang = (savedLang === "ar") ? "ar" : "en";

    document.documentElement.setAttribute("lang", savedLang);
    document.documentElement.setAttribute("dir", savedLang === "ar" ? "rtl" : "ltr");
  } catch (e) {
    console.error("Init theme/lang error:", e);
  }
})();


// =========================================================
// 2. COMPLETE BILINGUAL DICTIONARY
// =========================================================
const I18N = {
  en: {
    // Brand & Topbar
    "brand_title": "SMART ENERGY",
    "brand_sub": "AUTONOMOUS OPERATIONS",
    "eyebrow_center": "ENERGY OPERATIONS CENTER",
    "building_label": "BUILDING",
    "campus_option": "Campus",
    "b001_option": "B001 · Administration",
    "b002_option": "B002 · Labs",
    "b003_option": "B003 · Classrooms",
    "theme_toggle_tip": "Switch Theme",
    "lang_toggle_tip": "Switch to Arabic",
    "lang_btn_text": "العربية",
    "system_ready": "System ready",
    "sim_badge": "SIMULATED EXECUTION",
    "footer_sub": "Autonomous operations · Digital Twin · Human approval",

    // Navigation Sections
    "nav_sec_ops": "OPERATIONS CENTER",
    "nav_overview": "Overview",
    "nav_energy": "Energy Monitor",
    "nav_operations": "AI Operations",
    "nav_digital_twin": "Digital Twin",
    "nav_verification": "Verification",
    "nav_sec_history": "HISTORICAL REPOSITORY",
    "nav_history": "Historical Data",
    "nav_sec_intel": "INTELLIGENCE",
    "nav_knowledge": "AI Knowledge",
    "nav_activity": "Activity Log",
    "nav_sec_account": "ACCOUNT & ACCESS",
    "nav_admin": "Admin Panel",
    "nav_profile": "My Profile",
    "nav_logout": "Sign Out",
    "nav_login": "Sign In",
    "nav_read_only": "READ ONLY",
    "nav_live": "LIVE",

    // Agent Sidebar Card
    "agent_title": "Autonomous Energy Agent",
    "agent_mode": "SIMULATION MODE · HUMAN APPROVAL",

    // Auth & Login
    "auth_signin_title": "Sign In",
    "auth_signin_sub": "Enter your credentials to access the Operations Center",
    "auth_login_label": "Username or Email",
    "auth_password_label": "Password",
    "auth_forgot_pwd": "Forgot password?",
    "auth_signin_btn": "Sign In",
    "auth_no_account": "Don't have an account?",
    "auth_register_link": "Create Account",
    "auth_have_account": "Already have an account?",
    "auth_login_link": "Sign In",
    "auth_register_title": "Create Account",
    "auth_register_sub": "Register for Smart Energy AI platform access",
    "auth_username_label": "Username",
    "auth_email_label": "Email Address",
    "auth_confirm_password_label": "Confirm Password",
    "auth_register_btn": "Create Account",
    "auth_forgot_title": "Reset Password",
    "auth_forgot_sub": "Enter your registered email address to receive a verification code",
    "auth_send_reset_code": "Send Verification Code",
    "auth_remember_pwd": "Remember your password?",
    "auth_reset_title": "Set New Password",
    "auth_reset_sub": "Create a strong new password for your account",
    "auth_new_password_label": "New Password",
    "auth_save_new_pwd": "Save New Password & Sign In",
    "auth_cancel_back_login": "Cancel & Return to Sign In",

    // OTP Verification
    "auth_otp_title": "Security Verification",
    "auth_otp_sub": "We have sent a 6-digit verification code to your email",
    "auth_otp_label": "Enter 6-digit Code",
    "auth_otp_verify_btn": "Verify & Proceed",
    "auth_otp_resend": "Resend Code",
    "auth_otp_back": "Back to Sign In",
    "auth_otp_expires_in": "Code expires in:",

    // User Profile
    "profile_title": "User Profile",
    "profile_sub": "Manage your account credentials and view access roles",
    "profile_info_card": "Account Details",
    "profile_username": "Username",
    "profile_email": "Email Address",
    "profile_role": "Assigned Role",
    "profile_verified": "Verification Status",
    "profile_verified_yes": "Verified",
    "profile_verified_no": "Pending Verification",
    "profile_created_at": "Member Since",
    "profile_last_login": "Last Login",
    "profile_perms_card": "Granted Permissions",
    "perm_manage_users": "Manage Users",
    "perm_control_hvac": "Control HVAC",
    "perm_approve_actions": "Approve Actions",
    "perm_view_analytics": "View Analytics",
    "profile_pwd_card": "Change Password",
    "pwd_current": "Current Password",
    "pwd_new": "New Password",
    "pwd_confirm": "Confirm New Password",
    "pwd_update_btn": "Update Password",

    // Admin Control Panel
    "admin_title": "Admin Control Center",
    "admin_sub": "Centralized user administration, permission provisioning, and security audit",
    "kpi_total_users": "TOTAL USERS",
    "kpi_admins": "ADMINISTRATORS",
    "kpi_managers": "OPERATIONS MANAGERS",
    "kpi_analysts": "DATA ANALYSTS",
    "kpi_verified": "VERIFIED USERS",
    "kpi_active": "ACTIVE ACCOUNTS",
    "kpi_codes": "SECURITY CODES",
    "admin_create_user_btn": "Create New User",
    "admin_users_title": "System Users Directory",
    "admin_audit_title": "Verification Codes Audit Log",
    "tbl_id": "ID",
    "tbl_user": "User",
    "tbl_email": "Email",
    "tbl_role": "Role",
    "tbl_permissions": "Permissions",
    "tbl_status": "Status",
    "tbl_verified": "Verified",
    "tbl_last_login": "Last Login",
    "tbl_actions": "Actions",
    "tbl_code": "Code",
    "tbl_type": "Type",
    "tbl_created": "Created At",
    "tbl_expires": "Expires At",
    "tbl_state": "Code State",
    "status_active": "Active",
    "status_inactive": "Deactivated",
    "role_admin": "Administrator",
    "role_manager": "Operations Manager",
    "role_analyst": "Data Analyst",
    "role_user": "Standard User",
    "btn_edit": "Edit",
    "btn_reset_pwd": "Password",
    "btn_edit_role": "Role",
    "btn_edit_perms": "Permissions",
    "btn_toggle_active": "Toggle Active",
    "btn_activate": "Activate",
    "btn_deactivate": "Deactivate",
    "btn_login_as": "Login As",
    "btn_delete": "Delete",
    "confirm_delete_user": "Are you sure you want to permanently delete this user and all associated codes?",
    "modal_create_title": "Create New User Account",
    "modal_role_title": "Change User Role",
    "modal_perms_title": "Update Permissions",
    "modal_edit_user_title": "Edit User Profile",
    "modal_reset_pwd_title": "Reset User Password",
    "modal_reset_pwd_sub": "Target User:",
    "lbl_new_password": "New Password",
    "lbl_confirm_password": "Confirm New Password",
    "lbl_is_verified": "Email Verified (2FA Confirmed)",
    "btn_save": "Save Changes",
    "btn_cancel": "Cancel",
    "btn_close": "Close",
    "banner_impersonating": "IMPERSONATION MODE: Operating as",
    "btn_return_admin": "Return to Admin Account",

    // Decision & Replanning Modal
    "replan_kicker": "REPLANNING · ROUND",
    "replan_title": "The previous action missed its target",
    "replan_label": "The agent now proposes",
    "replan_approve": "Approve",
    "replan_reject": "Reject",
    "replan_later": "Decide later",
    "replan_review": "Review the replanning decision",
    "replan_why": "Why did it fall short?",
    "replan_why_hide": "Hide the reasons",
    "replan_why_loading": "Reading the conditions during that hour…",
    "replan_footnote": "Execution is simulated. Nothing runs until you approve."
  },

  ar: {
    // Brand & Topbar
    "brand_title": "الطاقة الذكية",
    "brand_sub": "العمليات الذاتية",
    "eyebrow_center": "مركز عمليات الطاقة الذكية",
    "building_label": "المبنى",
    "campus_option": "الحرم الجامعي",
    "b001_option": "B001 · مبنى الإدارة",
    "b002_option": "B002 · مبنى المختبرات",
    "b003_option": "B003 · القاعات الدراسية",
    "theme_toggle_tip": "تبديل المظهر",
    "lang_toggle_tip": "التحويل إلى الإنجليزية",
    "lang_btn_text": "English",
    "system_ready": "النظام جاهز",
    "sim_badge": "تشغيل محاكى",
    "footer_sub": "عمليات ذاتية · التوأم الرقمي · موافقة بشرية",

    // Navigation Sections
    "nav_sec_ops": "مركز العمليات",
    "nav_overview": "نظرة عامة",
    "nav_energy": "مراقبة الطاقة",
    "nav_operations": "عمليات الذكاء الاصطناعي",
    "nav_digital_twin": "التوأم الرقمي",
    "nav_verification": "التحقق والاعتماد",
    "nav_sec_history": "مستودع البيانات التاريخية",
    "nav_history": "البيانات التاريخية",
    "nav_sec_intel": "منظومة الاستخبار",
    "nav_knowledge": "قاعدة المعرفة الذكية",
    "nav_activity": "سجل الأنشطة",
    "nav_sec_account": "الحساب وإدارة الوصول",
    "nav_admin": "لوحة الإدارة",
    "nav_profile": "حسابي الشخصي",
    "nav_logout": "تسجيل الخروج",
    "nav_login": "تسجيل الدخول",
    "nav_read_only": "للقراءة فقط",
    "nav_live": "مباشر",

    // Agent Sidebar Card
    "agent_title": "وكيل الطاقة المستقل",
    "agent_mode": "نمط المحاكاة · موافقة بشرية",

    // Auth & Login
    "auth_signin_title": "تسجيل الدخول",
    "auth_signin_sub": "أدخل بياناتك للوصول إلى مركز العمليات الذكية",
    "auth_login_label": "اسم المستخدم أو البريد الإلكتروني",
    "auth_password_label": "كلمة المرور",
    "auth_forgot_pwd": "هل نسيت كلمة السر؟",
    "auth_signin_btn": "تسجيل الدخول",
    "auth_no_account": "ليس لديك حساب؟",
    "auth_register_link": "إنشاء حساب جديد",
    "auth_have_account": "لديك حساب بالفعل؟",
    "auth_login_link": "تسجيل الدخول",
    "auth_register_title": "إنشاء حساب جديد",
    "auth_register_sub": "سجّل بياناتك للوصول إلى منصة الطاقة الذكية",
    "auth_username_label": "اسم المستخدم",
    "auth_email_label": "البريد الإلكتروني",
    "auth_confirm_password_label": "تأكيد كلمة المرور",
    "auth_register_btn": "إنشاء الحساب",
    "auth_forgot_title": "استعادة كلمة المرور",
    "auth_forgot_sub": "أدخل بريدك الإلكتروني المسجل لاستلام رمز التحقق",
    "auth_send_reset_code": "إرسال رمز التحقق",
    "auth_remember_pwd": "هل تذكرت كلمة المرور؟",
    "auth_reset_title": "تعيين كلمة المرور الجديدة",
    "auth_reset_sub": "أنشئ كلمة مرور جديدة وقوية لحسابك",
    "auth_new_password_label": "كلمة المرور الجديدة",
    "auth_save_new_pwd": "حفظ كلمة المرور وتسجيل الدخول",
    "auth_cancel_back_login": "إلغاء والعودة لتسجيل الدخول",

    // OTP Verification
    "auth_otp_title": "التحقق الأمني",
    "auth_otp_sub": "أرسلنا رمز تحقق مكوّن من 6 أرقام إلى بريدك الإلكتروني",
    "auth_otp_label": "أدخل رمز التحقق المكون من 6 أرقام",
    "auth_otp_verify_btn": "تأكيد ومتابعة",
    "auth_otp_resend": "إعادة إرسال الرمز",
    "auth_otp_back": "العودة لتسجيل الدخول",
    "auth_otp_expires_in": "ينتهي الرمز خلال:",

    // User Profile
    "profile_title": "الملف الشخصي",
    "profile_sub": "إدارة بيانات الحساب والاطلاع على الرتب والصلاحيات",
    "profile_info_card": "تفاصيل الحساب",
    "profile_username": "اسم المستخدم",
    "profile_email": "البريد الإلكتروني",
    "profile_role": "الرتبة المعينة",
    "profile_verified": "حالة التأكيد",
    "profile_verified_yes": "مؤكد",
    "profile_verified_no": "بانتظار التأكيد",
    "profile_created_at": "تاريخ الانضمام",
    "profile_last_login": "آخر تسجيل دخول",
    "profile_perms_card": "الصلاحيات الممنوحة",
    "perm_manage_users": "إدارة المستخدمين",
    "perm_control_hvac": "التحكم بأنظمة التكييف",
    "perm_approve_actions": "اعتماد الإجراءات",
    "perm_view_analytics": "استعراض التحليلات",
    "profile_pwd_card": "تغيير كلمة المرور",
    "pwd_current": "كلمة المرور الحالية",
    "pwd_new": "كلمة المرور الجديدة",
    "pwd_confirm": "تأكيد كلمة المرور الجديدة",
    "pwd_update_btn": "تحديث كلمة المرور",

    // Admin Control Panel
    "admin_title": "لوحة الإدارة المركزية",
    "admin_sub": "إدارة المستخدمين ومنح الصلاحيات والتدقيق الأمني لرموز التحقق",
    "kpi_total_users": "إجمالي المستخدمين",
    "kpi_admins": "المسؤولون",
    "kpi_managers": "مدراء العمليات",
    "kpi_analysts": "محللو البيانات",
    "kpi_verified": "الحسابات المؤكدة",
    "kpi_active": "الحسابات النشطة",
    "kpi_codes": "رموز التحقق",
    "admin_create_user_btn": "إضافة مستخدم جديد",
    "admin_users_title": "دليل مستخدمي النظام",
    "admin_audit_title": "سجل التدقيق لرموز التحقق",
    "tbl_id": "المعرّف",
    "tbl_user": "المستخدم",
    "tbl_email": "البريد الإلكتروني",
    "tbl_role": "الرتبة",
    "tbl_permissions": "الصلاحيات",
    "tbl_status": "الحالة",
    "tbl_verified": "التأكيد",
    "tbl_last_login": "آخر دخول",
    "tbl_actions": "الإجراءات",
    "tbl_code": "الرمز",
    "tbl_type": "النوع",
    "tbl_created": "تاريخ الإنشاء",
    "tbl_expires": "تاريخ الانتهاء",
    "tbl_state": "حالة الرمز",
    "status_active": "نشط",
    "status_inactive": "مجمد",
    "role_admin": "مسؤول النظام",
    "role_manager": "مدير العمليات",
    "role_analyst": "محلل البيانات",
    "role_user": "مستخدم عادي",
    "btn_edit": "تعديل",
    "btn_reset_pwd": "كلمة المرور",
    "btn_edit_role": "الرتبة",
    "btn_edit_perms": "الصلاحيات",
    "btn_toggle_active": "تجميد / تنشيط",
    "btn_activate": "تنشيط",
    "btn_deactivate": "تجميد",
    "btn_login_as": "دخول بحسابه",
    "btn_delete": "حذف",
    "confirm_delete_user": "هل أنت متأكد من رغبتك في حذف هذا المستخدم نهائياً مع كافة رموز التحقق التابعة له؟",
    "modal_create_title": "إنشاء حساب مستخدم جديد",
    "modal_role_title": "تعديل رتبة المستخدم",
    "modal_perms_title": "تعديل الصلاحيات المخصصة",
    "modal_edit_user_title": "تعديل بيانات المستخدم",
    "modal_reset_pwd_title": "إعادة تعيين كلمة مرور المستخدم",
    "modal_reset_pwd_sub": "المستخدم المستهدف:",
    "lbl_new_password": "كلمة المرور الجديدة",
    "lbl_confirm_password": "تأكيد كلمة المرور الجديدة",
    "lbl_is_verified": "البريد الإلكتروني مؤكد (اعتماد التحقق)",
    "btn_save": "حفظ التغييرات",
    "btn_cancel": "إلغاء",
    "btn_close": "إغلاق",
    "banner_impersonating": "نمط التحكم المباشر: أنت تعمل حالياً بحساب",
    "btn_return_admin": "العودة لحساب الإدارة",

    // Decision & Replanning Modal
    "replan_kicker": "إعادة التخطيط · الجولة",
    "replan_title": "لم يحقق الإجراء السابق النتيجة المستهدفة",
    "replan_label": "يقترح الوكيل الذكي الآن",
    "replan_approve": "موافقة",
    "replan_reject": "رفض",
    "replan_later": "القرار لاحقاً",
    "replan_review": "مراجعة قرار إعادة التخطيط",
    "replan_why": "لماذا لم يبلغ الهدف؟",
    "replan_why_hide": "إخفاء الأسباب",
    "replan_why_loading": "جارٍ قراءة ظروف تلك الساعة…",
    "replan_footnote": "التشغيل محاكى بالكامل. لن يتم تنفيذ أي إجراء إلا بعد موافقتك الصريحة."
  }
};


// =========================================================
// 3. TRANSLATION ENGINE & UI REFRESH
// =========================================================

function getCurrentLanguage() {
  return document.documentElement.getAttribute("lang") || "en";
}

function t(key) {
  const lang = getCurrentLanguage();
  if (I18N[lang] && I18N[lang][key]) {
    return I18N[lang][key];
  }
  if (I18N.en && I18N.en[key]) {
    return I18N.en[key];
  }
  return key;
}

function translatePage(lang) {
  if (!lang) lang = getCurrentLanguage();
  const dict = I18N[lang] || I18N.en;

  // 1. Text elements with data-i18n
  document.querySelectorAll("[data-i18n]").forEach(el => {
    const key = el.getAttribute("data-i18n");
    if (dict[key]) {
      el.textContent = dict[key];
    }
  });

  // 2. Placeholder attributes
  document.querySelectorAll("[data-i18n-placeholder]").forEach(el => {
    const key = el.getAttribute("data-i18n-placeholder");
    if (dict[key]) {
      el.setAttribute("placeholder", dict[key]);
    }
  });

  // 3. Tooltip / Title attributes
  document.querySelectorAll("[data-i18n-title]").forEach(el => {
    const key = el.getAttribute("data-i18n-title");
    if (dict[key]) {
      el.setAttribute("title", dict[key]);
    }
  });

  // 4. Update Lang Button Label
  const langBtn = document.getElementById("lang-toggle");
  if (langBtn) {
    langBtn.textContent = (lang === "ar") ? "English" : "العربية";
    langBtn.setAttribute("title", (lang === "ar") ? "Switch to English" : "التحويل إلى العربية");
  }

  // 5. Update Theme Button Icon
  updateThemeButton();
}

function updateThemeButton() {
  const currentTheme = document.documentElement.getAttribute("data-theme") || "dark";
  const themeBtn = document.getElementById("theme-toggle");
  if (themeBtn) {
    themeBtn.textContent = (currentTheme === "dark") ? "☀️" : "🌙";
    themeBtn.setAttribute("title", (currentTheme === "dark") ? "Switch to Light Mode" : "Switch to Dark Mode");
  }
}


// =========================================================
// 4. GLOBAL TOGGLE FUNCTIONS (EXPOSED TO WINDOW)
// =========================================================

window.toggleLanguage = function(event) {
  if (event) event.preventDefault();
  const currentLang = getCurrentLanguage();
  const newLang = (currentLang === "ar") ? "en" : "ar";

  // Persist in localStorage and Cookie
  localStorage.setItem("smart_energy_lang", newLang);
  document.cookie = `smart_energy_lang=${newLang}; path=/; max-age=31536000; SameSite=Lax`;

  // Apply to DOM
  document.documentElement.setAttribute("lang", newLang);
  document.documentElement.setAttribute("dir", newLang === "ar" ? "rtl" : "ltr");

  // Re-translate page
  translatePage(newLang);
};

window.toggleTheme = function(event) {
  if (event) event.preventDefault();
  const currentTheme = document.documentElement.getAttribute("data-theme") || "dark";
  const newTheme = (currentTheme === "dark") ? "light" : "dark";

  // Persist
  localStorage.setItem("smart_energy_theme", newTheme);

  // Apply to DOM
  document.documentElement.setAttribute("data-theme", newTheme);

  // Update button visual
  updateThemeButton();
  renderPalettePicker();
};

// Colour themes: each has a dark and a light version (static/css/app.css, THEMES block).
const PALETTES = [{"key": "luxury", "name": "Luxury Gold", "ar": "ذهبي فاخر", "swatch": ["#5C1121", "#DEB85C", "#080709"]}, {"key": "midnight", "name": "Midnight Navy", "ar": "كحلي ليلي", "swatch": ["#1E3A8A", "#60A5FA", "#070B14"]}, {"key": "emerald", "name": "Emerald Energy", "ar": "زمردي طاقة", "swatch": ["#064E3B", "#34D399", "#06100D"]}, {"key": "teal", "name": "Ocean Teal", "ar": "فيروزي", "swatch": ["#134E4A", "#2DD4BF", "#061012"]}, {"key": "indigo", "name": "Royal Indigo", "ar": "نيلي ملكي", "swatch": ["#3730A3", "#A5B4FC", "#0A0916"]}, {"key": "ocean", "name": "Arctic Blue", "ar": "أزرق قطبي", "swatch": ["#075985", "#38BDF8", "#05101A"]}, {"key": "solar", "name": "Solar Amber", "ar": "كهرماني شمسي", "swatch": ["#7C2D12", "#F59E0B", "#0F0B05"]}, {"key": "graphite", "name": "Graphite Mono", "ar": "جرافيت أحادي", "swatch": ["#3F3F46", "#E4E4E7", "#0A0A0B"]}, {"key": "crimson", "name": "Crimson Rose", "ar": "قرمزي وردي", "swatch": ["#881337", "#FB7185", "#0E0709"]}];

window.setPalette = function(key) {
  const k = PALETTES.some(p => p.key === key) ? key : "luxury";
  if (k === "luxury") document.documentElement.removeAttribute("data-palette");
  else document.documentElement.setAttribute("data-palette", k);
  try { localStorage.setItem("smart_energy_palette", k); } catch (_) {}
  renderPalettePicker();
};

window.setMode = function(mode) {
  document.documentElement.setAttribute("data-theme", mode);
  try { localStorage.setItem("smart_energy_theme", mode); } catch (_) {}
  updateThemeButton();
  renderPalettePicker();
};

function renderPalettePicker() {
  const menu = document.getElementById("palette-menu");
  if (!menu) return;
  const ar = document.documentElement.getAttribute("lang") === "ar";
  const current = document.documentElement.getAttribute("data-palette") || "luxury";
  const mode = document.documentElement.getAttribute("data-theme") || "dark";
  menu.innerHTML = `
    <div class="palette-menu-head"><span>${ar ? "ثيم الألوان" : "COLOR THEME"}</span>
      <div class="palette-mode">
        <button type="button" data-mode="dark" class="${mode === "dark" ? "on" : ""}">${ar ? "داكن" : "Dark"}</button>
        <button type="button" data-mode="light" class="${mode === "light" ? "on" : ""}">${ar ? "فاتح" : "Light"}</button>
      </div></div>
    <div class="palette-grid">${PALETTES.map(p => `
      <button type="button" class="palette-opt ${p.key === current ? "on" : ""}" data-key="${p.key}">
        <span class="sw">${p.swatch.map(c => `<b style="background:${c}"></b>`).join("")}</span>
        <span>${ar ? p.ar : p.name}<small>${ar ? p.name : p.ar}</small></span>
      </button>`).join("")}</div>`;
  menu.querySelectorAll(".palette-opt").forEach(b => b.addEventListener("click", () => setPalette(b.dataset.key)));
  menu.querySelectorAll(".palette-mode button").forEach(b => b.addEventListener("click", () => setMode(b.dataset.mode)));
}

document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("palette-toggle");
  const menu = document.getElementById("palette-menu");
  if (!btn || !menu) return;
  btn.addEventListener("click", e => {
    e.stopPropagation();
    menu.hidden = !menu.hidden;
    btn.setAttribute("aria-expanded", String(!menu.hidden));
    if (!menu.hidden) renderPalettePicker();
  });
  menu.addEventListener("click", e => e.stopPropagation());
  document.addEventListener("click", () => { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); });
  document.addEventListener("keydown", e => { if (e.key === "Escape") menu.hidden = true; });
});

window.t = t;
window.translatePage = translatePage;


// =========================================================
// 5. INITIALIZE ON DOM READY
// =========================================================
document.addEventListener("DOMContentLoaded", () => {
  translatePage();
});
