"""
Adaptive Socratic Tutor Engine for TalibAI.
Supports Live Google Gemini API with seamless offline fallback.
Adapts depth, vocabulary, and pedagogy strictly to the student's academic tier.
"""

import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

genai_client = None
if GEMINI_API_KEY:
    try:
        from google import genai
        genai_client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"Notice: Live Gemini client not initialized ({e}). Using offline engine.")

LEVEL_DIRECTIVES = {
    "class_9_10": (
        "You are teaching a Secondary School / Matric / O-Level student (Ages 14-16). "
        "Use simple, encouraging language, everyday analogies (sports, school, daily life), and break math/code down into single steps. "
        "Avoid dense postgraduate jargon."
    ),
    "class_11_12": (
        "You are teaching a Higher Secondary / Intermediate / FSc / A-Level student. "
        "Align with board examination rubrics. Give precise textbook definitions, formulas with standard units, and structured bullet points."
    ),
    "bachelors": (
        "You are teaching a University Undergraduate student (BS / Engineering / Computer Science). "
        "Be rigorous, academic, and practical. Discuss time/space complexity (Big-O), system architecture tradeoffs, and edge cases."
    ),
    "masters": (
        "You are teaching a Postgraduate / Master's / PhD researcher. "
        "Provide critical theoretical analysis, references to state-of-the-art literature, epistemological limits, and comparative research critiques."
    )
}

OFFLINE_FALLBACKS = {
    "normalization": {
        "class_9_10": "Normalization is like organizing your school desk! If you scatter your homework papers across five different folders, you waste time finding them. In a database, we organize data into clean tables so you don't repeat the same student's phone number 10 times.",
        "class_11_12": "Normalization is a systematic process of decomposing database tables to eliminate redundancy and insertion/deletion/update anomalies. 1NF eliminates repeating groups; 2NF eliminates partial dependencies; 3NF eliminates transitive dependencies.",
        "bachelors": "Normalization decomposes relations with functional dependencies to satisfy normal forms up to BCNF. In BCNF, for every functional dependency X -> Y, determinant X must strictly be a Super Key. This guarantees elimination of all redundancy attributable to functional dependencies.",
        "masters": "Relational decomposition algorithms seek lossless-join and dependency-preserving properties. BCNF guarantees elimination of all redundancy from functional dependencies, though non-dependency-preserving decompositions necessitate trade-offs in distributed ACID transaction overhead.",
        "urdu": "ڈیٹا بیس نارملائزیشن (Normalization) ایک ایسا منظم طریقہ کار ہے جس کے ذریعے ٹیبلز میں غیر ضروری معلومات کی تکرار (Redundancy) کو ختم کیا جاتا ہے تاکہ ڈیٹا داخل کرتے یا حذف کرتے وقت خرابیاں (Anomalies) پیدا نہ ہوں۔ بی سی این ایف (BCNF) میں ہر وہ کالم جو کسی دوسرے کالم کا تعین کرے، وہ لازمی 'سپر کی' (Super Key) ہونا چاہیے۔"
    },
    "btree": {
        "class_9_10": "A B-Tree is like an organized library catalogue! Instead of looking through all 10,000 books one by one, you look at the section letter, then the shelf number, finding your book in 3 quick steps!",
        "class_11_12": "A B-Tree is a self-balancing search tree where each internal node can hold multiple keys and children. It guarantees search, insertion, and deletion operations run in O(log n) time.",
        "bachelors": "B-Trees minimize disk I/O latency by sizing tree nodes to match OS disk block pages (typically 4KB). High fan-out reduces tree height to 3-4 levels for millions of records, yielding O(log_B N) block reads.",
        "masters": "Cache-conscious B-Trees optimize cache lines and SSD block-erase cycles through sequential leaf scans, write amplification mitigation (LSM comparison), and latch-free concurrency.",
        "urdu": "بی ٹری (B-Tree) ایک خود کو متوازن رکھنے والا سرچ ٹری ہے۔ اس کا ایک نوڈ کمپیوٹر ہارڈ ڈسک کے ایک بلاک کے برابر ہوتا ہے، جس سے ڈیٹا بیس بغیر کسی تاخیر کے لاکھوں ریکارڈز میں سے مطلوبہ معلومات سیکنڈوں میں تلاش کر لیتا ہے۔"
    }
}

