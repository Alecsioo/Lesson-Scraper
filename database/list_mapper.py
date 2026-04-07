import os
import json
import re
from pathlib import Path
from tqdm import tqdm
from database.database import driver, verify_connection
from dotenv import load_dotenv

load_dotenv()

DATABASE = os.getenv("NEO4J_DATABASE")
PATH = "01-cleaned_courses"
TYPES = {"phrase_builder", "word_spelling", "gap_fill_typing", "highlight_selection"}
FAMILY = "LIST"

PATH_LANGUAGE_IDX = 0
PATH_LEVEL_IDX = 2
PATH_CHAPTER_IDX = 3 # Indice per il capitolo
PATH_LESSON_IDX = 4  # Indice per la lezione
PATH_MIN_DEPTH = 5

# ── helpers ──────────────────────────────────────────────────────────────────

def _parse_level(raw: str) -> str:
    return raw.rsplit("_", 1)[-1].upper()

def _extract_path_metadata(path: Path, base_path: Path) -> dict | None:
    parts = path.relative_to(base_path).parts
    if len(parts) < PATH_MIN_DEPTH:
        return None
    
    return {
        "language": parts[PATH_LANGUAGE_IDX],
        "level": _parse_level(parts[PATH_LEVEL_IDX]),
        "chapter": parts[PATH_CHAPTER_IDX],
        "lesson": parts[PATH_LESSON_IDX].replace(".json", ""),
        "lesson_file": parts[PATH_LESSON_IDX]
    }

# ... (funzione extract_items rimane identica alla tua versione precedente)
def extract_items(exercise: dict, exercise_type: str) -> list[dict] | None:
    if exercise_type == "phrase_builder":
        tokens = exercise.get("tokens", [])
        return [{"text": t, "isTarget": True} for t in tokens if t]
    if exercise_type == "gap_fill_typing":
        gap_sentence = exercise.get("gap_sentence_orig", "")
        solution = exercise.get("correct_answers", [""])[0] 
        if gap_sentence:
            parts = re.findall(r"_+|[¿?¡!\wáéíóúüñ]+", gap_sentence)
            res = []
            for p in parts:
                if p.startswith('_'): res.append({"text": solution, "isTarget": True})
                else: res.append({"text": p, "isTarget": False})
            return res if res else None
    if exercise_type == "word_spelling":
        full = exercise.get("full_text_orig", "")
        gap = exercise.get("gap_sentence_orig", "")
        if full and gap: return [{"text": f, "isTarget": (g == "_")} for f, g in zip(full, gap)]
    if exercise_type == "highlight_selection":
        full_chain = []
        blocks = exercise.get("selectable_data", [])
        for i, block in enumerate(blocks):
            correct_set = set(block.get("correct_options", []))
            for word in block.get("all_options", []):
                if word is None: continue
                full_chain.append({"text": str(word), "isTarget": word in correct_set})
            if i < len(blocks) - 1: full_chain.append({"text": "\n", "isTarget": False})
        return full_chain
    return None

# ── extraction ────────────────────────────────────────────────────────────────

def extract_lists(base_dir: str) -> list[dict]:
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
                        "exercise_type": ex_type,
                        "items": items,
                        **meta # Inseriamo language, level, chapter, lesson
                    })
    return results

# ── import ────────────────────────────────────────────────────────────────────

def import_list(tx, item: dict):
    nodes_data = item["items"]
    ex_id = item["exercise_id"]
    
    # 1. Pulizia preventiva (Idempotenza)
    tx.run("""
        MATCH (ls:Lesson {name: $lesson})-[r:HAS_START_NODE {exercise_id: $ex_id}]->(n)
        MATCH (n)-[:NEXT*0..]->(m)
        DETACH DELETE m
    """, lesson=item["lesson"], ex_id=ex_id)

    # 2. Struttura Gerarchica (MERGE)
    tx.run("""
        MERGE (lang:Language {code: $lang})
        MERGE (lvl:Level {name: $lvl})
        MERGE (ch:Chapter {name: $ch})
        MERGE (ls:Lesson {name: $ls})
        MERGE (lang)-[:HAS_LEVEL]->(lvl)
        MERGE (lvl)-[:HAS_CHAPTER]->(ch)
        MERGE (ch)-[:HAS_LESSON]->(ls)
    """, lang=item["language"], lvl=item["level"], ch=item["chapter"], ls=item["lesson"])

    # 3. Nodo Family (Metadata)
    tx.run("MERGE (f:Family {name: 'LIST'})")

    # 4. Costruzione della catena
    # Rimosso il parametro ex_type
    params = {"ls": item["lesson"], "ex_id": ex_id}
    cypher_parts = ["MATCH (ls:Lesson {name: $ls})", "MATCH (f:Family {name: 'LIST'})"]

    for i, node in enumerate(nodes_data):
        node_var = f"n{i}"
        params[f"text{i}"] = node["text"]
        params[f"isTarget{i}"] = node["isTarget"]
        
        # Il nodo è purissimo: solo l'etichetta e il testo
        cypher_parts.append(f"CREATE ({node_var}:ContentNode {{text: $text{i}}})")
        
        if i == 0:
            # Rimosso campo 'type' dalla relazione
            cypher_parts.append(
                f"CREATE (ls)-[:HAS_START_NODE {{exercise_id: $ex_id, isTarget: $isTarget{i}}}]->({node_var})"
            )
            cypher_parts.append(f"CREATE ({node_var})-[:IS_OF_FAMILY]->(f)")
        else:
            prev_var = f"n{i-1}"
            cypher_parts.append(
                f"CREATE ({prev_var})-[:NEXT {{isTarget: $isTarget{i}}}]->({node_var})"
            )

    tx.run("\n".join(cypher_parts), **params)

def run_import(base_dir: str):
    verify_connection()
    lists = extract_lists(base_dir)

    with driver.session(database=DATABASE) as session:
        for item in tqdm(lists, desc="Importing lists"):
            session.execute_write(import_list, item)

if __name__ == "__main__":
    run_import(PATH)