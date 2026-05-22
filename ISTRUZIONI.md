# 🏎️ Angelo Bot - Manuale d'Uso

Benvenuto nel manuale di **Angelo Bot**, il tuo assistente per il tracking del campionato su **F1 25**. Questo documento spiega cosa può fare il bot, come usarlo e quali sono i suoi limiti attuali.

---

## ✅ Cosa PUÒ fare il bot (Funzionalità)

1.  **Rilevamento Automatico**: Il bot ascolta costantemente il gioco. Non devi premere nulla; quando la gara finisce e arrivi alla schermata dei risultati, il bot cattura tutto da solo.
2.  **Calcolo Punti FIA**: Assegna i punti reali della Formula 1:
    *   25, 18, 15, 12, 10, 8, 6, 4, 2, 1.
3.  **Bonus Giro Veloce**: Aggiunge automaticamente **+1 punto** a chi fa il giro più veloce, a patto che sia arrivato tra i primi 10 (regola FIA).
4.  **Salvataggio Storico**: Ogni gara viene scritta nel file `classifica_campionato.csv`. Anche se chiudi il bot, i dati sono al sicuro.
5.  **Report su Discord**: Invia un "Embed" (un messaggio elegante) con:
    *   Il podio con le medaglie.
    *   La classifica dei primi 10 con i punti guadagnati.
    *   Il nome di chi ha fatto il giro veloce e il tempo.
    *   L'elenco dei piloti ritirati o squalificati.
6.  **Classifica Generale**: Con il comando `!classifica`, il bot somma tutti i punti di tutte le gare salvate e mostra la classifica aggiornata del campionato.

---

## ❌ Cosa NON può fare (Limiti Attuali)

1.  **Sessioni di Prova/Qualifica**: Il bot calcola i punti **solo per le Gare** (Gara standard, Sprint, ecc.). Ignora i risultati di Prove Libere e Qualifiche.
2.  **Live Timing**: Il bot non mostra i distacchi in tempo reale mentre guidi. Invia il messaggio solo a sessione conclusa.
3.  **Modifica Nomi Online**: Se giochi online, il bot usa il nome Steam/PSN/Xbox. Se vuoi cambiare il nome di un amico con un soprannome o configurare i nomi AI, usa il file `config.json`.
4.  **Gestione Multi-Canale**: Il bot invia i risultati solo nel canale indicato nel file `.env`.

---

## 🛠️ Comandi Disponibili

| Comando | Descrizione |
| :--- | :--- |
| `/classifica` | Mostra la classifica generale del campionato basata sui dati salvati nel CSV. |
| `/comandi` | Mostra la lista di tutti i comandi disponibili direttamente in Discord. |
| `/telemetria` | Mostra l'analisi telemetrica post-gara (passo gara, potenziale, ecc.) per un pilota. |
| `/importa_risultati` | Importa i risultati di una gara da un file CSV esportato dal gioco. |
| `/forza_salvataggio` | Forza il salvataggio della telemetria se il bot non ha rilevato in automatico. |
| `/annulla_gara` | Cancella l'ultima gara registrata. Mostra due bottoni (Conferma / Annulla). |
| `/nuovo_campionato` | Archivia il campionato attuale in un file separato e ne inizia uno nuovo da zero. |
| `/campionati_lista` | Mostra tutti i file di campionato salvati in precedenza. |
| `/campionato_carica` | Attiva un campionato esistente specificandone il nome. |
| `/campionato_elimina` | Elimina definitivamente il file di un campionato (Irreversibile). |
| `/imposta_scuderia` | Associa retroattivamente e manualmente un pilota a una scuderia specifica. |
| `/assegnazioni_scuderia` | Mostra la lista di tutti i piloti assegnati manualmente a scuderie custom. |
| `/reset_scuderie` | Cancella tutte le assegnazioni manuali delle scuderie. |
| `/rinomina_pilota` | Rinomina un pilota nel campionato corrente e nella telemetria. |
| `/pulisci` | Cancella i messaggi vecchi del bot mantenendo solo l'ultima classifica o report. |

> **Nota:** I comandi appaiono come suggerimenti quando digiti `/` nella chat di Discord.

---

## 💡 Consigli per l'uso

*   **Il file CSV**: Puoi aprire i file `.csv` con Excel per vedere tutti i dettagli (giri fatti, pit stop, penalità ricevute).
*   **Mappa Piloti e Scuderie**: Se fai un campionato locale dove ognuno "impersona" un pilota reale, apri il file `config.json`. Troverai l'elenco `AI_DRIVER_NAMES` e `TEAM_NAMES`. Puoi cambiare i nomi come preferisci (non c'è bisogno di riavviare il bot se usi un JSON tool esterno, altrimenti un riavvio carica le nuove impostazioni).
*   **Stabilità**: Assicurati che il bot sia acceso *prima* di finire la gara, altrimenti non riceverà il pacchetto dei risultati finali.

---

*Creato con passione per i piloti virtuali di F1 25.*
