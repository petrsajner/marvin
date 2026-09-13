# Ověření llama.cpp b10935 proti současnému prostředí

Datum: 13. 9. 2026. Aplikace: Marvin 1.7.0, zdrojový základ `6b687458ca09879ceac81baa72bd53f9b52fad65`.

**Výsledek: v otestovaných scénářích nebyla prokázána funkční regrese nového llama.cpp.** Na fyzické RTX 5090 prošlo všech 22 praktických kombinací stávajícího modelu a KV profilu na starém i novém runtime, celkem 44 kombinací. Nový runtime zůstává ve stagingu; nebyla provedena aktivace v běžné aplikaci ani integrace/stahování Flash-Next.

Při testu byla navíc reprodukována dosavadní chyba ApplicationService při příchodu další úlohy těsně po dokončení první. Je nezávislá na llama.cpp a v této testovací etapě nebyla opravována. Před úplným nasazením nové integrační cesty je potřeba tuto chybu vyřešit.

## Přesné prostředí

| Součást | Výchozí prostředí | Testovaný kandidát |
|---|---|---|
| llama.cpp | b10549, `b2e5e9b28`, 0.1.2-dev | b10935, `8e330954a`, 0.4.0-dev |
| Adresář | `runtime/llama` | `runtime/candidates/llama-b10935-cuda13.3/bin` |
| GPU | RTX 5090, 32 607 MiB, Windows WDDM | stejná karta |
| Ovladač | NVIDIA 591.86 | nezměněný |
| CPU | Core Ultra 7 265K, 8 P + 12 E, bez SMT | nezměněný |
| RAM | 64GB třída | nezměněná |
| Python | stávající `.venv`, 95 balíčků podle locku | stejná `.venv`, žádný update balíčků |

V každém okamžiku běžel jediný model, na izolovaném portu 8087. Testovací data byla oddělena od projektů a chatů uživatele. Zachována byla existující konfigurace modelových a KV profilů, NP1, Flash Attention a projektory. Přímé porovnávací dotazy používaly deterministické nastavení; skutečné úlohy ApplicationService používaly modelový sampling a stávající implementaci nástrojů.

Kandidát byl stažen jako oficiální Windows x64 CUDA 13.3 balík. Kontrolní součty obou ZIPů byly porovnány s digesty vydání před rozbalením:

- `llama-b10935-bin-win-cuda-13.3-x64.zip`: `9ece1d33916caefe2ed1f74092dabe05cf955b112f9afdabc2de5c5e2b7285ad`
- `cudart-llama-bin-win-cuda-13.3-x64.zip`: `1462a050eb4c684921ba51dcc4cc488a036674c3e73e9945ee705b854808d03e`

Soubory `cublas64_13.dll`, `cublasLt64_13.dll` a `cudart64_13.dll` mají v obou adresářích totožné SHA-256. Tato etapa tedy nevyměnila Python ani tyto CUDA knihovny za odlišný obsah; podstatná změna je llama.cpp/GGML. Ovladač, systémový Python a PATH nebyly měněny.

Kontrolní součty serverů:

- původní EXE: `c8b1e5a66e1bb45854bed3daaab116c37e74526e30143d737c67557bab822359`
- kandidátní EXE: `3e17f28f693dfcbca90d4aa7f04cf9eb389300aa228b28b69d00271d3c4bd451`

## Rozsah a výsledky

| Model | Počet KV profilů | Starý runtime | Nový runtime |
|---|---:|---|---|
| Qwen3.8-27B Q5_K_M | 2 | prošel | prošel |
| Qwen3.8-27B Q4_K_M | 4 | prošel | prošel |
| Qwen3.8-27B IQ3_S | 6 | prošel | prošel |
| Ornith 1.5 35B-A3B Abliterated Q5 | 1 | prošel | prošel |
| Nemotron 3.5 Lightning Q4_K_XL | 5 | prošel | prošel |
| Nemotron 3.5 Lightning Q5_K_XL | 4 | prošel | prošel |

Pro každý profil bylo ověřeno načtení, skutečná deklarovaná kapacita serveru bez tichého zmenšení, odpověď, strukturovaný tool call s kontrolou argumentů a následná odpověď ze skutečně předaného výsledku nástroje. U všech vision profilů byly přečteny dva rozdílné obrázky s kódem položky a částkou; druhý obraz nesměl přebírat údaje z prvního.

