# Frame By Plane 7.1.18 — audit tecnico

Data: 1 agosto 2026  
Ambiente verificato: Blender 5.2.0 LTS, Windows 11 x64  
Branch locale: `audit/frame-by-plane-7-1-18`  
Versione add-on: invariata (`7.1.18`)  
Pubblicazione: non eseguita

## Esito sintetico

Tutti i problemi P0 indicati nel prompt sono stati riprodotti o confermati e corretti. La suite finale passa in Blender 5.2 sia in background sia in modalità interattiva. Non sono stati rinominati `bl_idname`, proprietà RNA persistenti, Effect ID, Mask ID o chiavi di schema.

La raccomandazione è **GO tecnico per una candidate Windows x64 destinata a revisione manuale**. La raccomandazione resta **NO-GO per una pubblicazione multi-piattaforma immediata** finché non vengono completati i test reali su Windows ARM64, macOS Intel/ARM e Linux x64 e la verifica manuale esaustiva F3/editor/mode indicata nei rischi residui.

## Registro dei problemi

| ID | Severità | Stato | Evidenza attuale | Riproduzione e causa | Correzione | Verifica | Rischio regressione |
|---|---|---|---|---|---|---|---|
| P0.1 | Bloccante | CONFERMATO → RISOLTO | `lifecycle.py:37-38`, `geometry_nodes.py:2482`, `geometry_nodes.py:32960` | Prima del fix, enable registrava in POST ma Project Doctor pretendeva PRE; Repair lasciava una copia in entrambe le fasi. | Contratto unico `frame_change_post`; PRE atteso a zero; rimozione normalizza entrambe le liste. | PASS: da PRE=2/POST=1 a PRE=0/POST=1; Project Doctor senza mismatch; reload senza duplicati. | Basso: fase coerente con docstring e valutazione Blender già usata a runtime. |
| P0.2 | Bloccante | CONFERMATO → RISOLTO | `__init__.py:176`, `__init__.py:221` | Failure injection in `properties.register()` lasciava `registration_busy=True`. | Transazione completa con `try/finally`, rollback inverso, quiesce prima/dopo, stati `FAILED` e `FAILED_UNSAFE`. | PASS: 13 moduli in rollback, busy rilasciato nello stato sicuro, 0 handler residui, re-enable nella stessa sessione. | Medio-basso: teardown incompleto resta volutamente bloccato come `FAILED_UNSAFE`. |
| P0.3 | Alta | RIPRODOTTO → RISOLTO | `operator_common.py:499-560` | Timer esterno da 0,01 s avviava la generazione a 0,012 s invece dei 0,20 s richiesti. | Deadline monotonic, claim singolo, confronto del timer quando disponibile, cleanup unico. | PASS reale interattivo: avvio a 0,2103 s; nessun timer/operatore orfano. | Basso. |
| P0.4 | Alta | CONFERMATO → RISOLTO per import/Multiplane | `operator_common.py:569-666`, `operator_import.py:405`, `operator_import.py:1849-2403` | Dopo il timer il lavoro era sincrono; ESC funzionava solo prima dell’avvio. | Iterator a chunk sul main thread, progress reale, step non interrompibili dichiarati, cancel fra step, snapshot e rollback; modalità sincrona mantenuta per background/test. | PASS: cancel durante i chunk, scena identica per oggetti/mesh/materiali/immagini/node group, report `CANCELLED`, registri vuoti. | Medio: un singolo step Blender non è interrompibile nel mezzo; la UI lo dichiara. |
| P1.1 | Media | CONFERMATO → RISOLTO | `grease_pencil_bridge.py:6678-6717`, `grease_pencil_bridge.py:10538` | La matrice calcolava il motivo ma mostrava solo il tier. | Motivo per riga, filtri All/Native/GN/Raster, conteggi e Copy Compatibility Report. | PASS: 87 effetti classificati, 11 Native, 15 GN Candidate, 61 Raster Only. | Basso. |
| P1.2 | Media | CONFERMATO → RISOLTO | `tooltips.py:13-148`, test in `tests/blender_lts_suite.py:928-967` | 40 operatori usavano fallback generici. | Descrizioni specifiche con modifica/non modifica, prerequisiti, multi-layer, Undo, skip/errori e Preview. | PASS: 40/40 descrizioni esatte; 14 descrizioni Compositor dichiarano Preview. | Basso, solo testo UI. |
| P1.3 | Media | CONFERMATO → RISOLTO | `feature_scope.py:78-144`, `operator_project.py:202`, `project_health.py:427` | Badge e diagnostica Preview non erano coerenti tra ingressi e Project Doctor. | Uso corrente rilevato per Compositor, Procreate e Generic Mesh; Copy Diagnostics locale; avvisi distinti dagli errori LTS. | PASS: 3 feature/3 usi rilevati e Project Doctor produce issue Preview separata. | Basso. |
| P1.4 | Alta | CANDIDATO → RISOLTO per i 6 operatori richiesti | `geometry_nodes.py:28233`, `geometry_nodes.py:29287`, `operator_import.py:2526-2907`, `operator_import.py:3150`, `operator_layers.py:775-828`, `operator_render.py:422` | Alcune azioni filesystem o repair pubblicizzavano Undo o non richiedevano conferma sufficiente. | Backup atomico preset, anteprima/conferma e manifest rollback per rinomina file; remove corrupted con conferma; repair mirato interno; poll espliciti; sync render dichiarato scene-only/idempotente. | PASS: backup `effect_presets.backup.json`, manifest `.fbp_sequence_rename_*.json`, nessun falso Undo filesystem. | Medio-basso: il rollback dei nomi disco dipende comunque dalla disponibilità dei file. |
| P1.5 | Media | PARZIALE | `operator_layers.py:775-828`, `operator_render.py:422`, `operator_import.py:3150` | Verifica mirata dei poll degli operatori ad alto rischio; non completata una scansione manuale di tutti i 422 operatori in ogni editor/mode. | Azioni impossibili ad alto rischio nascoste o dotate di `poll_message_set`; repair mirato rimosso da F3. | PASS sui contratti mirati; SKIP residuo documentato per matrice F3 completa. | Medio: azioni legacy meno frequenti possono ancora restituire un `CANCELLED` poco specifico. |
| P1.6 | Media | PARZIALE | `operator_common.py:569-771`, `operator_import.py:487-611` | Import/Multiplane non avevano avanzamento/cancel affidabili. Gli altri processi lunghi non condividono ancora un’unica API. | Contratto completo applicato alla generazione auditata; report con stato, step, conteggi, skip e rollback. | PASS import sincrono e cancel interattivo. | Medio: refresh/relink, conversioni e cache richiedono ancora convergenza nel ciclo post-7.1. |
| P2.1 | Media | IMPLEMENTATO | `performance_dashboard.py:148-309`, `performance_dashboard.py:1198`, `geometry_nodes.py:2462`, `runtime_scheduler.py:1060`, `ui_icons.py:300` | Il dashboard era principalmente stimativo. | Developer/Profile locale, default off; import/register per modulo, handler avg/p50/p95/max, scheduler, media/cache disponibili, UI/icon metrics, JSON e Text report, Profile 120 Frames. | PASS: JSON serializzabile, 120 campioni, frame ripristinato, nessuna rete. | Basso quando spento; tracemalloc è attivo solo durante il benchmark. |
| P2.2 | Alta | MISURATO; REFACTOR DEFERITO | `geometry_nodes.py:2482`, piano cache in `geometry_nodes.py:15126` | Fixture 1/10/100: 100 layer animati 5,82 ms medi baseline. Il primo instrumentation pass aggiungeva +3,3% perché contava dettagli anche da spento. | Contatori dettagliati condizionati a Profile; nessun refactor architetturale non giustificato. | Dopo: 100 statici 1,729 ms (+0,1%); 100 animati 5,715 ms (-1,8%), p95 6,256 ms. | Basso. Il piano runtime più invasivo resta backlog finché una scena reale non supera il budget. |
| P2.3 | Alta | RISOLTO nel perimetro P0.4; RESTO DEFERITO | `operator_common.py:609-666`, `operator_import.py:313-611` | Generazione monolitica e rollback tardivo. | Chunk, snapshot logico e cleanup transazionale per i flussi auditati. | PASS su successo, cancel ed errore artificiale. | Medio per importatori Preview/terze parti non inclusi nella fixture. |
| P2.4 | Media | CLASSIFICATO, NON REFACTORED IN MASSA | 157 occorrenze production; maggiori: `operator_import.py` 23, `grease_pencil_bridge.py` 19, `operator_layers.py` 17 | A: render/GP con contesto necessario; B: alcune selezioni/import sostituibili con data API; C: operatori editor/mode-sensitive; D/E: chiamate ripetute o di preparazione selezione da rivedere. | Nessuna sostituzione indiscriminata; override inevitabili restano isolati. | Suite background/interattiva passa. | Medio; audit per-call completo resta lavoro separato. |
| P2.5 | Media | CONFERMATO → RISOLTO | `ui_icons.py:382`, `ui_icons.py:538`, `ui_icons.py:592` | Preload di tutta la libreria, alias duplicati caricati come preview distinti, helper ricreato a ogni `ui_icon()`. | Preload di 12 icone visibili, effetti lazy, deduplica per path normalizzato, cache esistenza path, helper module-level. | Preview startup 31→12 (-61,3%); 300k chiamate 44,96→30,24 ms (-32,7%); 3 alias → 1 `icon_id`. | Basso; File Load/Revert continua a ricreare gli ID preview. |
| P2.6 | Media | DEFERITO PER SCELTA | `geometry_nodes.py` e altri moduli monolitici | Il refactor massivo insieme ai bugfix aumenterebbe il rischio e il diff. | Nessuna divisione di moduli in questo audit. | N/A. | Rischio noto di manutenibilità/startup; pianificare dopo stabilizzazione. |
| P2.7 | Media | PARZIALE + FIX MIRATO | `operator_render.py:968`, `operator_render.py:1030`, `tools/verify_repository.py` | Due `except BaseException` nello script render child intercettavano anche process-control exceptions. Restano 318 `except Exception` e 1.710 `pass` come indicatori da classificare, non bug automatici. | Catture ristrette a `Exception`; verifier vieta regressioni. | Verifica statica PASS; nessun `except BaseException` residuo. | Basso. La classificazione di ogni catch ampio è ancora incompleta. |
| P2.8 | Media | IMPLEMENTATO con limite dichiarato | `performance_dashboard.py:195`, `performance_dashboard.py:1198` | Mancavano benchmark ripetibile e stato ripristinato. | Profile 120 Frames con warm-up, avg/p50/p95/max, FPS effettivo CPU-side, frame budget, handler, scheduler, memoria Python e `finally` di ripristino. | PASS: 120/120 campioni, 0 frame oltre budget nella scena vuota, stato ripristinato. | Basso; Playback/Render sono esplicitamente approssimazioni CPU, non GPU/final render. |

