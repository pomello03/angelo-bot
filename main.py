"""
main.py - Entry point: Bot Discord + Telemetria F1 25.

Funzionamento:
  1. Avvia il bot Discord (discord.py)
  2. Avvia il listener UDP telemetria F1 25 (porta 20777) in un thread separato
  3. Quando la gara finisce, calcola i punti FIA, salva nel CSV,
     e invia un Embed curato nel canale Discord configurato
  4. Il comando !classifica mostra la classifica generale dal CSV

Configurazione:
  - DISCORD_TOKEN:      Token del bot (dal file .env)
  - DISCORD_CHANNEL_ID: ID del canale dove inviare i risultati (dal file .env)
"""

import sys
import os

# Forza la codifica UTF-8 su Windows per evitare UnicodeEncodeError in console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import glob
import asyncio
import re
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from telemetry import TelemetryListener, RaceResult, format_lap_time
from telemetry import RESULT_FINISHED, RESULT_DNF, RESULT_DSQ, RESULT_RETIRED
from telemetry import RESULT_STATUS_NAMES
from championship import (process_race_result, get_championship_standings,
                         delete_last_race, reset_championship,
                         get_constructors_standings, get_active_csv, set_active_csv,
                         rename_driver, is_duplicate_race)
from config import set_driver_team, clear_driver_teams, get_custom_driver_to_team, DEFAULT_OFFICIAL_TEAMS, get_driver_to_team
from import_parser import parse_exported_csv

# Carica variabili dal file .env
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))

# ============================================================================
# BOT DISCORD
# ============================================================================
intents = discord.Intents.default()
intents.message_content = True

def sanitize_filename(name: str) -> str:
    """Evita path traversal ripulendo il nome del file."""
    clean = re.sub(r'[^\w\-\s]', '', name.replace('.csv', ''))
    return f"{clean}.csv" if clean else "classifica_campionato.csv"

class AngeloBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.telemetry_listener = None

    async def close(self):
        if self.telemetry_listener:
            self.telemetry_listener.stop()
        await super().close()

bot = AngeloBot(command_prefix="!", intents=intents)


# ============================================================================
# EVENTO: BOT PRONTO
# ============================================================================
@bot.event
async def on_ready():
    """Chiamato quando il bot si connette a Discord."""
    print(f"[Discord] Bot connesso come {bot.user}")
    print(f"[Discord] Canale risultati: {DISCORD_CHANNEL_ID}")

    # Avvia il listener telemetria in un thread separato immediatamente per non bloccare
    if not bot.telemetry_listener:
        bot.telemetry_listener = TelemetryListener(on_race_end=lambda result: handle_race_end(result))
        bot.telemetry_listener.start()

    # Avvia la sincronizzazione dei comandi in background
    asyncio.create_task(sync_commands())


async def sync_commands():
    """Sincronizza i comandi in background per evitare blocchi all'avvio."""
    try:
        # Cerca prima in cache
        channel = bot.get_channel(DISCORD_CHANNEL_ID)
        if not channel:
            try:
                # Tenta di recuperare via API se non in cache
                channel = await bot.fetch_channel(DISCORD_CHANNEL_ID)
            except Exception as e:
                print(f"[Discord] Impossibile recuperare il canale {DISCORD_CHANNEL_ID} via API: {e}")

        if channel and hasattr(channel, 'guild') and channel.guild:
            guild = channel.guild
            print(f"[Discord] Sincronizzazione comandi per il server '{guild.name}'...")
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            print(f"[Discord] {len(synced)} slash commands sincronizzati per il server '{guild.name}'.")
        else:
            print(f"[Discord] Canale {DISCORD_CHANNEL_ID} non trovato. Sincronizzazione comandi globale (può richiedere tempo)...")
            synced = await bot.tree.sync()
            print(f"[Discord] {len(synced)} slash commands sincronizzati globalmente.")
    except Exception as e:
        print(f"[Discord] Errore sync comandi: {e}")


# ============================================================================
# GESTIONE FINE GARA (bridge thread -> async)
# ============================================================================
def handle_race_end(result: RaceResult):
    """
    Callback chiamata dal thread telemetria quando la gara finisce.
    Usa asyncio per schedulare l'invio dell'embed nel loop del bot.
    """
    asyncio.run_coroutine_threadsafe(send_race_results(result), bot.loop)


async def send_race_results(result: RaceResult):
    """Calcola i punti, salva il CSV e invia l'embed su Discord."""
    # Calcola punti e salva (in un thread separato per non bloccare il bot)
    scored = await asyncio.to_thread(process_race_result, result)

    # Ottieni il canale
    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    if not channel:
        print(f"[Discord] ERRORE: Canale {DISCORD_CHANNEL_ID} non trovato!")
        return

    # Costruisci l'embed
    embed = build_race_embed(scored, result)
    await channel.send(embed=embed)
    print("[Discord] Embed risultati inviato!")


