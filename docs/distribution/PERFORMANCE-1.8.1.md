# Marvin 1.8.1 — prodlevy mezi kroky Flash-Next

Ověřeno 13. 9. 2026 na RTX 5090 32 GiB, Core Ultra 7 265K (8 P + 12 E) a 64 GiB RAM. Předchozí vydání: `9d8bf49`, Marvin 1.8.0.

## Příčina a hranice opravy

V běžícím výzkumu ukazoval llama-server přibližně 23–27 generovaných tokenů/s. Zpracování nových podkladů bylo přibližně 85–130 tokenů/s. Například 7 796 nových tokenů způsobilo 66 sekund načítání, přestože předchozích 13 047 tokenů server převzal z cache. Později znovu použil přes 49 tisíc tokenů; cache tedy nebyla globálně vypnutá.

Současný 256k Q8 profil umísťuje expertní části 34 ze 48 vrstev do CPU/RAM. VRAM je téměř plná, i když GPU většinu času nepočítá. Samotné procento vytížení GPU není důkaz, že lze přidáním vláken nebo zvýšením jejího příkonu dosáhnout vyššího výkonu. Předchozí porovnání osmi P jader proti všem 20 jádrům při zpracování vstupu vyšlo lépe pro osm P jader. Toto vydání plánování hardwaru nemění.

Samostatný profil byl vzorkován až po prvním vygenerovaném reasoning tokenu: všech osm P jader mělo 95,2–100 %, proces spotřebovával přibližně 7,7 CPU jádra, GPU 25–26 % a 142 W při 29 865 MiB obsazené VRAM. Krátké generování dosáhlo 29,04 tok/s s xhigh. Procesní čítač čtení hlásil 0 MiB/s; celkové fyzické čtení systému 13–23 MiB/s nelze připsat jen modelu. Výsledek podporuje závěr o omezení CPU částí výpočtu a její obsluhou paměti; neizoluje přesný podíl výpočtu proti latenci/propustnosti RAM. Jde o krátký diagnostický vzorek, nikoliv příslib stejné rychlosti nad plným kontextem.

Oddělený pokus se 20 decode vlákny a maskou všech 20 jader (prefill stále 8 P) ukončil stávající paměťový hlídač po poklesu dostupné RAM pod 2 GiB. Nevzniklo platné měření rychlosti, a proto z něj nelze tvrdit, že je decode na 20 jádrech rychlejší či pomalejší. Přesný zdroj dodatečné paměťové potřeby nebyl izolovaně profilován. Nastavení produkční aplikace se nezměnilo; zůstává bezpečně ověřená varianta osmi P jader. Evidence: `decode-all-cores/outcome.json` a log serveru.

Druhý problém se týkal úloh s proměnlivým kontextem projektu/plánu: harness připojil aktuální snapshot před odpověď, ale v dalším kroku jej odstranil a přesunul až na konec. Tím zneplatnil prefix před právě vygenerovanou odpovědí a reasoningem. U kontrolovaného výzkumu bez projektu a připnutých souborů tato druhá příčina nebyla hlavním zdrojem čekání.

## Změny

- Změny kontextu se při skutečném požadavku zapíší jako interní zpráva. Zůstávají před odpovědí, ke které patří. Porovnávají se samostatně projekt, instrukce, rozhodnutí, plán a připnuté soubory: změna jednoho kroku plánu tak znovu neposílá dlouhý nezměněný dokument. Nejnovější hodnota nahrazuje danou sekci, prázdná ji ruší. UI interní záznamy nezobrazuje jako uživatelské zprávy, netvoří nové hranice úloh a náhled požadavku nic nezapisuje. Historii nadále spravuje běžná komprese a undo/retry.
- Transport předává nativní `prompt_progress` z llama.cpp. **Načítám kontext / Reading context** ukazuje postup nového textu bez započtení cache do procent a samostatně počet znovu použitých tokenů. Zobrazení fáze funguje i pro pomocné plánování, syntézu a kompresi. Čas se počítá pro aktuální fázi; STOP zůstává dostupný.
- `web_fetch` umí `query` pro doslovné hledání pasáže (alternativy přes `|`), `start` pro čtení další části a `refresh` pro nové stažení. Stejný zdroj během úlohy znovu nestahuje. Celý načtený zdroj se nadále ukládá do výzkumné evidence podle dosavadního limitu; výřez jej nenahrazuje. Nejde o automatické zahazování informací podle jejich důvěryhodnosti.
- Váhy Q3_K_XL, Q8 KV, požadovaný 256k kontext, xhigh, zachování reasoningu, upstream b10935 i verze závislostí zůstávají stejné. IQ3 nebylo staženo ani aktivováno.

## Naměřené porovnání

`tests/check_prompt_performance.py` spouští jeden izolovaný server na portu 8081, odmítá souběh s jiným modelovým serverem a svůj proces v závěru zastaví. Výsledky jsou v `runtime/validation/performance-1.8.1/` (po úklidu uvnitř lokálního archivu).

| Test následného kroku | Původní chování | Zachovaný prefix |
|---|---:|---:|
| První výstup, měření 1 | 5,543 s | 1,030 s |
| První výstup, měření 2 | 5,886 s | 1,016 s |
| Převzato z cache | 68 tokenů | 606 tokenů |
| Znovu zpracováno | 560 tokenů | 44 tokenů |

Pořadí bylo ABBA. V obou variantách byl první výstup omezen na stejných 512 tokenů, sampling shodný a effort `low` pouze pro tento syntetický test. Jde o měření prodlevy při zachování historie, ne o srovnání inteligence nebo rychlosti celých uživatelských úloh. Čtyři srovnání prefixu v `flash-abba/results.json` jsou dokončená; následný pokus o výpis číselného údaje ve stejném skriptu narazil na příliš nízký limit pro reasoning a byl odděleně opakován.

