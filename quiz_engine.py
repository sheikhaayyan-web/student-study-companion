"""
15-MCQ Learning Verification Engine.
Generates comprehensive 15-question assessments to verify true student comprehension.
Supports Live AI generation for any custom topic, plus curated offline question pools.
"""

import os
import json
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
        print(f"Notice: Live Gemini client not initialized in quiz engine: {e}")

# High-quality 15-question verified bank for Database Systems: Normalization
NORMALIZATION_15_MCQS = [
    {
        "id": 1,
        "question": "What primary problem does database normalization aim to eliminate?",
        "options": ["Slow network transmission", "Data redundancy and modification anomalies", "High CPU temperature", "Physical disk partition errors"],
        "correct_index": 1,
        "explanation": "Normalization organizes tables to eliminate insertion, deletion, and update anomalies while minimizing data redundancy."
    },
    {
        "id": 2,
        "question": "A table is in First Normal Form (1NF) if and only if:",
        "options": ["It has no foreign keys", "All attributes contain atomic (indivisible) values", "It has more than three columns", "It contains at least one composite primary key"],
        "correct_index": 1,
        "explanation": "1NF requires that each column contain only single atomic values and no repeating groups or arrays."
    },
    {
        "id": 3,
        "question": "Second Normal Form (2NF) directly eliminates which type of dependency?",
        "options": ["Transitive dependency", "Partial functional dependency on a candidate key", "Multi-valued dependency", "Join dependency"],
        "correct_index": 1,
        "explanation": "2NF requires the table to be in 1NF and guarantees that no non-prime attribute is functionally dependent on a subset of any candidate key."
    },
    {
        "id": 4,
        "question": "If A -> B and B -> C, then A -> C is an example of what dependency?",
        "options": ["Trivial dependency", "Partial dependency", "Transitive dependency", "Cyclic dependency"],
        "correct_index": 2,
        "explanation": "A transitive dependency occurs when an indirect functional relationship exists between non-key attributes via an intermediary."
    },
    {
        "id": 5,
        "question": "Third Normal Form (3NF) requires that for every non-trivial functional dependency X -> Y:",
        "options": ["X is a superkey OR Y is a prime attribute", "X must be an integer", "Y must always be null", "X and Y must reside in different tables"],
        "correct_index": 0,
        "explanation": "Under 3NF, either X is a superkey or Y is a prime attribute (part of any candidate key)."
    },
    {
        "id": 6,
        "question": "How does Boyce-Codd Normal Form (BCNF) differ from 3NF?",
        "options": ["BCNF permits partial dependencies", "BCNF strictly requires X to be a superkey for every non-trivial X -> Y", "BCNF is weaker than 3NF", "BCNF only applies to NoSQL databases"],
        "correct_index": 1,
        "explanation": "BCNF eliminates the 3NF exception where Y could be a prime attribute. In BCNF, every determinant X must be a superkey."
    },
    {
        "id": 7,
        "question": "Which anomaly occurs when deleting a student record unintentionally deletes course details?",
        "options": ["Insertion anomaly", "Deletion anomaly", "Update anomaly", "Read anomaly"],
        "correct_index": 1,
        "explanation": "A deletion anomaly occurs when the removal of one piece of data results in the unintentional loss of unrelated essential information."
    },
    {
        "id": 8,
        "question": "What is a 'prime attribute'?",
        "options": ["An attribute that is a prime number", "An attribute that belongs to at least one candidate key", "The first column in a table", "An attribute with no null values"],
        "correct_index": 1,
        "explanation": "A prime attribute is any attribute that forms a member of any candidate key in the relation."
    },
    {
        "id": 9,
        "question": "A decomposition of relation R into R1 and R2 is 'lossless-join' if:",
        "options": ["R1 and R2 have no common attributes", "R1 union R2 has fewer columns than R", "R1 intersect R2 is a superkey in R1 or R2", "R1 and R2 are stored on different disks"],
        "correct_index": 2,
        "explanation": "Lossless decomposition ensures the natural join of R1 and R2 reconstructs original relation R without generating spurious tuples."
    },
    {
        "id": 10,
        "question": "Can every relational schema be decomposed into BCNF while always preserving dependencies?",
        "options": ["Yes, always", "No, dependency preservation is not guaranteed in BCNF", "Only if the database uses PostgreSQL", "Only if there are no primary keys"],
        "correct_index": 1,
        "explanation": "A classic theoretical property: 3NF guarantees both lossless join and dependency preservation, but BCNF may sacrifice dependency preservation."
    },
    {
        "id": 11,
        "question": "Fourth Normal Form (4NF) specifically handles which kind of dependency?",
        "options": ["Multi-valued dependencies (MVD)", "Transitive dependencies", "Join dependencies", "Foreign key dependencies"],
        "correct_index": 0,
        "explanation": "4NF addresses multi-valued dependencies where independent multi-valued facts are stored in the same relation."
    },
    {
        "id": 12,
        "question": "Fifth Normal Form (5NF) is also widely known as:",
        "options": ["Domain-Key Normal Form", "Project-Join Normal Form (PJNF)", "Atomic Normal Form", "Binary Normal Form"],
        "correct_index": 1,
        "explanation": "5NF is termed Project-Join Normal Form because it prevents anomalies arising from join dependencies of three or more relations."
    },
    {
        "id": 13,
        "question": "If relation R(A, B, C) has functional dependencies AB -> C and C -> B, what are its candidate keys?",
        "options": ["Only AB", "AB and AC", "Only C", "A, B, and C independently"],
        "correct_index": 1,
        "explanation": "(AB)+ = {A,B,C}. Since C -> B, (AC)+ = {A,C,B}. Thus both AB and AC are valid candidate keys."
    },
    {
        "id": 14,
        "question": "Why might a database architect intentionally denormalize a database in production?",
        "options": ["To save disk space", "To improve read query performance by avoiding expensive multi-table joins", "Because normalization is obsolete", "To make SQL queries longer"],
        "correct_index": 1,
        "explanation": "Denormalization introduces controlled redundancy to speed up heavy analytical read queries (OLAP) at the expense of update costs."
    },
    {
        "id": 15,
        "question": "What is the closure of an attribute set under a set of functional dependencies?",
        "options": ["The attributes that can be deleted", "The complete set of attributes functionally determined by that set", "The first row in the table", "The database backup file"],
        "correct_index": 1,
        "explanation": "The attribute closure X+ represents all attributes that can be functionally derived from X using Armstrong's axioms."
    }
]

