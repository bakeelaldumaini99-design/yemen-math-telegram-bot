# -*- coding: utf-8 -*-
"""
بوت تيليجرام التعليمي — الرياضيات للصف الثالث الثانوي
- واجهة عربية بسيطة: الطالب يكتب سؤاله مباشرة
- حلول مختصرة بأسلوب تعليمي: المعطيات ← القانون ← النتيجة النهائية
- لوحة تحكم كاملة للمشرفين: متابعة مباشرة + أوامر تحكم
- نظام ذكاء محلي مستقل: قاعدة بيانات + محرك رياضيات (SymPy) + محرك فيزياء
  بدون أي API خارجي للذكاء الاصطناعي
"""

import os
import re
import json
import difflib
import logging
from pathlib import Path
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters,
)

# ---------------- الإعدادات ----------------
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PROXY = os.getenv("TELEGRAM_PROXY") or os.getenv("HTTPS_PROXY")

TEACHER_NAME = "شاجع الدميني"
GRADE = "الصف الثالث الثانوي"

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
ADMINS_FILE = DATA_DIR / "admins.json"
USERS_FILE = DATA_DIR / "users.json"
LOG_FILE = DATA_DIR / "conversations.jsonl"
SETTINGS_FILE = DATA_DIR / "settings.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

WELCOME_DEFAULT = (
    "مرحباً بك في بوت الرياضيات للصف الثالث الثانوي 📚\n"
    "هذا البوت يساعدك في حل وفهم مسائل الرياضيات بطريقة سهلة.\n"
    f"إعداد الأستاذ: {TEACHER_NAME}\n\n"
    "اكتب سؤالك مباشرة، مثال: حل س^٢-٥س+٦=٠\n\n"
    "📢 لا تنسَ متابعة القناة التعليمية للرياضيات — اكتب «القناة» لمعرفة الرابط."
)


# ---------------- التخزين ----------------
def load_json(path, default):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_admins() -> list:
    env = [x for x in os.getenv("BOT_ADMIN_IDS", "").split(",") if x.strip()]
    return sorted(set(env) | set(str(i) for i in load_json(ADMINS_FILE, [])))


def get_settings() -> dict:
    s = load_json(SETTINGS_FILE, {})
    return {
        "welcome": s.get("welcome", WELCOME_DEFAULT),
        "channel": s.get("channel", ""),          # رابط أو معرف القناة
        "enabled": s.get("enabled", True),        # البوت يعمل أو متوقف
    }


def save_settings(**kw):
    s = get_settings()
    s.update(kw)
    save_json(SETTINGS_FILE, s)


def bot_enabled() -> bool:
    return bool(get_settings()["enabled"])


def log_conversation(user_id, username, question, answer):
    entry = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "user_id": user_id, "username": username,
        "question": question, "answer": answer,
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ---------------- معالجة اللغة العربية ----------------
AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def normalize(text: str) -> str:
    """تطبيع عربي: إزالة التشكيل وتوحيد الألف والهاء والتاء المربوطة"""
    t = text.translate(AR_DIGITS).lower()
    t = re.sub(r"[ً-ٰٟ]", "", t)
    t = (t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
          .replace("ى", "ي").replace("ة", "ه"))
    return re.sub(r"\s+", " ", t).strip()


INTENTS = {
    "greeting": ["السلام عليكم", "سلام عليكم", "مرحبا", "اهلا", "اهلا وسهلا",
                 "هلا", "صباح الخير", "مساء الخير", "هاي", "السلام"],
    "who_are_you": ["من انت", "ما اسمك", "عرف نفسك", "وش انت",
                    "ما هذا البوت", "وش هذا البوت", "عرف البوت", "عرفني عليك"],
    "what_bot_does": ["ما وظيفه هذا البوت", "وش يسوي البوت", "وش وظيفتك",
                      "كيف استخدم البوت", "كيف استخدمك", "طريقه الاستخدام", "ماذا تفعل"],
    "teacher": ["من اعداد هذا البوت", "اعداد البوت", "من صنع هذا البوت", "من المعلم",
                "من الاستاذ", "من هو الاستاذ", "من هو شاجع", "سيره الاستاذ", "معلومات عن الاستاذ"],
    "channel": ["القناه", "رابط القناه", "اشتراك", "متابعه القناه", "قناه البوت"],
    "how_are_you": ["كيف حالك", "كيفك", "كيف الحال", "اخبارك", "اخباركم", "عامل ايه"],
    "bye": ["مع السلامه", "الي اللقاء", "وداعا", "باي", "تصبح علي خير"],
    "thanks": ["شكرا", "مشكور", "مشكورين", "مشكوره", "يعطيك العافيه", "جزاك الله خير",
               "تسلم", "تسلمين", "ممتاز", "رائع", "اشكرك", "ما قصرت"],
}

# حالة الرد المباشر: معرف المشرف -> معرف الطالب المستهدف
PENDING_REPLY: dict = {}
# حالة إضافة سؤال للقاعدة: معرف المشرف -> {step, data}
PENDING_ADD: dict = {}

# تصنيفات التنبيهات للمشرف
HELP_WORDS = ("مساعده", "لم افهم", "ما فهمت", "اشرح", "صعب", "صعبه", "ساعدني", "استاذ")
COMPLAINT_WORDS = ("شكوي", "اقتراح", "مشكله", "عطل", "خطا", "خطأ", "سيء")

