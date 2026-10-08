# Marvin 1.19.0 - instalace pro Windows

Veřejné stažení: **[Full](https://github.com/petrsajner/marvin/releases/latest/download/Marvin-Setup-Full.exe)** · **[Minimal](https://github.com/petrsajner/marvin/releases/latest/download/Marvin-Setup-Minimal.exe)**.
Odkazy míří na nejnovější vydání. Veřejné soubory mají stálé názvy `Marvin-Setup-Full.exe` a `Marvin-Setup-Minimal.exe`; místní a offline balíčky obsahují také číslo verze v názvu.

## Minimal a Full

- `Marvin-Setup-1.19.0-Minimal.exe`: menší instalátor. Vyžaduje samostatný 64bitový Python 3.12 s Python Launcherem (`py`). Balíčky a llama.cpp/CUDA získá při nastavení.
- `Marvin-Setup-1.19.0-Full.exe`: obsahuje vlastní Python 3.12, uzamčené balíčky a ověřené llama.cpp/CUDA b10935 a jádro modelu Flash-Next s jeho balíčky, takže se při přípravě Flash-Next nestahují. Systémový Python není potřeba. Modely nejsou součástí samotného EXE.
- `Marvin-Offline-Backup-1.19.0`: úplná místní sada s Full instalátorem, modely včetně Flash-Next a jeho jádra, jejich projektory, runtime, snapshotem závislostí a manifestem kontrolních součtů.

Obě varianty vyžadují podporované 64bitové Windows a ovladač NVIDIA nainstalovaný uživatelem. WebView2 pro desktopové okno instalátor rozpozná a připraví automaticky. Minimal jej v případě potřeby stáhne; Full obsahuje celý runtime i pro instalaci bez internetu. Není potřeba otevírat stránky Microsoftu ani WebView2 instalovat samostatně. Microsoft Edge je nadále potřeba pro volitelné prohlížečové nástroje. Samostatný CUDA Toolkit ani Node.js nejsou potřeba.

## Postup

1. Pouze pro Minimal nainstalujte Python 3.12 a zapněte Add Python to PATH. Pro Full tento krok přeskočte.
2. Spusťte vybraný instalátor, vyberte jazyk, adresář a modely podle paměti GPU.
3. Full vytvoří nové izolované `.venv` z přibaleného Pythonu. Neregistruje Python a nemění systémový PATH. První příprava může chvíli trvat.
4. Ponechte zapnuté stažení modelů a dokončete nastavení.
5. Spusťte Marvin z plochy nebo nabídky Start. Model se načte automaticky.

Při aktualizaci použijte stávající adresář aplikace a nejprve ukončete běžící úlohy i Marvin. Chaty, projekty, paměť, skilly a modely zůstávají zachované, včetně vah a připravených souborů Flash-Next: průvodce nechá již stažené modely zaškrtnuté, nastavení je místo nového stahování jen ověří a Marvin připraví jen to, co ještě chybí (při aktualizaci z 1.18 a starší jádro Flash-Next, asi 0,7 GB, při jeho prvním startu). Při změně venv na Full se původní prostředí uchová pod `runtime/environment-history` a nové vznikne čistě z přibalených balíčků.

## Offline Backup

Zachovejte celou offline složku pohromadě a spusťte její Full instalátor přímo vedle `manifest.json`. Průvodce zálohu rozpozná a první příprava obnoví místní soubory přednostně. Nepotřebujete samostatně instalovat Python ani znovu stahovat přibalené modely. Úplná obnova kopíruje všechny modely obsažené v balíčku; vyžaduje přes 200 GB prostoru, pokud na cíli ještě nejsou.

Existující instalaci lze propojit se zálohou také přes nabídku Start **Instalace z offline zálohy** nebo přes **Nastavení > Data a zálohy**. Běžné online nastavení používá registrovanou zálohu jako náhradní zdroj. Modely či součásti, které záloha neobsahuje, je nutné získat zvlášť.

## Flash-Next

V průvodci je Flash-Next volitelný a nikdy není zaškrtnutý automaticky. Lze jej později vybrat v **Model a zařízení**. **IQ3_S** stáhne 84,5 GB; **IQ2_XS** stáhne 69 GB (vedle IQ3_S, se kterým sdílí dva soubory, asi 39 GB) a na počítačích se 48 nebo 32 GB RAM odpovídá rychleji. Obě varianty potřebují kartu NVIDIA se 16 GB a více, 32 GB RAM a více a ovladač 580 nebo novější a nabízejí kontext 256k a 128k. Při prvním startu si Marvin připraví jádro a soubory modelu (zhruba 7 GB navíc, z toho 5 GB stahováním). Naměřené rychlosti jsou v manuálu. Výchozím obecným modelem nové instalace zůstává Qwen Q5/Q8/192k.

Distribuce ani offline instalační sada neobsahují osobní chaty, projekty nebo paměť. Ty zálohujte samostatně. Oba aktualizované PDF manuály jsou součástí instalátorů. Ovladač NVIDIA instaluje uživatel.
