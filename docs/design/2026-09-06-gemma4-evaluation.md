# Gemma 4 v Marvinovi: proveditelnost, paměť a doporučení

Datum ověření: 6. 9. 2026. Jde o průzkum a návrh, nikoli implementaci nebo schválenou roadmapu. Gemma nebyla stažena ani spuštěna. Odhady paměti a rychlosti nejsou výsledkem lokálního benchmarku Gemmy.

**Rozhodnutí vlastníka, 6. 9. 2026: výzkum uložit, nyní neimplementovat.** Integrace, stahování modelů a experimentální benchmarky jsou odloženy. Níže uvedené profily a testovací postupy slouží pouze jako podklad pro případné budoucí pokračování na výslovný pokyn vlastníka; nejsou oprávněním k automatickému zahájení práce.

**Doporučení: Qwen 3.8 27B Q5 ponechat jako výchozí model na 32 GB. Pro širší podporu hardwaru mají smysl dva kandidáti: Gemma 4 26B A4B pro 24–32 GB a Gemma 4 12B Unified pro 16 GB. Prioritou je ověřit jejich oficiální QAT Q4_0 varianty, u 12B také Q5. Gemmu 31B nyní nepřidávat jako další standardní profil.**

## 1. Skutečné prostředí

Lokálně ověřeno:

- RTX 5090, 32 607 MiB celkové VRAM, při kontrole 2 064 MiB obsazeno.
- Intel Core Ultra 7 265K, přibližně 64 GiB instalované systémové RAM.
- Windows, llama-server build 10549, commit `b2e5e9b28`, Clang 20.1.8; přibalený CUDA 13 runtime.
- Jeden model a jeden serverový slot (`-np 1`), Flash Attention, GGUF, samostatný vision projektor. Zachovat současnou sekvenční architekturu.
- Výchozí Qwen Q5 má přes výběr KV profilu skutečný limit 196 608 tokenů. Samostatná hodnota `ctx_size: 98304` u modelu tento zvolený profil nepřebíjí.

| Stažený model | Velikost samotného souboru | Kontext relevantního profilu |
|---|---:|---:|
| Qwen 3.8 27B Q5 | 18,414 GiB | 192k, Q8 KV |
| Qwen 3.8 27B Q4 | 15,334 GiB | 128k F16 / 256k Q8 |
| Qwen 3.8 27B IQ3_S | 11,214 GiB | profil pro menší GPU |
| Ornith 1.5 35B-A3B Abliterated Q5 | 23,031 GiB | 128k Q8 |
| Nemotron 3.5 Lightning Q4_K_XL | 23,754 GiB | několik profilů |
| Nemotron 3.5 Lightning Q5_K_XL | 28,326 GiB | několik profilů |

Projektory Qwenu a Ornithu mají dalších 0,864 a 0,841 GiB. Konfigurace Nemotronu v YAML je odsazena pod `hardware`, ale oba modely jsou také v programových výchozích hodnotách `harness/config.py`; pouhé čtení YAML by proto dalo neúplný přehled. Existující milionový profil není doporučením tohoto průzkumu a odporuje současným produktovým invariantům.

Zdroje v repozitáři: `config.yaml`, `harness/config.py`, `harness/servermgmt.py`, `harness/llm.py`, `harness/session.py`, `scripts/download_models.py`, `docs/ARCHITECTURE.md`. Pracovní strom již před průzkumem obsahoval rozpracované změny; analýza je neupravuje.

## 2. Varianty Gemmy

| Varianta | Parametry | Architektura | Nativní kontext | Vstupy |
|---|---|---|---:|---|
| E2B | 2,3B efektivních / 5,1B s embeddingy | malý dense + PLE | 128k | text, obraz, audio |
| E4B | 4,5B efektivních / 8B s embeddingy | malý dense + PLE | 128k | text, obraz, audio |
| 12B Unified | 11,95B | decoder bez samostatných multimodálních encoderů | 256k | text, obraz, audio |
| 26B A4B | 25,2B celkem / 3,8B aktivních | MoE | 256k | text, obraz |
| 31B | 30,7B | dense | 256k | text, obraz |

