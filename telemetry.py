"""
telemetry.py - Gestione del socket UDP e parsing dei pacchetti F1 25.

Ascolta sulla porta 20777 e decodifica:
  - PacketHeader (29 byte)
  - PacketSessionData (packetId=1) per rilevare se siamo in gara
  - PacketParticipantsData (packetId=4) per mappare indice -> nome pilota
  - PacketFinalClassificationData (packetId=8) risultati fine gara

Formato: Little-Endian, strutture packed.
"""

import socket
import struct
import threading
from dataclasses import dataclass, field
from typing import List, Optional, Callable

# ============================================================================
# COSTANTI
# ============================================================================
UDP_PORT = 20777
HEADER_SIZE = 29

# Packet IDs
PACKET_SESSION = 1
PACKET_PARTICIPANTS = 4
PACKET_FINAL_CLASSIFICATION = 8
PACKET_SESSION_HISTORY = 11

# Header: uint16, uint8x5, uint64, float, uint32x2, uint8x2
HEADER_FORMAT = '<HBBBBBQfIIBB'

# sessionType values
SESSION_TYPE_RACE = 10
SESSION_TYPE_RACE2 = 11
SESSION_TYPE_RACE3 = 12

# resultStatus
RESULT_FINISHED = 3
RESULT_DNF = 4
RESULT_DSQ = 5
RESULT_NOT_CLASSIFIED = 6
RESULT_RETIRED = 7

RESULT_STATUS_NAMES = {
    0: "Invalido", 1: "Inattivo", 2: "Attivo", 3: "Finito",
    4: "DNF", 5: "DSQ", 6: "Non Classificato", 7: "Ritirato",
}

TRACK_IDS = {
    0: "Melbourne",
    1: "Paul Ricard",
    2: "Shanghai",
    3: "Sakhir (Bahrain)",
    4: "Catalunya",
    5: "Monaco",
    6: "Baku",
    7: "Silverstone",
    8: "Hungaroring",
    9: "Spa-Francorchamps",
    10: "Monza",
    11: "Singapore",
    12: "Suzuka",
    13: "Abu Dhabi",
    14: "Austin (Texas)",
    15: "Interlagos (Brasile)",
    16: "Paul Ricard (Short)",
    17: "Silverstone (Short)",
    18: "Texas (Short)",
    19: "Suzuka (Short)",
    20: "Hanoi",
    21: "Zandvoort",
    22: "Imola",
    23: "Portimao",
    24: "Jeddah (Short)",
    25: "Mugello",
    26: "Jeddah",
    27: "Imola",
    28: "Portimao",
    29: "Singapore (Short)",
    30: "Jeddah",
    31: "Miami",
    32: "Las Vegas",
    33: "Losail (Qatar)",
    34: "Losail",
    39: "Losail (Qatar)"
}

from config import get_ai_driver_names, get_team_names, canonicalize_driver_name

# ============================================================================
# DATACLASS
# ============================================================================
@dataclass
class DriverResult:
    """Risultato di un singolo pilota a fine gara."""
    name: str
    scuderia: str
    position: int
    num_laps: int
    grid_position: int
    points: int
    num_pit_stops: int
    result_status: int
    best_lap_time_ms: int
    total_race_time: float
    penalties_time: int


@dataclass
class RaceResult:
    """Risultato complessivo di una gara."""
    drivers: List[DriverResult] = field(default_factory=list)
    fastest_lap_driver: Optional[str] = None
    fastest_lap_time_ms: int = 0
    session_type: int = 0
    game_year: int = 25
    track_name: str = "Sconosciuta"



