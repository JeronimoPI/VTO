# VTO — Video Transmission Observer

Een desktopapp om op je lokale netwerk één NDI-, RTSP- of HTTP/HLS-feed tegelijk te kiezen en te bekijken. De interface draait in een eigen applicatievenster. Een gebouwde versie bevat Python, de media-dependencies en FFmpeg; dagelijks gebruik vereist geen Terminal, Homebrew of aparte browser.

## Platformdoelen

| Platform | Bouwdoel | Verificatie |
| --- | --- | --- |
| Jouw Intel-Mac, macOS 14 Sonoma of nieuwer | `VTO.app` voor x86-64 | Bouwconfiguratie aanwezig; native build en test op een Mac nog nodig |
| Apple Silicon, macOS 14 of nieuwer | Eigen `VTO.app` voor arm64 | Bouwconfiguratie aanwezig; nog niet native gebouwd/getest |
| Windows 11, x64 | `VTO.exe` met bijbehorende bestanden | Bouwconfiguratie aanwezig; nog niet native gebouwd/getest |
| Linux | Ontwikkeling en backendtests | Functioneel getest in de cloud |

Dit is geen garantie voor alle historische macOS- en Windows-versies. Oudere systemen en Windows ARM zijn nog geen gevalideerde doelen. De huidige OpenCV-wheel voor Intel-Mac vereist macOS 14. De afhankelijkheden worden apart per architectuur gebundeld; de Mac-app is nog geen Universal Binary.

`cyndilib` levert de NDI-runtime en discovery-binding voor Intel-Mac, Apple Silicon en Windows x64. Dit vervangt de eerdere `ndi-python`-dependency, waarvan de actuele macOS-wheel alleen Apple Silicon ondersteunt. Beschikbare wheels bewijzen nog geen werkende NDI-ontvangst op elk platform.

## Een Mac-app bouwen

Deze stappen zijn voor het eenmalig bouwen door een ontwikkelaar, op een Mac met dezelfde architectuur als de gewenste app. Een Intel-Mac produceert de Intel-app. Voor de Apple Silicon-app gebruik je een Apple Silicon-Mac met een native arm64-Python. PyInstaller kan geen Mac-app vanuit deze Linux-cloudomgeving bouwen.

Installeer Python 3.12 van python.org en voer in de projectmap uit:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-desktop.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/build_desktop.py
.venv/bin/python scripts/verify_bundle.py
```

Resultaat: `dist/VTO.app` en een zipbestand met de architectuur in de naam. Kopieer `VTO.app` naar Programma's en open de app. Sta lokale-netwerktoegang toe wanneer macOS daarom vraagt: die is nodig voor netwerkdetectie en het ontvangen van camerafeeds.

De bundel is momenteel een ontwikkelbuild. Apple Developer-ondertekening en notarization zijn nog niet ingericht. Er is in deze cloudomgeving nog geen `.app`-bestand geproduceerd, dus er is ook nog geen installatieklare Mac-release gevalideerd.

Om de desktopinterface zonder bundeling op een Mac te starten:

```sh
.venv/bin/python desktop.py
```

## Windows als volgend platform

Gebruik native x64-Python 3.12 op Windows en voer in PowerShell uit:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-desktop.txt
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe scripts/build_desktop.py
.venv\Scripts\python.exe scripts/verify_bundle.py
```

De uitvoer staat in `dist/VTO/` en `dist/VTO-Windows-x64.zip`. Houd de volledige map bij elkaar. De app gebruikt Microsoft Edge WebView2; die runtime moet op de computer aanwezig zijn. De gebruikelijke Windows 11-installatie bevat deze runtime. Windows-ondertekening en een installer zijn nog niet ingericht.

Een handmatig te starten GitHub Actions-workflow in `.github/workflows/desktop.yml` bouwt afzonderlijk voor Intel-Mac, Apple Silicon en Windows. Hij voert eerst de bestaande tests uit en controleert daarna de daadwerkelijk gebundelde executable met een smoketest. De workflow is alleen toegevoegd als configuratie; hij is nog niet uitgevoerd of gepubliceerd.