# ============================================================================
# COSTRUZIONE EMBED
# ============================================================================
def build_race_embed(scored: list, result: RaceResult) -> discord.Embed:
    """
    Costruisce un Embed esteticamente curato con i risultati della gara.

    Struttura:
      - Titolo: "Risultati Gara"
      - Colore: Rosso Ferrari (#DC0000)
      - Podio (Top 3) con emoji medaglie
      - Classifica completa Top 10
      - Giro Veloce
      - Ritirati / DNF / DSQ
    """
    embed = discord.Embed(
        title="🏁  RISULTATI GARA",
        description="Classifica finale e punti campionato",
        color=0xDC0000,  # Rosso F1
    )

    # --- PODIO (Top 3) ---
    medals = ["🥇", "🥈", "🥉"]
    podium_lines = []
    for d in scored[:3]:
        medal = medals[d["posizione"] - 1] if d["posizione"] <= 3 else ""
        lap_info = f" — Miglior giro: {d['miglior_giro']}" if d['miglior_giro'] != "N/A" else ""
        scuderia_str = f" [{d.get('scuderia', '')}]" if d.get("scuderia") and d.get("scuderia") != "Sconosciuta" else ""
        podium_lines.append(
            f"{medal} **P{d['posizione']}** — {d['pilota']}{scuderia_str} "
            f"(+{d['punti_totali']} pt){lap_info}"
        )

    embed.add_field(
        name="🏆  Podio",
        value="\n".join(podium_lines) if podium_lines else "Nessun dato",
        inline=False,
    )

    # --- CLASSIFICA P4-P10 ---
    mid_lines = []
    for d in scored[3:10]:
        if d["posizione"] > 10:
            break
        pts_str = f"+{d['punti_totali']} pt" if d['punti_totali'] > 0 else "0 pt"
        scuderia_str = f" [{d.get('scuderia', '')}]" if d.get("scuderia") and d.get("scuderia") != "Sconosciuta" else ""
        mid_lines.append(f"**P{d['posizione']}** — {d['pilota']}{scuderia_str} ({pts_str})")

    if mid_lines:
        embed.add_field(
            name="📊  Classifica (P4-P10)",
            value="\n".join(mid_lines),
            inline=False,
        )

    # --- GIRO VELOCE ---
    if result.fastest_lap_driver:
        fl_time = format_lap_time(result.fastest_lap_time_ms)
        # Controlla se il pilota ha ottenuto il punto bonus
        fl_driver_data = next(
            (d for d in scored if d["pilota"] == result.fastest_lap_driver), None
        )
        bonus_note = ""
        if fl_driver_data and fl_driver_data["bonus_giro_veloce"] > 0:
            bonus_note = " *(+1 pt bonus)*"

        embed.add_field(
            name="⚡  Giro Veloce",
            value=f"**{result.fastest_lap_driver}** — {fl_time}{bonus_note}",
            inline=False,
        )

    # --- RITIRATI / DNF / DSQ ---
    retired_statuses = {RESULT_DNF, RESULT_DSQ, RESULT_RETIRED}
    retired = [
        d for d in scored
        if _status_code(d["stato"]) in retired_statuses
    ]

    if retired:
        retired_lines = []
        for d in retired:
            retired_lines.append(f"💥 {d['pilota']} — {d['stato']}")
        embed.add_field(
            name="🚫  Ritirati",
            value="\n".join(retired_lines),
            inline=False,
        )

    # Footer
    game_year = getattr(result, "game_year", 25)
    embed.set_footer(text=f"F1 {game_year} Championship Tracker • Powered by Angelo Bot")

    return embed


def _status_code(status_text: str) -> int:
    """Converte il testo dello stato nel codice numerico."""
    for code, text in RESULT_STATUS_NAMES.items():
        if text == status_text:
            return code
    return -1


# ============================================================================
# SLASH COMMAND: /classifica
# ============================================================================
@bot.tree.command(name="classifica", description="Mostra la classifica generale del campionato")
async def classifica_command(interaction: discord.Interaction):
    standings = await asyncio.to_thread(get_championship_standings)
    constructors = await asyncio.to_thread(get_constructors_standings)

    if not standings:
        await interaction.response.send_message(
            "📋 Nessun dato di campionato disponibile. Completa almeno una gara!")
        return

    active_champ = get_active_csv().replace(".csv", "").replace("_", " ").title()

    embed = discord.Embed(
        title=f"🏆  CLASSIFICA: {active_champ}",
        description="Classifica generale aggiornata",
        color=0xFFD700,
    )

    lines = []
    for i, (name, points) in enumerate(standings, start=1):
        if i == 1: prefix = "🥇"
        elif i == 2: prefix = "🥈"
        elif i == 3: prefix = "🥉"
        else: prefix = f"**{i}.**"
        lines.append(f"{prefix} {name} — **{points} pt**")

    chunk_size = 25
    for idx in range(0, len(lines), chunk_size):
        chunk = lines[idx:idx + chunk_size]
        field_name = "Piloti" if idx == 0 else "Piloti (cont.)"
        embed.add_field(name=field_name, value="\n".join(chunk), inline=False)

    if constructors:
        c_lines = []
        for i, (team, points) in enumerate(constructors, start=1):
            if i == 1: prefix = "🥇"
            elif i == 2: prefix = "🥈"
            elif i == 3: prefix = "🥉"
            else: prefix = f"**{i}.**"
            c_lines.append(f"{prefix} {team} — **{points} pt**")
        embed.add_field(name="Costruttori", value="\n".join(c_lines), inline=False)

    embed.set_footer(text=f"File: {get_active_csv()} • /classifica")
    await interaction.response.send_message(embed=embed)