# In-memory session store for active quiz sessions
ACTIVE_QUIZZES = {}


class QuizUnavailableError(Exception):
    pass


def get_15_mcqs_for_topic(topic_title: str) -> dict:
    """
    Returns 15 MCQs for any given topic.
    If live Gemini client is present and topic is not normalization, generates on the fly!
    """
    is_normalization_topic = any(term in topic_title.lower() for term in ("normaliz", "bcnf", "3nf"))
    if genai_client and not is_normalization_topic:
        try:
            prompt = (
                f"You are an expert university examiner. Generate exactly 15 rigorous multiple-choice questions "
                f"to test student comprehension of the academic topic: '{topic_title}'.\n"
                "Return ONLY a valid JSON array of 15 objects. Each object must have:\n"
                "- 'id': integer from 1 to 15\n"
                "- 'question': string\n"
                "- 'options': array of 4 distinct string choices\n"
                "- 'correct_index': integer from 0 to 3 pointing to the correct choice\n"
                "- 'explanation': string explaining why that answer is correct\n"
                "Do not wrap in markdown quotes if possible, output pure JSON."
            )
            response = genai_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[{"role": "user", "parts": [{"text": prompt}]}]
            )
            raw = response.text.strip()
            if raw.startswith("```json"):
                raw = raw[7:]
            if raw.endswith("```"):
                raw = raw[:-3]
            generated_questions = json.loads(raw.strip())
            if isinstance(generated_questions, list) and len(generated_questions) == 15 and all(
                isinstance(question, dict)
                and isinstance(question.get("question"), str)
                and isinstance(question.get("options"), list)
                and len(question["options"]) == 4
                and question.get("correct_index") in range(4)
                and isinstance(question.get("explanation"), str)
                for question in generated_questions
            ):
                ACTIVE_QUIZZES[topic_title] = generated_questions
                return {
                    "topic": topic_title,
                    "total_questions": len(generated_questions),
                    "passing_threshold_pct": 70.0,
                    "min_correct_to_pass": 11,
                    "questions": generated_questions
                }
        except Exception as e:
            print(f"Notice: Failed to generate live MCQs ({e}). Using standard verified bank.")

    if not is_normalization_topic:
        raise QuizUnavailableError("A topic-specific quiz requires a configured AI service.")
    ACTIVE_QUIZZES[topic_title] = NORMALIZATION_15_MCQS
    return {
        "topic": topic_title,
        "total_questions": len(NORMALIZATION_15_MCQS),
        "passing_threshold_pct": 70.0,
        "min_correct_to_pass": 11,
        "questions": NORMALIZATION_15_MCQS
    }

def evaluate_quiz_submission(user_answers: dict, topic_title: str = "BCNF & Normalization", questions: list | None = None) -> dict:
    """
    Evaluates the 15-MCQ submission.
    user_answers is a dict like {"1": 1, "2": 1, "3": 0, ...}
    """
    questions = questions or ACTIVE_QUIZZES.get(topic_title, NORMALIZATION_15_MCQS)
    total = len(questions)
    correct_count = 0
    feedback = []

    for q in questions:
        qid_str = str(q["id"])
        selected = user_answers.get(qid_str)
        is_correct = (selected == q["correct_index"])
        if is_correct:
            correct_count += 1
        
        feedback.append({
            "id": q["id"],
            "question": q["question"],
            "user_choice": selected,
            "correct_choice": q["correct_index"],
            "is_correct": is_correct,
            "explanation": q["explanation"]
        })

    score_pct = round((correct_count / total) * 100, 1) if total > 0 else 0
    passed = score_pct >= 70.0

    return {
        "score_pct": score_pct,
        "correct_count": correct_count,
        "total_questions": total,
        "passed": passed,
        "message": "🎉 Outstanding! You passed the 15-MCQ verification gatekeeper (>= 70%). Topic is now verified on your timetable!" if passed else "⚠️ You scored below 70%. Review the explanations below and re-test to verify this topic.",
        "feedback": feedback
    }
