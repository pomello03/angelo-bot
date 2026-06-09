import unittest
import struct
import io
from championship import calculate_points
from telemetry import RaceResult, DriverResult, TelemetryListener
from import_parser import parse_exported_csv
from config import get_driver_to_team

class TestAngeloBot(unittest.TestCase):
    def test_calculate_points_standard(self):
        # 10 drivers finished, P1 has fastest lap
        drivers = [
            DriverResult(name="Charles Leclerc", scuderia="Ferrari", position=1, num_laps=50, grid_position=1, points=0, num_pit_stops=1, result_status=3, best_lap_time_ms=80000, total_race_time=5000.0, penalties_time=0),
            DriverResult(name="Lewis Hamilton", scuderia="Ferrari", position=2, num_laps=50, grid_position=2, points=0, num_pit_stops=1, result_status=3, best_lap_time_ms=81000, total_race_time=5005.0, penalties_time=0),
            DriverResult(name="George Russell", scuderia="Mercedes", position=11, num_laps=50, grid_position=3, points=0, num_pit_stops=1, result_status=3, best_lap_time_ms=82000, total_race_time=5100.0, penalties_time=0)
        ]
        result = RaceResult(drivers=drivers, fastest_lap_driver="Charles Leclerc", fastest_lap_time_ms=80000, session_type=10, game_year=25)
        scored = calculate_points(result)
        
        # Leclerc should get 25 + 1 = 26 points
        p1 = next(x for x in scored if x["pilota"] == "Charles Leclerc")
        self.assertEqual(p1["punti_base"], 25)
        self.assertEqual(p1["bonus_giro_veloce"], 1)
        self.assertEqual(p1["punti_totali"], 26)
        
        # Hamilton should get 18 points, 0 bonus
        p2 = next(x for x in scored if x["pilota"] == "Lewis Hamilton")
        self.assertEqual(p2["punti_base"], 18)
        self.assertEqual(p2["bonus_giro_veloce"], 0)
        
    def test_calculate_points_sprint(self):
        drivers = [
            DriverResult(name="Charles Leclerc", scuderia="Ferrari", position=1, num_laps=15, grid_position=1, points=0, num_pit_stops=0, result_status=3, best_lap_time_ms=80000, total_race_time=1500.0, penalties_time=0),
            DriverResult(name="Lewis Hamilton", scuderia="Ferrari", position=2, num_laps=15, grid_position=2, points=0, num_pit_stops=0, result_status=3, best_lap_time_ms=81000, total_race_time=1502.0, penalties_time=0),
        ]
        # session_type 11 = Sprint
        result = RaceResult(drivers=drivers, fastest_lap_driver="Charles Leclerc", fastest_lap_time_ms=80000, session_type=11, game_year=25)
        scored = calculate_points(result)
        
        # Leclerc should get 8 points base and 0 fastest lap bonus (no fastest lap bonus in sprint)
        p1 = next(x for x in scored if x["pilota"] == "Charles Leclerc")
        self.assertEqual(p1["punti_base"], 8)
        self.assertEqual(p1["bonus_giro_veloce"], 0)
        self.assertEqual(p1["punti_totali"], 8)

    def test_f1_26_teams_config(self):
        driver_mapping = get_driver_to_team()
        # Verify Cadillac is present and Sergio Perez is mapped to it
        self.assertEqual(driver_mapping.get("Sergio Perez"), "Cadillac")
        self.assertEqual(driver_mapping.get("Sergio Pérez"), "Cadillac")
        self.assertEqual(driver_mapping.get("Valtteri Bottas"), "Cadillac")
        
        # Verify Audi is present and Nico Hulkenberg is mapped to it
        self.assertEqual(driver_mapping.get("Nico Hulkenberg"), "Audi")
        self.assertEqual(driver_mapping.get("Nico Hülkenberg"), "Audi")
        self.assertEqual(driver_mapping.get("Gabriel Bortoleto"), "Audi")

        # Verify Red Bull Racing has Isack Hadjar
        self.assertEqual(driver_mapping.get("Isack Hadjar"), "Red Bull Racing")
        
        # Verify RB has Arvid Lindblad
        self.assertEqual(driver_mapping.get("Arvid Lindblad"), "RB")

    def test_csv_auto_detect_game_year(self):
        # CSV with F1 25 teams
        csv_25_content = (
            "\"Pos.\",\"Pilota\",\"Scuderia\",\"Migliore\",\"Tempo\",\"Griglia\",\"Soste\",\"tipo di pilota\"\n"
            "1,Charles Leclerc,Scuderia Ferrari,1:30.000,1:20:00.000,1,1,IA\n"
            "2,Valtteri Bottas,Kick Sauber,1:31.000,1:20:10.000,2,1,IA\n"
        )
        result_25, _ = parse_exported_csv(csv_25_content, {})
        self.assertIsNotNone(result_25)
        self.assertEqual(result_25.game_year, 25)

        # CSV with F1 26 teams (Cadillac)
        csv_26_content = (
            "\"Pos.\",\"Pilota\",\"Scuderia\",\"Migliore\",\"Tempo\",\"Griglia\",\"Soste\",\"tipo di pilota\"\n"
            "1,Charles Leclerc,Scuderia Ferrari,1:30.000,1:20:00.000,1,1,IA\n"
            "2,Valtteri Bottas,Cadillac,1:31.000,1:20:10.000,2,1,IA\n"
        )
        result_26, _ = parse_exported_csv(csv_26_content, {})
        self.assertIsNotNone(result_26)
        self.assertEqual(result_26.game_year, 26)

    def test_telemetry_dynamic_parsing_2024(self):
        # Test parsing F1 24 layout
        listener = TelemetryListener(on_race_end=None)
        
        # 1. Test Participants parsing
        # F1 24 header size = 28, m_numActiveCars = 1 (1 byte)
        packet_header = struct.pack('<HBBBBQfIIBB', 2024, 1, 0, 1, 4, 12345, 10.0, 100, 100, 0, 0)
        # ParticipantData: ai_controlled, driver_id, network_id, team_id, my_team, race_number, nationality, name (48s), others
        part_data = struct.pack('<BBBBBBB48s', 1, 0, 0, 1, 0, 55, 12, b'Carlos Sainz')
        # Padding to 60 bytes (PART_SIZE)
        part_data += b'\x00' * 5
        # Pad packet to contain 22 cars so that PART_SIZE matches exactly 60
        packet = packet_header + b'\x01' + part_data + (b'\x00' * 60 * 21)
        
        listener._parse_participants(packet, 2024)
        self.assertEqual(listener._participant_names.get(0), "Carlos Sainz")
        self.assertEqual(listener._participant_teams.get(0), "Ferrari")

        # 2. Test Final Classification parsing
        # CLASS_SIZE = 45. Fields: pos (1), n_laps (50), grid (1), pts (25), pits (1), status (3)
        # followed by best_ms (uint32) at offset 6, total_time (double) at offset 10, pen_time (uint8) at offset 18
        class_data = struct.pack('<BBBBBBIdB', 1, 50, 1, 25, 1, 3, 80000, 5000.0, 0)
        class_data += b'\x00' * 26 # Pad to 45 bytes
        # Pad to contain 22 cars so that CLASS_SIZE is exactly 45
        packet_class = packet_header + b'\x01' + class_data + (b'\x00' * 45 * 21)
        
        # We need to set session type to race (10) to avoid ignoring the classification
        listener._current_session_type = 10
        
        # Set callback to receive the results
        received_results = []
        listener.on_race_end = lambda res: received_results.append(res)
        
        listener._parse_final_classification(packet_class, 2024)
        self.assertEqual(len(received_results), 1)
        res = received_results[0]
        self.assertEqual(len(res.drivers), 1)
        driver = res.drivers[0]
        self.assertEqual(driver.name, "Carlos Sainz")
        self.assertEqual(driver.position, 1)
        self.assertEqual(driver.best_lap_time_ms, 80000)
        self.assertEqual(driver.total_race_time, 5000.0)

    def test_telemetry_dynamic_parsing_2025(self):
        # Test parsing F1 25 layout
        listener = TelemetryListener(on_race_end=None)
        
        # 1. Test Participants parsing
        # F1 25 header size = 29, m_numActiveCars = 1 (1 byte)
        packet_header = struct.pack('<HBBBBBQfIIBB', 2025, 25, 1, 0, 1, 4, 12345, 10.0, 100, 100, 0, 0)
        # ParticipantData: ai_controlled, driver_id, network_id, team_id, my_team, race_number, nationality, name (32s), others
        part_data = struct.pack('<BBBBBBB32s', 1, 72, 0, 1, 0, 16, 12, b'Charles Leclerc')
        # Padding to 57 bytes (PART_SIZE)
        part_data += b'\x00' * 18
        # Pad packet to contain 22 cars so that PART_SIZE matches exactly 57
        packet = packet_header + b'\x01' + part_data + (b'\x00' * 57 * 21)
        
        listener._parse_participants(packet, 2025)
        self.assertEqual(listener._participant_names.get(0), "Charles Leclerc")
        self.assertEqual(listener._participant_teams.get(0), "Ferrari")

        # 2. Test Final Classification parsing
        # CLASS_SIZE = 46. Fields: pos (1), n_laps (50), grid (1), pts (25), pits (1), status (3)
        # followed by result_reason (uint8) at offset 6, best_ms (uint32) at offset 7, total_time (double) at offset 11, pen_time (uint8) at offset 19
        class_data = struct.pack('<BBBBBBBIdB', 1, 50, 1, 25, 1, 3, 0, 80000, 5000.0, 0)
        class_data += b'\x00' * 26 # Pad to 46 bytes
        # Pad to contain 22 cars so that CLASS_SIZE is exactly 46
        packet_class = packet_header + b'\x01' + class_data + (b'\x00' * 46 * 21)
        
        listener._current_session_type = 10
        received_results = []
        listener.on_race_end = lambda res: received_results.append(res)
        
        listener._parse_final_classification(packet_class, 2025)
        self.assertEqual(len(received_results), 1)
        res = received_results[0]
        self.assertEqual(len(res.drivers), 1)
        driver = res.drivers[0]
        self.assertEqual(driver.name, "Charles Leclerc")
        self.assertEqual(driver.position, 1)
        self.assertEqual(driver.best_lap_time_ms, 80000)
        self.assertEqual(driver.total_race_time, 5000.0)

    def test_session_history_timing_parsing(self):
        listener = TelemetryListener(on_race_end=None)
        
        # F1 25 header (29 bytes)
        packet_header = struct.pack('<HBBBBBQfIIBB', 2025, 25, 1, 0, 1, 11, 12345, 10.0, 100, 100, 0, 0)
        
        # Session history payload starts with car_idx (uint8), num_laps (uint8), num_tyre_stints (uint8),
        # best_lap_num (uint8), best_s1_lap (uint8), best_s2_lap (uint8), best_s3_lap (uint8) -> 7 bytes
        history_header = struct.pack('<BBBBBBB', 3, 1, 1, 1, 1, 1, 1)
        
        # LapHistoryData (14 bytes): lap_time (uint32), s1_ms (uint16), s1_min (uint8), s2_ms (uint16), s2_min (uint8), s3_ms (uint16), s3_min (uint8), flags (uint8)
        # Sector 1 = 1:15.500 = 75500 ms -> s1_ms = 15500, s1_min = 1
        # Sector 2 = 0:35.250 = 35250 ms -> s2_ms = 35250, s2_min = 0
        # Sector 3 = 0:25.100 = 25100 ms -> s3_ms = 25100, s3_min = 0
        # Lap time = 135850 ms (2:15.850)
        lap_data = struct.pack('<I H B H B H B B', 135850, 15500, 1, 35250, 0, 25100, 0, 1)
        
        packet = packet_header + history_header + lap_data
        
        listener._parse_session_history(packet, 2025)
        
        # Check that we parsed the driver's history correctly
        history = listener._session_histories.get(3)
        self.assertIsNotNone(history)
        self.assertEqual(len(history), 1)
        lap_entry = history[0]
        self.assertEqual(lap_entry["lap"], 1)
        self.assertEqual(lap_entry["lap_time_ms"], 135850)
        self.assertEqual(lap_entry["s1_ms"], 75500)
        self.assertEqual(lap_entry["s2_ms"], 35250)
        self.assertEqual(lap_entry["s3_ms"], 25100)
        self.assertTrue(lap_entry["is_valid"])

if __name__ == "__main__":
    unittest.main()