# ============================================================================
# SLASH COMMAND: /assegnazioni_scuderia
# ============================================================================
@bot.tree.command(name="assegnazioni_scuderia", description="Mostra le assegnazioni manuali dei piloti alle scuderie")
async def assegnazioni_scuderia_command(interaction: discord.Interaction):
    custom_mappings = await asyncio.to_thread(get_custom_driver_to_team)

    if not custom_mappings:
        await interaction.response.send_message(
            "📋 Nessuna assegnazione manuale creata. I piloti usano i team di default.")
        return

    embed = discord.Embed(
        title="🔧 ASSEGNAZIONI MANUALI SCUDERIE",
        description="Questi piloti hanno una scuderia personalizzata che sovrascrive quella ufficiale.",
        color=0x9B59B6, # Viola
    )

    lines = []
    for pilota, scuderia in custom_mappings.items():
        lines.append(f"**{pilota}** ➡️ {scuderia}")

    embed.add_field(name="Piloti Assegnati", value="\n".join(lines), inline=False)
    embed.set_footer(text="/assegnazioni_scuderia")
    
    await interaction.response.send_message(embed=embed)


# ============================================================================
# SLASH COMMAND: /pulisci
# ============================================================================
@bot.tree.command(name="pulisci", description="Pulisce la chat mantenendo solo l'ultimo report o classifica del bot")
async def pulisci_command(interaction: discord.Interaction):
    # Risponde in modo pubblico in modo che Discord crei un messaggio di interazione eliminabile
    await interaction.response.defer(ephemeral=False)
    
    try:
        original = await interaction.original_response()
    except:
        original = None
    
    # Trova l'ultimo messaggio del bot che contiene un Embed (report o classifica)
    last_bot_msg = None
    async for msg in interaction.channel.history(limit=50):
        if msg.author == bot.user and msg.embeds:
            last_bot_msg = msg
            break
            
    def check(msg):
        # Elimina solo i messaggi del bot per non cancellare messaggi di utenti reali
        if msg.author != bot.user:
            return False
        # Salva solo l'ultimo messaggio Embed del bot
        if last_bot_msg and msg.id == last_bot_msg.id:
            return False
        # Salva il messaggio di interazione per non far fallire l'edit successivo
        if original and msg.id == original.id:
            return False
        return True

    try:
        # Cancella fino a 100 messaggi che rispettano la regola sopra
        deleted = await interaction.channel.purge(limit=100, check=check)
        
        # Invia il messaggio di conferma pubblico aggiornando la risposta originale
        await interaction.edit_original_response(content=f"🧹 Pulizia completata! Cancellati {len(deleted)} messaggi obsoleti.")
        
        # Aspetta 3 secondi e poi cancella il messaggio di conferma,
        # che eliminerà automaticamente anche la traccia del comando "/pulisci" inviato dall'utente
        await asyncio.sleep(3)
        await interaction.delete_original_response()
        
    except discord.Forbidden:
        await interaction.edit_original_response(content="❌ Errore: Il bot non ha i permessi per gestire i messaggi. Assicurati che abbia il ruolo di amministratore o il permesso 'Gestisci Messaggi'.")
    except Exception as e:
        try:
            await interaction.edit_original_response(content=f"❌ Errore durante la pulizia: {e}")
        except:
            pass


# ============================================================================
# SLASH COMMAND: /imposta_scuderia
# ============================================================================
async def pilota_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    # Raccogli piloti dal CSV attivo
    standings = await asyncio.to_thread(get_championship_standings)
    csv_drivers = [s[0] for s in standings] if standings else []
    
    # Raccogli piloti ufficiali
    official_drivers = list(DEFAULT_OFFICIAL_TEAMS.keys())
    
    # Unisci rimuovendo i duplicati
    all_drivers = list(set(csv_drivers + official_drivers))
    all_drivers.sort()
    
    choices = []
    for name in all_drivers:
        if current.lower() in name.lower():
            choices.append(app_commands.Choice(name=name, value=name))
    return choices[:25]

