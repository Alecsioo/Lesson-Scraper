import json
import re
from pathlib import Path
from tqdm import tqdm
from database import driver, verify_connection, close_driver

DATABASE = "neo4j"
PATH = "v2/01-cleaned_courses/es"
TYPES = {"true_false", "multiple_choice"}

# ── helpers ──────────────────────────────────────────────────────────────────

def make_question_text(exercise: dict, exercise_type: str) -> str | None:
    if exercise_type == "true_false":
        return {
            "context": exercise.get("context_text_orig"),
            "statement": exercise.get("statement_title_en")
        }
    # Per multiple_choice usiamo instructions come testo della domanda
    return exercise.get("instructions")

def make_answers(exercise: dict, exercise_type: str) -> list[dict] | None:
    """
    Ritorna una lista di dizionari con metadati per le risposte.
    """
    if exercise_type == "multiple_choice":
        answers = []
        correct = exercise.get("solution_text_orig")
        if correct:
            answers.append({"text": correct, "correct": True})
        for i, opt in enumerate(exercise.get("options", []), 1):
            if opt:
                answers.append({"text": str(opt), "correct": False})
        return answers

    return None

# ── extraction ────────────────────────────────────────────────────────────────

def extract_questions(base_dir: str) -> list[dict]:
    results = []
    base_path = Path(base_dir)

    json_files = list(base_path.rglob("*.json"))
    for path in tqdm(json_files, desc="Scanning JSON files"):
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        for unit in data.get("units", []):
            for exercise in unit.get("exercises", []):
                ex_type = exercise.get("type")
                if ex_type not in TYPES: continue

                q_text = make_question_text(exercise, ex_type)
                ex_id = exercise.get("exercise_id")
                
                if not q_text or not ex_id: continue

                if ex_type == "true_false":
                    results.append({
                        "exercise_id": ex_id,
                        "exercise_type": ex_type,
                        "question_text": q_text,
                        "is_correct": bool(exercise.get("is_correct")),
                        "answers": None
                    })
                else:
                    answers = make_answers(exercise, ex_type)
                    if answers:
                        results.append({
                            "exercise_id": ex_id,
                            "exercise_type": ex_type,
                            "question_text": q_text,
                            "answers": answers
                        })
    return results

# ── import ────────────────────────────────────────────────────────────────────

def import_question(tx, item: dict):
    ex_id = item["exercise_id"]
    ex_type = item["exercise_type"]
    
    if ex_type == "true_false":
        # Il nodo radice unisce Contesto e Affermazione per dare senso alla domanda
        q_data = item["question_text"]
        root_text = f"{q_data['context']}\n\n{q_data['statement']}"
        
        # Generiamo le due opzioni standard
        is_correct = item["is_correct"]
        answers = [
            {"text": "True", "correct": is_correct},
            {"text": "False", "correct": not is_correct}
        ]
    else:
        # Multiple Choice standard
        root_text = item["question_text"]
        answers = item["answers"]

    # 1. MERGE del nodo radice (Solo TEXT)
    tx.run("MERGE (q:ContentNode {text: $root_text})", root_text=root_text)

    # 2. Creazione delle relazioni HAS_ANSWER
    for ans in answers:
        tx.run("""
            MATCH (q:ContentNode {text: $root_text})
            MERGE (a:ContentNode {text: $ans_text})
            MERGE (q)-[r:HAS_ANSWER {exercise_id: $ex_id}]->(a)
            SET r.family = "QUESTION",
                r.exercise_type = $ex_type,
                r.correct = $correct
            """, 
            root_text=root_text,
            ans_text=ans["text"],
            ex_id=ex_id,
            ex_type=ex_type,
            correct=ans["correct"]
        )

def run_import(base_dir: str):
    verify_connection()
    questions = extract_questions(base_dir)
    with driver.session(database=DATABASE) as session:
        for item in tqdm(questions, desc="Importing"):
            session.execute_write(import_question, item)
    close_driver()

if __name__ == "__main__":
    run_import(PATH)