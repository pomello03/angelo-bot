import json
import os
from typing import Dict, Any

CONFIG_FILE = "config.json"
DEFAULT_CSV = "classifica_campionato.csv"

def load_config() -> Dict[str, Any]:
    """Load configuration from config.json. If it doesn't exist or is invalid, return a default dictionary."""
    if not os.path.isfile(CONFIG_FILE):
        return {
            "ACTIVE_CHAMPIONSHIP": DEFAULT_CSV,
            "TEAM_NAMES": {},
            "AI_DRIVER_NAMES": {},
            "DRIVER_TO_TEAM": {}
        }
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[Config] Error loading {CONFIG_FILE}: {e}")
        return {
            "ACTIVE_CHAMPIONSHIP": DEFAULT_CSV,
            "TEAM_NAMES": {},
            "AI_DRIVER_NAMES": {},
            "DRIVER_TO_TEAM": {}
        }

def save_config(config: Dict[str, Any]):
    """Save configuration to config.json."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[Config] Error saving {CONFIG_FILE}: {e}")

def get_active_csv() -> str:
    """Return the name of the active championship CSV file."""
    config = load_config()
    return config.get("ACTIVE_CHAMPIONSHIP", DEFAULT_CSV)

def set_active_csv(name: str) -> str:
    """Set the active championship CSV file."""
    if not name.endswith(".csv"):
        name += ".csv"
    config = load_config()
    config["ACTIVE_CHAMPIONSHIP"] = name
    save_config(config)
    return name

def get_ai_driver_names() -> Dict[int, str]:
    """Return AI driver names mapping with integer keys."""
    config = load_config()
    str_dict = config.get("AI_DRIVER_NAMES", {})
    return {int(k): v for k, v in str_dict.items() if k.isdigit()}

def get_team_names() -> Dict[int, str]:
    """Return team names mapping with integer keys."""
    config = load_config()
    str_dict = config.get("TEAM_NAMES", {})
    return {int(k): v for k, v in str_dict.items() if k.isdigit()}

# ============================================================================
# ALIAS NOMI PILOTI: nome corto/variante -> nome canonico completo
# ============================================================================
# Usato sia dalla telemetria che dall'importazione CSV per garantire
# che lo stesso pilota venga sempre salvato con lo stesso nome.
DRIVER_NAME_ALIASES = {
    "Antonelli": "Andrea Kimi Antonelli",
    "Piastri": "Oscar Piastri",
    "Colapinto": "Franco Colapinto",
    "Bortoleto": "Gabriel Bortoleto",
    "Bearman": "Oliver Bearman",
    "Hadjar": "Isack Hadjar",
    "Lawson": "Liam Lawson",
    "Doohan": "Jack Doohan",
}

def canonicalize_driver_name(name: str) -> str:
    """Normalizza il nome di un pilota al formato canonico.
    Cerca prima un match esatto, poi case-insensitive."""
    if name in DRIVER_NAME_ALIASES:
        return DRIVER_NAME_ALIASES[name]
    # Match case-insensitive
    name_lower = name.lower()
    for alias, canonical in DRIVER_NAME_ALIASES.items():
        if alias.lower() == name_lower:
            return canonical
    return name


DEFAULT_OFFICIAL_TEAMS = {
    # Ferrari
    "Charles Leclerc": "Ferrari",
    "Lewis Hamilton": "Ferrari",
    # Mercedes
    "George Russell": "Mercedes",
    "Andrea Kimi Antonelli": "Mercedes",
    # McLaren
    "Lando Norris": "McLaren",
    "Oscar Piastri": "McLaren",
    # Red Bull Racing
    "Max Verstappen": "Red Bull Racing",
    "Sergio Perez": "Red Bull Racing",
    # Aston Martin
    "Fernando Alonso": "Aston Martin",
    "Lance Stroll": "Aston Martin",
    # Alpine
    "Pierre Gasly": "Alpine",
    "Jack Doohan": "Alpine",
    "Franco Colapinto": "Alpine",
    # Williams
    "Alexander Albon": "Williams",
    "Carlos Sainz": "Williams",
    "Logan Sargeant": "Williams",
    # RB
    "Yuki Tsunoda": "RB",
    "Liam Lawson": "RB",
    "Isack Hadjar": "RB",
    "Daniel Ricciardo": "RB",
    # Haas
    "Esteban Ocon": "Haas",
    "Oliver Bearman": "Haas",
    "Kevin Magnussen": "Haas",
    # Kick Sauber
    "Nico Hulkenberg": "Kick Sauber",
    "Gabriel Bortoleto": "Kick Sauber",
    "Valtteri Bottas": "Kick Sauber",
    "Guanyu Zhou": "Kick Sauber"
}

def get_driver_to_team() -> Dict[str, str]:
    """Restituisce il mapping manuale Pilota -> Scuderia unito a quello ufficiale di base."""
    config = load_config()
    manual_mapping = config.get("DRIVER_TO_TEAM", {})
    
    # Crea un dizionario combinato: i manuali sovrascrivono quelli ufficiali se ci sono conflitti
    combined = DEFAULT_OFFICIAL_TEAMS.copy()
    combined.update(manual_mapping)
    return combined

def get_custom_driver_to_team() -> Dict[str, str]:
    """Restituisce SOLO il mapping manuale Pilota -> Scuderia."""
    config = load_config()
    return config.get("DRIVER_TO_TEAM", {})

def set_driver_team(pilota: str, scuderia: str):
    """Associa manualmente un pilota a una scuderia nel config."""
    config = load_config()
    if "DRIVER_TO_TEAM" not in config:
        config["DRIVER_TO_TEAM"] = {}
    config["DRIVER_TO_TEAM"][pilota] = scuderia
    save_config(config)

def clear_driver_teams():
    """Svuota tutte le assegnazioni manuali nel config."""
    config = load_config()
    if "DRIVER_TO_TEAM" in config:
        config["DRIVER_TO_TEAM"] = {}
        save_config(config)