GREETING_REPLY = ("وعليكم السلام ورحمة الله وبركاته، أهلًا بك في بوت الرياضيات. "
                  "كيف يمكنني مساعدتك؟")
WHO_REPLY = (
    "أنا بوت الرياضيات الذكي للصف الثالث الثانوي في الجمهورية اليمنية، "
    "تم تطويري لمساعدة الطلاب على فهم وحل مسائل الرياضيات بطريقة سهلة ومنظمة.\n"
    "أول بوت ذكاء صناعي متخصص في مادة الرياضيات ومرتبط بقناة تعليمية للرياضيات "
    "في الجمهورية اليمنية."
)
HELP_REPLY = ("اكتب سؤالك الرياضي مباشرة وسأجيبك بخطوات الحل.\n"
              "أدعم: العمليات الحسابية، المعادلات، المشتقات، التكامل، والنهايات.\n\n"
              "أمثلة:\n"
              "• احسب ٢٥×٤+٣\n"
              "• حل المعادلة س^٢-٥س+٦=٠\n"
              "• أوجد مشتقة س^٣+٢س\n"
              "• تكامل ٢س\n"
              "• نهاية (س^٢-١)/(س-١) عندما س تقترب من ١")
TEACHER_REPLY = (
    f"الأستاذ {TEACHER_NAME}\n"
    "معلم متخصص في مادة الرياضيات، يهتم بتقديم محتوى تعليمي مبسط ومساعدة "
    "طلاب الصف الثالث الثانوي على فهم القوانين والطرق الرياضية وحل المسائل "
    "بطريقة سهلة ومنظمة."
)
CHANNEL_REPLY = (
    "يمكنك متابعة القناة التعليمية المرتبطة بالبوت للحصول على الشروحات، "
    "المراجعات، والتنبيهات الخاصة بمادة الرياضيات للصف الثالث الثانوي."
)
THANKS_REPLY = "العفو، بالتوفيق في دراستك! 🌟 إذا عندك سؤال آخر اكتبه مباشرة."
HOW_REPLY = ("بخير والحمد لله، شكرًا لسؤالك 🌹 أنا جاهز دائمًا لمساعدتك في الرياضيات "
             "وغيرها من المواد — اكتب سؤالك مباشرة.")
BYE_REPLY = "مع السلامة، بالتوفيق في مذاكرتك! 📚 عد متى شئت، أنا هنا لمساعدتك."
UNCLEAR_REPLY = ("لم أجد إجابة لهذا السؤال في قاعدة بياناتي بعد 🤔\n"
                 "سأرفعه للأستاذ ليضيف إجابته قريبًا، ويمكنك إعادة صياغة السؤال بكلمات أبسط.")


def channel_text() -> str:
    ch = get_settings()["channel"]
    return CHANNEL_REPLY + (f"\nالقناة: {ch}" if ch else "\nاسأل المشرف عن رابط القناة.")


def detect_intent(text: str) -> str | None:
    """يفهم التحيات والأسئلة العامة حتى مع أخطاء إملائية بسيطة"""
    t = normalize(text)
    padded = f" {t} "  # حدود كلمات حتى لا تطابق كلمة قصيرة داخل كلمة أخرى
    for intent, examples in INTENTS.items():
        for ex in examples:
            ne = normalize(ex)
            if f" {ne} " in padded or ne == t:
                return intent
        # تسامح مع الأخطاء الإملائية: تشابه نصي
        for ex in examples:
            if len(t) <= 40 and difflib.SequenceMatcher(None, t, normalize(ex)).ratio() > 0.78:
                return intent
    return None


# ---------------- محرك الرياضيات ----------------
def prep_expr(raw: str) -> str:
    """تحويل كتابة الطالب العربية إلى صيغة يفهمها محرك الحساب"""
    t = raw.translate(AR_DIGITS)
    t = (t.replace("×", "*").replace("÷", "/").replace("^", "**")
          .replace("٪", "/100").replace("√", "sqrt").replace("π", "pi")
          .replace("جذر", "sqrt").replace("الجذر التربيعي", "sqrt"))
    t = re.sub(r"(س|ص)\s*(تربيع|مربع)", r"\1**2", t)
    t = re.sub(r"(س|ص)\s*تكعيب", r"\1**3", t)
    t = re.sub(r"pi\s*تربيع|مربع\spi", "pi**2", t)
    t = t.replace("س", "x").replace("ص", "y")
    t = t.replace("د س", "dx").replace("دس", "dx").replace("دص", "dy")
    return t.strip()


def parse_math(t: str):
    from sympy.parsing.sympy_parser import (
        parse_expr, standard_transformations,
        implicit_multiplication_application, convert_xor,
    )
    transformations = standard_transformations + (
        implicit_multiplication_application, convert_xor)
    return parse_expr(t, transformations=transformations)


def fmt(expr) -> str:
    """تنسيق الناتج بلغة واضحة"""
    import sympy as sp
    if expr in (sp.oo, -sp.oo):
        return "∞" if expr == sp.oo else "-∞"
    if expr in (sp.zoo, sp.nan):
        return "غير موجودة (∞)"
    try:
        f = float(expr)
        if abs(f - round(f)) < 1e-9:
            return str(int(round(f)))
        return str(round(f, 6))
    except Exception:
        pass
    s = str(expr)
    s = s.replace("**2", "²").replace("**3", "³").replace("**", "^")
    s = s.replace("sqrt", "√").replace("pi", "ط").replace("oo", "∞")
    s = s.replace("x", "س").replace("y", "ص").replace("z", "ع")
    return s


