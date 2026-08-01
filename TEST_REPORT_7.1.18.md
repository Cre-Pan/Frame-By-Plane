# Frame By Plane 7.1.18 — test report

Data: 1 agosto 2026  
Blender: 5.2.0 LTS (`fbe6228777e7`)  
Sistema: Windows 11 x64  
Esito suite finale: background **PASS**, interattiva **PASS**

## Artefatti principali

- `work/audit-7.1.18/final-suite/combined-2_background.json`
- `work/audit-7.1.18/final-suite/interactive-undo_interactive.json`
- `work/audit-7.1.18/p0-4-final/generation-timer.json`
- `work/audit-7.1.18/p0-4-final/generation-cancel.json`
- `work/audit-7.1.18/p2-final/hot-path-fixture-after-2.json`
- `work/audit-7.1.18/p2-icons/icon-after.json`

`PASS` indica una verifica automatica conclusa. `SKIP` indica una combinazione non disponibile o non coperta dalla fixture; non viene trasformato in PASS implicito.

## Suite automatica finale

| Test | Modalità | Esito | Evidenza |
|---|---|---:|---|
| Blender version | Background + UI | PASS | 5.2.0 LTS. |
| Enable/disable/re-enable/reload | Background | PASS | 3 cicli puliti + 1 reload in-place; scheduler quiescente. |
| Handler evolution lifecycle | Background | PASS | PRE 2/POST 1 simulato → PRE 0/POST 1 dopo Repair. |
| Registration failure transaction | Background | PASS | 13 moduli rollback, 0 handler, re-enable riuscito. |
| Generation timer deadline | Background + probe UI | PASS | Timer estraneo ignorato; avvio a 0,2103 s; claim singolo. |
| Progress e rollback | Background | PASS | Oggetti, mesh, materiali, immagini e node group ripristinati. |
| Cancel durante chunk | Probe UI | PASS | `CANCELLED`, rollback confermato, 0 timer/operatori residui. |
| Import immagine sincrono | Background | PASS | Un rig generato e rollback della fixture riuscito. |
| Scheduler RNA capture | Background | PASS | Payload RNA annidati/opachi rifiutati; payload primitivi accettati. |
| Collection e Layer Tree | Background | PASS | Create/reparent/toggle/delete e snapshot scalari. |
| Undo/Redo 20 cicli | Interattiva | PASS | 20 push, 10 Undo, 10 Redo. |
| Scrub Bar regressions | Background | PASS | Contratti magnet/direct-scrub e icone. |
| Grease Pencil support matrix | Background | PASS | 87 totali: 11 Native, 15 GN Candidate, 61 Raster Only. |
| 40 tooltip auditati | Background | PASS | 40/40 specifici; 14 Preview compositor. |
| Preview scope policy | Background | PASS | 3 feature/3 usi; Project Doctor distingue Preview da LTS. |
| Azioni irreversibili | Background | PASS | Backup preset, manifest rename, no falso Undo filesystem. |
| GP native apply/remove | Background | PASS | Backend nativo applicato e rimosso. |
| Generic Mesh matrix/topology/contracts | Background | PASS | Matrice, profili topologici e contratti node group. |
| Generic Mesh apply artist-preservation | Background | SKIP | Asset `CAMERA_SCALE_LOCK` non disponibile nel contesto di quella singola fixture; gli altri contratti Generic Mesh sono PASS. |
| Compositor artist graph | Background | PASS | Nodi/link dell’artista preservati. |
| Toon Boom e Projector contracts | Background | PASS | Estensioni e routing verificati. |
| Performance profile contract | Background | PASS | JSON serializzabile, 12 campioni test, stato frame ripristinato. |
| Icon runtime contract | Interattiva | PASS | 12 preload; tre alias → stesso `icon_id`; due alias hit. |
| Save/reopen | Background | PASS | `.blend` salvato e riaperto. |
| Workbench render | Background | PASS | PNG 16×16 prodotto. |
| Eevee render | Background | PASS | PNG 16×16 prodotto con `BLENDER_EEVEE`. |
| Cycles render | Background | PASS | PNG 16×16 prodotto, 1 sample, denoise off. |
| 300 redraw View3D | Interattiva | PASS | 1,8956 s con GP e collection annidate. |
| Preferences reload + splash | Interattiva | PASS | Reload stabile; prompt What's New schedulato. |
| Repository verifier | Python 3.13 | PASS | Versione, piattaforme, wheel, file vietati, assenza di `BaseException` catches. |

## Matrice obbligatoria

### Lifecycle

| Scenario | Esito | Nota |
|---|---:|---|
| Install/enable da factory startup | PASS | Import diretto della sorgente e register completo. |
| Disable/re-enable | PASS | Tre cicli puliti. |
| Reload scripts/in-place | PASS | Quiesce scheduler e nessun task precedente. |
| File > New | PARTIAL | Factory startup usato a inizio suite; comando UI manuale non ripetuto con file utente. |
| File > Open | PASS | Save/reopen automatico. |
| File > Revert | SKIP | Non automatizzato nella matrice finale. |
| Errore register | PASS | Failure injection intermedia. |
| Errore unregister | PASS | Stato `FAILED_UNSAFE` testato, poi recupero. |
| Handler/timer/draw handler duplicati | PASS | Audit lifecycle e registri generation vuoti. |

### Handler

