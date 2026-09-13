# Marvin 1.8.2 — pokračování po změně modelu

Datum: 14. 9. 2026. Oprava navazuje na sestavení s automatickou přípravou WebView2; číslo vydání a veřejné odkazy zůstávají 1.8.2.

## Příčina a oprava

Uživatel po nedostatku paměti Flash-Next ručně spustil Qwen Q5. Volba v nastavení i poslední úspěšně spuštěný model byly správně uložené, ale přerušená úloha měla v SQLite nadále vlastní kopii původní konfigurace Flash-Next. Continue pouze znovu zařadilo tuto úlohu. Worker potom podle staré konfigurace zastavil nový model a znovu načetl původní.

`ApplicationService.resume()` nyní při kliknutí na Continue převezme aktuálně vybraný model, jeho aktuální definici a KV profil, hardwarové nastavení a požadavek na adaptivní KV. Stejnou opravenou konfiguraci uloží do pokračující úlohy i jejích nastavení. Již běžící správný model se kvůli pokračování znovu nespouští.

Zůstávají zachované identita úlohy, zprávy, přílohy, režim práce, hloubka přemýšlení a bezpečnostní nastavení původní úlohy. Oprava funguje i pro dříve uložené přerušené úlohy; nevyžaduje migraci ani ruční úpravu uživatelské databáze. Nové zprávy a běžná fronta si ponechávají dosavadní pravidla pořizování konfigurace při odeslání.

Při menším kontextu vychází automatická komprese z limitu nově vybraného modelu. Úplná historie zůstává uložená a dostupná v rozhraní.

## Ověření

- Před opravou regresní test reprodukoval návrat ke starému modelu, restart kvůli starému KV profilu i použití nesprávného kontextového limitu.
- API testy pokrývají stavy failed, stopped, interrupted a waiting_confirmation; Flash-Next → Qwen Q5/Q4/Q3, změnu KV stejného modelu i nižší profil Flash-Next. Pokud vybraný model již běží se správným profilem, nepřijde žádný požadavek na jeho restart.
- Ověřeno pokračování po restartu aplikace: obnoví se částečná odpověď, neznámý výsledek nástroje se označí pro kontrolu a použije se nově zvolený model.
- Test přechodu na 32k kontext používá sumarizaci s novým modelem a zachovává všechny původní zprávy.
- Na izolované kopii nahlášené skutečné úlohy se původní Flash-Next změnil na Qwen Q5 / Q8 / 196 608 tokenů. Nebyl vyžádán restart modelu; původní historie zůstala bajtově nezměněná. Šlo o řízenou zkoušku směrování bez generování nebo nástrojových akcí nad uživatelskou konverzací.
- Prošlo 366 základních kontrol a 82 servisních testů včetně WebView2, obnovy historie, fronty a přepínání modelů.
- Skutečný upgrade přes Minimal skončil kódem 0; všech 82 servisních testů prošlo i v nainstalované aplikaci. Instalovaný zdroj opravy a oba manuály odpovídají distribuci. Běžný Marvin se následně otevřel s Qwenem Q5 ve stavu Ready.
- Full prošel sestavením a kontrolou přemístěného privátního Python prostředí, včetně API a načtení DLL llama.cpp. Inference runtime ani závislosti se v této opravě nemění.

Aktuální instalátory, manuály a jejich kontrolní součty uvádí [manifest vydání](release-1.8.2.json). Offline balíček se aktualizuje pouze změněnými soubory distribuce; váhy, WebView2 a inference prostředí se nepřebalují.
