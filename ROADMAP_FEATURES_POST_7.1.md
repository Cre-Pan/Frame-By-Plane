# Frame By Plane — roadmap feature post-7.1

Questa roadmap è separata dai bugfix LTS. Nessuna voce è stata implementata automaticamente nell’audit 7.1.18.

## Ordine consigliato

| Ordine | ID | Feature | Valore utente | Costo | Rischio | Dipendenze | Compatibilità LTS |
|---:|---|---|---|---|---|---|---|
| 1 | F10 | Headless self-test e CI | Molto alto | Medio | Basso-medio | Fixture versionate, runner multi-OS, artifact retention | Nessun cambio dati; gate indispensabile per le feature successive. |
| 2 | F4 | Collect Project / Portability Checker | Molto alto | Medio-alto | Medio | Scanner media, hash incrementali, dry-run, collision policy | Solo copia per default; originali immutati; schema report versionato. |
| 3 | F1 | Proxy e cache per sequenze | Molto alto | Alto | Alto | F10, cache journal, fingerprint mtime/size/hash, budget RAM/disk | Render usa gli originali salvo opt-in; cache esterna ricostruibile. |
| 4 | F2 | Performance budget di scena | Alto | Medio | Basso-medio | Dashboard schema 2, misure cache/GPU più solide | Suggerimenti default read-only; Optimize Viewport reversibile. |
| 5 | F5 | Batch relink con regole | Alto | Medio | Medio-alto | F4 scanner/hash, preview conflitti, manifest rollback | Nessuna rinomina/copia prima di conferma; path RNA invariati. |
| 6 | F9 | Recovery journal operazioni lunghe | Alto | Alto | Alto | Transazioni chunk attuali, schema journal, cleanup orfani | Journal locale senza dati sensibili; migrazione/versione obbligatoria. |
| 7 | F3 | Effect Graph / Dependency Inspector | Alto | Medio-alto | Medio | Indice runtime stabile, ownership graph, cost model | Prima release diagnostica/read-only; nessun nuovo Effect ID. |
| 8 | F11 | Accessibilità e navigazione UI | Medio | Medio | Basso | Audit keyboard/focus, token UI, test contrasto | Preferenze `SKIP_SAVE` dove possibile; nessuna dipendenza esclusiva dal colore. |
| 9 | F7 | Preset versioning e migrazione | Medio | Medio | Medio | Backup attuale, schema diff, migratori fixture | Versione schema e migrazione esplicita; Keep Both come default sicuro. |
| 10 | F6 | A/B compare e snapshot effetti | Medio-alto | Medio | Medio | Transazioni effect stack, overlay compare, restore in `finally` | Snapshot temporanei; nessun duplicato permanente o cambio ID. |
| 11 | F8 | Grease Pencil effect conversion roadmap | Alto | Alto | Alto | Matrice compatibilità, benchmark visuali, GN/raster backends | Sempre non distruttiva; differenze visive dichiarate; resta Preview finché non qualificata. |

## Milestone A — infrastruttura di fiducia

### F10 — Headless self-test e CI

- Eseguire background suite su Windows x64/ARM64, macOS x64/ARM64 e Linux x64.
- Separare core LTS e feature Preview.
- Salvare JSON, stdout/stderr, `.blend` di riproduzione e render minimi.
- Fallire su handler/timer/classi duplicati, leak, mismatch schema e render mancanti.
- Aggiungere fixture piccole per versione precedente 7.1.x, Unicode, path lunghi e read-only.

Exit criteria: tutti i target dichiarati nel manifest hanno almeno enable/disable, save/reopen, import, GP, Eevee/Cycles e Project Doctor verdi.

### F4 — Collect Project / Portability Checker

- Dry-run obbligatorio con dimensione prevista, file mancanti, collisioni e hash.
- Copia in destinazione nuova; mai modificare gli originali.
- Path relativi applicati in una transazione Blender separata e annullabile.
- Includere preset e proxy soltanto se necessari e dichiarati.

