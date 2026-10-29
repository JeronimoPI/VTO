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

`cyndilib` levert de huidige NDI-binding voor Intel-Mac, Apple Silicon en Windows x64. Dit vervangt de eerdere `ndi-python`-dependency, waarvan de actuele macOS-wheel alleen Apple Silicon ondersteunt. Beschikbare wheels bewijzen nog geen werkende NDI-ontvangst op elk platform.

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
- De preview toont alleen beeld, zonder audio, maximaal 1280 pixels breed. Je kunt nu clips van het getoonde beeld opnemen. RTSP/HTTP wordt op 15 fps weergegeven. HLS kan merkbare buffering hebben.
- Eén actieve ontvanger voor de app. Bronwisselen stopt de vorige ontvanger. Sluiten van het desktopvenster stopt de ontvanger, de lokale server en netwerkdetectie.
- Handmatige adressen staan alleen in het geheugen en verdwijnen na afsluiten. Toegangsgegevens in streamadressen worden niet naar de bronlijst teruggestuurd of gelogd.

De desktopapp start intern een server op een vrije loopbackpoort en toont de interface in WKWebView op macOS of WebView2 op Windows. De interface wordt lokaal meegeleverd; een externe website is niet nodig. De videocode leest subprocess-pipes zonder de Unix-specifieke `select()`-aanpak, zodat de ontvangst ook op Windows kan werken.

## Clips opnemen: 3 seconden terug, 7 seconden vooruit

1. Start een bron en laat minstens 3 seconden ononderbroken beeld binnenkomen. De bufferindicator laat zien wanneer opnemen mogelijk is.
2. Klik in de desktopapp op **Opnamemap kiezen**. Je krijgt de gewone macOS-/Windows-mapkiezer. De gekozen map wordt gecontroleerd op schrijfrechten en voor volgende sessies onthouden. Annuleren behoudt de bestaande map.
3. Klik op **Neem 10 seconden op**. VTO neemt de 3 seconden vóór ontvangst van het commando mee, verzamelt daarna nog 7 seconden en schrijft automatisch één MP4-bestand.
4. Wacht tot **Opgeslagen · 10 s** verschijnt. **Map openen** opent de ingestelde map in Finder of Verkenner.

De clips bevatten het **getoonde beeld**, maximaal 1280 pixels breed, H.264/MP4 op 15 fps, zonder audio. Ze gebruiken de ontvangsttijd op deze computer; bij bijvoorbeeld HLS met buffering ligt die later dan de oorspronkelijke gebeurtenis. Binnenkomende frames worden op tijdstempels bemonsterd naar exact 150 frames voor 10 seconden video. Bij kleine timingverschillen kan een frame herhaald worden. Er wordt niet op aantallen binnengekomen frames teruggeteld.

Tijdens het verzamelen van de resterende 7 seconden kun je geen bron wisselen of stoppen. Er wordt één clip tegelijk gemaakt. Bij bronverlies langer dan 0,75 seconde of een resolutiewijziging wordt de clip afgebroken met een melding. Onvolledige clips worden niet als geslaagde MP4 bewaard. De beeldbuffer vult zich daarna opnieuw. Sluiten tijdens verzamelen of opslaan vraagt in de desktopapp of je de nog niet opgeslagen clip wilt afbreken.

Zonder eigen keuze is de opnamemap op macOS `~/Movies/VTO` en op Windows `~/Videos/VTO`. De mapkeuze staat op macOS in `~/Library/Application Support/VTO/settings.json`, op Windows onder `%LOCALAPPDATA%/VTO/settings.json` en op Linux onder `$XDG_CONFIG_HOME/vto/settings.json` (of `~/.config/vto/settings.json`). `VTO_RECORDINGS_DIR` kan voor ontwikkeling een tijdelijke map afdwingen; voor normaal gebruik is die variabele niet nodig. De native mapkiezer is alleen in het desktopvenster beschikbaar.

Tijdelijke encoderbestanden worden in de gekozen map gemaakt en na succes atomisch naar de definitieve bestandsnaam hernoemd. Filenamen bevatten tijd, bronnaam en een unieke identificatie; bestaande clips worden niet overschreven. De bronbuffer is begrensd tot 64 MiB en het verzamelde clipbeeld tot 192 MiB. Overschrijding stopt de opname of schakelt de opnameknop tijdelijk uit in plaats van onbeperkt geheugen te gebruiken.

De automatische opname-test encodeert en decodeert een echte MP4: exact 10 seconden, 150 frames, met 45 frames van vóór de klik en 105 frames van erna. Browsercontrole met een bewegend testbeeld bevestigde automatisch verzamelen, opslaan, statusmeldingen en een werkende volgende opname. Mapkeuze en afsluitbevestiging zijn met een gesimuleerd native venster getest; de echte macOS-dialogen moeten nog op de Mac worden gecontroleerd. De gebruiker heeft de NDI-weergave van de voorafgaande versie op de Mac bevestigd.

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

- De actuele Linux-testsuite: tweeëntwintig geslaagde tests, twee expliciet overgeslagen integratietests voor NDI en een externe RTSP-bron.
- De desktop-smoketest als Python-broncode: templates, statische bestanden, NDI-binding laden, echte JPEG-frames en opruimen slagen.
- Chromium in de eerste versie: videobeeld, stoppen, toevoegen, foutmeldingen en mobiele layout. Het native Mac/Windows-venster is nog niet getest.
- RTSP-ontvangst is in de eerste versie getest met een tijdelijke MediaMTX-server en een H.264-testzender. De herwerkte platformonafhankelijke pipe-reader wordt door de huidige HTTP/HLS- en testbeeldtests gecontroleerd; RTSP moet daarmee nog opnieuw worden getest.
- De NDI-ontvanger gebruikt nu FrameSync zoals het cyndilib-viewervoorbeeld, met RGBX/RGBA-ontvangst en 15 fps preview. Regressietests controleren rijpadding, metadata vóór het vrijgeven van native frames, JPEG-uitvoer en aparte foutcodes voor verbindings- en videotimeouts. Dit zijn gesimuleerde ontvangstsituaties, geen bewijs van ontvangst op een Mac.
- De eerdere NDI-test met `ndi-python` vond in deze cloudcontainer geen eigen testzender. Avahi en systeem-D-Bus ontbreken. De nieuwe `cyndilib`-binding laadt, maar daadwerkelijke NDI-discovery en ontvangst op jouw LAN blijven te verifiëren.

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