## Gebruik

- Kies een bron in de lijst om het beeld te bekijken. **Opnieuw zoeken** vernieuwt de NDI-lijst.
- **Stream toevoegen** accepteert een RTSP/RTSPS- of HTTP/HTTPS-adres, bijvoorbeeld `rtsp://192.168.1.20:554/stream` of `http://192.168.1.20/live.m3u8`. Een gewone webpagina met een videospeler is geen streamadres.
- RTSP-bronnen die `_rtsp._tcp` via mDNS aankondigen worden ook automatisch gevonden. Er wordt geen volledige netwerkscan uitgevoerd. Andere camera's voeg je met hun streamadres toe.
- **Test de weergave** start een duidelijk gemarkeerd, intern gegenereerd bewegend testbeeld.
- De voorbeeldstand is instelbaar: zuinig (maximaal 1280×720 / 15 fps) of scherper (maximaal 1920×1080 / 30 fps). Er is geen audio. NDI-opnames gebruiken onafhankelijk hiervan de ontvangen resolutie en bronframerate; RTSP/HTTP-opnames volgen de voorbeeldstand. HLS kan merkbare buffering hebben.
- Eén actieve ontvanger voor de app. Bronwisselen stopt de vorige ontvanger. Sluiten van het desktopvenster stopt de ontvanger, de lokale server en netwerkdetectie.
- Handmatige adressen staan alleen in het geheugen en verdwijnen na afsluiten. Toegangsgegevens in streamadressen worden niet naar de bronlijst teruggestuurd of gelogd.

De desktopapp start intern een server op een vrije loopbackpoort en toont de interface in WKWebView op macOS of WebView2 op Windows. De interface wordt lokaal meegeleverd; een externe website is niet nodig. De videocode leest subprocess-pipes zonder de Unix-specifieke `select()`-aanpak, zodat de ontvangst ook op Windows kan werken.

## Clips opnemen: 3 seconden terug, 7 seconden vooruit

1. Start een bron en laat minstens 3 seconden ononderbroken beeld binnenkomen. De bufferindicator laat zien wanneer opnemen mogelijk is.
2. Klik in de desktopapp op **Opnamemap kiezen**. Je krijgt de gewone macOS-/Windows-mapkiezer. De gekozen map wordt gecontroleerd op schrijfrechten en voor volgende sessies onthouden. Annuleren behoudt de bestaande map.
3. Klik op **Neem 10 seconden op**. VTO neemt de 3 seconden vóór ontvangst van het commando mee, verzamelt daarna nog 7 seconden en schrijft automatisch één MP4-bestand.
4. Wacht tot **Opgeslagen · 10 s** verschijnt. **Map openen** opent de ingestelde map in Finder of Verkenner.

**NDI-clips** bevatten de ontvangen bronresolutie en bronframerate, zonder de verkleining of frameratebeperking van het voorbeeld. Een 1080p50-bron levert bijvoorbeeld een 1920×1080-MP4 op 50 fps met 500 bronframes per clip. Een 60fps-bron levert 600 frames. Er is een aparte directe SDK-ontvanger zonder FrameSync: de SDK raadt FrameSync voor enkelkanaalsopnames af, omdat die frames mag overslaan/herhalen om een weergaveklok te volgen. De opnamebuffer gebruikt hoogwaardige JPEG-frames (kwaliteit 95), gevolgd door H.264/MP4 (CRF 16); dit bewaart de framerate en resolutie, maar is geen pixelverliesloos origineel. Audio wordt niet opgenomen.

**RTSP/HTTP/testclips** bevatten het getoonde beeld op de gekozen voorbeeldframerate (15 of 30 fps). Hiervoor blijft tijdstempelbemonstering actief; een frame kan bij kleine timingverschillen worden herhaald. Bij HLS met buffering ligt de ontvangsttijd later dan de oorspronkelijke gebeurtenis.