V hlavním profilu každého modelu navíc prošlo:

- zapnuté reasoning a přenos myšlenek do LLMClient;
- STOP při generování a další funkční dotaz;
- STOP během aktivního prefillu a další funkční dotaz;
- dvě navazující skutečné úlohy přes ApplicationService, každá s `write_file` a `read_file`, kontrolou souboru a dokončení;
- vyhledání tří přesných informací na začátku, uprostřed a na konci dlouhého vstupu;
- navazující otázka nad stejným dlouhým kontextem.

Navazující úlohy ApplicationService byly po zachycení níže popsaného závodu testovány přes výslovnou frontu `delivery="queue"`. Tento test potvrzuje funkčnost fronty a agentní cesty; neřeší závod výchozího live steeringu. Původní neúspěšný pokus zůstal v JSON reportu v `previous_attempts`.

Další ověření:

- 366 základních kontrol: prošlo.
- 21 servisních testů: prošlo.
- `pip check`: bez rozbitých závislostí.
- 95 nainstalovaných balíčků: přesná shoda s `requirements-windows-py312.lock`.
- Kandidátní Qwen Q5 načetl uloženou historii z původního runtime a správně z ní odpověděl, včetně dřívějších tool-call zpráv.

Milionový profil Nemotronu nebyl spuštěn, protože je explicitním non-goalem produktu. Běžící profily byly ověřovány do 512k alokované kapacity. Testování kompaktních profilů na 5090 není náhradou za fyzickou validaci 16GB nebo 24GB karty.

## Dlouhý kontext a výkon

Čas zahrnuje zpracování vstupu a krátkou odpověď přes LLMClient. Jde o jednotlivá párová měření, nikoliv statistický benchmark. Operační systém ani souborová cache nebyly resetovány; nejde o ověření studeného SSD. Při každém porovnání se používaly stejné lokální váhy a stejné dotazy.

| Model / profil | Vstupní tokeny | Původní runtime | Kandidát |
|---|---:|---:|---:|
| Qwen Q5 / Q8 192k, kontrolní opakování | 122 397 | 72,61 s | 73,09 s |
| Qwen Q4 / F16 128k | 122 397 | 66,03 s | 65,06 s |
| Qwen IQ3 / Q8 48k | 43 681 | 15,53 s | 15,38 s |
| Ornith Q5 / Q8 128k | 122 397 | 24,53 s | 24,70 s |
| Nemotron Q4 / Q8 512k | 122 402 | 14,84 s | 14,44 s |
| Nemotron Q5 / Q8 128k | 122 402 | 14,88 s | 14,39 s |

První Q5 měření bylo 71,52 vs. 89,55 s. Kvůli tomuto rozdílu proběhlo kontrolní opakování z nových procesů v opačném pořadí runtime. Tam rozdíl klesl na přibližně půl sekundy. Stálá přibližně 25% regrese nebyla reprodukována; přesnou příčinu prvního odlehlého běhu nelze z těchto dat určit.

Navíc bylo ověřeno téměř plné dosavadní Q5 okno:

| Qwen Q5 / Q8, alokace 196 608 tokenů | Původní runtime | Kandidát |
|---|---:|---:|
| Vstup 191 147 tokenů + správná odpověď | 153,61 s | 151,84 s |
| Navazující otázka | 0,64 s | 0,69 s |

U dlouhých navazujících otázek byly skutečně použity cached tokeny. Například u 122k Qwen vstupu server vykázal 122 429 cached tokenů a doplnil jen 22 vstupních tokenů. Tím je ověřena návaznost, nikoliv pouze velká rezervace KV.

Paměť se vzorkovala během běhů. V kontrolním Q5 opakování byla špička privátní paměti serveru přibližně 34 586 MiB na původním a 35 047 MiB na novém runtime. Windows privátní commit, working set a GPU paměť nejsou sčitatelné jako nezávislé fyzické alokace. Device-wide GPU špičky zahrnují desktop a další procesy; jejich rozdíl nelze automaticky přisuzovat llama.cpp. Paměťový ochranný stop se při těchto bězích neaktivoval.