def solution(given: str, rule: str, result: str) -> str:
    """قالب الحل التعليمي الموحد: المعطيات ← القانون ← النتيجة النهائية"""
    return f"الحل:\nالمعطيات: {given}\nنطبق القانون: {rule}\nالنتيجة النهائية: {result}"


def clean_math(text: str) -> str:
    """إزالة كلمات الطلب حتى يبقى التعبير الرياضي"""
    t = normalize(text)
    for w in ["احسب", "اوجد", "حل", "ما ناتج", "يساوي كم", "كم يساوي",
              "قيمه", "بسط", "المعادله"]:
        t = t.replace(w, "")
    t = (t.replace("ناقص", "-").replace("زائد", "+")
          .replace("مضروب في", "*").replace("مقسوم على", "/")
          .replace("في", "*").replace("على", "/"))
    return t.strip()


def try_geometry(t: str) -> str | None:
    """حل المسائل الهندسية الشائعة: مساحات ومحيطات وأحجام"""
    if not any(w in t for w in ("مساحه", "محيط", "حجم")):
        return None
    nums = [float(x) for x in re.findall(r"[\d\.]+", t.translate(AR_DIGITS))]
    if not nums:
        return "اذكر القيم العددية في السؤال حتى أحسبها لك، مثال: «مساحة دائرة نصف قطرها ٥»"
    r = nums[0]
    p = 3.141592653589793
    if "محيط" in t and "دائر" in t:
        return solution(f"نصف القطر نق = {fmt(r)}",
                        "المحيط = ٢ × ط × نق",
                        f"٢ × ط × {fmt(r)} = {fmt(2*p*r)}")
    if "دائر" in t:
        return solution(f"نصف القطر نق = {fmt(r)}",
                        "المساحة = ط × نق²",
                        f"ط × {fmt(r)}² = {fmt(p*r**2)}")
    if "مربع" in t:
        return solution(f"طول الضلع = {fmt(r)}",
                        "المساحة = الضلع²",
                        f"{fmt(r)}² = {fmt(r**2)}")
    if "مستطيل" in t:
        a, b = (nums + [0])[:2]
        return solution(f"الطول = {fmt(a)} والعرض = {fmt(b)}",
                        "المساحة = الطول × العرض",
                        f"{fmt(a)} × {fmt(b)} = {fmt(a*b)}")
    if "مثلث" in t:
        a, h = (nums + [0])[:2]
        return solution(f"القاعدة = {fmt(a)} والارتفاع = {fmt(h)}",
                        "المساحة = ½ × القاعدة × الارتفاع",
                        f"½ × {fmt(a)} × {fmt(h)} = {fmt(a*h/2)}")
    if "كره" in t:
        return solution(f"نصف القطر نق = {fmt(r)}",
                        "الحجم = ٤/٣ × ط × نق³",
                        f"٤/٣ × ط × {fmt(r)}³ = {fmt(4/3*3.141592653589793*r**3)}")
    if "اسطوانه" in t:
        h = nums[1] if len(nums) > 1 else 0
        return solution(f"نق = {fmt(r)} والارتفاع = {fmt(h)}",
                        "الحجم = ط × نق² × الارتفاع",
                        f"ط × {fmt(r)}² × {fmt(h)} = {fmt(p*r**2*h)}")
    if "مخروط" in t:
        h = nums[1] if len(nums) > 1 else 0
        return solution(f"نق = {fmt(r)} والارتفاع = {fmt(h)}",
                        "الحجم = ⅓ × ط × نق² × الارتفاع",
                        f"⅓ × ط × {fmt(r)}² × {fmt(h)} = {fmt(p*r**2*h/3)}")
    return None