## Compatibilità e dati persistenti

- Nessun cambio di versione, manifest o support policy.
- Nessun `bl_idname` pubblico rinominato.
- Nessuna proprietà RNA persistente, Effect ID, Mask ID o chiave IDProperty rinominata.
- I nuovi controlli Performance vivono su `WindowManager`, hanno `SKIP_SAVE` e sono disattivati di default.
- I report del profiler contengono solo contatori e misure locali; non includono media, percorsi sorgente o telemetria di rete.
- Il codice resta privo di separatori di path hardcoded nelle modifiche e il verifier conferma le cinque piattaforme dichiarate.

## Problemi risolti

- Falso mismatch e Repair distruttivo del lifecycle handler.
- Stato registration busy zombie dopo errore.
- Partenza anticipata causata da timer estraneo.
- Cancel fittizio della generazione e rollback incompleto.
- Motivi mancanti nella compatibilità Grease Pencil.
- Quaranta tooltip generici.
- Policy Preview e diagnostica incoerenti.
- Conferme/backup/manifest per azioni irreversibili auditate.
- Preload e duplicazione delle icone.
- Cattura impropria di `BaseException` nel render child.

## Riprodotti ma non risolti integralmente

- La convergenza del contratto progress/cancel per refresh, relink, Procreate/PSD, cache animate e riparazioni globali.
- La dipendenza da `bpy.ops` di alcuni flussi legacy, soprattutto import, Grease Pencil e layer management.
- La frammentazione dei moduli maggiori.
- La classificazione puntuale di tutti i catch ampi e `pass` difensivi.

## Non riprodotti o non eseguiti

- Nessun ritardo di un frame osservato dopo l’allineamento POST.
- Nessun leak handler/timer/classe osservato nei cicli eseguiti.
- Test reali su Windows ARM64, macOS Intel/ARM e Linux x64 non eseguiti.
- Sequenze 4K, video lunghi, path Windows vicino al limite, filesystem read-only e dataset GP da 250.000 punti non inclusi nella fixture automatica finale.
- Matrice manuale esaustiva F3 in ogni editor e in tutte le modalità GP non completata.

## Rischi residui e decisione

Il rischio principale non è nei P0 corretti, ma nell’ampiezza del prodotto: 157 chiamate `bpy.ops` production, moduli molto grandi e una matrice piattaforma/media che supera l’ambiente Windows x64 disponibile.

**Decisione: GO tecnico condizionato su Windows x64; NO-GO alla pubblicazione multi-piattaforma finché i test residui sopra non sono chiusi.** Nessuna release è stata pubblicata durante l’audit.
