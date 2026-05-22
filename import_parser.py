"""
import_parser.py - Parser per i file CSV esportati da F1 25.

Legge i file generati dalla funzione "esporta risultati sessione" del gioco
e li converte in oggetti RaceResult compatibili con il sistema del bot.
"""

import csv
import io
import re
from typing import List, Dict, Optional, Tuple

from telemetry import DriverResult, RaceResult, RESULT_FINISHED, RESULT_RETIRED
from config import canonicalize_driver_name

# ============================================================================
# NORMALIZZAZIONE NOMI SCUDERIA
# ============================================================================
# Mappa dai nomi completi del gioco ai nomi brevi usati internamente dal bot.
# Necessario per coerenza con i dati delle gare registrate via telemetria.
GAME_TEAM_TO_BOT = {
    "mercedes-amg petronas": "Mercedes",
    "mercedes": "Mercedes",
    "scuderia ferrari hp": "Ferrari",
    "scuderia ferrari": "Ferrari",
    "ferrari": "Ferrari",
    "red bull racing": "Red Bull Racing",
    "red bull": "Red Bull Racing",
    "oracle red bull racing": "Red Bull Racing",
    "mclaren": "McLaren",
    "aston martin": "Aston Martin",
    "aston martin aramco": "Aston Martin",
    "alpine": "Alpine",
    "bwt alpine": "Alpine",
    "williams": "Williams",
    "williams racing": "Williams",
    "visa cash app racing bulls": "RB",
    "racing bulls": "RB",
    "rb": "RB",
    "haas": "Haas",
    "moneygram haas": "Haas",
    "kick sauber": "Kick Sauber",
    "stake f1 team kick sauber": "Kick Sauber",
    "sauber": "Kick Sauber",
}


def normalize_team_name(game_name: str) -> str:
    """Normalizza il nome scuderia dal formato del gioco a quello del bot."""
    lower = game_name.strip().lower()
    if lower in GAME_TEAM_TO_BOT:
        return GAME_TEAM_TO_BOT[lower]
    for key, value in GAME_TEAM_TO_BOT.items():
        if key in lower or lower in key:
            return value
    return game_name


def _normalize_driver_name(raw_name: str) -> str:
    """Normalizza 'Andrea Kimi ANTONELLI' -> 'Andrea Kimi Antonelli'."""
    parts = raw_name.strip().split()
    return " ".join(p.title() if p.isupper() and len(p) > 1 else p for p in parts)


def _parse_lap_time_to_ms(time_str: str) -> int:
    """Converte un tempo in formato italiano (es. '1:37,449') in millisecondi."""
    time_str = time_str.strip().replace(",", ".")
    if not time_str or time_str in ("N/A", "RIT", ""):
        return 0
    match = re.match(r'(\d+):(\d+)\.(\d+)', time_str)
    if match:
        minutes = int(match.group(1))
        seconds = int(match.group(2))
        millis = int(match.group(3).ljust(3, '0')[:3])
        return minutes * 60000 + seconds * 1000 + millis
    return 0


def _parse_penalties(content: str) -> Dict[str, int]:
    """
    Analizza la sezione incidenti/penalità del CSV e restituisce
    il tempo totale di penalità per ogni pilota (in secondi).
    """
    penalties: Dict[str, int] = {}
    lines = content.strip().split('\n')

    # Trova la sezione penalità (dopo la riga vuota)
    penalty_start = None
    for i, line in enumerate(lines):
        if line.strip() == '':
            penalty_start = i + 1
            break

    if penalty_start is None or penalty_start >= len(lines):
        return penalties

    try:
        reader = csv.DictReader(io.StringIO('\n'.join(lines[penalty_start:])))
        for row in reader:
            pilota = row.get("Pilota", "").strip()
            penalita = row.get("Penalità", "").strip().lower()
            if not pilota or not penalita:
                continue
            time_match = re.search(r'(\d+)\s*sec', penalita)
            if time_match:
                penalties[pilota] = penalties.get(pilota, 0) + int(time_match.group(1))
    except Exception:
        pass
    return penalties


def resolve_utente_names(
    rows: List[Dict], driver_to_team: Dict[str, str]
) -> Tuple[Dict[int, str], List[Tuple[int, str]]]:
    """
    Risolve i placeholder 'Utente' usando il mapping DRIVER_TO_TEAM.

    Restituisce:
        - Dict[indice_riga, nome_risolto] per i nomi risolti
        - List[(indice_riga, nome_scuderia)] per quelli NON risolti
    """
    resolved: Dict[int, str] = {}
    unresolved: List[Tuple[int, str]] = []

    # Nomi già presenti esplicitamente nel CSV (non-Utente), normalizzati per confronto
    explicit_normalized = set()
    for row in rows:
        name = row.get("Pilota", "").strip()
        if name and name != "Utente":
            explicit_normalized.add(name.lower())
            explicit_normalized.add(_normalize_driver_name(name).lower())

    already_assigned: set = set()

    for i, row in enumerate(rows):
        if row.get("Pilota", "").strip() != "Utente":
            continue

        game_team = row.get("Scuderia", "").strip()
        norm_team = normalize_team_name(game_team)

        # Cerca giocatori assegnati a questa scuderia nel config
        candidates = []
        for player, team in driver_to_team.items():
            if team.lower() != norm_team.lower():
                continue
            if player.lower() in explicit_normalized:
                continue
            if player in already_assigned:
                continue
            candidates.append(player)

        if len(candidates) == 1:
            resolved[i] = candidates[0]
            already_assigned.add(candidates[0])
        else:
            unresolved.append((i, game_team))

    return resolved, unresolved