# ============================================================================
# LISTENER PRINCIPALE
# ============================================================================
class TelemetryListener:
    """
    Server UDP per la telemetria F1 25.

    Uso:
        listener = TelemetryListener(on_race_end=my_callback)
        listener.start()
        # ...
        listener.stop()
    """

    def __init__(self, on_race_end: Callable[[RaceResult], None], port: int = UDP_PORT):
        self.port = port
        self.on_race_end = on_race_end
        self._is_race_session = False
        self._participant_names: dict = {}
        self._participant_teams: dict = {}
        self._race_already_processed = False
        self._current_session_uid: int = 0
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._sock: Optional[socket.socket] = None
        self._packet_count = 0
        self._current_session_type = 0
        self._session_histories: dict = {}
        self._last_classification_hash = None
        self._current_game_year = 25
        self._current_track_id = -1

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        print(f"[Telemetry] In ascolto sulla porta UDP {self.port}...")

    def stop(self):
        self._running = False
        if self._sock:
            self._sock.close()
        if self._thread:
            self._thread.join(timeout=2)
        print("[Telemetry] Ascolto terminato.")

    def _listen_loop(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("0.0.0.0", self.port))
        self._sock.settimeout(1.0)

        while self._running:
            try:
                data, _ = self._sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break

            if len(data) < 24:
                continue

            packet_format = struct.unpack_from('<H', data, 0)[0]
            if packet_format == 2024:
                header_size = 28
                header_format = '<HBBBBQfIIBB'
            else:
                header_size = 29
                header_format = '<HBBBBBQfIIBB'

            if len(data) < header_size:
                continue

            header = struct.unpack_from(header_format, data, 0)
            if packet_format == 2024:
                game_year = 24
                packet_id = header[4]
                session_uid = header[5]
            else:
                game_year = header[1]
                packet_id = header[5]
                session_uid = header[6]

            if game_year in (25, 26):
                self._current_game_year = game_year

            self._packet_count += 1
            if self._packet_count % 500 == 0:
                print(f"[Telemetry] Ricevuti {self._packet_count} pacchetti...")

            # Ignora i pacchetti con UID 0 (spesso pacchetti di sistema F1 non legati a una sessione)
            # che altrimenti farebbero resettare lo stato continuamente.
            if session_uid != 0 and session_uid != self._current_session_uid:
                print(f"\n[Telemetry] Nuova sessione rilevata: UID {session_uid}")
                self._current_session_uid = session_uid
                self._race_already_processed = False
                self._current_session_type = 0
                self._participant_names.clear()
                self._participant_teams.clear()
                self._session_histories.clear()
                self._last_classification_hash = None

            try:
                if packet_id == PACKET_SESSION:
                    self._parse_session(data, packet_format)
                elif packet_id == PACKET_PARTICIPANTS:
                    self._parse_participants(data, packet_format)
                elif packet_id == PACKET_SESSION_HISTORY:
                    self._parse_session_history(data, packet_format)
                elif packet_id == PACKET_FINAL_CLASSIFICATION:
                    self._parse_final_classification(data, packet_format)
            except Exception as e:
                print(f"[Telemetry] Errore nell'elaborazione del pacchetto ID {packet_id}: {e}")

        self._sock.close()

    # --- PacketSessionData (packetId=1) ---
    def _parse_session(self, data: bytes, packet_format: int):
        header_size = 28 if packet_format == 2024 else 29
        offset = header_size + 6
        if len(data) < offset + 2:
            return
        session_type, track_id = struct.unpack_from('<Bb', data, offset)
        
        if session_type != self._current_session_type:
            print(f"[Telemetry] Tipo sessione aggiornato: {session_type}")
            self._current_session_type = session_type

        if track_id != self._current_track_id:
            print(f"[Telemetry] ID Pista aggiornato: {track_id}")
            self._current_track_id = track_id

    # --- PacketParticipantsData (packetId=4) ---
    def _parse_participants(self, data: bytes, packet_format: int):
        header_size = 28 if packet_format == 2024 else 29
        if len(data) < header_size + 1:
            return

        num_cars = struct.unpack_from('<B', data, header_size)[0]
        offset = header_size + 1
        
        # Dimensione fissa dell'elemento ParticipantData per evitare disallineamenti dovuti a padding UDP
        PART_SIZE = 60 if packet_format == 2024 else 57

        if PART_SIZE <= 0:
            return

        ai_names = get_ai_driver_names()
        team_names = get_team_names()
        name_len = 48 if packet_format == 2024 else 32

        for i in range(min(num_cars, 22)):
            if offset + PART_SIZE > len(data):
                break
            ai_controlled = struct.unpack_from('<B', data, offset)[0]
            driver_id = struct.unpack_from('<B', data, offset + 1)[0]
            team_id = struct.unpack_from('<B', data, offset + 3)[0]
            
            # Il nome inizia sempre all'offset 7
            name_bytes = data[offset + 7: offset + 7 + name_len]
            name = name_bytes.split(b'\x00')[0].decode('utf-8', errors='replace').strip()

            if ai_controlled == 1:
                # Se è un'AI sconosciuta (es. Antonelli), usa il nome del gioco formattato bene (es: ANTONELLI -> Antonelli)
                fallback_name = name.title() if name else f"AI #{driver_id}"
                resolved = ai_names.get(driver_id, fallback_name)
            else:
                resolved = name or f"Giocatore #{i}"

            self._participant_names[i] = canonicalize_driver_name(resolved)
            self._participant_teams[i] = team_names.get(team_id, f"Team #{team_id}")
            offset += PART_SIZE

    # --- PacketFinalClassificationData (packetId=8) ---
    def _parse_final_classification(self, data: bytes, packet_format: int):
        # Ignora Prove Libere (1-4), Qualifiche (5-9), Time Trial (13)
        # Ignora Qualifiche Sprint / Shootout (14-18)
        # Accetta Gare (10, 11, 12), Sconosciuti (0) e qualsiasi ID multiplayer custom
        IGNORED_SESSIONS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 13, 17, 18]
        
        if self._current_session_type in IGNORED_SESSIONS:
            if not self._race_already_processed:
                print(f"[Telemetry] [!] Classifica finale ignorata (Session Type = {self._current_session_type} -> Prova/Qualifica)")
                self._race_already_processed = True  # per non spammare
            return
            
        if self._race_already_processed:
            return

        header_size = 28 if packet_format == 2024 else 29
        if len(data) < header_size + 1:
            return

        # Anti-Duplicati: se la classifica è identica a quella appena salvata, ignorala
        # (Risolve il problema del gioco che invia di nuovo i dati dopo un Alt+Tab)
        payload = data[header_size:]
        payload_hash = hash(payload)
        if self._last_classification_hash == payload_hash:
            return

        print("\n[Telemetry] [FINE] ELABORAZIONE CLASSIFICA FINALE IN CORSO...")

        num_cars = struct.unpack_from('<B', data, header_size)[0]
        offset = header_size + 1
        
        # Dimensione fissa dell'elemento FinalClassificationData per evitare disallineamenti dovuti a padding UDP
        if packet_format == 2024:
            CLASS_SIZE = 45
            shift = 0
        else:
            CLASS_SIZE = 46
            shift = 1

        if CLASS_SIZE <= 0:
            return

        # Validazione dei nomi dei piloti (ammorbidita per evitare blocchi su ID 15)
        valid_names_count = 0
        for i in range(min(num_cars, 22)):
            name = self._participant_names.get(i, "")
            if len(name.strip()) > 0:
                valid_names_count += 1
                
        if valid_names_count == 0:
            print("[Telemetry] [WAIT] Nomi piloti non ancora caricati. Attendo il pacchetto UDP dei partecipanti...")
            return  # Aspetta che il gioco invii i nomi (ogni 5 secondi) prima di salvare

        drivers = []
        fastest_ms = 0
        fastest_driver = ""

        for i in range(min(num_cars, 22)):
            if offset + CLASS_SIZE > len(data):
                break

            pos = struct.unpack_from('<B', data, offset)[0]
            n_laps = struct.unpack_from('<B', data, offset + 1)[0]
            grid = struct.unpack_from('<B', data, offset + 2)[0]
            pts = struct.unpack_from('<B', data, offset + 3)[0]
            pits = struct.unpack_from('<B', data, offset + 4)[0]
            status = struct.unpack_from('<B', data, offset + 5)[0]
            
            best_ms = struct.unpack_from('<I', data, offset + 6 + shift)[0]
            total_time = struct.unpack_from('<d', data, offset + 10 + shift)[0]
            pen_time = struct.unpack_from('<B', data, offset + 18 + shift)[0]

            name = self._participant_names.get(i, "")
            if '\ufffd' in name or not name.isprintable() or not name.strip():
                print(f"[Telemetry] [!] Ignorato pilota {i} (nome non valido o privacy UDP ristretta)")
                continue

            team_name = self._participant_teams.get(i, "Sconosciuta")

            drivers.append(DriverResult(
                name=name, scuderia=team_name, position=pos, num_laps=n_laps,
                grid_position=grid, points=pts, num_pit_stops=pits,
                result_status=status, best_lap_time_ms=best_ms,
                total_race_time=total_time, penalties_time=pen_time,
            ))

            if best_ms > 0 and (fastest_ms == 0 or best_ms < fastest_ms):
                fastest_ms = best_ms
                fastest_driver = name

            offset += CLASS_SIZE

        drivers.sort(key=lambda d: d.position)
        
        track_base = TRACK_IDS.get(self._current_track_id, f"Pista #{self._current_track_id}")
        if self._current_session_type in (11, 14, 15):
            track_name = f"{track_base} Sprint"
        else:
            track_name = track_base

        result = RaceResult(drivers=drivers, fastest_lap_driver=fastest_driver,
                            fastest_lap_time_ms=fastest_ms, session_type=self._current_session_type,
                            game_year=self._current_game_year, track_name=track_name)

        self._race_already_processed = True
        self._last_classification_hash = payload_hash
        print(f"[Telemetry] Fine gara! {len(drivers)} piloti classificati.")

        # Salva la telemetria della gara in un file JSON
        self._save_race_telemetry_to_json()

        if self.on_race_end:
            self.on_race_end(result)

    def _save_race_telemetry_to_json(self):
        """Salva lo storico dei giri e i nomi in un file JSON per il comando /telemetria."""
        import json
        export_data = {}
        for car_idx, name in self._participant_names.items():
            # Salva solo i piloti che hanno uno storico giri
            history = self._session_histories.get(car_idx, [])
            if history:
                export_data[name] = history

        try:
            with open("last_race_telemetry.json", "w", encoding="utf-8") as f:
                json.dump(export_data, f, indent=4)
            print("[Telemetry] Dati telemetrici storici salvati in last_race_telemetry.json")
        except Exception as e:
            print(f"[Telemetry] Errore nel salvataggio della telemetria JSON: {e}")

    # --- PacketSessionHistoryData (packetId=11) ---
    def _parse_session_history(self, data: bytes, packet_format: int):
        header_size = 28 if packet_format == 2024 else 29
        if len(data) < header_size + 7:
            return

        offset = header_size
        car_idx = struct.unpack_from('<B', data, offset)[0]
        num_laps = struct.unpack_from('<B', data, offset + 1)[0]
        
        lap_history_offset = offset + 7
        # F1 23/24/25 LapHistoryData struct size is 14 bytes
        LAP_DATA_SIZE = 14

        history = []
        for lap in range(min(num_laps, 100)):
            curr_offset = lap_history_offset + (lap * LAP_DATA_SIZE)
            if curr_offset + LAP_DATA_SIZE > len(data):
                break
            
            lap_time = struct.unpack_from('<I', data, curr_offset)[0]
            s1_ms = struct.unpack_from('<H', data, curr_offset + 4)[0]
            s1_min = struct.unpack_from('<B', data, curr_offset + 6)[0]
            s1 = s1_ms + s1_min * 60000

            s2_ms = struct.unpack_from('<H', data, curr_offset + 7)[0]
            s2_min = struct.unpack_from('<B', data, curr_offset + 9)[0]
            s2 = s2_ms + s2_min * 60000

            s3_ms = struct.unpack_from('<H', data, curr_offset + 10)[0]
            s3_min = struct.unpack_from('<B', data, curr_offset + 12)[0]
            s3 = s3_ms + s3_min * 60000

            valid_flags = struct.unpack_from('<B', data, curr_offset + 13)[0]

            # Bit 0 = Lap valid
            is_valid = (valid_flags & 0x01) == 0x01

            # Evita di salvare giri palesemente vuoti o corrotti
            if lap_time > 0:
                history.append({
                    "lap": lap + 1,
                    "lap_time_ms": lap_time,
                    "s1_ms": s1,
                    "s2_ms": s2,
                    "s3_ms": s3,
                    "is_valid": is_valid
                })

        # Aggiorna lo storico solo se ha senso (evita di sovrascrivere con pacchetti vuoti)
        if history:
            self._session_histories[car_idx] = history


# ============================================================================
# UTILITY
# ============================================================================
def format_lap_time(ms: int) -> str:
    """Converte millisecondi in formato M:SS.mmm"""
    if ms <= 0:
        return "N/A"
    minutes = ms // 60000
    seconds = (ms % 60000) / 1000
    return f"{minutes}:{seconds:06.3f}"