@bot.tree.command(name="imposta_scuderia", description="Associa retroattivamente un pilota a una scuderia")
@app_commands.describe(pilota="Scegli un pilota ufficiale o uno che ha completato una gara", scuderia="Scegli la scuderia")
@app_commands.autocomplete(pilota=pilota_autocomplete)
@app_commands.choices(scuderia=[
    app_commands.Choice(name="Ferrari", value="Ferrari"),
    app_commands.Choice(name="Mercedes", value="Mercedes"),
    app_commands.Choice(name="Red Bull Racing", value="Red Bull Racing"),
    app_commands.Choice(name="McLaren", value="McLaren"),
    app_commands.Choice(name="Aston Martin", value="Aston Martin"),
    app_commands.Choice(name="Alpine", value="Alpine"),
    app_commands.Choice(name="Williams", value="Williams"),
    app_commands.Choice(name="RB", value="RB"),
    app_commands.Choice(name="Haas", value="Haas"),
    app_commands.Choice(name="Kick Sauber", value="Kick Sauber")
])
async def imposta_scuderia_command(interaction: discord.Interaction, pilota: str, scuderia: app_commands.Choice[str]):
    # Validazione pilota
    standings = await asyncio.to_thread(get_championship_standings)
    csv_drivers = [s[0] for s in standings] if standings else []
    official_drivers = list(DEFAULT_OFFICIAL_TEAMS.keys())
    all_valid_drivers = set(csv_drivers + official_drivers)

    # Confronto case-insensitive ma salviamo il nome con la forma originale se è nel CSV
    valid_name = None
    for name in all_valid_drivers:
        if name.lower() == pilota.lower():
            valid_name = name
            break
            
    if not valid_name:
        # Se il pilota non è nei file ufficiali o nel CSV, lo accettiamo comunque per rompere il loop del nuovo campionato
        valid_name = pilota.strip()

    team_val = scuderia.value
    await asyncio.to_thread(set_driver_team, valid_name, team_val)
    await interaction.response.send_message(f"✅ Fatto! I punti di **{valid_name}** d'ora in poi andranno alla scuderia **{team_val}** nel calcolo costruttori.")


# ============================================================================
# SLASH COMMAND: /rinomina_pilota
# ============================================================================
@bot.tree.command(name="rinomina_pilota", description="Rinomina un pilota nel campionato (es. per correggere 'Pilota #0')")
@app_commands.describe(nome_attuale="Il nome sbagliato (es. Pilota #0)", nome_nuovo="Il nome corretto (es. Angelo)")
@app_commands.autocomplete(nome_attuale=pilota_autocomplete)
async def rinomina_pilota_command(interaction: discord.Interaction, nome_attuale: str, nome_nuovo: str):
    import json
    
    # 1. Rinomina nel CSV
    modifiche = await asyncio.to_thread(rename_driver, nome_attuale, nome_nuovo)
    
    # 2. Rinomina nella telemetria se presente
    file_path = "last_race_telemetry.json"
    telemetry_fixed = False
    if os.path.isfile(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # Cerca il nome attuale in modo flessibile
            found_key = None
            for key in data.keys():
                if nome_attuale.lower() == key.lower():
                    found_key = key
                    break
                    
            if found_key:
                data[nome_nuovo] = data.pop(found_key)
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4)
                telemetry_fixed = True
        except Exception as e:
            print(f"[Rinomina] Errore json: {e}")
            pass

    if modifiche > 0:
        msg = f"✅ Il pilota **{nome_attuale}** è stato rinominato in **{nome_nuovo}**."
        if telemetry_fixed:
            msg += "\n📊 Anche i dati telemetrici sono stati aggiornati!"
        await interaction.response.send_message(msg)
    else:
        await interaction.response.send_message(f"⚠️ Il pilota **{nome_attuale}** non è stato trovato nel campionato attivo.", ephemeral=True)


# ============================================================================
# SLASH COMMAND: /reset_scuderie
# ============================================================================
@bot.tree.command(name="reset_scuderie", description="Cancella tutte le assegnazioni manuali dei piloti alle scuderie")
async def reset_scuderie_command(interaction: discord.Interaction):
    await asyncio.to_thread(clear_driver_teams)
    await interaction.response.send_message("🧹 Tutte le assegnazioni manuali dei piloti sono state cancellate.\nI piloti ufficiali torneranno ai team di default.")


# ============================================================================
# SLASH COMMAND: /telemetria
# ============================================================================
async def telemetria_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    import json
    import os
    file_path = "last_race_telemetry.json"
    if not os.path.isfile(file_path):
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        choices = []
        for name in data.keys():
            if current.lower() in name.lower():
                choices.append(app_commands.Choice(name=name, value=name))
        return choices[:25] # Discord supporta max 25 scelte
    except Exception:
        return []

