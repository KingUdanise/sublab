# SubLab — app desktop per i sottotitoli in DaVinci Resolve

Applicazione Windows che sostituisce AutoSubs eliminando i suoi tre difetti:
**stile uguale per tutti in un click**, **preview vera**, **nessun bottone “Update”**.
Gira in una **finestra nativa** (WebView2, niente browser).

## Installazione

1. Doppio click su **`dist\SubLabSetup.exe`** (installer Inno Setup, ~2 MB).
2. Nessun permesso di amministratore: installa in `%LOCALAPPDATA%\Programs\SubLab`.
3. Crea:
   * icona **SubLab** sul Desktop e nella Start Menu;
   * voce **Workspace ▸ Workflow Integrations ▸ SubLab** in Resolve (dopo un riavvio di Resolve);
   * disinstallazione da *App e funzionalità* o dalla Start Menu.
4. All'avvio l'app apre la sua finestra; il backend HTTP resta **solo su 127.0.0.1:8777**.

Requisiti: **Python 3.10+** con le dipendenze di `requirements.txt`
(`pip install -r requirements.txt`). L'installer sceglie automaticamente, tra i Python
presenti, quello che ha davvero le dipendenze e lo segnala se non ne trova nessuno.

### Ricompilare l'installer

```powershell
powershell -ExecutionPolicy Bypass -File build_installer.ps1   # richiede Inno Setup 6
```

### Sviluppo / avvio senza installare

```powershell
pythonw C:\aivinci\sublab\app.pyw      # app desktop (finestra nativa)
python  C:\aivinci\sublab\app.pyw      # stessa cosa, con console per vedere gli errori
```

Log dell'app: `%LOCALAPPDATA%\Programs\SubLab\out\app.log` (o `sublab\out\app.log` in sviluppo).

## Flusso di lavoro

1. In Resolve imposta **In/Out** sulla timeline (o seleziona le clip da sottotitolare).
2. Nella UI: *Da sottotitolare* = In/Out · Clip selezionate · Tutta la timeline → **Trascrivi**.
   - ASR locale `faster-whisper` (large-v3, IT) con timing per parola, GPU se disponibile.
3. Regola lo stile a destra: font, size, posizione, fill, outline, shadow, highlighter.
   La preview 1080×1920 si aggiorna in tempo reale, con safe zone e reveal parola per parola.
4. **Applica a tutti i sottotitoli** / **Applica ai selezionati** → scrive gli input della Fusion
   Text+ (nessun bottone *Update Fill/Outline/Shadow*: l’effetto è immediato).
5. **Push in DaVinci** → crea/aggiorna la traccia `SUBS` in cima con un clip per cue.

## Come è fatto

| File | Ruolo |
|---|---|
| `bridge.py` | tutto il parlato con l’API Resolve (info, range, stile, render audio) |
| `asr.py` | faster-whisper + costruzione cue leggibili (max caratteri/durata) |
| `push.py` | creazione clip `SUBS` + Fusion comp `Text+ → MediaOut` + stile |
| `fonts.py` | catalogo font di Windows + file da servire alla preview |
| `server.py` | FastAPI: `/api/info`, `/api/fonts`, `/api/transcribe`, `/api/apply`, `/api/push` |
| `web/` | UI (HTML/JS/CSS), preview su canvas |

### Regole imparate a spese di Resolve (non cambiarle)

* `Input.GetData()` restituisce `None` → usare `Tool.GetInput(id)` / `SetInput(id, val)`.
* `Tool.GetData()` **blocca Resolve** (render sincrono) → mai.
* `AppendToTimeline` lavora sulla timeline **corrente**: `SetCurrentTimeline` prima.
* `endFrame` è **esclusivo**: `endFrame = start + dur` per `dur` frame.
* Collegare i tool in Fusion solo con `dest.FindMainInput(1).ConnectTo(src.Output)`.
* **Mai importare `.comp` scritte a mano** (ha fatto crashare Resolve): solo comp costruite via API.
* `ProjectManager.SaveProject()` non è chiamabile in 21.1 → salva con Ctrl+S in Resolve.

## Sicurezza (leggere prima di usare il Push)

Resolve 21.1 è risultato **instabile** quando si costruiscono comp Fusion da script
(4 crash durante lo sviluppo, sempre ~30-60 s dopo il cambio/cancellazione di un progetto).
Per questo il push:

1. esporta **automaticamente un .drp** in `sublab/out/backup/` prima di scrivere;
2. di default lavora **su una copia** della timeline (`push-copy` nella UI): crea
   `Timeline 1 · SubLab`, ci si sposta sopra e lì inserisce i sottotitoli;
3. crea solo comp **semplici e valide** (`Text+ → MediaOut`): niente tool scollegati.

In più `POST /api/backup` esporta un .drp quando vuoi.

## Come viene estratto l'audio (e perché prima falliva)

La trascrizione non legge i file originali: fa un **render audio del range** dalla timeline
con il preset di Resolve **`Audio Only`** (Wave / Linear PCM), esattamente come fa AutoSubs.

Trappole verificate su 21.1:

* `SetCurrentRenderFormatAndCodec("wav", "lpcm")` → **False**: l'API vuole i nomi leggibili
  `Wave` / `Linear PCM` (che si leggono da `GetAudioRenderFormats()` / `GetAudioRenderCodecs()`).
  Se si sbaglia, Resolve renderizza un `.mp4` e il file `.wav` che cerchiamo non esiste.
* Il render mette qualche secondo in stato *Ready for background render* prima di partire:
  va atteso il `Complete` (qui si aspetta fino a 20 minuti, mostrando la percentuale).
* `SetMarkInOut` **consuma/azzera** i marchi: il codice salva `GetMarkInOut()` e li ripristina
  sempre, anche in caso di errore.
* Il preset corrente della pagina Deliver passa a `Audio Only`: è normale, si può cambiare a mano.

Prima volta con `large-v3`: scarica ~3 GB di modello (una volta sola, in
`%USERPROFILE%\.cache\huggingface`).

## Troubleshooting

| Sintomo | Cosa fare |
|---|---|
| La finestra si apre vuota o resta su “connessione a Resolve…” | guarda `out\app.log` accanto all'app; di solito è Resolve chiuso |
| “render audio non completato” | controlla che i file sorgente siano raggiungibili (dischi di rete) |
| “Nessuna timeline aperta” | apri un progetto con una timeline in Resolve |
| Font non in elenco | la UI legge i font installati: installa il font e riapri l'app |

## Stato / roadmap

- [x] ASR locale con word timestamps, GPU (x2.4 realtime con `small`)
- [x] Preview live con font reale, safe zone, reveal
- [x] Applica a tutti / ai selezionati su Text+ AutoSubs e clip SubLab
- [x] Push: traccia `SUBS` + clip con frame esatti + comp Text+/MediaOut
- [ ] Reveal parola-per-parola anche in timeline — **bloccato**: in 21.1 non ho trovato
      un modo via Python di collegare `Follower1.Text` e `DelayByCharacterPosition`
      (`ConnectTo` → False, `FindInput` non esiste). Ed è proprio il follower a far
      crashare Resolve. Strada alternativa: clonare una comp AutoSubs già funzionante.
- [ ] Editing timing dei cue dalla UI, undo per singolo passo
- [ ] Verifica a video dell’alpha del comp sopra le tracce sottostanti