def try_math(text: str) -> str | None:
    """يحل سؤال الرياضيات ويعرض الحل بأسلوب المعطيات ← القانون ← النتيجة"""
    t = normalize(text)
    try:
        import sympy as sp

        # ---------- 1) المشتقات ----------
        if "مشتق" in t or "اشتق" in t:
            m = re.search(r"(?:مشتق[هة]?\s*(?:الداله)?|اشتق(?:اق)?\s*(?:الداله)?)\s*(.*)", t)
            raw = m.group(1) if m else clean_math(t)
            raw = re.sub(r"بالنسبه ل(س|ص)", "", raw)
            expr = parse_math(prep_expr(raw))
            d = sp.diff(expr, sp.Symbol("x"))
            return solution(f"الدالة د(س) = {fmt(expr)}",
                            "نشتق كل حد: الأس ينزل أمام الحد ويُنقص واحد",
                            f"د'(س) = {fmt(d)}")

        # ---------- 2) التكامل ----------
        if "تكامل" in t:
            raw = re.sub(r"^.*?تكامل", "", t)
            raw = raw.replace("د س", "دس")
            m_def = re.search(r"من\s*(-?[\d\.]+)\s*الي\s*(-?[\d\.]+)", raw)
            raw_expr = re.sub(r"من\s*-?[\d\.]+\s*الي\s*-?[\d\.]+", "", raw)
            raw_expr = re.sub(r"(دس|د س)$", "", raw_expr.strip()).strip()
            expr = parse_math(prep_expr(raw_expr))
            x = sp.Symbol("x")
            F = sp.integrate(expr, x)
            rule = "نزيد الأس واحدًا ونقسم على الأس الجديد"
            if m_def:
                a, b = float(m_def.group(1)), float(m_def.group(2))
                val = sp.integrate(expr, (x, a, b))
                return solution(f"الدالة = {fmt(expr)}، من {fmt(a)} إلى {fmt(b)}",
                                rule + "، ثم نعوض بالحدين ونطرح",
                                f"{fmt(val)}")
            return solution(f"الدالة = {fmt(expr)}", rule, f"∫ = {fmt(F)} + ج")

        # ---------- 3) النهايات ----------
        if "نهايه" in t:
            raw = re.sub(r"^.*?نهايه", "", t)
            point = None
            m = re.search(r"(?:عندما|عند|لما)\s*س?\s*(?:تقترب\s*(?:من)?|⟶|->)?\s*(-?[\d\.]+|مال\s*(?:ال)?\s*نهايه|ما\s*لا\s*(?:ال)?\s*نهايه|∞)", raw)
            if m:
                pt = normalize(m.group(1))
                point = sp.oo if ("نهايه" in pt or pt == "∞") else float(pt)
                raw = raw[:m.start()] + raw[m.end():]
            if point is None:
                m2 = re.search(r"س\s*=\s*(-?[\d\.]+)", raw)
                if m2:
                    point = float(m2.group(1))
                    raw = raw[:m2.start()] + raw[m2.end():]
            expr = parse_math(prep_expr(raw))
            if point is None:
                point = 0
            lim = sp.limit(expr, sp.Symbol("x"), point)
            ptxt = "∞ (مال النهاية)" if point == sp.oo else fmt(point)
            return solution(f"الدالة = {fmt(expr)}، و س ← {ptxt}",
                            "نعوض بالقيم مباشرة، أو نحلل العوامل إذا كانت الصيغة غير مباشرة",
                            f"النهاية = {fmt(lim)}")

        # ---------- 4) المعادلات ----------
        if "=" in text or "معادله" in t:
            expr_raw = clean_math(text)
            if "=" in expr_raw:
                lhs, rhs = expr_raw.split("=", 1)
            else:
                lhs, rhs = expr_raw, "0"
            lhs_e = parse_math(prep_expr(lhs))
            rhs_e = parse_math(prep_expr(rhs))
            eq = sp.Eq(lhs_e, rhs_e)
            symbols = eq.free_symbols
            if not symbols:
                return None
            sols = sp.solve(eq, list(symbols))
            moved = sp.simplify(lhs_e - rhs_e)
            return solution(f"المعادلة: {fmt(lhs_e)} = {fmt(rhs_e)}",
                            f"ننقل الحدود ← {fmt(moved)} = 0، ثم نحل بالتحليل أو القانون العام",
                            f"س = {fmt(sols)}")

        # ---------- 5) المسائل الهندسية ----------
        geo = try_geometry(t)
        if geo:
            return geo

        # ---------- 6) عمليات حسابية وتبسيط ----------
        if not re.search(r"[0-9=+\-*/()]", text.translate(AR_DIGITS)):
            return None
        expr = parse_math(prep_expr(clean_math(text)))
        if expr.free_symbols:
            return solution(f"التعبير: {fmt(expr)}",
                            "نبسط الحدود المتشابهة ونحلل إن أمكن",
                            f"{fmt(sp.simplify(expr))} = {fmt(sp.factor(expr))}")
        return solution("عملية حسابية",
                        "ننفذ العمليات بالترتيب: الأقواس ثم الأس ثم الضرب والقسمة",
                        fmt(expr))

    except Exception as exc:
        logger.info("تعذر فهم السؤال رياضيًا: %s", exc)
        return None


# ---------------- الردود ----------------
def build_reply(text: str) -> str | None:
    """التوجيه الذكي: نوايا التواصل ← قاعدة البيانات ← محركات الحل المحلية"""
    intent = detect_intent(text)
    if intent == "greeting":
        return GREETING_REPLY
    if intent == "who_are_you":
        return WHO_REPLY
    if intent == "what_bot_does":
        return HELP_REPLY
    if intent == "teacher":
        return TEACHER_REPLY
    if intent == "channel":
        return channel_text()
    if intent == "how_are_you":
        return HOW_REPLY
    if intent == "bye":
        return BYE_REPLY
    if intent == "thanks":
        return THANKS_REPLY

    subject = classify_subject(text)

    # 1) قاعدة البيانات التعليمية المحلية (مع أولوية لمادة السؤال)
    ans = search_db(text, subject if subject else None)
    if ans:
        return ans

    # 2) محركات الحل المتخصصة
    if subject == "رياضيات":
        ans = try_math(text)
        if ans:
            return ans
    elif subject == "فيزياء":
        ans = try_physics(text)
        if ans:
            return ans

    # 3) بحث عام في القاعدة ثم محاولة رياضية أخيرة (أسئلة بصيغ غير متوقعة)
    if subject != "رياضيات":
        ans = search_db(text)
        if ans:
            return ans
        if looks_like_math(text):
            return try_math(text)
    return None


# ---------------- قاعدة البيانات التعليمية المحلية ----------------
DB_FILE = Path(__file__).parent / "subjects_db.json"
DB_SUBJECTS = ["رياضيات", "أحياء", "فيزياء", "كيمياء", "لغة عربية", "معلومات عامة", "اجتماعيات"]


