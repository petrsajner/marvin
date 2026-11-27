# Marvin 1.24.0 - instalace pro Windows

Veřejné stažení: **[Full](https://github.com/petrsajner/marvin/releases/latest/download/Marvin-Setup-Full.exe)** · **[Minimal](https://github.com/petrsajner/marvin/releases/latest/download/Marvin-Setup-Minimal.exe)**.
Odkazy míří na nejnovější vydání. Veřejné soubory mají stálé názvy `Marvin-Setup-Full.exe` a `Marvin-Setup-Minimal.exe`; místní a offline balíčky obsahují také číslo verze v názvu.

## Minimal a Full

- `Marvin-Setup-1.24.0-Minimal.exe`: menší instalátor bez přibaleného prostředí. Vyžaduje samostatný 64bitový Python 3.12 s Python Launcherem (`py`); při nastavení sám stáhne balíčky, llama.cpp/CUDA i chybějící vybrané váhy modelů.
- `Marvin-Setup-1.24.0-Full.exe`: obsahuje kompletní prostředí — vlastní Python 3.12, uzamčené balíčky, ověřené `llama.cpp` v1.0.0 (`b12359`, CUDA 13.5), balíček jádra Strata `0.2.17` pro Flash-Next, balíček jádra Infernix `2026.11.20` pro karty RTX řady 50 i offline WebView2. Systémový Python není potřeba. Mimo EXE jsou jen váhy modelů, které se stahují jen pokud nejsou na disku.
- `Marvin-Offline-Backup-1.24.0`: úplná místní sada s Full instalátorem, všemi přibalenými modely (Qwen3.8-27B Q2/IQ3/Q4/Q5 + MTP, Bonsai 2.5 27B Ternary Q2_0 + BF16 vision, Flash-Next IQ3_S na Stratě + DFlash2, Qwen3.8-27B NVFP4 a Flash-Next IQ3_S na Infernixu + DFlash2, diktování a sémantické hledání), všemi enginy, snapshotem závislostí a manifestem SHA-256 — instaluje se kompletně bez internetu.

Obě varianty vyžadují podporované 64bitové Windows a ovladač NVIDIA nainstalovaný uživatelem (580 a novější pro Stratu a Infernix). WebView2 pro desktopové okno instalátor rozpozná a připraví automaticky. Minimal jej v případě potřeby stáhne; Full obsahuje celý runtime i pro instalaci bez internetu. Microsoft Edge je nadále potřeba pro volitelné prohlížečové nástroje. Samostatný CUDA Toolkit ani Node.js nejsou potřeba.

## Postup

1. Pouze pro Minimal nainstalujte Python 3.12 a zapněte Add Python to PATH. Pro Full tento krok přeskočte.
2. Spusťte vybraný instalátor, vyberte jazyk, adresář a modely podle paměti GPU (minimum 12 GB VRAM).
3. Full vytvoří nové izolované `.venv` z přibaleného Pythonu. Neregistruje Python a nemění systémový PATH. První příprava může chvíli trvat.
4. Ponechte zapnuté stažení modelů a dokončete nastavení. Již stažené modely na disku se zachovají a pouze ověří.
5. Spusťte Marvin z plochy nebo nabídky Start. Model se načte automaticky.

Při aktualizaci použijte stávající adresář aplikace a nejprve ukončete běžící úlohy i Marvin. Chaty, projekty, paměť, skilly a modely zůstávají zachované. Případná uložená volba odstraněných modelů Nemotron či Ornith se automaticky přepne na Qwen3.8-27B (`q4` / `q5`). Při změně venv na Full se původní prostředí uchová pod `runtime/environment-history` a nové vznikne čistě z přibalených balíčků.

## Offline Backup

Zachovejte celou offline složku pohromadě a spusťte její Full instalátor přímo vedle `manifest.json`. Průvodce zálohu rozpozná a první příprava obnoví místní soubory přednostně. Není potřeba internet, samostatný Python ani opakované stahování přibalených modelů. Úplná obnova kopíruje všechny modely obsažené v balíčku a vyžaduje přibližně 250 GB prostoru, pokud na cíli ještě nejsou.

Existující instalaci lze propojit se zálohou také přes nabídku Start **Instalace z offline zálohy** nebo přes **Nastavení > Data a zálohy**. Běžné online nastavení používá registrovanou zálohu jako náhradní zdroj. Modely či součásti, které záloha neobsahuje, je nutné získat zvlášť.

## Flash-Next a Infernix (RTX řady 50 / Blackwell)

- **Flash-Next na Stratě (všechny NVIDIA GPU od 12 GB VRAM, 32 GB+ RAM, ovladač 580+):** volitelný v průvodci i v **Nastavení > Model a zařízení**. **IQ3_S** stáhne 84,5 GB; **IQ2_XS** stáhne 69 GB (~39 GB vedle IQ3_S). Marvin využívá Stratu `0.2.17` s laděným DFlash2 drafterem.
- **Infernix (pouze NVIDIA RTX řady 50 Blackwell, `sm_120+`, ovladač 580+):** volitelné vysoce rychlé modely (**Qwen 3.8 27B · NVFP4**, 22,2 GB pro 24 GB+ VRAM, a **Qwen 3.8 Flash-Next · IQ3_S**, 85,9 GB + 776 MB drafter pro 12 GB+ VRAM). Na starších kartách NVIDIA (RTX 20/30/40) zůstávají v nabídce viditelné jako zašedlé položky s upozorněním na požadavek Blackwellu, zatímco všechny modely `llama.cpp` a Straty fungují normálně.

Výchozím modelem nové instalace zůstává Qwen3.8-27B Q5/Q8/192k (na 24/16/12 GB kartách se automaticky zvolí Q4, IQ3 nebo Q2). Distribuce ani offline instalační sada neobsahují osobní chaty, projekty nebo paměť — ty zálohujte samostatně. Oba aktualizované PDF manuály jsou součástí instalátorů. Ovladač NVIDIA instaluje uživatel.
