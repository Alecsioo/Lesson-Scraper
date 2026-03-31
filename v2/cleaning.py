import json
import re
import html
from tqdm import tqdm
from pathlib import Path

SOURCE = "00-raw_courses"
TARGET = "01-cleaned_courses"

def clean_tags(text):
    """Rimuove tag e normalizza gli spazi senza spezzare le parole coniugate."""
    if not isinstance(text, str): return text
    
    # 1. Decodifica entità HTML (es. &nbsp; -> spazio)
    text = html.unescape(text)
    
    # 2. RIMUOVI i tag di formattazione (senza aggiungere spazi)
    # Usiamo stringa vuota '' invece di ' ' per b, i, u, k, h
    text = re.sub(r'\[/?k\]|\[/?h\]|<b>|</b>|<i>|</i>|<u>|</u>', '', text)
    
    # 3. SOSTITUISCI i break lineari con uno spazio reale
    text = re.sub(r'<br>|<br/>', ' ', text)
    
    # 4. Normalizza gli spazi multipli (ma ora non ci saranno spazi dentro le parole)
    text = ' '.join(text.split()).strip()
    
    # 5. FIX PUNTEGGIATURA (Regex per eliminare spazi intorno ai simboli)
    text = re.sub(r'\s+([.,!?%:\;\)\]])', r'\1', text)
    text = re.sub(r'([¡¿\(\[])\s+', r'\1', text)
    return text

def extract_tokens(text):
    """Estrae tutte le parole/frasi racchiuse tra i tag [k]."""
    if not text: return []
    return re.findall(r'\[k\](.*?)\[/k\]', text)

def extract_gap(text):
    """Estrae la parola corretta tra i tag [k]."""
    match = re.search(r'\[k\](.*?)\[/k\]', text)
    return match.group(1) if match else None

def get_gap_sentence(text):
    """Crea la frase con il 'buco' ____."""
    if not text: return None
    return re.sub(r'(\[k\].*?\[/k\])+', '____', text)