def load_db() -> list:
    if DB_FILE.exists():
        return json.load(open(DB_FILE, encoding="utf-8")).get("entries", [])
    return []


def save_db(entries: list):
    json.dump({"entries": entries}, open(DB_FILE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


def search_db(text: str, subject: str = None, threshold: float = 7) -> str | None:
    """يبحث في قاعدة البيانات المحلية مع أولوية لمادة محددة"""
    try:
        q = normalize(text)
        q_words = set(q.split())
        best = (0, None)
        for e in load_db():
            if subject and e.get("subject") != subject:
                continue
            hay = normalize(e.get("question", "") + " " + " ".join(e.get("keywords", [])))
            hay_words = set(hay.split())
            overlap = len(q_words & hay_words)
            if overlap < 2:          # لا نطابق إلا بكلمتين مشتركتين على الأقل
                continue
            ratio = difflib.SequenceMatcher(None, q, normalize(e.get("question", ""))).ratio()
            score = overlap * 2 + ratio * 5
            if score > best[0]:
                best = (score, e)
        if best[1] and best[0] >= threshold:
            e = best[1]
            return f"📘 {e['subject']}\n\n{e['answer']}"
    except Exception as exc:
        logger.warning("تعذر البحث في قاعدة البيانات: %s", exc)
    return None


# ---------------- تصنيف المادة تلقائيًا ----------------
SUBJECT_WORDS = {
    "رياضيات": ["معادله", "مشتق", "اشتق", "تكامل", "نهايه", "جذر",
                  "مساحه", "محيط", "حجم", "مربع", "مكعب", "لوغاريتم", "مثلث", "زاويه",
                  "خطيه", "متتاليه", "احتمال", "مجموعات", "داله", "قطع", "تمام", "اسيه",
                  "نسبه", "كسر", "فيثاغورس", "اس", "قطع مخروطي", "منحني"],
    "أحياء": ["خليه", "ميتوكوندريا", "نواه", "بلاستيدات", "بلاستيد", "بناء ضوئي", "تنفس خلوي",
              "الحمض النووي", "دي ان ايه", "dna", "الانقسام", "ميوزي", "ميتوزي", "كريات الدم",
              "فيروس", "بكتيريا", "وراثه", "كروموسوم", "عضويه", "هرمون", "جهاز هضمي",
              "جهاز عصبي", "نبات", "بذور", "الدم", "قلب", "رئه", "عضو"],
    "فيزياء": ["سرعه", "عجله", "قوه", "نيوتن", "طاقه", "شغل", "قدره", "ضغط", "كثافه",
               "كميه التحرك", "موجات", "تردد", "طول موجي", "قانون اوم", "تيار", "جهد",
               "مقاومه", "كهرب", "مغناطيس", "حراره", "ضوء", "صوت", "احتكاك", "قصور ذاتي",
               "سقوط حر", "جاذبيه", "كتله", "زمن", "مسافه", "ازاحه", "جول", "واط", "فولت",
               "امبير", "اوم"],
    "كيمياء": ["ذره", "ذرات", "جزيء", "عنصر", "مركب", "تفاعل", "حمض", "قاعده", "ph",
               "المول", "مولاريه", "اكسده", "اختزال", "جدول دوري", "روابط", "تساهمي",
               "ايوني", "محلول", "تركيز", "بروتون", "نيوترون", "الكترون", "نووي"],
    "لغة عربية": ["جمله", "فاعل", "مفعول", "مبتدأ", "خبر", "نعت", "حال", "بلاغه",
                  "تشبيه", "استعاره", "كنايه", "طباق", "سجع", "قصيده", "شعر", "نحو",
                  "صرف", "اعراب", "همزه", "تاء مربوطه", "فصحي", "ادب", "قصه", "روايه"],
}


def looks_like_math(text: str) -> bool:
    if re.search(r"[0-9=+\-*/()^×÷√]", text.translate(AR_DIGITS)):
        return True
    t = normalize(text)
    return any(w in t for w in SUBJECT_WORDS["رياضيات"])


def classify_subject(text: str) -> str | None:
    """يحدد مادة السؤال تلقائيًا — كلمات المادة تتفوق على مجرد وجود أرقام"""
    t = normalize(text)
    best_subject, best_hits = None, 0
    for subject, words in SUBJECT_WORDS.items():
        hits = sum(1 for w in words if w in t)
        if hits > best_hits:
            best_subject, best_hits = subject, hits
    # مادة بكلمات مميزة (غير رياضيات) تفوز حتى لو وُجدت أرقام في السؤال
    if best_subject and best_subject != "رياضيات":
        return best_subject
    math_hits = sum(1 for w in SUBJECT_WORDS["رياضيات"] if w in t)
    if math_hits >= 1 or re.search(r"[0-9=+\-*/()^×÷√]", text.translate(AR_DIGITS)):
        return "رياضيات"
    return None


# ---------------- محرك الفيزياء المحلي (قوانين جاهزة) ----------------
def try_physics(text: str) -> str | None:
    """يحل المسائل الفيزيائية الشائعة بتطبيق القانون مباشرة على المعطيات"""
    t = normalize(text)
    nums = [float(x) for x in re.findall(r"[\d\.]+", t)]
    if not nums:
        return None

    patterns = [
        ("قانون اوم", "V = I × R (فرق الجهد = التيار × المقاومة)",
         lambda n: f"V = {fmt(n[0])} × {fmt(n[1])} = {fmt(n[0]*n[1])} فولت", 2),
        ("طاقه حركيه", "ط_ح = ½ × م × ص²",
         lambda n: f"ط_ح = ½ × {fmt(n[0])} × {fmt(n[1])}² = {fmt(0.5*n[0]*n[1]**2)} جول", 2),
        ("طاقه وضع", "ط_و = م × ع × هـ (ع ≈ 9.8)",
         lambda n: f"ط_و = {fmt(n[0])} × 9.8 × {fmt(n[1])} = {fmt(n[0]*9.8*n[1])} جول", 2),
        ("كميه التحرك", "ك = م × ص",
         lambda n: f"ك = {fmt(n[0])} × {fmt(n[1])} = {fmt(n[0]*n[1])} كجم×م/ث", 2),
        ("شغل", "ش = ق × د",
         lambda n: f"ش = {fmt(n[0])} × {fmt(n[1])} = {fmt(n[0]*n[1])} جول", 2),
        ("قدره", "ق = ش ÷ ز",
         lambda n: f"ق = {fmt(n[0])} ÷ {fmt(n[1])} = {fmt(n[0]/n[1])} واط", 2),
        ("كثافه", "ك = م ÷ ح",
         lambda n: f"ك = {fmt(n[0])} ÷ {fmt(n[1])} = {fmt(n[0]/n[1])} جم/سم³", 2),
        ("ضغط", "ض = ق ÷ أ",
         lambda n: f"ض = {fmt(n[0])} ÷ {fmt(n[1])} = {fmt(n[0]/n[1])} باسكال", 2),
        ("سرعه", "ص = المسافة ÷ الزمن",
         lambda n: f"ص = {fmt(n[0])} ÷ {fmt(n[1])} = {fmt(n[0]/n[1])} م/ث", 2),
        ("عجله", "ع = (السرعة النهائية − الابتدائية) ÷ الزمن",
         lambda n: f"ع = ({fmt(n[1])} − {fmt(n[0])}) ÷ {fmt(n[2])} = {fmt((n[1]-n[0])/n[2])} م/ث²", 3),
        ("قوه", "ق = م × ع",
         lambda n: f"ق = {fmt(n[0])} × {fmt(n[1])} = {fmt(n[0]*n[1])} نيوتن", 2),
        ("سقوط حر", "ص = ع × ز (ع = 9.8)",
         lambda n: f"ص = 9.8 × {fmt(n[0])} = {fmt(9.8*n[0])} م/ث", 1),
    ]
    for word, rule, calc, need in patterns:
        if word in t and len(nums) >= need:
            return solution(f"المعطيات الرقمية من السؤال: {', '.join(fmt(x) for x in nums[:need])}",
                            rule, calc(nums))
    return None


# ---------------- لوحة تحكم المشرفين ----------------
def is_admin(user_id) -> bool:
    return str(user_id) in get_admins()


async def admin_only(update: Update) -> bool:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("هذا الأمر مخصص للمشرفين فقط.")
        return False
    return True


def categorize(question: str, bot_reply: str) -> str:
    """تصنيف رسالة الطالب لتنبيه المشرف"""
    t = normalize(question)
    if bot_reply == UNCLEAR_REPLY:
        return "❓ رسالة لم يفهمها البوت — قد تحتاج تدخلك"
    if any(w in t for w in COMPLAINT_WORDS):
        return "📮 شكوى أو اقتراح من طالب"
    if any(w in t for w in HELP_WORDS):
        return "🆘 طلب مساعدة من طالب"
    return "💬 سؤال جديد"


async def notify_admins(ctx, user, question: str, bot_reply: str):
    """إرسال نسخة كاملة من المحادثة للمشرفين مع زر للرد المباشر على الطالب"""
    admins = get_admins()
    if str(user.id) in admins:      # لا نرسل للمشرف نسخًا من محادثته هو
        return
    who = f"@{user.username}" if user.username else "بدون اسم مستخدم"
    when = datetime.now().strftime("%Y-%m-%d %H:%M")
    tag = categorize(question, bot_reply)
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("↩️ رد على الطالب", callback_data=f"reply:{user.id}")
    ]])
    try:
        for admin in admins:
            await ctx.bot.send_message(
                chat_id=int(admin),
                text=(f"📩 {tag}\n"
                      f"الوقت: {when}\n"
                      f"الطالب: {who}\n"
                      f"المعرف: {user.id}\n"
                      f"رقم المحادثة: {user.id}\n"
                      f"السؤال: {question}"),
                reply_markup=keyboard)
            await ctx.bot.send_message(
                chat_id=int(admin),
                text=f"💬 رد البوت:\n{bot_reply}")
    except Exception as exc:
        logger.warning("تعذر إشعار المشرفين: %s", exc)


