# Marvin 1.8.2 — automatická příprava WebView2

Instalátory vydání 1.8.2 byly na výslovné přání vlastníka aktualizovány pod stejným číslem a se stejnými veřejnými odkazy. Aktuální soubory a SHA-256 uvádí [manifest vydání](release-1.8.2.json).

## Instalace a spuštění

- Minimal obsahuje Microsoft Evergreen Bootstrapper (1 783 000 bajtů). Pokud kompatibilní WebView2 chybí, bootstrapper jej automaticky stáhne a nainstaluje.
- Full navíc obsahuje kompletní Evergreen x64 Standalone Installer (212 745 424 bajtů); příprava desktopového okna tak nevyžaduje internet. Váhy modelů zůstávají samostatné.
- Existující kompatibilní runtime se použije beze změny. Instalace běží ve stávajícím uživatelském kontextu, bez samostatného průvodce Microsoftu.
- Instalátor po zkopírování aplikace spustí zabalený `Marvin.exe --prepare-webview2`. Tento režim nepotřebuje systémový Python, připravené venv, backend ani model. Normální spuštění používá stejnou funkci před vytvořením okna.
- Pokud je runtime později odstraněn, použije se přednostně místní standalone soubor nebo registrovaná offline záloha, potom bootstrapper. Chybějící či poškozený bootstrapper se znovu stáhne z připnutého zdroje a ověří.
- Microsoft Edge je nadále potřebný pro volitelné prohlížečové nástroje. Desktopové WebView2 není totéž jako prohlížeč Edge.

## Implementace a ověření

`harness/webview_runtime.py` kontroluje verzi `pv` stabilního runtime v HKCU/HKLM, v obou pohledech registru. Minimální verze odpovídá zabalenému pywebview. Instalátory Microsoftu se spouštějí skrytě s `/silent /install`; návratový kód sám o sobě neznamená úspěch. Rozhoduje následná registrace použitelného runtime, včetně krátkého čekání na dokončení registrace jiným updaterem. Vypršení časového limitu násilně nezastaví probíhající aktualizátor.

`scripts/download_webview2.py` při sestavení ověřuje SHA-256 i platný Authenticode podpis Microsoft Corporation. Přesné zdroje, velikosti a podpisy jsou v `installer/webview2.json`. Běžné sestavení verze nestahuje jinou aktuální verzi pod stejným hashem; změna připnutí vyžaduje explicitní `--refresh`. Před spuštěním se kontrolní součet ověřuje znovu.

Prošlo 366 základních kontrol a 80 servisních testů. Z toho 15 nových testů pokrývá detekci registru, opětovné použití runtime bez sítě a payloadu, offline přednost, Minimal, poškozené soubory, ověřené stažení, skryté parametry procesu, opožděnou registraci, falešný úspěch instalačního procesu, timeout, samostatný režim launcheru a obnovu z offline zálohy.

Případy chybějícího runtime jsou ověřovány řízenými testy, které nemění sdílený systémový WebView2. Na tomto hostiteli je WebView2 152.0.4191.66; skutečný launcher a instalátor ověřují jeho opětovné použití. Čistý Windows virtuální stroj bez WebView2 není v tomto prostředí dostupný, proto takovou zkoušku toto vydání nedeklaruje.

Skutečný upgrade dokončily oba instalátory s návratovým kódem 0 (Minimal 21 s, Full 76 s). V nainstalované aplikaci následně prošlo všech 80 servisních testů; 75 Python zdrojů, oba PDF manuály i oba instalační soubory Microsoftu odpovídají výsledné distribuci. Běžný `Marvin.exe` otevřel pracovní rozhraní 1.8.2. Full prošel i samostatnou zkouškou přemístěného Python prostředí bez systémového Pythonu, včetně API a načtení DLL llama.cpp.

Distribuční ZIP má sedm položek s ověřenými CRC a SHA-256. Offline sada má 82 položek; 73 původních položek zachovalo velikost, čas změny a uložený kontrolní součet. SHA-256 aktualizovaného offline manifestu: `0e619dd2e229be830e93a669728faeeddadc7a2af1fe481c096035eb4a24832c`.

Oficiální postup distribuce, detekce a tiché instalace: [Microsoft WebView2 distribution](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution).

Inference prostředí, uzamčené Python balíčky, llama.cpp, modely, Q3 váhy a Q8 KV zůstávají beze změny. Offline sada dostává pouze aktualizovaný Full instalátor, návody, manuály, tři soubory WebView2 a nový manifest; váhy ani snapshot Python prostředí se znovu nebalí.
