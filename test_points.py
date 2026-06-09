import unittest
import struct
import io
from championship import calculate_points, rename_driver, get_completed_races, upgrade_csv_headers
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

    def test_rename_driver(self):
        import os
        import csv
        temp_csv = "temp_test_rename_championship.csv"
        
        # Ensure clean state
        if os.path.exists(temp_csv):
            os.remove(temp_csv)
            
        try:
            # 1. Test when file does not exist
            res = rename_driver("Pilota #0", "Angelo", csv_path=temp_csv)
            self.assertEqual(res, 0)
            
            # 2. Setup test data
            headers = [
                "data", "pilota", "scuderia", "posizione", "punti_base", "bonus_giro_veloce",
                "punti_totali", "giri", "pit_stop", "miglior_giro", "stato",
                "griglia_partenza", "tempo_penalita"
            ]
            rows = [
                {"data": "2026-06-09 18:00:00", "pilota": "Pilota #0", "scuderia": "Ferrari", "posizione": "1", "punti_base": "25", "bonus_giro_veloce": "0", "punti_totali": "25", "giri": "50", "pit_stop": "1", "miglior_giro": "1:30.000", "stato": "Finito", "griglia_partenza": "1", "tempo_penalita": "0"},
                {"data": "2026-06-09 18:00:00", "pilota": "pilota #0", "scuderia": "Ferrari", "posizione": "2", "punti_base": "18", "bonus_giro_veloce": "0", "punti_totali": "18", "giri": "50", "pit_stop": "1", "miglior_giro": "1:30.500", "stato": "Finito", "griglia_partenza": "2", "tempo_penalita": "0"},
                {"data": "2026-06-09 18:00:00", "pilota": "Charles Leclerc", "scuderia": "Ferrari", "posizione": "3", "punti_base": "15", "bonus_giro_veloce": "0", "punti_totali": "15", "giri": "50", "pit_stop": "1", "miglior_giro": "1:31.000", "stato": "Finito", "griglia_partenza": "3", "tempo_penalita": "0"},
            ]
            with open(temp_csv, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()
                writer.writerows(rows)
                
            # 3. Rename with exact match & case-insensitive match
            mod_count = rename_driver("Pilota #0", "Angelo", csv_path=temp_csv)
            self.assertEqual(mod_count, 2) # Both "Pilota #0" and "pilota #0" should match case-insensitively
            
            # 4. Verify content
            with open(temp_csv, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                updated_rows = list(reader)
                
            self.assertEqual(updated_rows[0]["pilota"], "Angelo")
            self.assertEqual(updated_rows[1]["pilota"], "Angelo")
            self.assertEqual(updated_rows[2]["pilota"], "Charles Leclerc")
            
            # 5. Rename non-existent driver
            mod_count_zero = rename_driver("NonExistent", "Nobody", csv_path=temp_csv)
            self.assertEqual(mod_count_zero, 0)
            
        finally:
            if os.path.exists(temp_csv):
                os.remove(temp_csv)

    TEST_CSV_CONTENT = (
        '"Pos.","Pilota","Scuderia","Griglia","Soste","Migliore","Tempo","Pti.","tipo di pilota"\n'
        '"1","Utente","Oracle Red Bull Racing","1","2","1:21,163","42:15,912","25","Utente"\n'
        '"2","POMELLO","Mercedes-AMG F1 Team","2","1","1:21,358","+0,349","18","Utente"\n'
        '"3","Charles LECLERC","Scuderia Ferrari HP","9","1","1:21,146","+4,318","15","IA"\n'
        '"4","Oscar PIASTRI","McLaren","3","1","1:22,469","+4,926","12","IA"\n'
        '"5","Carlos SAINZ","Atlassian Williams F1 Team","7","2","1:22,178","+5,162","10","IA"\n'
        '"6","Andrea Kimi ANTONELLI","Mercedes-AMG F1 Team","5","1","1:22,231","+5,782","8","IA"\n'
        '"7","Lando NORRIS","McLaren","4","1","1:22,065","+6,784","6","IA"\n'
        '"8","Max VERSTAPPEN","Oracle Red Bull Racing","6","1","1:21,523","+7,255","4","IA"\n'
        '"9","Arvid LINDBLAD","Visa Cash App Racing Bulls","12","1","1:22,826","+9,124","2","IA"\n'
        '"10","Alexander ALBON","Atlassian Williams F1 Team","20","2","1:22,224","+9,439","1","IA"\n'
        '"11","Pierre GASLY","Alpine","8","2","1:22,314","+10,352","0","IA"\n'
        '"12","Liam LAWSON","Visa Cash App Racing Bulls","13","1","1:23,288","+11,620","0","IA"\n'
        '"13","Esteban OCON","Haas","16","2","1:22,576","+11,822","0","IA"\n'
        '"14","Nico HULKENBERG","Audi Revolut F1 Team","18","1","1:22,869","+12,180","0","IA"\n'
        '"15","Fernando ALONSO","Aston Martin Aramco","15","2","1:22,236","+12,810","0","IA"\n'
        '"16","Gabriel BORTOLETO","Audi Revolut F1 Team","19","1","1:22,925","+13,126","0","IA"\n'
        '"17","Sergio PÉREZ","Cadillac Formula 1® Team","21","2","1:23,105","+15,300","0","IA"\n'
        '"18","Oliver BEARMAN","Haas","17","2","1:23,099","+15,710","0","IA"\n'
        '"19","Valtteri BOTTAS","Cadillac Formula 1® Team","22","2","1:23,481","+ 1 giro","0","IA"\n'
        '"20","Utente","Scuderia Ferrari HP","11","4","1:19,451","+ 1 giro","0","Utente"\n'
        '"21","Lance STROLL","Aston Martin Aramco","14","2","1:22,965","RIT","0","IA"\n'
        '"22","Franco COLAPINTO","Alpine","10","2","1:23,325","RIT","0","IA"\n'
        '\n'
        '"Tempo","Giro","Pilota","Scuderia","Incidente","Penalità"\n'
    )

    def test_parse_real_csv_files(self):
        # We need a driver_to_team mapping to resolve the two "Utente" players.
        # One is in Oracle Red Bull Racing (Red Bull Racing)
        # Another is in Scuderia Ferrari HP (Ferrari)
        driver_to_team = {
            "Angelo": "Red Bull Racing",
            "Franco": "Ferrari",
        }
        
        result, unresolved = parse_exported_csv(self.TEST_CSV_CONTENT, driver_to_team)
        self.assertEqual(len(unresolved), 0)
        self.assertIsNotNone(result)
        
        # Check that the Red Bull "Utente" is resolved to "Angelo"
        d1 = next(d for d in result.drivers if d.position == 1)
        self.assertEqual(d1.name, "Angelo")
        self.assertEqual(d1.scuderia, "Red Bull Racing")
        
        # Check that the Ferrari "Utente" is resolved to "Franco"
        d20 = next(d for d in result.drivers if d.position == 20)
        self.assertEqual(d20.name, "Franco")
        self.assertEqual(d20.scuderia, "Ferrari")
        
        # Check that "POMELLO" is preserved
        dpomello = next(d for d in result.drivers if d.position == 2)
        self.assertEqual(dpomello.name, "POMELLO")
        self.assertEqual(dpomello.scuderia, "Mercedes")
        
        # Check game year detection (should be 26 because of Audi/Cadillac teams)
        self.assertEqual(result.game_year, 26)

    def test_completed_races_and_migration(self):
        import os
        import csv
        temp_csv = "temp_test_completed_races.csv"
        
        # Ensure clean state
        if os.path.exists(temp_csv):
            os.remove(temp_csv)
            
        try:
            # 1. Setup old CSV data (without nome_gara column)
            old_headers = [
                "data", "pilota", "scuderia", "posizione", "punti_base", "bonus_giro_veloce",
                "punti_totali", "giri", "pit_stop", "miglior_giro", "stato",
                "griglia_partenza", "tempo_penalita"
            ]
            rows = [
                {"data": "2026-06-08 18:00:00", "pilota": "Charles Leclerc", "scuderia": "Ferrari", "posizione": "1", "punti_base": "25", "bonus_giro_veloce": "0", "punti_totali": "25", "giri": "50", "pit_stop": "1", "miglior_giro": "1:30.000", "stato": "Finito", "griglia_partenza": "1", "tempo_penalita": "0"},
                {"data": "2026-06-09 18:00:00", "pilota": "Lewis Hamilton", "scuderia": "Ferrari", "posizione": "2", "punti_base": "18", "bonus_giro_veloce": "0", "punti_totali": "18", "giri": "50", "pit_stop": "1", "miglior_giro": "1:30.500", "stato": "Finito", "griglia_partenza": "2", "tempo_penalita": "0"},
            ]
            with open(temp_csv, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=old_headers)
                writer.writeheader()
                writer.writerows(rows)
                
            # 2. Trigger migration and get races
            races = get_completed_races(temp_csv)
            self.assertEqual(len(races), 2)
            self.assertEqual(races[0], "Gara 2026-06-08")
            self.assertEqual(races[1], "Gara 2026-06-09")
            
            # 3. Check CSV content schema is migrated
            with open(temp_csv, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames
                updated_rows = list(reader)
                
            self.assertIn("nome_gara", headers)
            self.assertEqual(updated_rows[0]["nome_gara"], "Gara 2026-06-08")
            self.assertEqual(updated_rows[1]["nome_gara"], "Gara 2026-06-09")
            
            # 4. Check new race with custom track name
            drivers = [
                DriverResult(name="Charles Leclerc", scuderia="Ferrari", position=1, num_laps=50, grid_position=1, points=0, num_pit_stops=1, result_status=3, best_lap_time_ms=80000, total_race_time=5000.0, penalties_time=0),
            ]
            result = RaceResult(drivers=drivers, fastest_lap_driver="Charles Leclerc", fastest_lap_time_ms=80000, session_type=10, game_year=25, track_name="Monza")
            scored = calculate_points(result)
            self.assertEqual(scored[0]["nome_gara"], "Monza")
            
        finally:
            if os.path.exists(temp_csv):
                os.remove(temp_csv)

    def test_sprint_import_logic(self):
        # Test parsing a CSV file as a Sprint race.
        # It should allocate sprint points (8 to 1) and no fastest lap bonus.
        driver_to_team = {
            "Angelo": "Red Bull Racing",
            "Franco": "Ferrari",
        }
        
        # Parse with is_sprint=True
        result, unresolved = parse_exported_csv(self.TEST_CSV_CONTENT, driver_to_team, is_sprint=True)
        self.assertEqual(len(unresolved), 0)
        self.assertIsNotNone(result)
        self.assertEqual(result.session_type, 11)
        
        # Calculate points
        scored = calculate_points(result)
        
        # P1 (Angelo) should get 8 points
        p1 = next(x for x in scored if x["pilota"] == "Angelo")
        self.assertEqual(p1["punti_base"], 8)
        self.assertEqual(p1["bonus_giro_veloce"], 0)
        self.assertEqual(p1["punti_totali"], 8)
        
        # P2 (POMELLO) should get 7 points
        p2 = next(x for x in scored if x["pilota"] == "POMELLO")
        self.assertEqual(p2["punti_base"], 7)
        
        # P8 (Max Verstappen) should get 1 point
        p8 = next(x for x in scored if x["pilota"] == "Max Verstappen")
        self.assertEqual(p8["punti_base"], 1)
        
        # P9 (Arvid Lindblad) should get 0 points
        p9 = next(x for x in scored if x["pilota"] == "Arvid Lindblad")
        self.assertEqual(p9["punti_base"], 0)

if __name__ == "__main__":
    unittest.main()
