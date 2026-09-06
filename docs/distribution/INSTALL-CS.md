# Marvin 1.7.0 - instalace pro Windows

## Minimal a Full

- `Marvin-Setup-1.7.0-Minimal.exe`: malý instalátor. Vyžaduje samostatný 64bitový Python 3.12 s Python Launcherem (`py`). Python balíčky a llama.cpp/CUDA získá při nastavení ze sítě.
- `Marvin-Setup-1.7.0-Full.exe`: obsahuje vlastní Python 3.12, uzamčené balíčky a llama.cpp/CUDA. Systémový Python není potřeba. Modely přibalené nejsou.

Obě varianty vyžadují podporované 64bitové Windows a ovladač NVIDIA nainstalovaný uživatelem. Pro desktopové okno a prohlížečové nástroje mějte dostupný Microsoft Edge/WebView2. Samostatný CUDA Toolkit ani Node.js nejsou potřeba.

## Postup

1. Pouze pro Minimal nainstalujte Python 3.12 a zapněte Add Python to PATH. Pro Full tento krok přeskočte.
2. Spusťte vybraný instalátor, vyberte jazyk, adresář a modely podle paměti GPU.
3. Full vytvoří nové izolované `.venv` z přibaleného Pythonu. Neregistruje Python a nemění systémový PATH. První příprava může chvíli trvat.
4. Ponechte zapnuté stažení modelů a dokončete nastavení.
5. Spusťte Marvin z plochy nebo nabídky Start. Model se načte automaticky.

Při aktualizaci použijte stávající adresář aplikace a nejprve ukončete běžící úlohy i Marvin. Chaty, projekty, paměť, skilly a modely zůstávají zachované. Při změně venv na Full se původní prostředí uchová pod `runtime/environment-history` a nové vznikne čistě z přibalených balíčků.

## Offline Backup

`QwenHarness-Offline-Backup` zůstává samostatným balíčkem a touto verzí se nemění. Není součástí instalátorů. Běžné získávání modelů preferuje internet; nakonfigurovaná záloha je náhradní zdroj. Výslovná instalace z offline zálohy obnovuje místní soubory přednostně.

Distribuce neobsahuje osobní data. Oba PDF manuály jsou součástí každého instalátoru. Modely se stahují v obou variantách, ovladač NVIDIA řeší uživatel.