@bot.tree.command(name="telemetria", description="Ingegnere di Pista: Analisi telemetrica post-gara per un pilota")
@app_commands.describe(pilota="Nome del pilota (es. Leclerc)")
@app_commands.autocomplete(pilota=telemetria_autocomplete)
async def telemetria_command(interaction: discord.Interaction, pilota: str):
    import json
    
    file_path = "last_race_telemetry.json"
    if not os.path.isfile(file_path):
        await interaction.response.send_message("❌ Nessuna telemetria recente. Completa una gara prima di usare questo comando.", ephemeral=True)
        return
        
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        await interaction.response.send_message("❌ Errore nella lettura del file telemetria.", ephemeral=True)
        return
        
    # Cerca il pilota case-insensitive
    target_history = None
    target_name = ""
    for name, history in data.items():
        if pilota.lower() in name.lower():
            target_history = history
            target_name = name
            break
            
    if not target_history:
        await interaction.response.send_message(f"❌ Nessuna telemetria trovata per il pilota '{pilota}'. Verifica il nome esatto.", ephemeral=True)
        return

    # Calcoli Ingegneristici
    valid_laps = [lap for lap in target_history if lap["lap_time_ms"] > 0]
    if not valid_laps:
        await interaction.response.send_message(f"❌ Il pilota {target_name} non ha completato alcun giro valido.", ephemeral=True)
        return

    best_lap = min(valid_laps, key=lambda x: x["lap_time_ms"])
    
    # Settori Ideali
    s1_laps = [lap["s1_ms"] for lap in valid_laps if lap["s1_ms"] > 0]
    s2_laps = [lap["s2_ms"] for lap in valid_laps if lap["s2_ms"] > 0]
    s3_laps = [lap["s3_ms"] for lap in valid_laps if lap["s3_ms"] > 0]
    
    best_s1 = min(s1_laps) if s1_laps else 0
    best_s2 = min(s2_laps) if s2_laps else 0
    best_s3 = min(s3_laps) if s3_laps else 0
    
    ideal_lap_ms = best_s1 + best_s2 + best_s3
    
    # Passo Gara (escludiamo giri > 107% del best lap per tagliare outlaps, pitstop, SC)
    threshold_ms = best_lap["lap_time_ms"] * 1.07
    pace_laps = [lap["lap_time_ms"] for lap in valid_laps if lap["lap_time_ms"] <= threshold_ms]
    
    avg_pace_ms = sum(pace_laps) / len(pace_laps) if pace_laps else 0
    
    # Differenza Migliore vs Ideale
    delta_ms = best_lap["lap_time_ms"] - ideal_lap_ms
    
    # Creazione Embed
    embed = discord.Embed(
        title=f"📊  TELEMETRIA POST-GARA: {target_name}",
        description="Analisi Ingegneristica (Passo, Settori, Potenziale)",
        color=0x2ECC71, # Verde "Ingegnere"
    )
    
    embed.add_field(
        name="⏱️  Passo Gara (Race Pace)",
        value=f"**{format_lap_time(avg_pace_ms)}**\n*(Media calcolata su {len(pace_laps)} giri competitivi)*",
        inline=False
    )
    
    embed.add_field(
        name="🚀  Miglior Giro",
        value=f"**{format_lap_time(best_lap['lap_time_ms'])}** (Giro {best_lap['lap']})",
        inline=True
    )
    
    embed.add_field(
        name="✨  Giro Ideale",
        value=f"**{format_lap_time(ideal_lap_ms)}**\n*(S1: {best_s1/1000:.3f} | S2: {best_s2/1000:.3f} | S3: {best_s3/1000:.3f})*",
        inline=True
    )
    
    delta_str = f"+{delta_ms/1000:.3f}s" if delta_ms > 0 else "Giro Perfetto!"
    embed.add_field(
        name="🔍  Potenziale Inespresso",
        value=f"Hai lasciato **{delta_str}** sul tavolo rispetto alla somma dei tuoi migliori settori assoluti.",
        inline=False
    )
    
    embed.set_footer(text="F1 25 Virtual Race Engineer • Powered by Angelo Bot")
    await interaction.response.send_message(embed=embed)


# ============================================================================
# SLASH COMMAND: /annulla_gara
# ============================================================================
@bot.tree.command(name="annulla_gara", description="Cancella l'ultima gara registrata dal campionato")
async def annulla_gara_command(interaction: discord.Interaction):
    # Invia un messaggio con i bottoni di conferma
    confirm_view = ConfirmView(interaction.user)
    await interaction.response.send_message(
        "⚠️ Stai per cancellare l'ultima gara registrata. Sei sicuro?",
        view=confirm_view
    )
    await confirm_view.wait()

    if confirm_view.confirmed:
        result_msg = await asyncio.to_thread(delete_last_race)
        await interaction.edit_original_response(content=f"🗑️ {result_msg}", view=None)
    else:
        await interaction.edit_original_response(content="❌ Operazione annullata.", view=None)