def process_file(input_path):
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    lesson_id = data.get("id", "unknown_id")
    trans = data.get("translation_map", {})
    ents = data.get("entity_map", {})

    # 1. Identificiamo dinamicamente la lingua del corso (es. 'es', 'ja', 'fr')
    course_lang = "en" 
    for entry in trans.values():
        if isinstance(entry, dict):
            for l in entry.keys():
                if l not in ["en", "interface", "audio"]:
                    course_lang = l
                    break
            if course_lang != "en": break

    # Helper per estrarre testi in lingue specifiche
    def get_val(s_id, lang): return trans.get(s_id, {}).get(lang, {}).get("value", "")
    
    def get_audio(s_id, lang):
        entry = trans.get(s_id, {})
        if isinstance(entry, dict):
            # Prova prima la lingua richiesta, se manca prova qualsiasi lingua
            audio = entry.get(lang, {}).get("audio")
            if audio: return audio
            for l in entry:
                if isinstance(entry[l], dict) and entry[l].get("audio"):
                    return entry[l].get("audio")
        return None
    
    def get_audio_by_lang(s_id, lang):
        """Cerca l'audio specifico per una lingua data."""
        entry = trans.get(s_id, {})
        if isinstance(entry, dict):
            return entry.get(lang, {}).get("audio")
        return None

    def get_e_data(e_id):
        """Recupera testi (orig/en), audio e media di un'entità."""
        e = ents.get(e_id, {})
        p_id = e.get("phrase")
        k_id = e.get("keyphrase")
        target_id = p_id or k_id
        
        text_orig = get_val(target_id, course_lang) or get_val(k_id, course_lang)
        text_trans = get_val(target_id, "en") or get_val(k_id, "en")
         
        audio_orig = get_audio_by_lang(target_id, course_lang)
        audio_en = get_audio_by_lang(target_id, "en")
        
        v_urls = e.get("video_urls", {}).get("mp4", {})
        
        return {
            "raw_orig": text_orig,
            "text_orig": clean_tags(text_orig),
            "text_en": clean_tags(text_trans),
            "audio_orig": audio_orig,
            "audio_en": audio_en,
            "image": e.get("image") if e.get("image") else None,
            "video": v_urls.get("L") or v_urls.get("M") or v_urls.get("S")
        }

    # Helper compatibili con la tua struttura originale
    def get_s(s_id): return clean_tags(get_val(s_id, "en") or get_val(s_id, course_lang))
    def get_e_text(e_id): return get_e_data(e_id)["text_orig"]


    output = {
        "lesson_id": lesson_id,
        "lesson_title": clean_tags(get_val(data["content"].get("title"), "en")),
        "lesson_description": clean_tags(get_val(data["content"].get("description"), "en")),
        "units": []
    }

    def extract_exercises(structure_list):
        found = []
        for item in structure_list:
            if item.get("class") == "exercise":
                old_t = item.get("type")
                c = item.get("content", {})
                
                # --- MAPPATURA NOMI DESCRITTIVI ---
                new_t = old_t
                if old_t in ["26a", "26a_aud", "26a_img"]: new_t = "gap_fill_click"
                elif old_t == "26b": new_t = "gap_fill_multiple"
                elif old_t in ["27a", "27a_aud", "27a_img"]: new_t = "gap_fill_typing"
                elif old_t == "24": new_t = "phrase_builder"
                elif old_t == "28": new_t = "highlight_selection"
                elif old_t in ["23", "23i"]: new_t = "true_false"
                elif old_t == "multipleChoiceQuestion": new_t = "multiple_choice"
                elif old_t == "matchUpEntity": new_t = "match_up"
                elif old_t == "fill-gap-typing": new_t = "word_spelling"
                elif old_t == "singleEntity": new_t = "flashcard"
                elif old_t == "listenRepeat": new_t = "listen_repeat"
                elif old_t == "speech_rec": new_t = "speech_recognition"
                elif old_t == "writing": new_t = "writing"
                elif old_t == "comprehension_video": new_t = "comprehension_video"
                elif old_t == "comprehension_text": new_t = "comprehension_text"
                elif old_t == "tip_table": new_t = "tip_table"
                elif old_t == "tip": new_t = "tip"
                elif old_t in ["dialogue", "review_34"]: new_t = "dialogue"
 
                ex_out = {
                    "exercise_id": item.get("id"),
                    "type": new_t,
                    "instructions": clean_tags(get_val(c.get("instructions"), "en")),
                    "instructions": get_s(c.get("instructions")),
                    "grammar_tag": c.get("grammar_topic_id")
                }

                if new_t == "flashcard":
                    mid = c.get("entity") or c.get("phrase")
                    if mid:
                        ed = get_e_data(mid)
                        ex_out.update({"text_orig": ed["text_orig"], "text_en": ed["text_en"], "audio_orig": ed["audio_orig"], "audio_en": ed["audio_en"], "image": ed["image"], "video": ed["video"]})

                elif new_t in ["comprehension_video", "comprehension_text"]:
                    mid = c.get("entity")
                    ed = get_e_data(mid)
                    ex_out["content_title"] = get_s(c.get("title"))
                    ex_out["content_body_orig"] = ed["text_orig"]
                    ex_out["content_body_en"] = ed["text_en"]
                    ex_out.update({"image": ed["image"], "audio_orig": ed["audio_orig"], "video": ed["video"]})

                elif new_t == "listen_repeat":
                    mid = c.get("phrase")
                    if mid:
                        ed = get_e_data(mid)
                        ex_out.update({
                            "text_orig": ed["text_orig"],
                            "text_en": ed["text_en"],
                            "audio_orig": ed["audio_orig"],
                            "image": ed["image"],
                            "video": ed["video"]
                        })
                        ex_out["time_limit"] = item.get("timeLimit")

                elif new_t == "speech_recognition":
                    mid = c.get("question")
                    ed = get_e_data(mid)
                    ex_out["text_to_speak_orig"] = ed["text_orig"]
                    ex_out.update({"image": ed["image"], "audio_orig": ed["audio_orig"]})

                elif new_t == "word_spelling":
                    m_id = c.get("entity") or c.get("sentence")
                    ed = get_e_data(m_id)
                    
                    ex_out.update({
                        "full_text_orig": ed["text_orig"],
                        "full_text_en": ed["text_en"],
                        "letters": extract_tokens(ed["raw_orig"]),
                        "gap_sentence_orig": clean_tags(get_gap_sentence(ed["raw_orig"])),
                        "audio_orig": ed["audio_orig"],
                        "image": ed["image"]
                    })

                elif new_t == "phrase_builder":
                    raw = get_e_data(c.get("sentence"))
                    ex_out["full_text_orig"] = raw["text_orig"]
                    ex_out["tokens"] = extract_tokens(raw["raw_orig"]) or raw["text_orig"].split()
                    ex_out.update({"image": raw["image"], "audio_orig": raw["audio_orig"]})

                elif new_t == "highlight_selection":
                    processed_items = []
                    for s_id in c.get("sentences", []):
                        raw = get_val(s_id, course_lang) 
                        
                        correct_tokens = re.findall(r'\[h\](.*?)\[/h\]', raw)
                        
                        clean_line = raw.replace('[h]', '').replace('[/h]', '')
                        all_tokens = clean_line.split()
                        
                        distractors = [t for t in all_tokens if t not in correct_tokens]
                        
                        processed_items.append({
                            "all_options": all_tokens,
                            "correct_options": correct_tokens,
                            "distractors": distractors
                        })
                    
                    ex_out["instructions"] = get_s(c.get("instructions"))
                    ex_out["selectable_data"] = processed_items

                elif new_t == "tip_table":
                    rows = []
                    ex_dict = c.get("examples", {})
                    for r_idx in sorted(ex_dict.keys(), key=int):
                        row = []
                        for c_idx in sorted(ex_dict[r_idx].keys(), key=int):
                            sid = ex_dict[r_idx][c_idx]
                            row.append({"text_orig": clean_tags(get_val(sid, course_lang)), "text_en": clean_tags(get_val(sid, "en")), "audio_orig": get_audio(sid, course_lang)})
                        rows.append(row)
                    ex_out["table_data"] = rows

                elif new_t == "tip":
                    ex_out["tip_title"] = get_s(c.get("title"))
                    ex_out["tip_text_orig"] = clean_tags(get_val(c.get("text"), course_lang))
                    ex_out["examples"] = [{"text_orig": clean_tags(get_val(sid, course_lang)), "audio_orig": get_audio(sid, course_lang)} for sid in c.get("examples", [])]

                elif new_t == "true_false":
                    ed = get_e_data(c.get("question"))
                    ex_out["statement_title_en"] = get_s(c.get("title"))
                    ex_out["context_text_orig"] = ed["text_orig"]
                    ex_out["is_correct"] = c.get("answer")
                    ex_out.update({"image": ed["image"], "audio_orig": ed["audio_orig"]})

                elif new_t == "gap_fill_click":
                    mid = c.get("sentence")
                    ed = get_e_data(mid)
                    sol = get_e_data(c.get("solution"))
                    ex_out["full_text_orig"] = ed["text_orig"]
                    ex_out["full_text_en"] = ed["text_en"]
                    
                    if "[k]" in ed["raw_orig"]: 
                        ex_out["gap_sentence_orig"] = clean_tags(get_gap_sentence(ed["raw_orig"]))
                        ex_out["correct_answer"] = extract_gap(ed["raw_orig"])
                    else:
                        ex_out["gap_sentence_orig"] = ed["text_orig"].replace(sol["text_orig"], "____")
                        ex_out["correct_answer"] = sol["text_orig"]
                    
                    ex_out["options"] = [get_e_text(d) for d in c.get("distractors", [])]
                    ex_out.update({"image": ed["image"], "audio_orig": ed["audio_orig"] or sol["audio_orig"], "video": ed["video"]})

                elif new_t == "multiple_choice":
                    sol = get_e_data(c.get("solution"))
                    qid = c.get("question")
                    ex_out["solution_text_orig"] = sol["text_orig"]
                    ex_out["solution_text_en"] = sol["text_en"]
                    ex_out["options"] = [get_e_text(d) for d in c.get("distractors", [])]
                    ex_out.update({
                        "image": sol["image"], 
                        "audio_orig": sol["audio_orig"] or get_audio_by_lang(qid, course_lang),
                        "audio_en": sol["audio_en"] or get_audio_by_lang(qid, "en"),
                        "audio_orig": sol["audio_orig"] or get_audio(c.get("question"), course_lang)})


                elif new_t == "match_up":
                    pairs = []
                    left_entities = c.get("entities", [])
                    right_entities = c.get("matchingEntities", [])
                    
                    for l_id, r_id in zip(left_entities, right_entities):
                        l_data = get_e_data(l_id)
                        
                        r_data = get_e_data(r_id)
                        right_text = r_data["text_en"] if r_data["text_en"] else r_data["text_orig"]
                        
                        pairs.append({
                            "left_orig": l_data["text_orig"],
                            "right_orig": right_text  
                        })
                    
                    ex_out["pairs"] = pairs

                elif new_t == "gap_fill_multiple":
                    mid = c.get("sentence") or c.get("entity")
                    ed = get_e_data(mid)
                    sol = get_e_data(c.get("solution"))
                    if ed["text_orig"]:
                        ex_out["full_text_orig"] = ed["text_orig"]
                        ex_out["full_text_en"] = ed["text_en"]
                        ex_out["gap_sentence_orig"] = clean_tags(get_gap_sentence(ed["raw_orig"])) or ed["text_orig"].replace(sol["text_orig"], "____")
                        ex_out["correct_answers"] = extract_tokens(ed["raw_orig"]) or [sol["text_orig"]]
                        ex_out["options"] = [get_e_text(d) for d in c.get("distractors", [])]
                        ex_out.update({"image": ed["image"], "audio_orig": ed["audio_orig"] or sol["audio_orig"]})

                elif new_t == "writing":
                    ex_out["hint_orig"] = clean_tags(get_val(c.get("hint"), course_lang))
                    ex_out["hint_en"] = clean_tags(get_val(c.get("hint"), "en"))
                    ex_out["word_counter"] = c.get("wordCounter")
                    ex_out["images"] = c.get("images", [])

                elif new_t == "gap_fill_typing":
                    m_id = c.get("sentence") or c.get("entity")
                    ed = get_e_data(m_id) 
        
                    tokens = extract_tokens(ed["raw_orig"])
                    
                    if not tokens:
                        raw_ans = c.get("correct_answers_to_type", [""])[0] if isinstance(c.get("correct_answers_to_type"), list) else ""
                        tokens = [a.strip() for a in str(raw_ans).split('|')] if raw_ans else []

                    ex_out.update({
                        "full_text_orig": ed["text_orig"],
                        "gap_sentence_orig": clean_tags(get_gap_sentence(ed["raw_orig"])),
                        "correct_answers": tokens,
                        "audio_orig": ed["audio_orig"],
                        "image": ed["image"],
                        "hint_en": get_s(c.get("hint"))
                    })

               
                elif new_t == "dialogue":
                    script_data = []
                    for line_item in c.get("script", []):
                        l_id = line_item.get("line")
                        raw_orig = get_val(l_id, course_lang)
                        
                        line_entry = {
                            "character_id": line_item.get("character_id"),
                            "text_orig": clean_tags(raw_orig),
                            "text_en": clean_tags(get_val(l_id, "en")),
                            "audio_orig": get_audio_by_lang(l_id, course_lang)
                        }

                        # Se ci sono tag [k], estraiamo TUTTE le occorrenze
                        if "[k]" in raw_orig:
                            # Estraiamo tutti i gruppi [k]...[/k] in una lista
                            all_answers = extract_tokens(raw_orig) # Ritorna es: ["carrera", "conseguir"]
                            
                            line_entry["gap_sentence_orig"] = clean_tags(re.sub(r'\[k\].*?\[/k\]', '____', raw_orig))
                            line_entry["correct_answers"] = [a.strip() for a in all_answers]
                            line_entry["is_exercise_line"] = True
                        else:
                            line_entry["is_exercise_line"] = False

                        script_data.append(line_entry)
                    
                    ex_out["dialogue_script"] = script_data
                    
                    # Raccolta di tutte le opzioni possibili (risposte + distrattori)
                    all_solutions = []
                    for line in script_data:
                        if line.get("is_exercise_line"):
                            all_solutions.extend(line["correct_answers"])

                    distractors = [clean_tags(get_e_text(d)) for d in c.get("distractors", [])]
                    ex_out["all_selectable_options"] = list(set(all_solutions + distractors))
                    
                    ex_out["characters"] = {cid: {"name": get_s(info.get("name")), "image": info.get("image"), "role": info.get("role")} for cid, info in c.get("characters", {}).items()}

                explanation = get_val(c.get("correctAnswer"), "en")
                if explanation: ex_out["explanation_en"] = clean_tags(explanation)
                found.append(ex_out)
            
            elif "structure" in item:
                found.extend(extract_exercises(item["structure"]))
        return found

    for unit in data.get("structure", []):
        u_out = {
            "unit_type": unit.get("type"),
            "points": unit.get("points"),
            "estimated_seconds": unit.get("time_estimate"),
            "grammar_ids": unit.get("content", {}).get("grammar_topic_ids", []),
            "exercises": extract_exercises(unit.get("structure", []))
        }
        output["units"].append(u_out)

    return output

def migrate_courses(source_root: str, target_root: str) -> None:
    source = Path(source_root)
    target = Path(target_root)

    json_files = list(source.rglob("*.json"))

    for input_path in tqdm(json_files, desc="Migrating", unit="file"):
        rel_path = input_path.relative_to(source)
        target_path = target / rel_path
        target_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            cleaned_data = process_file(str(input_path))
            with target_path.open("w", encoding="utf-8") as f:
                json.dump(cleaned_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            tqdm.write(f"[ERROR] {input_path}: {e}")


def main():
    migrate_courses(SOURCE, TARGET)

if __name__ == "__main__":
    raise SystemExit(main())