Exit criteria: pacchetto raccolto riapre offline su una seconda macchina senza path assoluti residui.

## Milestone B — media e performance

### F1 — Proxy e cache per sequenze

- Profili 25/50/100%, distinti per Viewport e Render.
- Cache LRU con limiti RAM/disk e statistiche hit/miss/eviction/prefetch.
- Fingerprint incrementale basato su path normalizzato, mtime, size e hash su richiesta.
- Rebuild/Clear con preview dell’impatto e recovery journal.
- Render sugli originali per default.

Exit criteria: benchmark 4K ripetibile, invalidazione corretta e nessun uso di proxy stale nel render finale.

### F2 — Performance budget di scena

- Target FPS, budget memoria e soglie giallo/rosso per profilo.
- Suggerimenti ordinati per impatto misurato, non soltanto tier stimato.
- Preset Quality/Balanced/Fast/Presentation/Render.
- “Optimize Viewport” produce un diff e uno snapshot ripristinabile.

Exit criteria: zero modifiche distruttive e restore byte/logicamente equivalente delle impostazioni interessate.

### F5 — Batch relink con regole

- Root mapping, basename/hash/size search e confidence score.
- Tabella preview con conflitti e scelta per riga.
- Conferma finale e manifest rollback.
- Nessuna scansione completa ripetuta per layer.

Exit criteria: dataset con duplicati, nomi Unicode e root differenti rilinka senza associazioni silenziose a bassa confidenza.

## Milestone C — recovery e comprensione del progetto

### F9 — Recovery journal

- Checkpoint per import/generazione/cache/relink.
- Resume/Rollback/Discard all’apertura dopo interruzione.
- Journal versionato, atomico e limitato a identificatori/path necessari.
- Cleanup di datablock e file temporanei posseduti dall’add-on.

Exit criteria: kill controllato in ogni fase lascia una scelta recuperabile e nessun orfano non dichiarato.

### F3 — Effect Graph

- Visualizzare ordine, stage Shader/GN/Raster, Original/Previous/Final, mask, source, gruppi e controller.
- Segnalare dipendenze mancanti, cicli, ownership ambigua e costo osservato/stimato.
- “Select Problem” senza mutazione; repair in operatori separati con preview.

Exit criteria: il grafo è deterministico, read-only e serializzabile per Project Doctor.

## Milestone D — esperienza e contenuti

### F11 — Accessibilità

- Ricerca unificata di effetti e azioni.
- Navigazione da tastiera, focus prevedibile, compact mode e label opzionali.
- Icone scalabili e stato comunicato anche da testo/forma, non solo colore.
- Test in scale UI differenti e contrasto documentato.

### F7 — Preset versioning

- Versione schema, autore, add-on minimo/massimo.
- Diff prima dell’applicazione e conflitto Rename/Replace/Keep Both.
- Migrazione esplicita con backup attuale come rete di sicurezza.

### F6 — A/B compare

- Snapshot A/B transitori dello stack.
- Split/wipe e solo-effect senza duplicati permanenti.
- Ripristino in `finally`, anche dopo errore o chiusura dell’area.

### F8 — Grease Pencil conversion

- Priorità guidata da domanda utenti e fattibilità, partendo dai 15 candidati GN.
- Conversione temporanea non distruttiva o bake raster esplicito.
- Differenze visive, costi e limiti per effetto.
- Nessun passaggio a LTS prima di benchmark, save/reopen, Undo isolation ed equivalenza visuale concordata.

## Regole trasversali

- Nessun cambio di Effect ID, Mask ID o proprietà RNA persistente senza alias/migrazione.
- Ogni mutazione multi-layer resta transazionale.
- Ogni filesystem write offre dry-run, conferma e rollback/backup quando possibile.
- Ogni benchmark pubblica fixture, warm-up, campioni, ambiente e limiti.
- Le feature Preview restano visivamente e diagnosticamente separate dal core LTS.