| Scenario | Esito | Nota |
|---|---:|---|
| Frame avanti/indietro e jump | PASS | Fixture 240 frame su range 1–120. |
| Set frame via Python | PASS | Usato da benchmark e Profile 120 Frames. |
| Scrubbing/playback CPU-side | PASS | Handler POST campionato; profilo dichiara il limite GPU. |
| Render e background | PASS | Workbench/Eevee/Cycles in background. |
| Project Doctor prima/dopo Repair | PASS | Nessun falso mismatch dopo fix. |
| Evolution senza ritardo | PASS | Fase unica POST e output coerente dopo Repair. |

### Import e generazione

| Scenario | Esito | Nota |
|---|---:|---|
| 1 immagine | PASS | Import sincrono reale. |
| Multiplane success/cancel/errore | PASS | Progress, cancel fra chunk e rollback. |
| Timer esterno concorrente | PASS | 0,01 s contro deadline 0,20 s. |
| ESC prima dell’avvio | PASS | Claim cancellato e timer rimosso. |
| Sequenza reale multi-file | PARTIAL | Contratti di generazione coperti; dataset lungo non incluso. |
| Video | SKIP | Nessuna fixture video versionata. |
| Cartelle annidate/media mancanti/Unicode | SKIP | Non inclusi nella matrice finale. |
| Path molto lungo/file read-only | SKIP | Richiede fixture filesystem dedicata. |

### Scene e performance

| Scenario | Esito | Nota |
|---|---:|---|
| 1/10/100 layer statici | PASS | 0,0265 / 0,1302 / 1,7291 ms medi handler. |
| 1/10/100 layer animati | PASS | 0,0832 / 0,5396 / 5,7149 ms medi handler. |
| Stack vuoto | PASS | 0,0031 ms medio su scena vuota. |
| Stack grandi/mask/source condivise | PARTIAL | Cache e deduplica coperte, non una scena massima dedicata. |
| Sequenze 4K | SKIP | Nessuna fixture 4K. |
| Controller/lattice/camera animata | PARTIAL | Contratti unitari presenti; benchmark combinato non eseguito. |
| File con dati Preview | PASS | Rilevamento e diagnostica di tre scope Preview. |
| File precedente 7.1.x | PARTIAL | Reload/schema verificati; fixture binaria storica non inclusa. |

### Grease Pencil

| Scenario | Esito | Nota |
|---|---:|---|
| Backend nativo apply/remove | PASS | Test automatico. |
| Matrice compatibilità e motivi | PASS | 87 righe e Copy Report. |
| Scrub copy/paste/duplicate/delete/mirror | PASS contrattuale | Tooltip specifici e regressioni scrub; non tutte le azioni sono state ripetute su dataset grandi. |
| Object/Draw/Edit/Sculpt | PARTIAL | Contratti di contesto verificati; matrice manuale completa non eseguita. |
| 1.000/50.000/250.000 punti | SKIP | Nessuna fixture pesante versionata. |
| Save/reopen e Undo isolation | PARTIAL | Save/reopen e Undo generico passano; dataset GP pesante non incluso. |

### Undo/Redo e filesystem

| Scenario | Esito | Nota |
|---|---:|---|
| 20 cicli Undo/Redo | PASS | Eseguiti in View3D interattiva. |
| Preset rename | PASS | Backup atomico; Blender Undo dichiarato non applicabile al file. |
| Sequence rename | PASS | Preview, conferma, manifest e rollback. |
| Repair e remove corrupted | PASS contrattuale | Poll/conferma e nessun falso `UNDO`. |
| Multi-layer/stack/reorder/GP, 20 cicli ciascuno | SKIP | Non automatizzato per ogni singolo operatore. |

### Render

| Scenario | Esito | Nota |
|---|---:|---|
| Workbench/Eevee/Cycles | PASS | Render still background 16×16. |
| Background render state | PASS | Stato e handler lifecycle verificati. |
| Output sync | PASS contrattuale | Scene-only, idempotente, poll esplicito. |
| Animation render completa | PARTIAL | Handler usato in render; sequenza lunga non prodotta. |
| Viewport render | SKIP | Nessuna cattura GPU automatizzata. |
| Stato dopo benchmark | PASS | Frame e profiler ripristinati in `finally`. |

### Contesto e piattaforme

| Scenario | Esito | Nota |
|---|---:|---|
| View3D/N-panel/Preferences/popup | PASS | Suite interattiva. |
| Background dove supportato | PASS | Suite completa. |
| F3 in tutti gli editor principali | PARTIAL | Operatori ad alto rischio auditati; matrice esaustiva non completata. |
| Windows x64 | PASS | Ambiente reale. |
| Windows ARM64/macOS Intel/macOS ARM/Linux x64 | SKIP | Manifest/wheel verificate staticamente; nessun runtime disponibile. |

## Failure e skip finali

- Failure finali: **0**.
- Skip di prodotto significativi: Generic Mesh apply su un asset non disponibile nella singola fixture; piattaforme non-Windows; fixture media/GP pesanti; matrice manuale F3 completa.
- Lo SKIP Undo della suite background è atteso; lo stesso test passa nella suite interattiva.

## Raccomandazione

**GO tecnico condizionato per candidate Windows x64.** Prima di pubblicare una build multi-piattaforma: eseguire i runtime test sulle altre quattro piattaforme dichiarate e chiudere le fixture media/GP/F3 ancora SKIP.