Všechna okna nebyla naplněna až po maximum: hlavní modelové profily byly zatíženy výše uvedenými dlouhými vstupy, ostatní profily ověřují alokaci a funkční krátké dotazy/nástroje/vision. Zejména 512k alokace Nemotronu není prezentována jako 512k naplněný prefill.

## Nalezená dosavadní chyba harnessu

Přirozený běh kandidátního Qwenu Q5 odhalil tuto situaci:

1. první úloha už má v SQLite stav `complete`;
2. `ApplicationService.active` ještě obsahuje první úlohu, protože worker dokončuje návrat;
3. další zpráva s výchozím `delivery="steer"` se uloží jako `steering`;
4. worker nastaví `active=None`, ale zprávu už nepřevezme; zůstane `steering` bez běžící úlohy.

Stejná situace byla deterministicky reprodukována bez llama.cpp s testovacím modelem a podržením completion hranice: `first_status=complete`, `second_final_status=steering`, `active=null`. Příčina je v koordinaci `ApplicationService.submit` a ukončení `_work`, nikoliv v modelovém serveru.

Původní testovací etapa produkční soubor `harness/application.py` neměnila. V navazující implementaci 13. 9. 2026 je chyba opravena: zprávy doručené po posledním kroku agenta přecházejí pod stejným zámkem do fronty před uvolněním aktivní úlohy. Pozastavení fronty po STOP zůstává zachované.

Dva regresní testy drží právě tuto hranici dokončení, včetně dvou rychle doručených zpráv a STOP. V navazující sadě prošlo 23 servisních a 19 testů přípravy modelu/runtime, dále 366 základních kontrol. Skutečný Qwen Q5 na b10935 následně prošel chatem, tool roundtripem, dvěma obrázky, dvěma úlohami s výchozím `delivery="steer"` a STOP během prefillu. Protokol je v `runtime/validation/flash-next/regression/results.json`; pět kontrol trvalo celkem 48,05 s včetně načtení modelu.

## Artefakty a opakování

- `tests/check_runtime_upgrade.py`: opakovatelný izolovaný test, CLI výběr runtime, modelů, profilů a kontrol; pouze jeden model současně.
- `runtime/validation/llama-b10935/results.json`: 44 kombinací, jednotlivé odpovědi, usage, latence, paměť a předchozí pokusy.
- `runtime/validation/llama-b10935/q5-repeat/results.json`: opakování Q5 v opačném pořadí a téměř plné 192k okno.
- `runtime/validation/llama-b10935/completion-handoff.json`: reprodukce dosavadní aplikační chyby bez modelového serveru.
- `runtime/validation/llama-b10935/cases/`: izolované testovací soubory, obrázky, SQLite data a serverové logy.
- `runtime/validation/llama-b10935/core-tests.log`: výsledek základních kontrol.

Spuštění používalo existující modely, nový runtime ve stagingu a stávající Python. Pro opakování do nového adresáře použít například:

```text
.venv/Scripts/python.exe -B tests/check_runtime_upgrade.py --candidate runtime/candidates/llama-b10935-cuda13.3/bin --output runtime/validation/new-audit
```

Další volby: `--profiles all --only chat,tool_roundtrip,vision`, `--only stop_prefill,long_context`, `--models q5 --only long_context,max_context`, `--diagnose-handoff`. `--resume` přeskočí již zaznamenané dokončené kontroly; pro nové srovnání použít nový výstupní adresář. `saved_baseline_history` vyžaduje v daném auditu již uloženou baseline historii.

**Stav při dokončení úvodního auditu:** nový llama.cpp byl ověřený kandidát pro pokračování testů na tomto PC. Běžná konfigurace tehdy ještě používala původní runtime a Flash-Next nebyl stažen ani integrován.

**Navazující aktivace 13. 9. 2026:** ověřené b10935 je nyní také v `runtime/llama`. Instalační cesta použila pinované balíky, zkontrolovala jejich hashe a GPU knihovny a zachovala b10549 v `runtime/llama-previous-1789275410529156700`. Hash aktivního EXE se shoduje s auditovaným kandidátem. Evidence je v `runtime/validation/flash-next/runtime-activation.json`. Žádná verze Python balíčku se nezměnila. Flash-Next a distribuce jsou dokončené podle [protokolu vydání 1.8.0](RELEASE-1.8.0.md); slabší fyzické GPU zůstávají neověřené.