# ============================================================================
# SLASH COMMAND: /importa_risultati
# ============================================================================
@bot.tree.command(name="importa_risultati", description="Importa i risultati di una gara da un file esportato da F1 25")
@app_commands.describe(
    file="Il file CSV generato dalla funzione 'esporta risultati sessione'",
    tipo_gara="Scegli se è una Gara Standard o una Gara Sprint"
)
@app_commands.choices(tipo_gara=[
    app_commands.Choice(name="Standard", value="standard"),
    app_commands.Choice(name="Sprint", value="sprint")
])
async def importa_risultati_command(interaction: discord.Interaction, file: discord.Attachment, tipo_gara: app_commands.Choice[str] = None):
    await interaction.response.defer()

    # --- Validazione file ---
    if not file.filename.lower().endswith('.csv'):
        await interaction.edit_original_response(
            content="❌ Il file deve essere un `.csv` esportato da F1 25 / F1 26.\n"
                    "Nel gioco: **Esporta risultati sessione** dalla schermata dei risultati.")
        return

    if file.size > 500_000:  # 500 KB, un CSV di gara non supera mai i 10 KB
        await interaction.edit_original_response(
            content="❌ Il file è troppo grande. Sei sicuro che sia un file esportato da F1 25 / F1 26?")
        return

    # --- Lettura file ---
    try:
        content_bytes = await file.read()
        # Prova UTF-8, poi fallback a latin-1 (Windows)
        try:
            content_text = content_bytes.decode('utf-8')
        except UnicodeDecodeError:
            content_text = content_bytes.decode('latin-1')
    except Exception as e:
        await interaction.edit_original_response(content=f"❌ Errore durante la lettura del file: {e}")
        return

    # --- Validazione contenuto minima ---
    if '"Pos."' not in content_text and '"Pilota"' not in content_text:
        await interaction.edit_original_response(
            content="❌ Il file non sembra essere un CSV di risultati F1 25 / F1 26.\n"
                    "Deve contenere le colonne `Pos.`, `Pilota`, `Scuderia`, ecc.")
        return

    # --- Parsing ---
    try:
        is_sprint = False
        if tipo_gara and tipo_gara.value == "sprint":
            is_sprint = True
        driver_mapping = await asyncio.to_thread(get_custom_driver_to_team)
        result, unresolved = await asyncio.to_thread(
            parse_exported_csv, content_text, driver_mapping, is_sprint)
    except Exception as e:
        await interaction.edit_original_response(
            content=f"❌ Errore durante il parsing del file: {e}")
        return

    # --- Gestione "Utente" non risolti ---
    if unresolved:
        lines = []
        for idx, team in unresolved:
            lines.append(f"• Posizione {idx + 1}, scuderia **{team}**")
        await interaction.edit_original_response(
            content="⚠️ Non riesco a capire chi sono questi giocatori:\n"
                    + "\n".join(lines) +
                    "\n\nUsa `/imposta_scuderia` per assegnare ogni giocatore "
                    "alla sua scuderia, poi riprova il comando.")
        return

    if result is None or not result.drivers:
        await interaction.edit_original_response(
            content="❌ Il file è stato letto ma non contiene piloti validi. "
                    "Controlla che sia un export di una gara completata.")
        return

    # --- Anteprima e conferma ---
    preview_lines = []
    for d in result.drivers[:5]:
        status = "🏁" if d.result_status == RESULT_FINISHED else "💥 RIT"
        preview_lines.append(f"P{d.position} — {d.name} [{d.scuderia}] {status}")
    if len(result.drivers) > 5:
        preview_lines.append(f"... e altri {len(result.drivers) - 5} piloti")

    # Controlla se è un duplicato
    is_dup = await asyncio.to_thread(is_duplicate_race, result)
    dup_warning = ""
    if is_dup:
        dup_warning = "\n\n⚠️ **ATTENZIONE: Questa gara sembra IDENTICA all'ultima già salvata!** Se procedi, potresti sdoppiare i punti. (In caso di errore potrai usare `/annulla_gara`)."

    confirm_view = ConfirmView(interaction.user)
    await interaction.edit_original_response(
        content=f"📋 **Anteprima importazione** ({len(result.drivers)} piloti):\n"
                + "\n".join(preview_lines)
                + f"\n\n⚡ Giro veloce: **{result.fastest_lap_driver}**"
                + dup_warning
                + f"\n\nVuoi salvare questi risultati nel campionato **{get_active_csv()}**?",
        view=confirm_view)
    await confirm_view.wait()

    if not confirm_view.confirmed:
        await interaction.edit_original_response(
            content="❌ Importazione annullata.", view=None)
        return

    # --- Salvataggio ---
    try:
        scored = await asyncio.to_thread(process_race_result, result)
    except Exception as e:
        await interaction.edit_original_response(
            content=f"❌ Errore durante il salvataggio: {e}", view=None)
        return

    embed = build_race_embed(scored, result)
    await interaction.edit_original_response(
        content="✅ Risultati importati e salvati con successo!",
        embed=embed, view=None)


# ============================================================================
# SLASH COMMAND: /forza_salvataggio
# ============================================================================
@bot.tree.command(name="forza_salvataggio", description="Forza il salvataggio della telemetria attuale (se avviato a gara finita)")
async def forza_salvataggio_command(interaction: discord.Interaction):
    if not bot.telemetry_listener:
        await interaction.response.send_message("❌ Il listener di telemetria non è attivo.", ephemeral=True)
        return
        
    # Forza il reset dei flag per catturare il prossimo pacchetto Classifica
    bot.telemetry_listener._race_already_processed = False
    bot.telemetry_listener._last_classification_hash = None
    
    await interaction.response.send_message("✅ Segnale inviato! Se il gioco sta ancora trasmettendo la schermata dei risultati, il bot elaborerà e salverà la gara entro 5 secondi.\n*Nota: Non spammare questo comando. Se salvi due volte per errore, usa `/annulla_gara`.*")