| Čtení stejného seznamu profesí | Celý zdroj | Cílená pasáž |
|---|---:|---:|
| Tokeny zdroje | 6 710 | 310 |
| První výstup | 53,037 s | 4,138 s |
| Vrácený ANZSCO kód | 261211 | 261211 |

Tento druhý test v `source-compare/results.json` má `complete=true`. Pro prostý výpis kódu bylo v obou větvích vypnuté přemýšlení; nastavení instalované aplikace se nezměnilo. Výřez byl vybrán pomocí konkrétního dotazu. Neprokazuje, že lze celý široký výzkum nahradit jednou pasáží. Nové dlouhé podklady a první načtení historie po restartu zůstávají nákladné.

## IQ3 proti současnému Q3

Pro tento checkpoint nabízí Unsloth `UD-IQ3_XXS` a `UD-Q3_K_XL`. Nejde o dva různé trénované modely. Publikované měření kvantizace:

| Varianta | Váhy bez projektoru | Top-1 shoda s referencí | Průměrná KLD |
|---|---:|---:|---:|
| UD-Q3_K_XL | 90,0 GB | 88,315 % | 0,106504 |
| UD-IQ3_XXS | 82,0 GB | 85,414 % | 0,165120 |

Top-1 shoda není procento inteligence a KLD není přímé skóre agentních úloh. Výsledek však ukazuje vyšší odchylku menšího IQ3 od referenční distribuce. Úspora přibližně 9 % vah sama o sobě nedokazuje zrychlení: rozhodují i kvantizační kernely a rozdělení expertů mezi RAM a VRAM. Vzhledem k prioritě vlastníka zachovat hloubku odpovědí zůstává doporučením současné Q3; místní rychlost ani kvalita IQ3 nebyly měřeny. [Unsloth: quantization analysis](https://unsloth.ai/docs/models/qwen3.8-next#quantization-analysis), [soubory checkpointu](https://huggingface.co/unsloth/Qwen3.8-Flash-Next-GGUF/tree/main).

Nativní opětovné použití prefixu a formát průběhu jsou popsány v [dokumentaci přesného použitého buildu llama.cpp](https://github.com/ggml-org/llama.cpp/blob/8e330954adb6e86c329c9d7e338f01f93ffe4b88/tools/server/README.md). Přesnost ani velikost modelu nebyla kvůli opravě změněna.

## Dokončená distribuce a instalace

- Prošlo 366 základních kontrol a 56 servisních/runtime testů, včetně zachování prefixu, nezdvojování připnutých dokumentů, obnovení historie, nativního průběhu, STOP a čtení cílených pasáží. V nainstalovaném prostředí prošlo stejných 56 servisních testů.
- Kompilované UI bylo skutečně otevřeno s izolovaným deterministickým modelem: zobrazilo 50 % nového vstupu a 10k tokenů z cache. STOP vrátil úlohu do stavu umožňujícího pokračování. Upravené stránky obou PDF manuálů byly vyrenderované a vizuálně ověřené (CS strana 11, EN strana 15).
- Aktualizace skutečné instalace na 1.8.1 i příprava privátního prostředí skončily kódem 0. Při aktualizaci se všech 699 kontrolovaných souborů uživatelských dat shodovalo s předchozím stavem. Konečné instalované Python zdroje se shodují se zdroji distribuce. Zachováno je Flash-Next, xhigh a 256k Q8.
- Nainstalovaný `Marvin.exe --smoke` spustil UI i vybraný model, poté oba správně ukončil a uvolnil VRAM; návratový kód 0.
- Distribuční ZIP má sedm položek; jejich CRC i SHA-256 byly ověřeny. Obnova závislostí do čistého dočasného prostředí a spuštění API prošly. Nejde o ověření na čisté Windows VM.
- Existující offline balíček byl aktualizován výměnou instalátoru, manuálů, návodů a manifestu; 73 nezměněných položek včetně vah a prostředí zůstalo se stejnou velikostí, časem změny a kontrolním součtem manifestu. Modely ani prostředí nebyly znovu kopírovány či přebalovány. Aktuální složka je `Marvin-Offline-Backup-1.8.1/` a její novou cestu zná i instalovaná aplikace.

| Aktuální soubor v `dist/` | Bajty | SHA-256 |
|---|---:|---|
| `Marvin-Setup-1.8.1-Minimal.exe` | 52 346 422 | `c686c0b5f4dde718f986a372f38b24fa08c22b7d808335ee9888628b1006eeab` |
| `Marvin-Setup-1.8.1-Full.exe` | 727 131 861 | `1d15613b71dd36607c6973b3a9107f86c7fcf2435840f50f5a00a00ccdbc9864` |
| `Marvin-1.8.1-Windows-x64.zip` | 778 627 972 | `0d50e2ed009f4bb926a2de9d68fdd9034e6d8319cc73c85662f9d8e9a431eff3` |

SHA manifestu offline balíčku: `64f9edf4dfd6bb395476aa16322dde3b45ca7c0710e68f6242259212d484b010`.

Lokální důkazy jsou sloučené v `runtime/archive/verification-1.8.1.zip` (103 souborů, ověřené CRC i SHA každého souboru, SHA archivu `4af2481d648dd995ff1853735c5e856a18a1ec6d55240f43eb2c39572e157318`). Obsahuje soukromou zálohu dat a není součástí Gitu ani distribuce. Reprodukovatelné mezivýsledky sestavení a rozbalených testů jsou označené pro ruční smazání v `runtime/KE-SMAZANI/after-1.8.1/`. Aktuální modely a aktivní závislosti zůstaly zachované.
