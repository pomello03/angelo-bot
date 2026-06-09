"""
championship.py - Logica di calcolo punti FIA e salvataggio CSV.

Sistema punti FIA standard:
  1° = 25, 2° = 18, 3° = 15, 4° = 12, 5° = 10,
  6° = 8,  7° = 6,  8° = 4,  9° = 2,  10° = 1

Bonus giro veloce: +1 punto, ma solo se il pilota e' nella Top 10.

I risultati vengono salvati in classifica_campionato.csv in modalita' append.
"""

import csv
import os
from datetime import datetime
from typing import List, Dict, Tuple

from telemetry import RaceResult, DriverResult, RESULT_FINISHED, format_lap_time
from config import get_active_csv, set_active_csv, get_driver_to_team

# ============================================================================
# SISTEMA PUNTI FIA
# ============================================================================
FIA_POINTS = {
    1: 25, 2: 18, 3: 15, 4: 12, 5: 10,
    6: 8,  7: 6,  8: 4,  9: 2,  10: 1,
}

SPRINT_POINTS = {
    1: 8, 2: 7, 3: 6, 4: 5,
    5: 4, 6: 3, 7: 2, 8: 1
}

CSV_HEADERS = [
    "data", "pilota", "scuderia", "posizione", "punti_base", "bonus_giro_veloce",
    "punti_totali", "giri", "pit_stop", "miglior_giro", "stato",
    "griglia_partenza", "tempo_penalita"
]


# ============================================================================
# CALCOLO PUNTI
# ============================================================================
def calculate_points(result: RaceResult) -> List[Dict]:
    """
    Calcola i punti del campionato per ogni pilota.

    Restituisce una lista di dizionari con i risultati, ordinati per posizione.
    I punti vengono calcolati secondo il sistema FIA, ignorando i punti
    eventualmente assegnati dal gioco (che potrebbero differire).
    """
    scored_drivers = []

    # ID 11, 14 o 15 = Sprint / Short Race. Controlliamo se è una sprint
    st = getattr(result, "session_type", 10)
    is_sprint = st in (11, 14, 15)
    points_system = SPRINT_POINTS if is_sprint else FIA_POINTS

    for driver in result.drivers:
        # Punti base dalla posizione (solo se ha finito la gara)
        if driver.result_status == RESULT_FINISHED:
            base_points = points_system.get(driver.position, 0)
        else:
            base_points = 0

        # Bonus giro veloce: +1 solo se nella top 10 E ha il giro piu' veloce (Non c'è nelle Sprint)
        fastest_bonus = 0
        if not is_sprint:
            if (driver.name == result.fastest_lap_driver
                    and driver.position <= 10
                    and driver.result_status == RESULT_FINISHED):
                fastest_bonus = 1

        total = base_points + fastest_bonus

        scored_drivers.append({
            "pilota": driver.name,
            "scuderia": driver.scuderia,
            "posizione": driver.position,
            "punti_base": base_points,
            "bonus_giro_veloce": fastest_bonus,
            "punti_totali": total,
            "giri": driver.num_laps,
            "pit_stop": driver.num_pit_stops,
            "miglior_giro": format_lap_time(driver.best_lap_time_ms),
            "stato": _status_text(driver.result_status),
            "griglia_partenza": driver.grid_position,
            "tempo_penalita": driver.penalties_time,
        })

    return scored_drivers


def _status_text(status: int) -> str:
    """Traduce il codice risultato in testo leggibile."""
    from telemetry import RESULT_STATUS_NAMES
    return RESULT_STATUS_NAMES.get(status, f"Sconosciuto ({status})")


# ============================================================================
# SALVATAGGIO CSV E LETTURA CLASSIFICHE
# ============================================================================
def save_to_csv(scored_drivers: List[Dict], csv_path: str = None):
    """
    Salva i risultati della gara nel file CSV in modalita' append.
    Crea il file con gli header se non esiste.
    """
    csv_path = csv_path or get_active_csv()
    file_exists = os.path.isfile(csv_path)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(csv_path, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)

        if not file_exists:
            writer.writeheader()

        for driver_data in scored_drivers:
            row = {"data": timestamp}
            row.update(driver_data)
            writer.writerow(row)

    print(f"[Championship] Risultati salvati in {csv_path} ({len(scored_drivers)} piloti)")


