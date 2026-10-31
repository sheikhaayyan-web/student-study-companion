"""
Assignment & Presentation Studio Generator.
Produces live editable documents and exports actual .docx and .pptx files using python-docx and python-pptx.
Supports dynamic generation via Live Gemini API with offline fallback.
"""

import os
import uuid
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from pptx import Presentation
from pptx.util import Inches as PptxInches, Pt as PptxPt
from pptx.dml.color import RGBColor as PptxRGBColor
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
        print(f"Notice: Live Gemini client not initialized in studio: {e}")

OUTPUT_DIR = os.getenv(
    "TALIB_GENERATED_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "generated_files"),
)
os.makedirs(OUTPUT_DIR, exist_ok=True)

def generate_draft_text(topic: str, level: str = "bachelors") -> str:
    """Generates assignment draft text."""
    if genai_client:
        try:
            prompt = (
                f"Write a university-grade academic assignment draft on the topic: '{topic}' "
                f"for a {level} level student.\n"
                "Structure it with Markdown headings: # Title, ## 1. Introduction, ## 2. Core Mechanics, ## 3. Practical Applications, ## 4. Conclusion & Academic References.\n"
                "Keep it concise, clear, and ready for editing."
            )
            response = genai_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[{"role": "user", "parts": [{"text": prompt}]}]
            )
            if response.text:
                return response.text
        except Exception as e:
            print(f"Studio live generation fallback: {e}")

    return None

def generate_assignment_docx(topic: str, content: str, student_name: str, level: str) -> str:
    """Generates an academic-formatted Microsoft Word (.docx) document."""
    doc = Document()

    # Title
    title_p = doc.add_paragraph()
    title_run = title_p.add_run(topic)
    title_run.font.name = "Arial"
    title_run.font.size = Pt(22)
    title_run.font.bold = True
    title_run.font.color.rgb = RGBColor(18, 50, 90)

    # Subtitle / Metadata
    sub_p = doc.add_paragraph()
    sub_run = sub_p.add_run(f"Student: {student_name} | Academic Tier: {level} | Prepared via TalibAI Ecosystem")
    sub_run.font.name = "Arial"
    sub_run.font.size = Pt(10)
    sub_run.font.italic = True
    sub_run.font.color.rgb = RGBColor(100, 100, 100)

    doc.add_paragraph("―" * 55)

    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("# "):
            h = doc.add_heading(line.replace("# ", ""), level=1)
            h.style.font.name = "Arial"
        elif line.startswith("## "):
            h = doc.add_heading(line.replace("## ", ""), level=2)
            h.style.font.name = "Arial"
        else:
            p = doc.add_paragraph(line)
            p.style.font.name = "Arial"
            p.style.font.size = Pt(11)

    filename = f"Assignment_{uuid.uuid4().hex}_{''.join(c for c in topic if c.isalnum() or c in ' _-')[:25].strip().replace(' ', '_')}.docx"
    filepath = os.path.join(OUTPUT_DIR, filename)
    doc.save(filepath)
    return filepath

def generate_presentation_pptx(topic: str, slides_data: list, student_name: str) -> str:
    """Generates a modern styled PowerPoint (.pptx) presentation."""
    prs = Presentation()

    if not slides_data:
        raise ValueError("Presentation slides are required")

    for s_idx, slide_info in enumerate(slides_data):
        blank_slide_layout = prs.slide_layouts[1 if s_idx > 0 else 0]
        slide = prs.slides.add_slide(blank_slide_layout)

        title_shape = slide.shapes.title
        title_shape.text = slide_info["title"]
        title_p = title_shape.text_frame.paragraphs[0]
        title_p.font.name = "Arial"
        title_p.font.size = PptxPt(28 if s_idx > 0 else 36)
        title_p.font.bold = True

        if s_idx > 0 and "bullets" in slide_info:
            body_shape = slide.placeholders[1]
            tf = body_shape.text_frame
            tf.clear()
            for b_idx, bullet in enumerate(slide_info["bullets"]):
                p = tf.add_paragraph() if b_idx > 0 else tf.paragraphs[0]
                p.text = bullet
                p.font.name = "Arial"
                p.font.size = PptxPt(16)

    filename = f"Presentation_{uuid.uuid4().hex}_{''.join(c for c in topic if c.isalnum() or c in ' _-')[:25].strip().replace(' ', '_')}.pptx"
    filepath = os.path.join(OUTPUT_DIR, filename)
    prs.save(filepath)
    return filepath
