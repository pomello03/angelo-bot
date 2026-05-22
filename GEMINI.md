# Angelo Bot - F1 25 Discord Telemetry Tracker

## Project Overview
Angelo Bot is a Python-based Discord bot designed to integrate with the F1 25 video game. Its primary purpose is to listen for UDP telemetry data sent by the game, parse race results when a session ends, calculate FIA championship points, save the data to a local CSV file, and automatically post a formatted leaderboard embed to a designated Discord channel.

### Main Technologies
*   **Language:** Python 3.12+
*   **Discord API:** `discord.py`
*   **Configuration:** `python-dotenv` (for `.env` file management)
*   **Networking:** Built-in `socket` and `struct` libraries for UDP packet parsing.

### Architecture
The project is structured into three main modules:
*   **`main.py`:** The entry point. It initializes the Discord bot, sets up **Slash Commands** (e.g., `/classifica`, `/nuovo_campionato`), and spawns a separate background thread for the telemetry listener. It uses `asyncio.to_thread` for blocking I/O and implements graceful shutdown. Includes UI components like `ConfirmView` for interactive confirmation buttons.
*   **`telemetry.py`:** Contains the `TelemetryListener` class. It opens a UDP socket on port 20777 and dynamically parses F1 24/F1 25 data packets (using the `packetFormat` header) to extract race results and driver names.
*   **`championship.py`:** Handles the business logic. It calculates standard FIA points (including fastest lap bonuses) and constructor points, persisting the data to CSV files in append mode.
*   **`config.py` & `config.json`:** Manages state and hardcoded data. It stores the currently active championship CSV, the mapping of AI drivers to real names, and the team names mappings.

## Building and Running

### Prerequisites
1.  Python 3.12 or higher.
2.  A virtual environment (`.venv`) with dependencies installed from `requirements.txt`.
3.  A `.env` file in the project root containing:
    ```env
    DISCORD_TOKEN=your_bot_token_here
    DISCORD_CHANNEL_ID=your_target_channel_id_here
    ```
4.  F1 25 game settings configured to broadcast UDP Telemetry to `127.0.0.1` on port `20777`.
5.  The Discord bot must have the **Message Content Intent** enabled in the Discord Developer Portal to read commands.

### Execution
To run the bot, activate the virtual environment and execute the main script:
```bash
# On Windows
.\.venv\Scripts\activate
python main.py
```

### Testing
There is a basic sanity check script for the point calculation logic.
```bash
python test_points.py
```

## Development Conventions
*   **Language:** Code structure, variables, and classes are primarily in English. However, documentation, comments, and the text output sent to Discord are in **Italian**.
*   **Typing:** The project utilizes standard Python type hinting (`typing` module) and `dataclasses` (`DriverResult`, `RaceResult`) for structured data management.
*   **Concurrency:** The UDP listener runs in a separate daemon thread to ensure the `discord.py` asyncio event loop remains responsive. Thread-to-async communication is handled via `asyncio.run_coroutine_threadsafe`.
*   **Environment:** The workspace is configured to use the local virtual environment `.venv`. VS Code/Cursor users have a `.vscode/settings.json` file configured to enforce this interpreter path.