# ============================================================================
# LETTURA CLASSIFICA GENERALE
# ============================================================================
def get_championship_standings(csv_path: str = None) -> List[Tuple[str, int]]:
    """
    Legge il CSV e calcola la classifica generale cumulativa.

    Restituisce una lista di tuple (nome_pilota, punti_totali)
    ordinata per punti decrescenti.
    """
    csv_path = csv_path or get_active_csv()
    if not os.path.isfile(csv_path):
        return []

    standings: Dict[str, int] = {}

    with open(csv_path, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("pilota", "Sconosciuto")
            pts = int(row.get("punti_totali", 0))
            standings[name] = standings.get(name, 0) + pts

    # Ordina per punti decrescenti, poi per nome alfabetico a parita'
    sorted_standings = sorted(standings.items(), key=lambda x: (-x[1], x[0]))
    return sorted_standings


def get_constructors_standings(csv_path: str = None) -> List[Tuple[str, int]]:
    """
    Legge il CSV e calcola la classifica generale costruttori.
    """
    csv_path = csv_path or get_active_csv()
    if not os.path.isfile(csv_path):
        return []

    standings: Dict[str, int] = {}
    driver_mapping = get_driver_to_team()
    driver_mapping_lower = {k.lower(): v for k, v in driver_mapping.items()}

    with open(csv_path, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            pilota = row.get("pilota", "Sconosciuto")
            team = row.get("scuderia", "")
            
            # Retro-compatibilità: se la scuderia manca nel CSV, usa il mapping in config
            if not team or team == "Sconosciuta":
                team = driver_mapping_lower.get(pilota.lower(), "Sconosciuta")
                
            if team == "Sconosciuta" or not team: 
                continue
                
            pts = int(row.get("punti_totali", 0))
            standings[team] = standings.get(team, 0) + pts

    sorted_standings = sorted(standings.items(), key=lambda x: (-x[1], x[0]))
    return sorted_standings


# ============================================================================
# CONTROLLO DUPLICATI
# ============================================================================
def is_duplicate_race(result: RaceResult, csv_path: str = None) -> bool:
    """
    Verifica se la gara che si sta per salvare è probabilmente un duplicato
    dell'ultima gara registrata nel CSV (stessi piloti, stesse posizioni, ecc.).
    """
    csv_path = csv_path or get_active_csv()
    if not os.path.isfile(csv_path):
        return False

    with open(csv_path, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        return False

    # Trova il timestamp dell'ultima gara
    last_timestamp = rows[-1]["data"]
    last_race_rows = [r for r in rows if r["data"] == last_timestamp]

    if not last_race_rows:
        return False

    # Confronta il numero totale di piloti in gara
    if len(last_race_rows) != len(result.drivers):
        return False
        
    # Verifica l'esatta corrispondenza di piloti e posizioni per evitare falsi positivi
    csv_results = {(r["pilota"].lower(), str(r["posizione"])) for r in last_race_rows}
    new_results = {(d.name.lower(), str(d.position)) for d in result.drivers}

    return csv_results == new_results

# ============================================================================
# FUNZIONE COMPLETA: calcola + salva
# ============================================================================
def process_race_result(result: RaceResult) -> List[Dict]:
    """
    Pipeline completa: calcola i punti e salva nel CSV.
    Restituisce la lista dei risultati calcolati (utile per l'embed Discord).
    """
    scored = calculate_points(result)
    save_to_csv(scored)
    return scored


# ============================================================================
# ANNULLA ULTIMA GARA
# ============================================================================
def delete_last_race(csv_path: str = None) -> str:
    """
    Rimuove l'ultima gara registrata dal CSV (tutte le righe con lo stesso timestamp).

    Restituisce un messaggio con l'esito dell'operazione.
    """
    csv_path = csv_path or get_active_csv()
    if not os.path.isfile(csv_path):
        return "Nessun file campionato trovato."

    with open(csv_path, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        return "Il campionato è vuoto, nessuna gara da cancellare."

    # Trova il timestamp dell'ultima gara (l'ultimo valore unico nella colonna "data")
    last_timestamp = rows[-1]["data"]

    # Conta quante righe appartengono a quella gara
    race_rows = [r for r in rows if r["data"] == last_timestamp]
    remaining_rows = [r for r in rows if r["data"] != last_timestamp]

    # Riscrivi il file senza l'ultima gara
    with open(csv_path, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()
        writer.writerows(remaining_rows)

    return (f"Gara del **{last_timestamp}** rimossa "
            f"({len(race_rows)} piloti cancellati, "
            f"{len(remaining_rows)} righe rimanenti).")


# ============================================================================
# NUOVO CAMPIONATO
# ============================================================================
def reset_championship(nome: str) -> str:
    """
    Crea un nuovo campionato e lo imposta come attivo.
    Se un campionato con lo stesso nome esiste già, non viene sovrascritto.
    """
    if not nome.endswith(".csv"):
        nome += ".csv"
        
    old_csv = get_active_csv()
    new_csv = set_active_csv(nome)
    
    # Crea il file vuoto con gli header se non esiste
    if not os.path.isfile(new_csv):
        with open(new_csv, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            writer.writeheader()
        return f"🏁 Creato e attivato il nuovo campionato: **{new_csv}**.\nIl campionato precedente ({old_csv}) è stato messo in pausa."
    else:
        return f"✅ Attivato il campionato esistente: **{new_csv}**.\nNessun dato è stato cancellato."


# ============================================================================
# RINOMINA PILOTA
# ============================================================================
def rename_driver(nome_attuale: str, nome_nuovo: str, csv_path: str = None) -> int:
    """
    Rinomina un pilota in tutto il file CSV del campionato (case-insensitive).
    Restituisce il numero di righe modificate.
    """
    csv_path = csv_path or get_active_csv()
    if not os.path.isfile(csv_path):
        return 0

    rows = []
    modifications = 0

    with open(csv_path, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            pilota = row.get("pilota", "")
            if pilota.lower() == nome_attuale.lower():
                row["pilota"] = nome_nuovo
                modifications += 1
            rows.append(row)

    if modifications > 0:
        with open(csv_path, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames or CSV_HEADERS)
            writer.writeheader()
            writer.writerows(rows)

    return modifications

