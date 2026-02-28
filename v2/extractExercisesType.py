import os
import json
from collections import defaultdict

def extract_exercise_types(root_dir):
    exercise_coverage = defaultdict(set)
    all_found_types = set()

    def find_exercises(data, file_path):
        """Funzione ricorsiva per scavare in tutte le 'structure'."""
        if isinstance(data, dict):
            # Se troviamo un esercizio, estraiamo il tipo
            if data.get("class") == "exercise" or "exercise_" in str(data.get("id")):
                ex_type = data.get("type")
                if ex_type:
                    all_found_types.add(ex_type)
                    exercise_coverage[ex_type].add(file_path)
            
            # Continua a scavare in tutte le liste chiamate 'structure'
            for key, value in data.items():
                if key == "structure" and isinstance(value, list):
                    for item in value:
                        find_exercises(item, file_path)
        elif isinstance(data, list):
            for item in data:
                find_exercises(item, file_path)

    # Scansione cartelle
    print(f"Inizio scansione nella cartella: {os.path.abspath(root_dir)}")
    file_count = 0
    
    for root, dirs, files in os.walk(root_dir):
        for file in files:
            if file.endswith(".json"):
                file_count += 1
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = json.load(f)
                        find_exercises(content, file_path)
                except Exception as e:
                    print(f"Errore in {file_path}: {e}")

    print(f"File JSON analizzati: {file_count}")
    return all_found_types, exercise_coverage

# --- CONFIGURAZIONE ---
root_path = "00-raw_courses/en" 

found_types, coverage_map = extract_exercise_types(root_path)

print("\n--- TIPI DI ESERCIZI TROVATI ---")
if not found_types:
    print("Nessun esercizio trovato. Controlla che il percorso root_path sia corretto.")
else:
    for ex_type in sorted(found_types):
        count = len(coverage_map[ex_type])
        print(f"- {ex_type:<25} (in {count:>3} lezioni)")



if found_types:
    print("\n⚠️  Tipi NUOVI trovati (da aggiungere al cleaning):")
    for m in sorted(found_types):
        # Mostra anche un esempio di file dove trovarlo per analizzarlo
        example_file = list(coverage_map[m])[0]
        print(f"  [!] {m:<20} -> Esempio: {example_file}")
else:
    print("\n✅ Tutti i tipi trovati sono già coperti dallo script di pulizia.")