# ============================================================================
# SLASH COMMAND: /nuovo_campionato
# ============================================================================
@bot.tree.command(name="nuovo_campionato", description="Crea un nuovo campionato e lo imposta come attivo")
@app_commands.describe(nome="Nome del nuovo campionato (es. Stagione 2)")
async def nuovo_campionato_command(interaction: discord.Interaction, nome: str):
    safe_nome = sanitize_filename(nome)
    confirm_view = ConfirmView(interaction.user)
    await interaction.response.send_message(
        f"🚨 Stai per iniziare il nuovo campionato: **{safe_nome}**.\nSei sicuro?",
        view=confirm_view
    )
    await confirm_view.wait()

    if confirm_view.confirmed:
        result_msg = await asyncio.to_thread(reset_championship, safe_nome)
        await interaction.edit_original_response(content=f"🆕 {result_msg}", view=None)
    else:
        await interaction.edit_original_response(content="❌ Operazione annullata.", view=None)


# ============================================================================
# GESTIONE CAMPIONATI MULTIPLI
# ============================================================================
async def campionati_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    files = glob.glob("*.csv")
    choices = []
    for f in files:
        name_display = f.replace(".csv", "")
        if current.lower() in name_display.lower():
            choices.append(app_commands.Choice(name=name_display, value=name_display))
    return choices[:25]

@bot.tree.command(name="campionati_lista", description="Mostra tutti i campionati salvati")
async def campionati_lista_command(interaction: discord.Interaction):
    files = glob.glob("*.csv")
    active = get_active_csv()
    
    if not files:
        await interaction.response.send_message("Nessun campionato trovato.")
        return
        
    msg = "**Campionati disponibili:**\n"
    for f in files:
        marker = "🟢 (Attivo)" if f == active else "⚪"
        msg += f"{marker} `{f}`\n"
        
    await interaction.response.send_message(msg)

@bot.tree.command(name="campionato_carica", description="Carica e attiva un campionato esistente")
@app_commands.describe(nome="Scegli il campionato dalla lista")
@app_commands.autocomplete(nome=campionati_autocomplete)
async def campionato_carica_command(interaction: discord.Interaction, nome: str):
    safe_nome = sanitize_filename(nome)
    if not os.path.isfile(safe_nome):
        await interaction.response.send_message(f"❌ File `{safe_nome}` non trovato. Usa /campionati_lista.")
        return
        
    set_active_csv(safe_nome)
    await interaction.response.send_message(f"✅ Campionato attivo cambiato in: **{safe_nome}**")

@bot.tree.command(name="campionato_elimina", description="Elimina definitivamente un campionato")
@app_commands.describe(nome="Scegli il campionato da eliminare")
@app_commands.autocomplete(nome=campionati_autocomplete)
async def campionato_elimina_command(interaction: discord.Interaction, nome: str):
    safe_nome = sanitize_filename(nome)
    if not os.path.isfile(safe_nome):
        await interaction.response.send_message(f"❌ File `{safe_nome}` non trovato.")
        return
        
    confirm_view = ConfirmView(interaction.user)
    await interaction.response.send_message(
        f"⚠️ Stai per eliminare DEFINITIVAMENTE il file **{safe_nome}**. L'operazione è IRREVERSIBILE. Sei sicuro?",
        view=confirm_view
    )
    await confirm_view.wait()

    if confirm_view.confirmed:
        was_active = (get_active_csv() == safe_nome)
        await asyncio.to_thread(os.remove, safe_nome)
        
        msg_content = f"🗑️ Campionato `{safe_nome}` eliminato."
        view = None
        
        if was_active:
            # Abbiamo eliminato quello attivo, cerchiamo di capire quale attivare
            files = glob.glob("*.csv")
            if len(files) == 1:
                set_active_csv(files[0])
                msg_content += f"\n✅ Il campionato **{files[0]}** è diventato automaticamente quello attivo."
            elif len(files) > 1:
                set_active_csv("classifica_campionato.csv") # Reset di sicurezza
                msg_content += "\n⚠️ Hai eliminato il campionato attivo. Seleziona il prossimo campionato da attivare:"
                view = SelectChampionshipView(interaction.user, files)
            else:
                set_active_csv("classifica_campionato.csv")
                msg_content += "\nℹ️ Nessun altro campionato trovato. Al prossimo salvataggio verrà creato `classifica_campionato.csv`."

        await interaction.edit_original_response(content=msg_content, view=view)
    else:
        await interaction.edit_original_response(content="❌ Operazione annullata.", view=None)