Výstupem je text. Video se zpracovává jako sekvence snímků. Gemma 4 má nativní volání nástrojů, system roli a přepínání thinking. Modelová řada je vydána pod Apache 2.0. Tato licence nezmění licenční režim ostatních částí aplikace. [Google: model card](https://ai.google.dev/gemma/docs/core/model_card_4), [přehled modelů](https://ai.google.dev/gemma/docs/core).

Pro širší cílení na 16GB karty je zvlášť relevantní 12B, podrobně vyhodnocená níže. E4B/E2B mají smysl jako další úsporná možnost, pokud je pro ně konkrétní potřeba; není důvod rozšířit katalog automaticky o celou rodinu. Multimodální schopnost checkpointu sama o sobě nezaručuje odpovídající vstup v našem UI a runtime.

## 3. Kvalita proti modelům, které skutečně máme

| Benchmark, vyšší je lepší | Qwen 3.8 27B | Ornith 1.5 35B-A3B | Gemma 4 31B | Gemma 4 26B A4B |
|---|---:|---:|---:|---:|
| GPQA Diamond | 89,2 | 89,2 | 84,3 | 82,3 |
| LiveCodeBench v6 | 90,3 | — | 80,0 | 77,1 |
| SWE-bench Pro | 61,7 | 59,6 | 35,7* | — |
| Terminal Bench 2.1, Terminus | 73,0 | 67,8 | 42,1* | — |

Zdroje: [Qwen model card](https://huggingface.co/Qwen/Qwen3.8-27B), [Ornith model card](https://huggingface.co/ornith-ai/Ornith-1.5-35B-A3B), [Google benchmarky](https://deepmind.google/models/gemma/gemma-4/). Hvězdička: číslo Gemmy převzaté ze srovnání publikovaného autory Ornithu.

**Toto není jednotný nezávislý A/B test.** Liší se harnessy, nastavení, rozpočty i některé úpravy benchmarků; Qwen například uvádí vlastní přehodnocení opravené sady SWE-bench Pro. Tabulka podporuje směr rozhodnutí, nikoli přesný procentní náskok. Navíc náš Ornith je upravená Abliterated Q5 varianta: skóre původního checkpointu nelze automaticky přisoudit našemu souboru. Stejně tak plná přesnost v benchmarku není naše GGUF kvantizace.

Praktické závěry:

- **Development:** zveřejněné důkazy nepodporují výměnu Qwenu nebo Ornithu za Gemmu. Vysoký LiveCodeBench není totéž jako spolehlivé opravy skutečného projektu.
- **Research a Discussion:** 26B může být příjemně rychlá alternativa. Nadřazenost v češtině, přesnosti citací a dlouhých dokumentech zatím není prokázána.
- **Writing:** má smysl porovnat styl a dodržování dlouhého zadání na našich ukázkách. Preference z obecného chatového žebříčku není zárukou lepšího psaní pro Petra.
- **Computer, PDF, obrázky:** Gemma zachovává vision. Proti nynějšímu textovému profilu Nemotronu je to konkrétní funkční přínos; proti Qwenu/Ornithu nejde o novou schopnost.

Také NVIDIA ve vlastním srovnání uvádí pro Gemmu 26B proti Lightningu lepší MMLU Pro (85,20 vs. 81,94) a GPQA (79,61 vs. 75,44). Je to další indicie pro kvalitnější rychlou univerzální alternativu. Rozdíl proti Google skóre GPQA názorně ukazuje vliv metodiky. [NVIDIA model card](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16).

## 4. Co znamená „načítat jen potřebné části“

Jde o několik různých mechanismů:

1. **MoE vybírá výpočty.** U 26B se pro každý token vybírá 8 ze 128 expertů a používá se také sdílený expert. Volba se mění podle tokenu a vrstvy. Pro rychlý běh na GPU je potřeba mít dostupné všechny váhy; nelze počítat VRAM jako 3,8B × počet bitů. [Konfigurace 26B](https://huggingface.co/google/gemma-4-26B-A4B-it/blob/main/config.json).
2. **Offload do RAM vybírá umístění vah.** `--n-cpu-moe` už naše konfigurace umí využít. Výpočet části expertů na CPU může uvolnit VRAM pro cache, ale přidává práci CPU a přesuny dat. Není to bezplatná inteligentní paměť. Pro 26B na 32GB GPU není nutný v doporučených profilech.
3. **PLE vybírá embeddingy tokenů.** U E2B/E4B jde o velké tabulky s vyhledáváním potřebných řádků; právě zde dává jejich držení mimo GPU architektonicky smysl. Náš build obsahuje odpovídající PLE cestu v `src/models/gemma4.cpp`. 26B ani 31B tento mechanismus nemají: jejich `hidden_size_per_layer_input` je nula.
4. **Sliding-window attention omezuje KV.** Většina vrstev si drží pouze nedávné okolí, menšina vidí celý kontext. To je hlavní přirozená úspora KV u velkých Gemma modelů.

Model sám nenačítá relevantní části našeho repozitáře nebo dávných chatů do VRAM. Výběr dokumentů zajišťuje harness, jeho indexy a nástroje historie. KV obsahuje mezivýsledky právě zpracovaných tokenů. Nativních 256k zahrnuje vstup, systémové instrukce, nástroje i generovanou odpověď a thinking; neznamená 256k čistého dokumentu plus neomezený výstup.

## 5. Výpočet KV pro přesně náš runtime

Ověřený upstream commit odpovídající místní binárce:

- [Gemma model](https://github.com/ggml-org/llama.cpp/blob/b2e5e9b28/src/models/gemma4.cpp).
- [SWA alokace](https://github.com/ggml-org/llama.cpp/blob/b2e5e9b28/src/llama-kv-cache-iswa.cpp).
- [K/V alokace](https://github.com/ggml-org/llama.cpp/blob/b2e5e9b28/src/llama-kv-cache.cpp).

26B má 5 globálních a 25 lokálních vrstev, globálně 2 KV hlavy × 512, lokálně 8 × 256. 31B má 10 globálních a 50 lokálních vrstev, globálně 4 × 512, lokálně 16 × 256. Obě mají lokální okno 1024. [26B config](https://huggingface.co/google/gemma-4-26B-A4B-it/blob/main/config.json), [31B config](https://huggingface.co/google/gemma-4-31B-it/blob/main/config.json).

Při jednom slotu a výchozím microbatch 512 kód alokuje lokální cache pro 1536 buněk, zaokrouhleno na 256. Globální cache roste s kontextem. Výpočet:

`KV bytes = 2 × (global_layers × global_kv_heads × global_head_dim × context + local_layers × local_kv_heads × local_head_dim × 1536) × bytes_per_element`

F16 = 2 B/prvek; Q8_0 = 34/32 B; Q4_0 = 18/32 B včetně blokové režie. Násobek 2 znamená K a V. Přestože konfigurace má `attention_k_eq_v: true`, runtime po odlišné normalizaci a RoPE ukládá K a V samostatně. Proto rozpočet nesnižovat ještě jednou na polovinu.

| Model / KV | 64k | 128k | 192k | 256k |
|---|---:|---:|---:|---:|
| 26B F16 | 1,54 GiB | 2,79 GiB | 4,04 GiB | 5,29 GiB |
| 26B Q8_0 | 0,82 GiB | 1,48 GiB | 2,15 GiB | 2,81 GiB |
| 26B Q4_0 | 0,43 GiB | 0,79 GiB | 1,14 GiB | 1,49 GiB |
| 31B F16 | 6,17 GiB | 11,17 GiB | 16,17 GiB | 21,17 GiB |
| 31B Q8_0 | 3,28 GiB | 5,94 GiB | 8,59 GiB | 11,25 GiB |
| 31B Q4_0 | 1,74 GiB | 3,14 GiB | 4,55 GiB | 5,95 GiB |

**Jde o spočtené K/V tenzory, nikoli celkovou naměřenou VRAM.** Navíc jsou váhy, projektor, compute/CUDA buffery, případné další stavy a Windows. Jiný microbatch změní lokální část. `--swa-full` by tuto úsporu zrušil; v našem buildu je výchozí hodnota false a harness jej nepřidává.

Qwen 3.8 už používá hybridní architekturu: 16 plných attention vrstev a 48 DeltaNet vrstev. Z jeho konfigurace vychází globální Q8 KV při 256k na 8,50 GiB, plus recurrentní stav. Gemma 26B má přibližně 3,2× menší přírůstek globální cache na token; Gemma 31B naopak přibližně o 25 % větší. Výhoda proto platí hlavně pro 26B, nikoli automaticky pro celou rodinu. [Qwen konfigurace](https://huggingface.co/Qwen/Qwen3.8-27B/blob/main/config.json).

## 6. Jakou kvantizaci bychom potřebovali

Váhy a KV se kvantizují nezávisle. Q5 vah + Q8 KV je normální kombinace. GGUF Q4/Q5 nejsou totéž jako hardwarový NVFP4 režim a názvy neurčují přesnou velikost souboru: některé tenzory mají vyšší přesnost.

Velikosti byly ověřeny přes veřejné API seznamů souborů, bez stažení vah:

| Gemma | Soubor vah | Projektor zvlášť |
|---|---:|---:|
| 26B oficiální QAT Q4_0 | 13,448 GiB | 1,113 GiB |
| 26B Unsloth UD Q5_K_M | 19,698 GiB | přibližně 1,113 GiB |
| 26B Unsloth UD Q6_K | 21,581 GiB | přibližně 1,113 GiB |
| 26B Q8_0 | 25,015 GiB | přibližně 1,113 GiB |
| 31B oficiální QAT Q4_0 | 16,439 GiB | 1,118 GiB |
| 31B Q5_K_M | 20,171 GiB | přibližně 1,118 GiB |
| 31B Q6_K | 23,471 GiB | přibližně 1,118 GiB |
| 31B Q8_0 | 30,394 GiB | přibližně 1,118 GiB |

Zdroje: [Google 26B QAT](https://huggingface.co/google/gemma-4-26B-A4B-it-qat-q4_0-gguf/tree/main), [Google 31B QAT](https://huggingface.co/google/gemma-4-31B-it-qat-q4_0-gguf/tree/main), [Unsloth 26B](https://huggingface.co/unsloth/gemma-4-26B-A4B-it-GGUF/tree/main), [Unsloth 31B](https://huggingface.co/unsloth/gemma-4-31B-it-GGUF/tree/main).

QAT znamená trénink zohledňující kvantizaci. Je rozumnější ji zahrnout do testu než předpokládat, že každá čtyřbitová verze bude nutně horší než libovolná Q5. Ani tvrzení výrobce o zachování kvality ale nenahrazuje test nástrojů. [Google QAT přehled](https://ai.google.dev/gemma/docs/core).

Pro hrubý provozní rozpočet přičítám k vahám + projektoru + KV **4–6 GiB** na desktop, compute buffery a rezervu. Není to garantovaná spotřeba; při kontrole samotný desktop/procesy zabíraly asi 2 GiB.

| Kandidát na této 5090 | Váhy + projektor + KV | Rozpočet včetně uvedené rezervy | Hodnocení |
|---|---:|---:|---|
| 26B QAT Q4 + F16 KV, 256k | 19,85 GiB | 23,9–25,9 GiB | velmi zajímavý profil |
| 26B QAT Q4 + Q8 KV, 256k | 17,37 GiB | 21,4–23,4 GiB | největší rezerva |
| 26B Q5 + Q8 KV, 256k | 23,62 GiB | 27,6–29,6 GiB | vyvážený kandidát |
| 26B Q6 + Q8 KV, 256k | 25,51 GiB | 29,5–31,5 GiB | proveditelný odhad, ověřit vision špičky |
| 26B Q8 + Q8 KV, 128k | 27,61 GiB | 31,6–33,6 GiB | zbytečně těsné |
| 31B QAT Q4 + Q8 KV, 128k | 23,49 GiB | 27,5–29,5 GiB | praktický 31B profil |
| 31B QAT Q4 + Q8 KV, 256k | 28,80 GiB | 32,8–34,8 GiB | nedoporučit jako bezpečný profil |
| 31B Q5 + Q8 KV, 64k | 24,57 GiB | 28,6–30,6 GiB | rozumné menší okno |
| 31B Q5 + Q8 KV, 128k | 27,22 GiB | 31,2–33,2 GiB | hraniční |

Celková skutečně hlášená kapacita GPU je 31,84 GiB. **Pro Gemmu 26B tedy nemusíme jít na 3–4 bity jen kvůli 256k kontextu. Q5/Q8 vychází dobře; Q6/Q8 může také vyjít.** QAT Q4 má navíc výhodu malého souboru a možnosti ponechat F16 cache. Běžné BF16 váhy velkých variant se do této karty celé nevejdou.

U 31B lze matematicky dostat 256k s Q4 vahami a Q4 KV, ale to je samostatný kompromis kvality cache. Q4 KV u dlouhých přesných úloh bych bez ověření nezařazoval. Smíšené přesnosti K/V nebo externí kompresní forky nejsou pro první 26B integraci potřeba.

## 7. Rychlost: co víme a co pouze odhadujeme

V místním starším `runtime/llama-server.log` jsou běhy z 22.–28. 8. 2026:

- Qwen Q5: krátké běhy přibližně 56–66 tok/s, další běh 39,8 tok/s.
- Qwen Q4: většinou zhruba 60–75 tok/s.
- Ornith Q5: několik velmi různých běhů přibližně 85–236 tok/s.
- Nemotron Q4: jediný krátký běh 400 výstupních tokenů při 266,86 tok/s.

Jsou to historické údaje pod danými aliasy, ne nový jednotný benchmark současných vah: bez kontroly tehdejšího souboru, obsazeného kontextu a nastavení nelze přesně přenést jejich rychlost na dnešní profil. Nulový výstup není rychlostní vzorek.

Autor experimentu na desktopové RTX 5090 publikuje pro Gemmu 26B Q4_K_M `tg128 = 219,9 tok/s` a `pp512 = 8744 tok/s`. Jde o krátký syntetický test v prostředí s úpravami runtime, nikoli naši Windows aplikaci. [Původní experiment a konfigurace](https://github.com/tlskinner26/llama-cpp-blackwell-optimization).

**Plánovací odhad bez spekulativního dekódování**, jeden stream, celý model na GPU, krátký obsazený kontext:

| Varianta | Orientační generování |
|---|---:|
| 26B QAT Q4 / obdobná Q4 | 130–220 tok/s |
| 26B Q5/Q6 | 110–190 tok/s |
| 31B Q4/Q5 | 40–70 tok/s |

Intervaly nejsou naměřeným výsledkem doporučených souborů. U 31B jde o hrubý odhad obdobné velikosti dense vah vůči místnímu Qwenu a běžné paměťové propustnosti, s velkou nejistotou. Při zaplnění 128k–256k rychlost klesá; přesné číslo bez měření neuvádím. MoE šetří FFN výpočty, ale dlouhou globální attention neodstraní.

Rozlišovat tři časy: zpracování nového vstupu (prefill), generování všech tokenů včetně thinking a dokončení celé úlohy s nástroji. Pouhé nastavení kapacity na 256k není test zaplněného 256k kontextu. Krátký `pp512` nelze lineárně extrapolovat na načtení celé knihy. Opakované agentní tahy navíc závisejí na opětovném využití prefixu cache.

Příklad pouze pro intuici: 3000 výstupních tokenů při 60 tok/s trvá 50 s; při 160 tok/s asi 19 s. To platí jen pro generování při stejném počtu tokenů, bez prefillu a nástrojů. Odlišný tokenizer a délka thinking mohou náskok zmenšit.

Gemma má také MTP draft checkpointy; tím se vysvětluje část internetových vysokých rychlostí. Základní návrh s nimi nepočítá: benchmark má odpovídat jednomu současnému modelu bez rozšíření produktové architektury. [Google přehled MTP](https://ai.google.dev/gemma/docs/core).

## 8. Konkrétní integrační práce

Není potřeba přepisovat FastAPI, web UI ani agentní smyčku. Existující GGUF/CUDA/OpenAI-compatible cesta je vhodná. Podporu architektury lze doložit v používaném commitu; skutečné načtení konkrétního GGUF a multimodálního projektoru je dosud neověřené.

1. Zaregistrovat model v `harness/config.py` i distribuční konfiguraci. Zachovat Qwen Q5 jako default. Přidat měřením podložené profily a hardwarové limity, ne jen odvozené minimum VRAM.
2. Použít unikátně pojmenovaný Gemma projektor. Nynější downloader kontroluje existenci a velikost souboru, nikoli rodinu modelu. Stažení dalšího generického `mmproj-F16.gguf` by mohlo ponechat již existující Qwen projektor. Oficiální QAT repozitář má vhodné vlastní jméno `gemma-4-26B-it-mmproj.gguf`.
3. Nastavit `supports_reasoning_effort: false`. Současný klient by jinak posílal Qwen `reasoning_effort=xhigh`; oficiální šablona Gemmy používá `enable_thinking` a výchozí hodnotu false. Zobrazit u Gemmy On/Off, nikoli předstírané úrovně hloubky.
4. Výslovně přepsat sampling v obou režimech: temperature 1,0; top_p 0,95; top_k 64; nevzít omylem Qwen non-thinking presence penalty 1,5. Sampling se totiž s defaulty slučuje. [Google nastavení](https://ai.google.dev/gemma/docs/core/model_card_4).
5. Ověřit normalizaci reasoning a tool calls na API hranici. Klient už čte `reasoning_content` i `reasoning`; fallback parser ale zná pouze `<think>`, zatímco Gemma má kanálové tokeny. Preferovat správné parsování serverem, ne nové ruční interpretování modelového textu. [Gemma formát](https://ai.google.dev/gemma/docs/core/prompt-formatting-gemma4), [function calling](https://ai.google.dev/gemma/docs/capabilities/text/function-calling-gemma4).
6. Zohlednit rozdílné zacházení s historií thinking. Launcher nyní globálně přidává `--reasoning-preserve`; Google rozlišuje uchování uvnitř tool-call cyklu a odstranění mezi uzavřenými uživatelskými tahy. Vybrat modelově správné chování a ověřit navazující odpověď.
7. Ověřit obrazový vstup: správný projektor, pořadí obraz/text a podporovaný token budget. Dosavadní globální `--image-min-tokens 1024` není automaticky správná modelová politika. Testovat screenshot s drobným textem a stránku PDF.
8. Zkontrolovat stop, přepnutí modelu, kompresi historie a další nástrojový tah při dlouhém kontextu. UI má při návratu do Qwenu zobrazit jeho vlastní správné možnosti.

## 9. Malý rozhodovací experiment

Nejprve technický smoke test 26B QAT Q4 při 32k: start, česká odpověď, thinking on/off, jediný tool call, řetězec alespoň pěti navazujících nástrojů, screenshot, STOP. Teprve potom měřit 128k a 256k a případně stahovat druhou kvantizaci.

Srovnat minimálně 15 reprezentativních úloh, každou dvakrát: pět oprav kódu ověřených výsledkem a testy, čtyři české textové/dokumentové úlohy s přesnými omezeními, tři obrazové/PDF úlohy a tři dlouhé kontexty s více informacemi na začátku, uprostřed i konci. Hodnotit správný výsledek, ne pouhý validní JSON nebo rychlý první token.

Rychlost měřit při stejných vstupech, s plně obsazenými prefixy např. 4k/32k/128k a téměř 256k s rezervou pro odpověď. Zaznamenat přesný hash modelu a projektoru, build, sampling, KV, vrchol VRAM, prompt tok/s, decode tok/s, čas celé úlohy a případný offload. Oddělit nové načtení vstupu od navázání přes prefix cache. Limity aktuálního profilu nepřekračovat jen kvůli srovnání.

Navržené rozhodovací pravidlo: nabídnout Gemmu jako rychlou alternativu, pokud zachová všechny základní funkce a v opakovaných relevantních úlohách přinese alespoň přibližně 1,5× kratší dobu dokončení bez významného poklesu úspěšnosti. Malá sada je pouze první filtr, nikoli statistický důkaz obecné převahy. Výchozí Qwen měnit až při jasném uživatelském přínosu v obtížných úlohách.

## 10. Profily pro 24GB a 16GB grafické karty

Kapacita VRAM určuje především možnost model načíst. Rychlost nelze spolehlivě odvodit jen z označení „16 GB“ nebo „24 GB“: rozhoduje konkrétní GPU, propustnost, příkon, desktop/laptop, ovladač a případné využití RAM. Níže uvedené rozpočty jsou návrhy k ověření, nikoli naměřené záruky na jiných kartách. Snížit dostupnou paměť na 5090 není plnohodnotná náhrada testu slabšího GPU.

### 24 GB: nejsilnější kandidát je 26B QAT Q4

Oficiální 26B QAT váhy s projektorem zaberou přibližně 14,56 GiB. Při 128k Q8 je součet 16,04 GiB; při 256k 17,37 GiB. S konzervativní rezervou 4–6 GiB je to:

| Profil pro 24 GB | Odhad rozpočtu včetně rezervy | Doporučení |
|---|---:|---|
| 26B QAT Q4, Q8 KV, 128k | 20,0–22,0 GiB | hlavní kandidát, celý model na GPU |
| 26B QAT Q4, Q8 KV, 256k | 21,4–23,4 GiB | rozšířený profil po ověření špiček |
| 26B QAT Q4, F16 KV, 128k | 21,4–23,4 GiB | alternativa pro vyšší přesnost cache |
| 26B UD Q5, Q8 KV, 64k | 25,6–27,6 GiB | nevhodné jako univerzální profil bez offloadu |

Poslední řádek se týká konkrétního velkého Unsloth UD Q5 souboru, ne všech existujících Q5 kvantizací. V případě zájmu o jiný GGUF je nutné přepočítat skutečnou velikost.

Proti současnému Qwen Q4 s 96k Q8 kompaktním profilem by tak Gemma mohla poskytnout vyšší rychlost a delší kontext. Není důvod odstranit Qwen: složitý vývoj může zvládat lépe i s menším oknem. Pro uživatele 24GB karty by šlo o smysluplnou volbu podle typu úlohy, stále vždy s jediným načteným modelem.

31B QAT s Q8 KV při 32k má přibližně 19,51 GiB ještě před provozní rezervou. Pro 24GB cílení je tedy těsná a nepřináší přesvědčivou výhodu. Na 16 GB ji jako standard vůbec nenavrhuji.

### 16 GB: preferovat 12B před dalším stlačováním 26B

26B QAT s projektorem potřebuje 14,56 GiB ještě před cache. I s malým 16k Q8 kontextem by součet dosáhl přibližně 14,88 GiB. Na desktop, compute a multimodální špičky zbývá příliš málo. Omezení kontextu samo problém nevyřeší; zbývá nižší kvantizace vah, odstranění vision nebo offload. Ani jedno není potřeba, pokud zvolíme 12B.

**Gemma 4 12B Unified je pro 16GB nabídku podstatně vhodnější kandidát:**

- Oficiální QAT Q4 váhy 6,497 GiB + projektor 0,163 GiB.
- Běžná Q5_K_M 7,836 GiB; Q6_K 9,114 GiB; Q8_0 11,800 GiB, vždy projektor zvlášť.
- Projektor stále existuje jako GGUF artefakt, přestože model nemá velký samostatný vision encoder. „Encoder-free“ tedy v naší integraci neznamená „ignorovat mmproj“.

Zdroje: [Google 12B QAT soubory](https://huggingface.co/google/gemma-4-12B-it-qat-q4_0-gguf/tree/main), [Unsloth 12B soubory](https://huggingface.co/unsloth/gemma-4-12b-it-GGUF/tree/main), [Google uvedení 12B](https://blog.google/innovation-and-ai/technology/developers-tools/introducing-gemma-4-12B/).

Z konfigurace 12B: 8 globálních vrstev, jedna globální KV hlava × 512; 40 lokálních vrstev, 8 hlav × 256, okno 1024. Stejný výpočet pro jeden slot a microbatch 512 dává:

| KV 12B | 32k | 64k | 128k | 256k |
|---|---:|---:|---:|---:|
| F16 | 0,97 GiB | 1,47 GiB | 2,47 GiB | 4,47 GiB |
| Q8_0 | 0,51 GiB | 0,78 GiB | 1,31 GiB | 2,37 GiB |

Odvozeno z [konfigurace 12B](https://huggingface.co/google/gemma-4-12B-it/blob/main/config.json) a výše uvedené SWA implementace. Přibalený commit má v multimodálním kódu větve `GEMMA4UV` a `GEMMA4UA`; existence těchto větví není end-to-end ověřením konkrétního souboru. Dlouhý obrazový vstup může mít odlišné compute nároky než čistý text.

| Profil pro 16 GB | Odhad rozpočtu včetně 4–6 GiB rezervy | Doporučení |
|---|---:|---|
| 12B QAT Q4, Q8 KV, 64k | 11,4–13,4 GiB | bezpečný počáteční kandidát |
| 12B QAT Q4, Q8 KV, 128k | 12,0–14,0 GiB | doporučený cílový standard |
| 12B QAT Q4, Q8 KV, 256k | 13,0–15,0 GiB | paměťově nadějné, až po testu rychlosti a vision |
| 12B Q5, Q8 KV, 64k | 12,8–14,8 GiB | druhý kandidát pro kvalitu |
| 12B Q5, Q8 KV, 128k | 13,3–15,3 GiB | možné, ověřit rezervu konkrétní karty |
| 12B Q6, Q8 KV, 64k | 14,1–16,1 GiB | nezačínat tím jako obecným defaultem |

Proti našemu Qwen 27B IQ3_S (11,214 GiB vah, navíc 0,864 GiB projektor a větší cache) je to velký paměťový rozdíl. Neznamená to však automaticky vyšší inteligenci: větší Qwen i při IQ3 může některé obtížné úlohy zvládnout lépe. Právě Qwen IQ3 v 32k/48k profilu musí být referencí pro lokální A/B test, ne Qwen Q5, který není realistickým 16GB soupeřem.

Google pro 12B publikuje GPQA 78,8 %, LiveCodeBench v6 72,0 % a Tau2 průměr přes tři domény 69,0 %. Pro 26B jsou odpovídající čísla 82,3 %, 77,1 % a 68,2 %; pro E4B 58,6 %, 52,0 % a 42,2 %. Na těchto konkrétních metrikách je 12B výrazně blíže 26B než E4B. Tau2 průměr není totožná metrika jako retail-only skóre z původní stránky velkých modelů. [Google 12B model card](https://huggingface.co/google/gemma-4-12B-it).

### Kde má smysl E4B a offload

E4B QAT má 4,801 GiB vah + 0,923 GiB projektor, před KV a provozními buffery. Je vhodná jako úsporný kandidát, pokud má na 16GB kartě běžet zároveň jiná GPU aplikace nebo je prioritou lehká diskuze. Pro náročný vývoj bych jí nedával přednost před 12B bez konkrétního měření. [Oficiální E4B soubory](https://huggingface.co/google/gemma-4-E4B-it-qat-q4_0-gguf/tree/main).

PLE u E4B dovoluje část embeddingových tabulek držet mimo GPU; přesnou úsporu a dopad na prefill ověřit logem a umístěním tenzorů. Na 16GB kartě s tímto Q4 souborem ale není nutné začínat specializovaným offloadem.

Offload 26B na 16 GB lze zkoumat jako volitelný kompromis, pokud se prokáže podstatně vyšší úspěšnost úloh než u 12B. Nabídka jej musí označovat jako využití CPU/RAM. Nepředstírat stejnou rychlost jako celý model na GPU. Pro takový profil počítat alespoň s 32 GB systémové RAM, komfortněji 64 GB, a samostatně změřit běžný procesor i PCIe. Pouhé úspěšné načtení nepostačuje.

### Jak slabší model podpořit v harnessu

Zachovat všechny základní operace, ale přizpůsobit jejich kontext: méně současně nabízených schémat nástrojů podle pracovního režimu, menší výsledky čtení se snadným pokračováním, průběžné shrnutí a explicitní plán. Stávající index a vyhledávání historie tomu již pomáhají. Měřit chyby argumentů, ztrátu zadání a opakování smyček; kratší prompt nesmí skrýt podstatná omezení uživatele.

Výchozí profil volit podle skutečně dostupné VRAM včetně rezervy, ne jen marketingové kapacity. Při nedostatku místa nejprve nabídnout menší kontext téhož modelu; přechod na jiný model má být viditelný. Instalátor má stáhnout vybraný doporučený model, ne automaticky všechny nové soubory jen proto, že jednotlivě vyhoví kapacitě.

Pro rychlost na 24/16 GB není poctivé dát jedno číslo. U 26B lze očekávat výhodu nízkého počtu aktivních parametrů; 12B dense může mít na téže kartě pomalejší generování než plně rezidentní 26B MoE, přestože má menší soubor. Referenční 5060 Ti experiment z oddílu 7 používá upravený runtime a jiné váhy, proto jeho rychlost nepřenášet na náš profil. Před zveřejněním parametrů změřit alespoň jednu skutečnou 24GB a jednu skutečnou 16GB kartu, vždy uvést model GPU, příkon a obsazený kontext.

**Výsledek průzkumu:** Gemma má pro podporu slabších GPU silnější produktový důvod než jako náhrada Qwenu na 5090. Doporučený experiment je 26B QAT pro 24 GB a 12B QAT/Q5 pro 16 GB; na 32 GB ponechat Qwen Q5 a případně nabídnout 26B jako rychlou alternativu. 31B, E2B a další kvantizace přidávat až při konkrétním prokázaném přínosu.