Een native NDI-clip start op het bronframe op of direct vóór de grens van 3 seconden terug. Bij hele framerates zoals 50/60/100 fps is de uitvoer exact 10 seconden. Bij fractionele framerates zoals 59,94 fps ligt de lengte op de dichtstbijzijnde hele bronframegrens. NDI-clips vullen ontbrekende bronframes niet aan met duplicaten: ontbrekende frames of SDK-verlies tijdens verzamelen breken de clip af. De videoframes worden in ontvangstvolgorde bewaard; een vrij instelbare bron-timecode wordt niet als betrouwbare frameverlies-teller gebruikt.

Tijdens het verzamelen van de resterende 7 seconden kun je geen bron wisselen of stoppen. Er wordt één clip tegelijk gemaakt. Bij bronverlies langer dan 0,75 seconde of een resolutiewijziging wordt de clip afgebroken met een melding. Onvolledige clips worden niet als geslaagde MP4 bewaard. De beeldbuffer vult zich daarna opnieuw. Sluiten tijdens verzamelen of opslaan vraagt in de desktopapp of je de nog niet opgeslagen clip wilt afbreken.

Zonder eigen keuze is de opnamemap op macOS `~/Movies/VTO` en op Windows `~/Videos/VTO`. De mapkeuze staat op macOS in `~/Library/Application Support/VTO/settings.json`, op Windows onder `%LOCALAPPDATA%/VTO/settings.json` en op Linux onder `$XDG_CONFIG_HOME/vto/settings.json` (of `~/.config/vto/settings.json`). `VTO_RECORDINGS_DIR` kan voor ontwikkeling een tijdelijke map afdwingen; voor normaal gebruik is die variabele niet nodig. De native mapkiezer is alleen in het desktopvenster beschikbaar.

Tijdelijke encoderbestanden worden in de gekozen map gemaakt en na succes atomisch naar de definitieve bestandsnaam hernoemd. Filenamen bevatten tijd, bronnaam en een unieke identificatie; bestaande clips worden niet overschreven. De bronbuffer is begrensd tot 256 MiB en het verzamelde clipbeeld tot 768 MiB; dit geheugen wordt naar behoefte gebruikt, niet vooraf gereserveerd. Overschrijding stopt de opname of schakelt de opnameknop tijdelijk uit in plaats van onbeperkt geheugen te gebruiken.

De automatische opname-tests encoderen en decoderen echte MP4-bestanden op 15, 50, 60 en 100 fps en controleren zowel de frameaantallen als de overgang tussen de 3 seconden vooraf en de 7 seconden erna. Browsercontrole met een bewegend testbeeld bevestigde automatisch verzamelen, opslaan, statusmeldingen en een werkende volgende opname. Mapkeuze en afsluitbevestiging zijn met een gesimuleerd native venster getest; de echte macOS-dialogen moeten nog op de Mac worden gecontroleerd. De gebruiker heeft de NDI-weergave van de voorafgaande versie op de Mac bevestigd.

## Signaalinformatie en behoud van bronframes

Het paneel **Signaal en kwaliteit** toont de NDI-decoderresolutie, gemelde bronframerate, pixelformaat en scanindeling vóór VTO-verkleining. RGBX/RGBA is het gedecodeerde pixelformaat, geen identificatie van NDI High Bandwidth versus HX of de oorspronkelijke bitdiepte. Broncodec en netwerkbitrate worden niet afgeleid.

De SDK-tellers tonen ontvangen en verloren videoframes sinds verbinden, het verschil sinds de vorige meting, en ontvangst-fps berekend uit tellerverandering/tijdsverloop. Deze meting staat los van het aantal gemaakte voorbeeldframes. `NDIlib_recv_get_performance` meldt verlies in de ontvanger (bijvoorbeeld wanneer lokale verwerking niet bijhoudt), geen aantal verloren netwerkpakketten. Bewuste voorbeeldbeperking naar 15/30 fps telt VTO niet zelf als NDI-verlies. Ontbrekende of verouderde SDK-cijfers blijven **niet beschikbaar**, niet nul. Bij bron-/voorbeeldstandwissel wordt een nieuwe ontvanger en tellerbasis gestart.