# ============================================================================
# SLASH COMMAND: /comandi
# ============================================================================
@bot.tree.command(name="comandi", description="Mostra la lista dei comandi disponibili")
async def comandi_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🛠️ COMANDI DISPONIBILI",
        description="Ecco cosa posso fare per te:",
        color=0x3498DB
    )
    comandi_lista = [
        ("`/classifica`", "Mostra la classifica generale del campionato attivo"),
        ("`/telemetria`", "Analisi telemetrica post-gara per un pilota"),
        ("`/importa_risultati`", "Importa i risultati da un file CSV esportato dal gioco"),
        ("`/annulla_gara`", "Cancella l'ultima gara registrata"),
        ("`/forza_salvataggio`", "Forza il salvataggio della telemetria a gara finita"),
        ("`/nuovo_campionato`", "Crea un nuovo campionato da zero"),
        ("`/campionati_lista`", "Mostra tutti i campionati salvati"),
        ("`/campionato_carica`", "Carica e attiva un campionato esistente"),
        ("`/campionato_elimina`", "Elimina definitivamente un file campionato"),
        ("`/imposta_scuderia`", "Associa un pilota a una scuderia"),
        ("`/assegnazioni_scuderia`", "Mostra le assegnazioni manuali attive dei piloti"),
        ("`/reset_scuderie`", "Cancella tutte le assegnazioni manuali"),
        ("`/rinomina_pilota`", "Rinomina un pilota nel campionato"),
        ("`/pulisci`", "Pulisce i messaggi vecchi del bot in chat")
    ]
    for cmd, desc in comandi_lista:
        embed.add_field(name=cmd, value=desc, inline=False)
        
    embed.set_footer(text="Angelo Bot • Gestione F1 25")
    await interaction.response.send_message(embed=embed)


# ============================================================================
# VIEW DI SELEZIONE CAMPIONATO (Dropdown)
# ============================================================================
class SelectChampionshipView(discord.ui.View):
    def __init__(self, author: discord.User, files: list):
        super().__init__(timeout=60)
        self.author = author
        
        options = []
        for f in files[:25]: # Discord max 25 options
            options.append(discord.SelectOption(label=f.replace(".csv", ""), value=f))
            
        select = discord.ui.Select(
            placeholder="Scegli un campionato...",
            min_values=1,
            max_values=1,
            options=options
        )
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        if interaction.user != self.author:
            await interaction.response.send_message("Solo chi ha lanciato il comando può selezionare.", ephemeral=True)
            return
            
        selected_file = interaction.data["values"][0]
        set_active_csv(selected_file)
        
        # Disabilita il select
        for child in self.children:
            child.disabled = True
            
        await interaction.response.edit_message(
            content=f"✅ Campionato attivo cambiato con successo in: **{selected_file}**",
            view=self
        )
        self.stop()


# ============================================================================
# VIEW DI CONFERMA (bottoni Conferma / Annulla)
# ============================================================================
class ConfirmView(discord.ui.View):
    """Mostra due bottoni: Conferma e Annulla."""

    def __init__(self, author: discord.User):
        super().__init__(timeout=30)
        self.author = author
        self.confirmed = False

    @discord.ui.button(label="✅ Conferma", style=discord.ButtonStyle.danger)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            await interaction.response.send_message("Solo chi ha lanciato il comando può confermare.", ephemeral=True)
            return
        self.confirmed = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="❌ Annulla", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            await interaction.response.send_message("Solo chi ha lanciato il comando può annullare.", ephemeral=True)
            return
        self.confirmed = False
        self.stop()
        await interaction.response.defer()

    async def on_timeout(self):
        self.confirmed = False
        self.stop()


# ============================================================================
# ENTRY POINT
# ============================================================================
if __name__ == "__main__":
    if not DISCORD_TOKEN or DISCORD_TOKEN == "IL_TUO_TOKEN_QUI":
        print("=" * 60)
        print("ERRORE: Token Discord non configurato!")
        print("")
        print("1. Vai su https://discord.com/developers/applications")
        print("2. Crea una nuova applicazione e un bot")
        print("3. Copia il token del bot")
        print("4. Incollalo nel file .env alla voce DISCORD_TOKEN")
        print("5. Invita il bot nel tuo server con i permessi necessari")
        print("=" * 60)
        exit(1)

    if DISCORD_CHANNEL_ID == 0:
        print("=" * 60)
        print("ERRORE: ID canale Discord non configurato!")
        print("")
        print("1. In Discord, attiva la Modalita' Sviluppatore")
        print("   (Impostazioni > App > Avanzate > Modalita' Sviluppatore)")
        print("2. Click destro sul canale > 'Copia ID canale'")
        print("3. Incolla l'ID nel file .env alla voce DISCORD_CHANNEL_ID")
        print("=" * 60)
        exit(1)

    print("[Angelo Bot] Avvio in corso...")
    print(f"[Angelo Bot] Canale target: {DISCORD_CHANNEL_ID}")
    print("[Angelo Bot] In attesa di telemetria F1 25 sulla porta 20777...")
    try:
        bot.run(DISCORD_TOKEN)
    except discord.errors.PrivilegedIntentsRequired:
        print("=" * 60)
        print("ERRORE: Privileged Intents non abilitati!")
        print("")
        print("Il bot richiede l'intento 'Message Content' per leggere i comandi.")
        print("1. Vai su https://discord.com/developers/applications")
        print("2. Seleziona la tua applicazione e vai nel tab 'Bot'")
        print("3. Scorri in basso fino a 'Privileged Gateway Intents'")
        print("4. Attiva 'Message Content Intent'")
        print("5. Salva le modifiche e riavvia il bot.")
        print("=" * 60)
        exit(1)
