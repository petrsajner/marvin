# Marvin 1.8.0 — dokončení a ověření

Datum: 13. 9. 2026. Windows, RTX 5090 32 GiB, 64 GiB RAM, Core Ultra 7 265K (8 P + 12 E, bez HT).

## Výsledek

- Flash-Next Q3_K_XL je v běžném výběru modelů, včetně vision, nástrojů a agentní smyčky. Příprava automaticky ověří model, upstream runtime, CPU topologii a volnou RAM/VRAM. Q8 kontext se volí mezi 256k, 192k a 128k; menší okno model nedostává.
- Je opraven závod při dokončení úlohy: rychle doručené upřesnění nezůstane bez běžícího pracovníka. STOP nadále pozastaví frontu.
- Startup a pevná spodní část pravého sloupce zobrazují © Petr Sajner 2026. Footer se při rolování obsahu neposouvá; ověřeno v reálném webovém UI. Ověřena byla také skutečná úvodní HTML obrazovka launcheru. Nativní Tk okno nebylo obrazově kontrolováno.
- České i anglické manuály popisují nynější UI, modely, ovládání úloh a offline instalaci. Aktuální PDF mají 20, respektive 26 stran; upravené stránky byly vyrenderované a vizuálně zkontrolované.
- Full 1.8.0 byl skutečně nainstalován přes dosavadní aplikaci 1.6.2 v `%LOCALAPPDATA%/QwenHarness`. Instalace i následná příprava z offline zálohy skončily kódem 0. Při aktualizaci zůstalo všech 369 kontrolovaných souborů uživatelských dat beze změny. Poslední vybraný model Ornith zůstal zachován.
- Instalovaný launcher načetl model, zpřístupnil UI a při ukončení zastavil oba servery a uvolnil GPU; proces skončil kódem 0. V instalovaném prostředí prošlo všech 50 servisních a runtime testů. Zdrojové Python soubory a instalované manuály byly porovnány s konečným balíčkem.

## Distribuce

| Soubor v `dist/` | Bajty | SHA-256 |
|---|---:|---|
| `Marvin-Setup-1.8.0-Minimal.exe` | 52 343 903 | `4029a02813664fe7259c8431b3adfbf684e63ac84fb3b6b573c799cb0524b469` |
| `Marvin-Setup-1.8.0-Full.exe` | 727 119 209 | `b4670692706e65d0d85b154e029a4f820ec6a0f0ac93d059b58927fe1ece762f` |
| `Marvin-1.8.0-Windows-x64.zip` | 778 611 911 | `134edb93476fa43cc826bb67a9cb0108f4bc59c58f9b945647c1ea878b5894b0` |

ZIP má sedm položek: dva instalátory, dva PDF manuály, dva instalační návody a kontrolní součty. CRC i SHA všech položek prošly. Čisté dočasné prostředí obnovilo závislosti z offline balíčku a spustilo API/UI bez osobních dat. Full navíc prošel ověřením privátního Pythonu bez systémového Pythonu a s konfliktními proměnnými prostředí. Nejde o test na čisté Windows VM.

Kompletní `Marvin-Offline-Backup-1.8.0/` obsahuje 79 položek manifestu o celkové velikosti 223 518 387 092 bajtů (208,17 GiB), včetně všech sedmi variant modelů, potřebných projektorů, llama.cpp, balíčků Pythonu a posledního Full instalátoru. Celá záloha prošla kontrolou SHA všech 79 souborů. Po poslední změně pouze instalátoru byly znovu ověřeny velikosti všech položek a hashe všech 65 nemodelových souborů; váhy od úplné kontroly zůstaly nedotčené. Manifest SHA-256: `dfb74277d40f2def1984393a2129eefda9a22c20e78271ae222b1ca0f6d3c8bd`.

## Ověření modelů a meze

- 366 základních kontrol a 50 servisních/runtime testů prošlo ve zdrojovém prostředí.
- Runtime audit porovnal 22 dosavadních modelových profilů před a po upgradu, tedy 44 kombinací, s chatem, nástroji, vision tam, kde je podporovaná, STOP a dlouhým kontextem. Podrobnosti: [b10935](LLAMA-b10935-VALIDATION.md).
- Flash-Next: praktický 128k test zpracoval 122 397 vstupních tokenů a správně nalezl tři údaje. První odpověď trvala 1 053,687 s, navazující 1,266 s díky cache. U krátkého běhu bylo naměřeno 27,29 generovaných tok/s.
- Funkční 256k profil prošel chatem, nástroji, vision, STOP a vstupem 24 101 tokenů. Celé 256k okno nebylo naplněno. Samostatný dlouhý 192k běh ani fyzické 16/24GB karty ověřené nejsou. Odhady dostupnosti profilů nejsou měřením těchto karet.
- Žádná z 95 zamčených verzí balíčků Pythonu se nezměnila. Upstream llama.cpp b10935 je pinovaný a původní b10549 zůstává jako rollback. Komunitní expert-cache fork nebyl použit.

Podrobnosti a měření: [Flash-Next](../design/2026-09-13-qwen38-flash-next-integration.md). Posouzení Macu je zachováno jako odložený výzkum, bez implementace.

## Uspořádání pracovního adresáře

| Místo | Účel |
|---|---|
| `harness/`, `frontend/`, `launcher/` | Současné zdroje aplikace |
| `scripts/`, `installer/`, `tests/` | Používané sestavení, instalace a opakovatelné testy |
| `docs/`, `output/pdf/` | Aktuální dokumentace, zachovaný výzkum a distribuované manuály |
| `.venv/`, `frontend/node_modules/`, `ui_dist/` | Zachované vývojové závislosti a připravené UI |
| `runtime/models/`, `runtime/llama/`, kandidát a rollback runtime | Zachované modely a inference prostředí |
| `dist/` | Pouze dva aktuální instalátory a distribuční ZIP |
| `Marvin-Offline-Backup-1.8.0/` | Ověřený úplný offline balíček |
| `runtime/archive/` | Ověřený archiv testů a přehled úklidu |
| `runtime/KE-SMAZANI/` | Jediné místo připravené k ručnímu odstranění vlastníkem |

`runtime/archive/verification-1.8.0.zip` uchovává 570 souborů (82 017 664 bajtů). CRC i SHA každého souboru byly porovnány s originálem. SHA archivu: `f5b18420186b118ffc3a69b5d701b155adb5b2337cd6c8caeb375b4b9ef7c1ea`. Původní cesty `runtime/validation/...` uvedené ve výzkumu jsou nyní cestami uvnitř tohoto ZIPu. Archiv obsahuje také soukromou zálohu předchozí instalace; zůstává lokální a ignorovaný Gitem.

Do `KE-SMAZANI` byly přesunuty pracovní kopie sestavení, staré instalátory, rozbalené testovací výstupy, prokazatelně testovací chaty, bytecode a nedokončená download cache. Přes 18 500 souborů je označeno pro ruční smazání; zatím fyzicky zůstávají na disku. Aktivní závislosti, kompletní GGUF váhy, uživatelská data skutečné instalace a aktuální distribuce nejsou součástí této složky. Automatická kontrola dříve zamítla mazání bez konkrétního odůvodnění; vlastník si výslovně převzal konečné odstranění.