async def send_admin_reply(ctx, admin_id: int, student_id: int, text: str) -> bool:
    """إيصال رد المشرف إلى الطالب بهوية إدارة البوت فقط (دون كشف حساب المشرف)"""
    try:
        await ctx.bot.send_message(
            chat_id=student_id,
            text=f"إدارة بوت الرياضيات:\n{text}")
        log_conversation(student_id, f"رد من المشرف {admin_id}", f"[رسالة إدارية] {text}", "")
        return True
    except Exception as exc:
        logger.warning("تعذر إرسال الرد للطالب %s: %s", student_id, exc)
        return False


async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """المشرف ضغط زر «رد على الطالب»"""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.answer("هذا الزر للمشرفين فقط.", show_alert=True)
        return
    try:
        _, student_id = query.data.split(":", 1)
    except ValueError:
        return
    PENDING_REPLY[str(query.from_user.id)] = student_id
    await query.edit_message_reply_markup(reply_markup=None)
    await ctx.bot.send_message(
        chat_id=query.from_user.id,
        text=(f"✍️ اكتب الآن ردك على الطالب (المعرف {student_id}).\n"
              f"سيصل الطالب رسالتك بهوية «إدارة بوت الرياضيات» دون معرفة حسابك.\n"
              f"لإلغاء الرد اكتب /cancelreply"))


