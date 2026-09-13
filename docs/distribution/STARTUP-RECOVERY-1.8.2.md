# Marvin 1.8.2 — automatické načtení a obnova historie

Datum: 13. 9. 2026. Oprava navazuje na `2fbce10` (1.8.1).

## Příčina

Po instalaci Minimal běžel model i webový server, ale `/api/state` vracelo HTTP 400 s chybou `Unterminated string starting at: line 1 column 29 (char 28)`. V konkrétním chatu bylo všech 44 fyzických záznamů JSONL platných. Text jednoho načteného webového zdroje obsahoval U+2028, běžný Unicode oddělovač řádku.

Čtečka používala `str.splitlines()`, které kromě skutečného konce záznamu rozděluje také U+0085, U+2028 a U+2029 uvnitř JSON řetězce. Platnou zprávu proto rozřízla uprostřed. Stejná chyba byla i při importu a obnově vyhledávacího indexu. Původní data nebyla poškozená. Předchozí diagnostika spuštění kontrolovala dostupný server a model, ale ne otevření vybraného chatu, takže tento případ nezachytila.

## Chování aplikace

- Čtení rozpoznává fyzické JSONL záznamy oddělené LF/CRLF. Unicode oddělovače uvnitř obsahu zůstávají součástí zprávy. Importy i hledání používají stejnou zásadu.
- Nové zápisy tyto znaky bezeztrátově escapují; text zprávy po načtení je totožný. Není třeba měnit, čistit nebo mazat původní platné chaty.
- Pokud je uložený záznam skutečně neplatný, načítač nejprve počká na dokončení případného probíhajícího zápisu a znovu přečte soubor. Čtení ani obnova tak nezasáhnou právě zapisovanou zprávu.
- Při skutečné obnově se zachová ověřená kopie původních bajtů v adresáři `recovery` daného chatu. Úplná zpráva se obnoví z trvalé události podle jednoznačně identifikovaného ID. Již přítomné zprávy se neduplikují a neobnovují se svévolně dříve odstraněné kroky.
- Pokud úplná kopie záznamu neexistuje, původní bajty zůstávají zachované a dostupné zprávy se otevřou. Chybějící pozice je zaznamenaná interně, aby se neposunuly hranice komprese a aby model nepředpokládal úspěch přerušené akce. Chybějící obsah se nevymýšlí.
- Obnova probíhá na pozadí. V hlavním i záložním UI nepřidává potvrzování, opravný dialog ani technickou chybovou zprávu. Běžný start není podmíněný novou diagnostickou bránou.

Rozšířené ověření `/api/state`, vybraného chatu a jeho detailu slouží pouze režimu `--smoke` pro kontrolu vydání. Uživatelskou chybu řeší čtečka a automatická obnova, ne přísnější odmítnutí startu.

## Ověření

- Původní chyba byla reprodukována regresním testem před opravou.
- Prošlo 366 základních kontrol a 65 servisních/runtime testů, včetně devíti kontrol Unicode historie, importu/exportu projektu, hledání, startu UI, obnovy z události, zachování původního souboru a souběhu se zápisem.
- Skutečný problematický chat se načetl se všemi 44 zprávami. SHA-256 před a po načtení se shoduje: nebyl přepsán ani jeden bajt.
- Na existující instalaci byl skutečně spuštěn instalátor **Minimal 1.8.2**, návratový kód 0. V nainstalovaném prostředí prošlo všech 65 servisních testů.
- Byl spuštěn běžný `Marvin.exe`, nikoliv jen testovací server. Skutečná instalace vrací HTTP 200 pro stav, vybraný chat i detail; hlavní UI se vykreslilo, původní historie je viditelná a Flash-Next je ve stavu Ready. Aplikace zůstala spuštěná pro uživatele.
- Q3, Q8 KV, xhigh, modelové soubory a inference prostředí se nemění. Offline balíček se aktualizuje pouze změněnými soubory distribuce; váhy a prostředí se nepřebalují.

Podklady jsou v lokálním archivu ověření 1.8.2. Obsahuje soukromý snímek problematické historie a databáze, proto není součástí Gitu ani instalační distribuce.

## Balíčky

Následující kontrolní součty zachycují původní sestavení opravy historie. Instalátory 1.8.2 byly následně na výslovné přání vlastníka nahrazeny sestavením s automatickou přípravou WebView2. Aktuální soubory a kontrolní součty jsou v [manifestu vydání](release-1.8.2.json).

| Soubor v `dist/` | Bajty | SHA-256 |
|---|---:|---|
| `Marvin-Setup-1.8.2-Minimal.exe` | 52 349 925 | `c70be547575dcbbfaf49f164044f406b4c0df17980c747c3d2ac4b8554fae79f` |
| `Marvin-Setup-1.8.2-Full.exe` | 727 137 000 | `81af7e0c0980b0d7cc4dbc724cd7538e217f91d0da04dac5dd3de7a6aa8c8fa6` |
| `Marvin-1.8.2-Windows-x64.zip` | 778 636 639 | `054b3436bad504591a50cce9d60730171d2f82700d6a9bf63240a217c48458c7` |

ZIP má sedm ověřených položek. V `Marvin-Offline-Backup-1.8.2/` bylo vyměněno jen šest souborů distribuce a aktualizován manifest; 73 ostatních položek má zachované velikosti, časy změny i kontrolní součty. SHA manifestu: `0c9c2f02afbbb962a44d4b3ac13b667905d4b34f5fd799763bd6cab875549c54`. Instalované Python zdroje a oba PDF manuály se shodují s výslednou distribucí.