def parse_exported_csv(
    content: str, driver_to_team: Dict[str, str], is_sprint: bool = False
) -> Tuple[Optional[RaceResult], List[Tuple[int, str]]]:
    """
    Parser principale. Converte il CSV esportato dal gioco in un RaceResult.

    Restituisce:
        - RaceResult (o None se ci sono "Utente" irrisolti)
        - Lista di (indice, scuderia) dei piloti "Utente" non risolti
    """
    lines = content.strip().split('\n')

    # Rimuovi BOM UTF-8 se presente (F1 25 lo aggiunge spesso)
    if lines and lines[0].startswith('\ufeff'):
        lines[0] = lines[0].lstrip('\ufeff')

    # Separa classificazione da incidenti (divisi da riga vuota)
    classification_lines = []
    for line in lines:
        if line.strip() == '':
            break
        classification_lines.append(line)

    if not classification_lines:
        return None, []

    # Normalizza gli header: rimuovi spazi, BOM e caratteri invisibili
    csv_text = '\n'.join(classification_lines)
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = list(reader)
    if not rows:
        return None, []

    # Pulisci le chiavi del dizionario da BOM e spazi residui
    cleaned_rows = []
    for row in rows:
        cleaned = {}
        for key, value in row.items():
            clean_key = key.strip().lstrip('\ufeff').strip('"').strip()
            cleaned[clean_key] = value
        cleaned_rows.append(cleaned)
    rows = cleaned_rows

    # Risolvi i nomi "Utente"
    resolved, unresolved = resolve_utente_names(rows, driver_to_team)
    if unresolved:
        return None, unresolved

    # Penalità dalla sezione incidenti
    penalties_map = _parse_penalties(content)

    # Trova giro veloce e costruisci i risultati
    fastest_ms = 0
    fastest_driver = ""
    drivers = []

    for i, row in enumerate(rows):
        # Nome pilota
        if i in resolved:
            name = resolved[i]
        else:
            raw = row.get("Pilota", f"Pilota #{i}").strip()
            if row.get("tipo di pilota", "").strip() == "IA":
                name = _normalize_driver_name(raw)
            else:
                name = raw

        # Applica alias canonici (es. "Antonelli" -> "Andrea Kimi Antonelli")
        name = canonicalize_driver_name(name)

        position = int(row.get("Pos.", 0))
        grid = int(row.get("Griglia", 0))
        pit_stops = int(row.get("Soste", 0))
        best_lap_ms = _parse_lap_time_to_ms(row.get("Migliore", ""))

        # Stato: "RIT" = ritirato, tutto il resto = finito
        tempo = row.get("Tempo", "").strip()
        result_status = RESULT_RETIRED if tempo == "RIT" else RESULT_FINISHED

        # Scuderia: normalizzata per coerenza con le gare via telemetria
        team = normalize_team_name(row.get("Scuderia", "Sconosciuta"))

        # Penalità: somma delle penalità in secondi dalla sezione incidenti
        # Cerca sia col nome originale CSV sia col nome risolto
        raw_name = row.get("Pilota", "").strip()
        pen = penalties_map.get(raw_name, 0) + penalties_map.get(name, 0)
        # Evita doppio conteggio se nome == raw_name
        if name == raw_name:
            pen = penalties_map.get(name, 0)

        drivers.append(DriverResult(
            name=name,
            scuderia=team,
            position=position,
            num_laps=0,
            grid_position=grid,
            points=0,  # Verranno ricalcolati da calculate_points()
            num_pit_stops=pit_stops,
            result_status=result_status,
            best_lap_time_ms=best_lap_ms,
            total_race_time=0.0,
            penalties_time=pen,
        ))

        if best_lap_ms > 0 and (fastest_ms == 0 or best_lap_ms < fastest_ms):
            fastest_ms = best_lap_ms
            fastest_driver = name

    drivers.sort(key=lambda d: d.position)

    result = RaceResult(
        drivers=drivers,
        fastest_lap_driver=fastest_driver,
        fastest_lap_time_ms=fastest_ms,
        session_type=10,  # Gara standard
    )
    return result, []
 session_type=10,  # Gara standard
    )
    return result, []