async def cmd_addadmin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    if not ctx.args or not ctx.args[0].isdigit():
        await update.message.reply_text("الاستخدام: /addadmin ثم معرف المستخدم (أرقام فقط)")
        return
    new_id = ctx.args[0]
    admins = set(str(i) for i in load_json(ADMINS_FILE, []))
    admins.add(new_id)
    save_json(ADMINS_FILE, sorted(admins))
    await update.message.reply_text(f"✅ تمت إضافة المشرف بالمعرف {new_id}")


async def cmd_removeadmin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    if not ctx.args or not ctx.args[0].isdigit():
        await update.message.reply_text("الاستخدام: /removeadmin ثم معرف المستخدم")
        return
    rm = ctx.args[0]
    admins = set(str(i) for i in load_json(ADMINS_FILE, []))
    if rm in admins:
        admins.discard(rm)
        save_json(ADMINS_FILE, sorted(admins))
        await update.message.reply_text(f"✅ تم حذف المشرف بالمعرف {rm}")
    else:
        await update.message.reply_text("هذا المعرف ليس في قائمة المشرفين.")


async def cmd_admins(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    admins = get_admins()
    await update.message.reply_text(
        "قائمة المشرفين (المعرفات):\n" + "\n".join(f"• {a}" for a in admins))


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    users = load_json(USERS_FILE, {})
    total = sum(1 for _ in open(LOG_FILE, encoding="utf-8")) if LOG_FILE.exists() else 0
    state = "يعمل ✅" if bot_enabled() else "متوقف ⏸️"
    await update.message.reply_text(
        f"📊 إحصائيات البوت\n"
        f"الحالة: {state}\n"
        f"عدد الطلاب المسجلين: {len(users)}\n"
        f"عدد الأسئلة والردود المسجلة: {total}")


async def cmd_chats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """عرض آخر المحادثات المسجلة"""
    if not await admin_only(update):
        return
    if not LOG_FILE.exists():
        await update.message.reply_text("لا توجد محادثات مسجلة بعد.")
        return
    n = 5
    if ctx.args and ctx.args[0].isdigit():
        n = max(1, min(20, int(ctx.args[0])))
    lines = open(LOG_FILE, encoding="utf-8").read().strip().split("\n")[-n:]
    out = []
    for line in lines:
        try:
            e = json.loads(line)
            who = f"@{e['username']}" if e.get("username") else e.get("user_id")
            out.append(f"🕒 {e['time']}\nالطالب: {who}\nس: {e['question'][:120]}\nج: {e['answer'][:150]}\n")
        except Exception:
            continue
    await update.message.reply_text("آخر المحادثات:\n\n" + "\n".join(out) if out else "لا شيء.")


async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    save_settings(enabled=False)
    await update.message.reply_text("⏸️ تم إيقاف البوت مؤقتًا — لن يرد على الطلاب حتى أمر التشغيل.")


async def cmd_run(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    save_settings(enabled=True)
    await update.message.reply_text("▶️ البوت يعمل الآن — يرد على الطلاب بشكل طبيعي.")


async def cmd_setwelcome(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    if not ctx.args:
        await update.message.reply_text("الاستخدام: /setwelcome ثم نص الترحيب الجديد")
        return
    save_settings(welcome=" ".join(ctx.args))
    await update.message.reply_text("✅ تم تحديث رسالة الترحيب:\n\n" + " ".join(ctx.args))


async def cmd_setchannel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    if not ctx.args:
        await update.message.reply_text("الاستخدام: /setchannel ثم رابط أو معرف القناة")
        return
    save_settings(channel=" ".join(ctx.args))
    await update.message.reply_text("✅ تم حفظ رابط القناة: " + " ".join(ctx.args))


async def cmd_addqa(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """بدء إضافة سؤال وإجابة لقاعدة البيانات — للمشرف فقط"""
    if not await admin_only(update):
        return
    PENDING_ADD[str(update.effective_user.id)] = {"step": "subject", "data": {}}
    await update.message.reply_text(
        "إضافة سؤال جديد لقاعدة البيانات 📝\n"
        "اختر المادة (اكتبها كما هي):\n" + "\n".join(DB_SUBJECTS) +
        "\n\nلإلغاء العملية اكتب /canceladd في أي وقت.")


async def cmd_subjectsqa(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """عرض محتويات قاعدة البيانات حسب المادة"""
    if not await admin_only(update):
        return
    counts = {}
    for e in load_db():
        counts[e.get("subject", "غير مصنف")] = counts.get(e.get("subject", "غير مصنف"), 0) + 1
    lines = [f"• {s}: {n} سؤال" for s, n in sorted(counts.items())]
    await update.message.reply_text(
        f"📚 محتويات قاعدة البيانات (المجموع: {sum(counts.values())} سؤال)\n" + "\n".join(lines))


# ---------------- الأوامر العامة ----------------
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not bot_enabled() and not is_admin(update.effective_user.id):
        await update.message.reply_text("⏸️ البوت متوقف مؤقتًا للصيانة، عُد لاحقًا.")
        return
    await update.message.reply_text(get_settings()["welcome"])


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_REPLY)


async def cmd_myid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"معرفك في تيليجرام هو:\n{update.effective_user.id}")


# ---------------- معالجة الرسائل ----------------
async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()
    uid = str(user.id)

    # تسجيل الطالب
    users = load_json(USERS_FILE, {})
    if uid not in users:
        users[uid] = {"name": user.full_name, "username": user.username,
                      "first_seen": datetime.now().isoformat(timespec="seconds")}
        save_json(USERS_FILE, users)

    # ---------- رد المشرف المباشر على طالب ----------
    if is_admin(user.id):
        # إلغاء الرد المعلّق
        if text.startswith("/cancelreply"):
            PENDING_REPLY.pop(uid, None)
            await update.message.reply_text("✅ تم إلغاء الرد المعلّق.")
            return
        # إضافة سؤال وإجابة لقاعدة البيانات (خطوات متتابعة)
        if text.startswith("/canceladd"):
            PENDING_ADD.pop(uid, None)
            await update.message.reply_text("✅ تم إلغاء الإضافة.")
            return
        if uid in PENDING_ADD:
            st = PENDING_ADD[uid]
            if st["step"] == "subject":
                subj = text.strip()
                if subj not in DB_SUBJECTS:
                    await update.message.reply_text(
                        "اختر مادة من القائمة التالية (اكتبها كما هي):\n" + "\n".join(DB_SUBJECTS))
                    return
                st["data"]["subject"] = subj
                st["step"] = "question"
                await update.message.reply_text(f"المادة: {subj} ✔️ اكتب الآن نص السؤال:")
            elif st["step"] == "question":
                st["data"]["question"] = text
                st["step"] = "answer"
                await update.message.reply_text("تمام! الآن اكتب الإجابة النموذجية:")
            elif st["step"] == "answer":
                d = st["data"]
                entries = load_db()
                entries.append({
                    "subject": d["subject"],
                    "keywords": list(set(normalize(d["question"]).split()))[:8],
                    "question": d["question"],
                    "answer": text,
                })
                save_db(entries)
                PENDING_ADD.pop(uid, None)
                await update.message.reply_text(
                    f"✅ تمت إضافة السؤال إلى قاعدة البيانات ({d['subject']}).")
            return
        # الطريقة 1: ضغط زر «رد على الطالب» ثم كتب الرد
        target = PENDING_REPLY.pop(uid, None)
        # الطريقة 2: ردّ مباشر على إشعار المحادثة (Reply على رسالة فيها المعرف)
        if target is None and update.message.reply_to_message:
            m = re.search(r"المعرف: (\d+)", update.message.reply_to_message.text or "")
            if m:
                target = m.group(1)
        if target is not None:
            ok = await send_admin_reply(ctx, user.id, int(target), text)
            if ok:
                await update.message.reply_text(f"✅ تم إرسال ردك إلى الطالب (المعرف {target}).")
            else:
                await update.message.reply_text("⚠️ تعذر إرسال الرد — ربما حظر الطالب البوت.")
            return

    # إيقاف مؤقت للطلاب فقط — المشرف يحتفظ بصلاحية التحكم دائمًا
    if not bot_enabled() and not is_admin(user.id):
        reply = "⏸️ البوت متوقف مؤقتًا للصيانة، عُد لاحقًا."
        await update.message.reply_text(reply)
        log_conversation(user.id, user.username or "", text, reply)
        await notify_admins(ctx, user, text, reply)
        return

    reply = build_reply(text)
    if reply is None:
        reply = UNCLEAR_REPLY

    await update.message.reply_text(reply)

    # حفظ المحادثة وإشعار المشرفين
    log_conversation(user.id, user.username or "", text, reply)
    await notify_admins(ctx, user, text, reply)


def main():
    if not TOKEN:
        raise SystemExit("ضع توكن البوت في متغير البيئة TELEGRAM_BOT_TOKEN")

    builder = Application.builder().token(TOKEN)
    if PROXY:
        builder = builder.proxy(PROXY).get_updates_proxy(PROXY)
        logger.info("سيتم استخدام البروكسي: %s", PROXY)

    app = builder.build()
    # أوامر عامة
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("myid", cmd_myid))
    # أوامر المشرفين
    app.add_handler(CommandHandler("addadmin", cmd_addadmin))
    app.add_handler(CommandHandler("removeadmin", cmd_removeadmin))
    app.add_handler(CommandHandler("admins", cmd_admins))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("chats", cmd_chats))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("run", cmd_run))
    app.add_handler(CommandHandler("setwelcome", cmd_setwelcome))
    app.add_handler(CommandHandler("setchannel", cmd_setchannel))
    app.add_handler(CommandHandler("addqa", cmd_addqa))
    app.add_handler(CommandHandler("subjectsqa", cmd_subjectsqa))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    logger.info("بوت الرياضيات يعمل الآن...")
    app.run_polling()


if __name__ == "__main__":
    main()