def generate_tutor_response(query: str, level: str = "bachelors", language: str = "en", mode: str = "tutor", context: str | None = None) -> dict:
    level = level.lower()
    if level not in LEVEL_DIRECTIVES:
        level = "bachelors"

    tier_directive = LEVEL_DIRECTIVES[level]
    lang_directive = "Provide your answer in Urdu (اردو) using clear, natural educational phrasing." if language == "ur" else "Provide your answer in clear, articulate English."

    # If Live Gemini client is configured, call Gemini API
    if genai_client:
        try:
            system_prompt = (
                f"{tier_directive}\n{lang_directive}\n"
                "You are 'Prof. Talib', an empathetic, brilliant academic tutor. "
                + ("Use the Socratic method: provide an intuitive hint, ask an insightful follow-up question, and guide them to discover the solution rather than spoon-feeding it." if mode == "hint" else "Explain clearly, step-by-step, with practical examples.")
            )
            response = genai_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[
                    {"role": "user", "parts": [{"text": f"System Directive:\n{system_prompt}\n\nStudent Query:\n{query}\n\nReference Material:\n{context or 'No reference material supplied.'}"}]}
                ]
            )
            if response.text:
                return {
                    "response": response.text,
                    "mode": mode,
                    "level": level,
                    "language": language,
                    "source": "live_gemini"
                }
        except Exception as err:
            print(f"Gemini live API error: {err}. Falling back to curated engine.")

    # Graceful fallback: Curated Offline Engine
    q_lower = query.lower()
    topic = None
    if any(k in q_lower for k in ["normaliz", "bcnf", "3nf", "anomaly", "redundancy"]):
        topic = "normalization"
    elif any(k in q_lower for k in ["btree", "b-tree", "index", "disk", "i/o"]):
        topic = "btree"

    if mode == "hint":
        hint = "💡 **Teacher Hint:** Notice the relationship between the determinant and the candidate key. Ask yourself: Can a non-candidate attribute determine other columns without causing duplicate data?"
        if language == "ur":
            hint = "💡 **استاد کی رہنمائی:** ہمیشہ چیک کریں کہ کیا معلومات کا تعین کرنے والی 'کی' (Key) ایک سپر کی ہے یا نہیں؟ اگر نہیں ہے تو ڈیٹا دہرایا جائے گا۔"
        return {"response": hint, "mode": "hint", "level": level, "language": language, "source": "offline"}

    if language == "ur":
        if topic:
            body = OFFLINE_FALLBACKS[topic]["urdu"]
        else:
            body = f"بہت عمدہ سوال ہے! آپ نے پوچھا: '{query}'۔ آپ کی منتخب کردہ سطح ({level}) کے مطابق:\n\nاس تصور کو سمجھنے کے لیے پہلے بنیادی اصول پر غور کریں، پھر اس کا اطلاق عملی مسائل پر کریں۔ کیا آپ چاہیں گے کہ میں اسے مثال کے ساتھ مزید واضح کروں؟"
    else:
        if topic:
            body = OFFLINE_FALLBACKS[topic][level]
        else:
            body = f"Regarding your question on **'{query}'** at the **{level.capitalize()}** level:\n\nThe core concept centers on structured decomposition and underlying principles according to university and college rubrics.\n\nWould you like a worked example, past exam questions, or a practice quiz on this?"

    return {
        "response": body,
        "mode": mode,
        "level": level,
        "language": language,
        "source": "offline"
    }
