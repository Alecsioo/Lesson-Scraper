import json
import os
from pathlib import Path
from tqdm import tqdm
from database.database import driver, verify_connection, close_driver
from dotenv import load_dotenv

load_dotenv()

DATABASE = os.getenv("NEO4J_DATABASE")
PATH = "01-cleaned_courses"
TYPES = {"true_false", "multiple_choice"}
FAMILY = "QUESTION"

# Metadati percorso
PATH_LANGUAGE_IDX = 0
PATH_LEVEL_IDX = 2
PATH_CHAPTER_IDX = 3
PATH_LESSON_IDX = 4
PATH_MIN_DEPTH = 5

# ── helpers ──────────────────────────────────────────────────────────────────

def _parse_level(raw: str) -> str:
    """'pack_level_it_a1' -> 'A1'"""
    return raw.rsplit("_", 1)[-1].upper()

def _extract_path_metadata(path: Path, base_path: Path) -> dict | None:
    parts = path.relative_to(base_path).parts
    if len(parts) < PATH_MIN_DEPTH:
        return None
    return {
        "language": parts[PATH_LANGUAGE_IDX],
        "level": _parse_level(parts[PATH_LEVEL_IDX]),
        "chapter": parts[PATH_CHAPTER_IDX],
        "lesson": parts[PATH_LESSON_IDX].replace(".json", "")
    }

def make_question_root_text(exercise: dict, exercise_type: str) -> str:
    if exercise_type == "true_false":
        context = exercise.get("context_text_orig", "")
        statement = exercise.get("statement_title_en", "")
        return f"{context}\n\n{statement}".strip()
    return exercise.get("instructions", "Multiple Choice Question")

# ── extraction ────────────────────────────────────────────────────────────────

def extract_questions(base_dir: str) -> list[dict]:
    results = []
    base_path = Path(base_dir)
    json_files = list(base_path.rglob("*.json"))

    for path in tqdm(json_files, desc="Scanning JSON files"):
        meta = _extract_path_metadata(path, base_path)
        if not meta: continue

        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        for unit in data.get("units", []):
            for exercise in unit.get("exercises", []):
                ex_type = exercise.get("type")
                if ex_type not in TYPES: continue

                ex_id = exercise.get("exercise_id")
                root_text = make_question_root_text(exercise, ex_type)
                if not root_text or not ex_id: continue

                answers = []
                if ex_type == "true_false":
                    is_correct = bool(exercise.get("is_correct"))
                    answers = [
                        {"text": "True", "isCorrect": is_correct},
                        {"text": "False", "isCorrect": not is_correct}
                    ]
                else:
                    sol = exercise.get("solution_text_orig")
                    if sol:
                        answers.append({"text": sol, "isCorrect": True})
                    for opt in exercise.get("options", []):
                        if opt:
                            answers.append({"text": str(opt), "isCorrect": False})

                results.append({
                    "exercise_id": ex_id,
                    "root_text": root_text,
                    "answers": answers,
                    **meta
                })
    return results

# ── import ────────────────────────────────────────────────────────────────────

def import_question(tx, item: dict):
    # 1. Pulizia preventiva (Idempotenza)
    tx.run("""
        MATCH (ls:Lesson {name: $ls})-[r:HAS_START_NODE {exercise_id: $ex_id}]->(q:ContentNode)
        OPTIONAL MATCH (q)-[:HAS_ANSWER]->(a:ContentNode)
        DETACH DELETE q, a
    """, ls=item["lesson"], ex_id=item["exercise_id"])

    # 2. Struttura Gerarchica (Language -> Level -> Chapter -> Lesson)
    tx.run("""
        MERGE (lang:Language {code: $lang})
        MERGE (lvl:Level {name: $lvl})
        MERGE (ch:Chapter {name: $ch})
        MERGE (ls:Lesson {name: $ls})
        MERGE (lang)-[:HAS_LEVEL]->(lvl)
        MERGE (lvl)-[:HAS_CHAPTER]->(ch)
        MERGE (ch)-[:HAS_LESSON]->(ls)
    """, lang=item["language"], lvl=item["level"], ch=item["chapter"], ls=item["lesson"])

    # 3. Nodo Family
    tx.run("MERGE (f:Family {name: 'QUESTION'})")

    # 4. Creazione Domanda (Senza campo 'type' nella relazione)
    res = tx.run("""
        MATCH (ls:Lesson {name: $ls})
        MATCH (f:Family {name: 'QUESTION'})
        CREATE (q:ContentNode {text: $text})
        CREATE (ls)-[:HAS_START_NODE {exercise_id: $ex_id}]->(q)
        CREATE (q)-[:IS_OF_FAMILY]->(f)
        RETURN elementId(q) as q_id
        """, text=item["root_text"], ls=item["lesson"], ex_id=item["exercise_id"])
    
    q_id = res.single()["q_id"]

    # 5. Creazione Risposte (Solo informazione isCorrect)
    for ans in item["answers"]:
        tx.run("""
            MATCH (q) WHERE elementId(q) = $q_id
            CREATE (a:ContentNode {text: $ans_text})
            CREATE (q)-[:HAS_ANSWER {isCorrect: $isCorrect}]->(a)
        """, q_id=q_id, ans_text=ans["text"], isCorrect=ans["isCorrect"])

def run_import(base_dir: str):
    verify_connection()
    questions = extract_questions(base_dir)

    if not questions:
        print("[INFO] No questions to import")
        return

    with driver.session(database=DATABASE) as session:
        for item in tqdm(questions, desc="Importing Questions"):
            session.execute_write(import_question, item)

    print("[INFO] Import complete")

if __name__ == "__main__":
   run_import(PATH)