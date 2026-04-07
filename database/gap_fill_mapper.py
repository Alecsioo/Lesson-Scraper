import os
import json
import re
from pathlib import Path
from tqdm import tqdm
from database.database import driver, verify_connection, close_driver
from dotenv import load_dotenv

load_dotenv()

DATABASE = os.getenv("NEO4J_DATABASE")
PATH = "01-cleaned_courses"
TYPES = {"gap_fill_click", "gap_fill_multiple"}

# Metadati percorso
PATH_LANGUAGE_IDX = 0
PATH_LEVEL_IDX = 2
PATH_CHAPTER_IDX = 3
PATH_LESSON_IDX = 4
PATH_MIN_DEPTH = 5

# ── helpers ──────────────────────────────────────────────────────────────────

def _parse_level(raw: str) -> str:
    return raw.rsplit("_", 1)[-1].upper()

def _extract_path_metadata(path: Path, base_path: Path) -> dict | None:
    parts = path.relative_to(base_path).parts
    if len(parts) < PATH_MIN_DEPTH: return None
    return {
        "language": parts[PATH_LANGUAGE_IDX],
        "level": _parse_level(parts[PATH_LEVEL_IDX]),
        "chapter": parts[PATH_CHAPTER_IDX],
        "lesson": parts[PATH_LESSON_IDX].replace(".json", "")
    }

def extract_items(exercise: dict, ex_type: str):
    gap_sentence = exercise.get("gap_sentence_orig", "")
    if not gap_sentence: return None

    if ex_type == "gap_fill_click":
        correct_list = [exercise.get("correct_answer", "")]
    else:
        correct_list = exercise.get("correct_answers", [])
    
    all_distractors = exercise.get("options", [])
    parts = re.findall(r"_+|[¿?¡!\wáéíóúüñ]+", gap_sentence)
    
    tokens = []
    gap_counter = 0 
    
    for p in parts:
        if p.startswith('_'):
            if gap_counter < len(correct_list):
                tokens.append({
                    "text": correct_list[gap_counter],
                    "isTarget": True,
                    "options": all_distractors 
                })
                gap_counter += 1
        else:
            tokens.append({
                "text": p,
                "isTarget": False,
                "options": []
            })
    return tokens

# ── extraction ────────────────────────────────────────────────────────────────

def extract_all_gap_fills(base_dir: str) -> list[dict]:
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

                items = extract_items(exercise, ex_type)
                if items:
                    results.append({
                        "exercise_id": exercise.get("exercise_id"),
                        "tokens": items,
                        **meta
                    })
    return results

# ── import ────────────────────────────────────────────────────────────────────

def import_gap_fill(tx, item: dict):
    ex_id = item["exercise_id"]
    tokens = item["tokens"]
    
    # 1. Creazione Pool Opzioni (Corrette di tutti i gap + Distrattori)
    all_correct_texts = [t["text"] for t in tokens if t["isTarget"]]
    distractors = []
    for t in tokens:
        if t["options"]:
            distractors = t["options"]
            break
    full_options_pool = list(set(all_correct_texts + distractors))

    # 2. Pulizia Idempotenza
    tx.run("""
        MATCH (ls:Lesson {name: $ls})-[r:HAS_START_NODE {exercise_id: $ex_id}]->(n:ContentNode)
        MATCH (n)-[:NEXT*0..]->(m)
        OPTIONAL MATCH (m)-[:HAS_ANSWER]->(o)
        DETACH DELETE m, o
    """, ls=item["lesson"], ex_id=ex_id)

    # 3. Struttura Gerarchica (MERGE)
    tx.run("""
        MERGE (lang:Language {code: $lang})
        MERGE (lvl:Level {name: $lvl})
        MERGE (ch:Chapter {name: $ch})
        MERGE (ls:Lesson {name: $ls})
        
        MERGE (lang)-[:HAS_LEVEL]->(lvl)
        MERGE (lvl)-[:HAS_CHAPTER]->(ch)
        MERGE (ch)-[:HAS_LESSON]->(ls)
    """, lang=item["language"], lvl=item["level"], ch=item["chapter"], ls=item["lesson"])

    # 4. Nodi Family
    tx.run("MERGE (:Family {name: 'LIST'})")
    tx.run("MERGE (:Family {name: 'QUESTION'})")

    # 5. Creazione Catena e Opzioni
    prev_node_id = None

    for i, t_data in enumerate(tokens):
        # Ogni nodo ContentNode ha SOLO il testo
        res = tx.run("CREATE (n:ContentNode {text: $text}) RETURN elementId(n) as id", 
                     text=t_data["text"])
        curr_node_id = res.single()["id"]

        if i == 0:
            # Primo nodo: collega a Lesson e a Family LIST
            tx.run("""
                MATCH (ls:Lesson {name: $ls}), (f:Family {name: 'LIST'}), (n)
                WHERE elementId(n) = $id
                CREATE (ls)-[:HAS_START_NODE {exercise_id: $ex_id, isTarget: $isTarget}]->(n)
                CREATE (n)-[:IS_OF_FAMILY]->(f)
            """, ls=item["lesson"], id=curr_node_id, ex_id=ex_id, isTarget=t_data["isTarget"])
        
        if prev_node_id:
            # Collegamento NEXT
            tx.run("""
                MATCH (a) WHERE elementId(a) = $id_a 
                MATCH (b) WHERE elementId(b) = $id_b 
                CREATE (a)-[:NEXT {isTarget: $isTarget}]->(b)
            """, id_a=prev_node_id, id_b=curr_node_id, isTarget=t_data["isTarget"])

        # 6. Se è un buco, colleghiamo TUTTO il pool di opzioni (Family QUESTION)
        if t_data["isTarget"]:
            for opt_text in full_options_pool:
                is_this_correct = (opt_text == t_data["text"])
                tx.run("""
                    MATCH (q) WHERE elementId(q) = $q_id
                    MATCH (f:Family {name: 'QUESTION'})
                    CREATE (o:ContentNode {text: $opt_text}) 
                    CREATE (o)-[:IS_OF_FAMILY]->(f)
                    CREATE (q)-[:HAS_ANSWER {isCorrect: $is_correct}]->(o)
                """, q_id=curr_node_id, opt_text=opt_text, is_correct=is_this_correct)

        prev_node_id = curr_node_id

def run_import(base_dir: str):
    verify_connection()
    data_list = extract_all_gap_fills(base_dir)
    with driver.session(database=DATABASE) as session:
        for item in tqdm(data_list, desc="Importing Gap Fills"):
            session.execute_write(import_gap_fill, item)

if __name__ == "__main__":
    run_import(PATH)