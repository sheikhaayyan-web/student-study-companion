"""
Lecture Finder & Short Courses Service.
Provides curated educational YouTube lectures in English and Urdu,
plus top-viewed short courses and skill-development tracks.
"""

CURATED_LECTURES = {
    "normalization": [
        {
            "id": "vid_norm_1",
            "title": "BCNF (Boyce-Codd Normal Form) Complete Explanation with Solved Examples",
            "channel": "Gate Smashers",
            "language": "Urdu / Hindi",
            "youtube_url": "https://www.youtube.com/results?search_query=gate+smashers+bcnf",
            "topic": "BCNF & 3NF Decomposition Anomalies",
            "difficulty": "Undergraduate"
        },
        {
            "id": "vid_norm_2",
            "title": "Database Normalization – 1NF, 2NF, 3NF, BCNF Explained Simply",
            "channel": "Fireship",
            "language": "English",
            "youtube_url": "https://www.youtube.com/results?search_query=fireship+database+normalization",
            "topic": "BCNF & 3NF Decomposition Anomalies",
            "difficulty": "All Levels"
        },
        {
            "id": "vid_norm_3",
            "title": "DBMS Lecture 24: BCNF with Functional Dependencies Proofs",
            "channel": "NPTEL / IIT",
            "language": "English",
            "youtube_url": "https://www.youtube.com/results?search_query=nptel+dbms+bcnf",
            "topic": "BCNF & 3NF Decomposition Anomalies",
            "difficulty": "Advanced"
        }
    ],
    "btree": [
        {
            "id": "vid_btree_1",
            "title": "B-Tree Insertion and Search Operations in Data Structures",
            "channel": "Abdul Bari",
            "language": "English",
            "youtube_url": "https://www.youtube.com/results?search_query=abdul+bari+b+tree",
            "topic": "B-Tree vs B+ Tree Search Complexity",
            "difficulty": "Undergraduate"
        },
        {
            "id": "vid_btree_2",
            "title": "B Trees and B+ Trees in DBMS in Urdu / Hindi",
            "channel": "Knowledge Gate",
            "language": "Urdu / Hindi",
            "youtube_url": "https://www.youtube.com/results?search_query=knowledge+gate+b+tree",
            "topic": "B-Tree vs B+ Tree Search Complexity",
            "difficulty": "Undergraduate"
        }
    ]
}

SHORT_COURSES = [
    {
        "id": "course_python",
        "title": "Python for Beginners (Full Course 2026)",
        "instructor": "FreeCodeCamp / Programming with Mosh",
        "category": "Programming",
        "language": "English & Urdu available",
        "level": "Beginner to Intermediate",
        "youtube_search": "https://www.youtube.com/results?search_query=python+for+beginners+full+course",
        "icon": "fa-brands fa-python"
    },
    {
        "id": "course_freelancing",
        "title": "Freelancing on Upwork & Fiverr: Complete Guide",
        "instructor": "Hisham Sarwar / Azad Chaiwala",
        "category": "Career & Freelancing",
        "language": "Urdu",
        "level": "All Levels",
        "youtube_search": "https://www.youtube.com/results?search_query=hisham+sarwar+freelancing+complete+course",
        "icon": "fa-solid fa-briefcase"
    },
    {
        "id": "course_design",
        "title": "UI/UX Design in Figma: From Zero to Hero",
        "instructor": "GFXMentor (Imran Ali Dina)",
        "category": "Graphic & UI Design",
        "language": "Urdu / Hindi",
        "level": "Beginner",
        "youtube_search": "https://www.youtube.com/results?search_query=gfxmentor+figma+complete+course",
        "icon": "fa-brands fa-figma"
    },
    {
        "id": "course_prompt_ai",
        "title": "Generative AI & Prompt Engineering Masterclass",
        "instructor": "Andrew Ng / DeepLearning.AI",
        "category": "Artificial Intelligence",
        "language": "English",
        "level": "Beginner to Pro",
        "youtube_search": "https://www.youtube.com/results?search_query=andrew+ng+prompt+engineering+for+developers",
        "icon": "fa-solid fa-wand-magic-sparkles"
    }
]

def get_curated_lectures(topic_keyword: str = "normalization") -> list:
    k = topic_keyword.lower()
    if "tree" in k or "index" in k:
        return CURATED_LECTURES.get("btree", [])
    if any(term in k for term in ("normaliz", "bcnf", "3nf")):
        return CURATED_LECTURES.get("normalization", [])
    return []

def get_short_courses() -> list:
    return SHORT_COURSES