De standaard zuinige stand kan een 1080p50-bron dus als 720p15-voorbeeld tonen terwijl de opname alle ontvangen 1080p50-frames bewaart. **Scherper · 1080p / 30 fps** geeft een scherper/vloeiender voorbeeld met meer CPU-belasting. SDK-counters, verwerkingstempo en de opnamebuffer laten zien of de computer de stroom bijhoudt.

NDI-opname accepteert een bekende bronframerate tot 120 fps. Er is geen optie die een 50/60fps-bron door dupliceren tot 100 fps maakt. Een toekomstige camera moet zelf 100 verschillende frames leveren. Kleine synthetische 100fps-frames zijn via een echte NDI-zender/ontvanger ontvangen en als 1000-frame-MP4 getest. De volledige opnameketen is functioneel op 1080p50 getest; dit kwalificeert nog geen Mac/camera-combinatie voor 1080p100 of 4K100. Een ontbrekende bronframerate of overschrijding van de geheugenlimiet schakelt opname uit; een onvolledige native clip wordt niet door verzonnen frames passend gemaakt.

## NDI en jouw netwerk

Draai de app op een computer in hetzelfde LAN als de bronnen. Deze cloudomgeving heeft geen toegang tot je thuis- of studionetwerk. macOS gebruikt Bonjour voor detectie; daarvoor hoef je geen Avahi te installeren. Op Linux heeft de NDI-runtime Avahi en systeem-D-Bus nodig.

Als de lijst leeg blijft: controleer een actieve zender, lokale-netwerktoestemming en firewall, en of beide computers elkaar mogen bereiken. Gastwifi, VLANs en VPNs kunnen mDNS blokkeren. NDI Discovery Server-configuratie is nog geen onderdeel van de interface. Bij RTSP is automatische detectie afhankelijk van de camera; gebruik anders het adres uit de cameradocumentatie.

De app omzeilt geen camera-authenticatie, DRM of certificaatcontrole. Voor HTTPS gebruikt de ontvanger een CA-bundel; `certifi` wordt meegeleverd voor systemen zonder geschikte standaardbundel.

## Cloudontwikkeling en tests

Gebruik de bestaande checkout; maak geen extra Git-worktree tenzij expliciet gevraagd. De Linux-omgeving gebruikt de distributieversie van FFmpeg. De statische Linux-binary van `imageio-ffmpeg` bleek op deze glibc-host te crashen bij netwerkontvangst; daarom wordt deze alleen op de macOS/Windows-bouwdoelen gebruikt.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python app.py
```

De ontwikkelserver luistert op loopbackpoort 8000; `PORT` kan een andere poort kiezen. Gebruik lokale requests voor cloudvalidatie. De cloud heeft geen native macOS-GUI; `desktop.py` kan daar alleen met `--smoke-test` zonder venster worden gecontroleerd.

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python desktop.py --smoke-test
```

De standaardtests controleren adresvalidatie, lokale toegang, afschermen van credentials, foutafhandeling, bewegend testbeeld, HTTP/HLS-ontvangst en het starten/sluiten van de desktopserver met daadwerkelijke videoframes. De smoketest controleert templates, statische bestanden, laden van de NDI-binding en FFmpeg-videoframes. Dit is geen test van NDI-ontvangst of het native venster.

Op een systeem met werkende NDI/mDNS-infrastructuur kun je aanvullend een echte NDI-testzender laten zoeken en ontvangen:

```sh
VTO_TEST_NDI=1 .venv/bin/python -m unittest discover -s tests -v
```

Een echte RTSP-testbron kun je apart opgeven:

```sh
VTO_TEST_RTSP_URL=rtsp://127.0.0.1:8554/test .venv/bin/python -m unittest discover -s tests -v
```

### Wat is daadwerkelijk gecontroleerd?

- De actuele Linux-testsuite: drieëndertig geslaagde tests, twee expliciet overgeslagen integratietests voor NDI en een externe RTSP-bron.
- De desktop-smoketest als Python-broncode: templates, statische bestanden, NDI-binding laden, echte JPEG-frames en opruimen slagen.
- Chromium in de eerste versie: videobeeld, stoppen, toevoegen, foutmeldingen en mobiele layout. Het native Mac/Windows-venster is nog niet getest.
- RTSP-ontvangst is in de eerste versie getest met een tijdelijke MediaMTX-server en een H.264-testzender. De herwerkte platformonafhankelijke pipe-reader wordt door de huidige HTTP/HLS- en testbeeldtests gecontroleerd; RTSP moet daarmee nog opnieuw worden getest.
- De NDI-ontvanger gebruikt nu de directe NDI SDK-capture-API uit de bij cyndilib meegeleverde runtime, zonder FrameSync. De C-structuurindeling is met de meegeleverde officiële headers vergeleken. Regressietests controleren geheugenlevensduur, vrijgeven van native frames, rijpadding, JPEG-uitvoer, SDK-statistiek en gerichte verbindingsfouten. Een echte lokale NDI-test op 1920×1080/50 fps leverde een 10-seconden-MP4 met 500 bronframes en nul door de SDK gemelde verloren frames op; het voorbeeld bleef tegelijk op 1280×720/15 fps. Dit is op Linux getest; de vernieuwde native ontvanger moet nog op de Mac worden gecontroleerd.
- De eerdere NDI-test met `ndi-python` vond in deze cloudcontainer geen eigen testzender. Avahi en systeem-D-Bus ontbreken. De gebruiker heeft daarna NDI-weergave en de eerdere opnamefunctie op de Mac bevestigd. De nieuwe directe capture-API moet nog op de Mac worden getest; de cloudtest gebruikte een expliciet lokaal NDI-adres omdat discovery in de cloud geen Avahi heeft.

NDI® is een geregistreerd merk van Vizrt NDI AB; zie https://ndi.video. De gebundelde runtime en afhankelijkheden hebben hun eigen licenties. De bouwconfiguratie neemt de bijgeleverde runtime- en licentiebestanden mee; raadpleeg de NDI-distributievoorwaarden bij het voorbereiden van een release.

## NDI-bron zichtbaar, maar geen beeld

De app maakt nu onderscheid tussen:

- `NDI_CONNECT_TIMEOUT`: de bron is ontdekt, maar de videoverbinding is na 15 seconden niet actief.
- `NDI_VIDEO_TIMEOUT`: de verbinding is actief, maar er wordt geen videoframe aangeleverd.
- `NDI_PIXEL_FORMAT`, `NDI_FRAME_LAYOUT`, `NDI_FRAME_SIZE`: de ontvangen beeldgegevens kunnen niet veilig worden omgezet.
- `NDI_RECEIVE_ERROR`: een onverwachte fout, met de fase en het exceptiontype in de melding. Willekeurige exceptiontekst wordt niet getoond of gelogd.

Voor een test zonder desktopvenster: sluit VTO en laat de NDI-zender aanstaan. Voer in de projectmap uit:

```sh
.venv/bin/python scripts/diagnose_ndi.py
```

Bij meerdere bronnen kun je selecteren op een deel van de naam:

```sh
.venv/bin/python scripts/diagnose_ndi.py --source "Test Patterns"
```

De uitvoer toont de runtimeversie, het aantal actieve NDI-verbindingen, de ontvangstfase en of meerdere previewframes daadwerkelijk zijn ontvangen. Deel die uitvoer wanneer de feed nog geen beeld geeft. Het programma wijzigt geen netwerkinstellingen.
