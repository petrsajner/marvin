# Qwen3.8-Flash-Next: integrační návrh pro Marvin

Aktualizováno 13. 9. 2026. Flash-Next je integrovaný a nainstalovaný v Marvinu 1.8.0; výsledky a omezení jsou v části 10 a v [protokolu vydání](../distribution/RELEASE-1.8.0.md). Části 1–9 zachycují výzkum a původní plán nad verzí 1.7.0, commit `6b687458ca09879ceac81baa72bd53f9b52fad65`. Srovnání dosavadních modelů před aktivací runtime je v [protokolu b10935](../distribution/LLAMA-b10935-VALIDATION.md).

## Závazné zadání

- Použít standardní upstream llama.cpp; **GenerelSchwerz je z návrhu vyřazen**. Vlastník upozornil, že autor videa jej výslovně nedoporučuje kvůli nelepším výsledkům a zamrznutí počítače. Původní doporučení forku v tomto dokumentu tím neplatí.
- Cílová kvantizace vah je **Q3**, jako výchozí konkrétní kandidát **UD-Q3_K_XL**. IQ3_XXS z videa je referenční výsledek a případný slabší profil, nikoliv automatická náhrada zvoleného Q3.
- KV cache **Q8_0**, kontext nejméně **131 072 tokenů (128k)**; preferovat 196 608 nebo 262 144, pokud projdou paměťově, rychlostí i kvalitou.
- Krátký smoke test smí odhalit problém s načtením, ale 16k/32k nesplňuje podmínku hotové integrace Flash-Next.
- Pro uživatele zůstává běžná volba modelu. Veškeré nastavování runtime, počtu vláken, CPU/GPU umístění, shardů a projektoru provádí aplikace.
- Upgrade llama.cpp nebo jiné závislosti nesmí rozbít žádný současný model ani jeho dosavadní funkce. Vyžaduje skutečné regresní měření, ne pouze úspěšný import nebo test s falešným modelem.
- Konfigurace je podle skutečného PC: topologie CPU, RAM, VRAM, ovladač a úložiště. Nezapevňovat nastavení 5090/265K pro všechny instalace.
- Nadále jediný model a jeden sekvenční agent; vision je nativní součást vybraného modelu.

## 1. Ověřené zdroje a model

Video: Codacus, [Is Frontier Class Local AI Finally Practical?](https://www.youtube.com/watch?v=IH8XmxiwliQ). Z popisu videa ověřeno: RTX 3060 12 GB, Ryzen 5 5600X, 64 GB DDR4; `unsloth/Qwen3.8-Flash-Next-GGUF`, varianta UD-IQ3_XXS, přibližně 82 GB. Autor uvádí 13,6 vs. 24,4 tok/s při 12 vs. 6 vláknech. Údaje o 24/40 GB RAM a negativní zkušenost s forkem jsou převzaté od vlastníka z videa; nejsou naším reprodukovaným benchmarkem.

V [spec-wins](https://github.com/thecodacus/spec-wins) autor uvádí agentní harness Pi, shell/SSH do sandboxu a 17/17 kontrol tří úloh pro Flash-Next IQ3_XXS. Je to malý důkaz agentního použití, bez ověření vision a bez důkazu obecné převahy nad cloudovými modely. Odkaz na fork v popisu videa nebyl dostatečný důvod interpretovat jej jako doporučení.

Otevřený model se jmenuje **Qwen3.8-Flash-Next**. Architektura je `qwen4_exp` v Transformers a `qwen4exp` v llama.cpp. Má přibližně 125B parametrů hlavní sítě, 6B aktivních na token a 51B n-gram embeddingů; MTP je uváděné samostatně. Je nativně multimodální. Model používá 48 vrstev, hybrid Gated DeltaNet/Qwen Sparse Attention a 10 z 512 expertů plus sdíleného experta. [Technický report](https://arxiv.org/abs/2608.30320), [konfigurace](https://huggingface.co/Qwen/Qwen3.8-Flash-Next/blob/main/config.json).

## 2. Paměť: co úspora znamená

| Součást | Umístění a práce | Omezení |
|---|---|---|
| PLE/n-gram tabulka | Naučené vektory čtené podle potřebných řádků ze souboru | Čtení využívá RAM/page cache; nejde o nulovou spotřebu RAM |
| Routed experti | CPU/GPU umístění podle množství paměti; pouze vybraní se počítají pro daný token | Aktivní parametry nejsou celková velikost potřebných vah |
| Dense/shared části a vision | Přednostně GPU, pokud je dost místa | Potřebují rezervu pro obrazový vstup a compute |
| KV, QSA indexer a recurrentní stav | Stav právě zpracovaného prefixu | Musí se korektně obnovit po tool call, STOP, steering a kompresi |
| Souborové indexy a historie Marvina | Výběr relevantních vstupů pomocí nástrojů | Lookup tabulka tuto práci nenahrazuje |

Lookup tabulka není databáze hotových odpovědí. SSD přístup může být omezen latencí náhodných čtení, i při nízkém celkovém počtu MB/s.

Upstream označuje `per_layer_tok_embd` jako `TENSOR_READ_LAZY`. Loader pro tyto tenzory vytváří potřebná mapování i vedle jiného režimu načítání běžných vah. **Lazy PLE a mmap celého modelu jsou odlišné mechanismy.** Pro tento návrh nepřidáváme experimentální expert cache. [Model](https://github.com/ggml-org/llama.cpp/blob/b10935/src/models/qwen4exp.cpp), [loader](https://github.com/ggml-org/llama.cpp/blob/b10935/src/llama-model-loader.cpp).

Preferovaný výchozí směr je lazy PLE + standardní CPU/GPU offload, s mmap podle měřeného tlaku na RAM. Blanket mlock celé tabulky ani agresivní alokace téměř veškeré RAM nejsou vhodné pro běžný desktop.

## 3. Q3 a požadované okno 128k–256k

Revize Unsloth souborů ověřená při průzkumu: `38bb39ee97821de2c9009abb7e93950eec396e66`.

| Varianta | Váhy na disku | Shardy | Význam |
|---|---:|---:|---|
| **UD-Q3_K_XL** | **89,986 GB / 83,806 GiB** | 3 | cílový kandidát |
| UD-IQ3_XXS | 81,962 GB / 76,333 GiB | 3 | reference videa, případně slabší varianta po ověření |
| UD-IQ4_XS | 93,683 GB / 87,249 GiB | 3 | mimo první cílový profil |
| UD-Q4_K_XL | 111,335 GB / 103,688 GiB | 4 | mimo první cílový profil |

Projektor `mmproj-F16.gguf` má dalších 904 004 000 B, přibližně 0,842 GiB. Všechny shardy jsou nutné, serveru se předává první. První shard je jen 10 946 624 B. [Ověřený seznam souborů](https://huggingface.co/unsloth/Qwen3.8-Flash-Next-GGUF/tree/38bb39ee97821de2c9009abb7e93950eec396e66).

Kvantizační skóre zveřejněné dodavatelem není procento zachované inteligence. Volbu Q3 potvrdit úlohami, nástroji a obrazovými vstupy. [Analýza kvantizace](https://unsloth.ai/docs/models/qwen3.8-next).

Pro 12 QSA vrstev se dvěma KV hlavami × 256 a indexerem s jednou 128prvkovou key hlavou vychází v b10935:

`attention + indexer bytes = 12 × (2 × 2 × 256 + 128) × context × (34 / 32)`

| Kontext | Samotné Q8 attention + indexer tenzory |
|---|---:|
| 128k / 131 072 | 1,793 GiB |
| 192k / 196 608 | 2,689 GiB |
| 256k / 262 144 | 3,586 GiB |

Jde o odhad odvozený ze zdrojového kódu, nikoliv celkovou naměřenou VRAM. Navíc jsou váhy, recurrentní stavy/checkpointy, compute buffery, vision a desktop. QSA výběr neznamená, že lze zbytek KV zahodit. [Hybridní indexer cache](https://github.com/ggml-org/llama.cpp/blob/b10935/src/llama-memory-hybrid-idx.cpp).

Navýšení 128k → 256k zde znamená asi 1,79 GiB navíc v těchto cache tenzorech. Celkový dopad na rychlost a compute paměť nemusí být malý. To je dobrý důvod testovat 256k, nikoliv důkaz, že bude dobře fungovat.

Při kontrole zůstávaly otevřené upstream návrhy [QSA gather #28213](https://github.com/ggml-org/llama.cpp/pull/28213), [pooled indexer #28699](https://github.com/ggml-org/llama.cpp/pull/28699) a [CUDA sparse FA #28770](https://github.com/ggml-org/llama.cpp/pull/28770). Jejich přínos nelze vydávat za vlastnost běžného releasu. Tuto integraci nestavět na jejich neověřeném cherry-pickování.

**Přijímací podmínka je použitelný dlouhý kontext, ne jen úspěšná alokace.** Testovat přibližně 120k vstupu a rezervu na výstup v 128k profilu, analogicky zaplněný 192k/256k profil. Kontext zahrnuje systémové instrukce, schémata nástrojů, obrazové tokeny, historii, reasoning a odpověď.

## 4. Automatické přizpůsobení počítači

Současné `harness/gpu.py` pracuje hlavně s celkovou VRAM. Potřebujeme interní plán běhu oddělený od uživatelské volby modelu.

### Detekce

- CPU: fyzická jádra, logická vlákna, dostupné procesory/skupiny, výkonnostní třídy, případně NUMA. Windows `GetSystemCpuSetInformation` a související topologické API, nikoliv dělení logických vláken dvěma.
- RAM: fyzická celková i dostupná paměť, volný commit a tlak na stránkování. Virtuální commit/pagefile se nepočítá jako rychlá fyzická RAM.
- GPU: identita karty, architektura, kompatibilita ovladače, celková a dostupná VRAM; zohlednit desktop a jiné procesy.
- Disk: místo pro všechny shardy a projektor, lokální úložiště; parametry dostupného I/O mohou ovlivnit profil.
- Runtime/model: verze binárky a knihoven, skutečné typy a velikosti tenzorů, vybraná kvantizace a projektor.

[CPU sets](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getsystemcpusetinformation), [stav paměti](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/ns-sysinfoapi-memorystatusex).

**Na našem 265K je 8 P + 12 E jader bez Hyper-Threadingu.** Read-only sonda přes Windows CPU sets v tomto průzkumu vrátila EfficiencyClass 1: 8 fyzických / 8 logických; EfficiencyClass 0: 12 fyzických / 12 logických. Číslování logických CPU nepředpokládat podle pořadí a nezakódovat natvrdo masku „prvních osm“.

Pro generování je osm P jader rozumný první kandidát. Pro prefill porovnat P jádra proti kombinaci P+E; u jiných CPU případně SMT. Volba počtu vláken a jejich přiřazení jsou dvě různé věci. Nastavit odděleně decode a batch/prefill pool. Nic z toho neměnit globálně ve Windows; platí pouze pro náš inferenční proces.

### Plán běhu

Interní výstup detekce/plánování: runtime ID, model manifest, skutečný kontext, typy K/V, počet decode/batch vláken, případné CPU sets/affinity, počet CPU expertových vrstev, GPU umístění, load/lazy režim, batch/ubatch, kontrolované paměťové rezervy a platnost kalibrace.

Postup volby:

1. Respektovat explicitně vybranou variantu vah; na našem stroji cílit Q3_K_XL.
2. Z kandidátů 256k → 192k → 128k vybrat nejvyšší **ověřeně použitelný** profil s Q8 KV a rezervami.
3. Pro každé okno vyhodnotit více legálních rozdělení CPU/GPU a batch/ubatch. Nepředpokládat, že maximální obsazení VRAM je nejrychlejší.
4. Podle volné RAM zvolit vhodný standardní způsob načítání. Kontrolovat zvlášť fyzickou paměť a commit; monitorovat i při samotném loadu.
5. Omezenou kalibrací ladit vlákna a pracovní buffery. Nedělat úplný benchmark nebo 128k warmup při každém kliknutí na model.
6. Výsledek uložit lokálně podle otisku hardwaru + ovladače + runtime + hashe modelu + pravidel plánovače. Po přenosu instalace na jiné PC nebo upgradu příslušnou kalibraci zneplatnit.
7. Před každým startem znovu zkontrolovat proměnlivou dostupnou RAM/VRAM. Započíst správně paměť, která se uvolní ukončením našeho dosavadního modelu, a po ukončení starého procesu stav znovu načíst.

Celková VRAM a počet jader určují kandidáty; reálné měření vybírá vhodnou konfiguraci. Když úspornější varianta Flash-Next na slabší kartě neudrží alespoň 128k s vision a agentní smyčkou, nepovažovat ji za hotově podporovaný Flash profil. Původní menší modely mají dál své vlastní praktické kontexty; požadavek 128k se zde týká nového modelu.

Paměťové rezervy musí chránit běžnou práci s browserem, PDF a obrázky. Monitorování má při hrozícím vyčerpání zastavit pouze náš load/běh a obnovit funkční stav; nemá čekat až na zamrznutí OS ani zabíjet cizí aplikace. Pomalé zpracování promptu samo o sobě není důvodem k falešnému označení procesu za mrtvý.

## 5. Neviditelná integrace v uživatelském rozhraní

Uživatel vybere model. Marvin sám:

1. ověří úplnost vah a správný projektor;
2. vybere kompatibilní runtime a místní plán běhu;
3. uvolní předchozí model, přepočítá skutečnou rezervu a načte zvolený;
4. nastaví thinking, šablonu a nástroje;
5. začne pracovat v dosavadním chatu/režimu.

Žádné ruční volby forků, CPU vrstev, afinit, mmap nebo ladicích příkazů. Příprava modelu používá dosavadní indikátor načítání a fungující STOP. Technické detaily patří do diagnostiky.

Nevydávat stav „ready“ při chybějícím shardu nebo nefunkčním vision projektoru. Menší profil může být vybraný automaticky v rámci podporovaných nastavení, ale UI a modelový klient musí znát jeho skutečný limit. **Nesmí se tajně snížit Flash-Next pod 128k nebo zaměnit vybraný model za jiný.** Když požadovaný model stroj nezvládne, aplikace zachová/obnoví funkční předchozí stav a sdělí stručný důvod. Neviditelné nastavení není slib podpory libovolného hardwaru.

Stejný plán musí používat ruční přepnutí, autostart, restart, pokračování uložené úlohy i změna konfigurace. Nyní tyto cesty sdílejí jen část logiky a `fit_hardware` může automaticky přepsat identitu modelu. To vyžaduje sjednocení, aby profil po restartu neodpovídal jinému počítači nebo jinému oknu než za běhu.

## 6. Agentní smyčka a vision

Agentní smyčka nepotřebuje druhou kopii vah. Potřebuje spolehlivé opětovné použití prefixu a návaznost všech druhů stavu.

Marvin přidává dynamický projektový kontext na konec promptu. Další tool-call tah tento dočasný konec změní, takže nestačí testovat jediný textový request. Ověřit:

- 10–20 navazujících tool kol při dlouhém prefixu;
- změny souborů a aktualizaci dynamických instrukcí;
- STOP/continue, steering, frontu, reload a změnu chatu;
- kompresi přes stejný lokální model a návrat k pracovnímu kontextu;
- screenshot → nástroj → další screenshot a PDF/OCR s drobným textem;
- hranice microbatchů, zkrácení/obnovení prefixu, PLE historii, recurrentní stav a QSA indexer.

[Issue 28425](https://github.com/ggml-org/llama.cpp/issues/28425) je externí hlášení rizika hybridního partial rollbacku, nikoliv naše reprodukovaná chyba. Podporu proto potvrdit na přesně vybraném upstream buildu.

Měřit nové vstupní tokeny skutečně vyhodnocené serverem. Například při 200 prompt tok/s by úplný přepočet 120k vstupu trval 10 minut; to je ilustrace, ne odhad výkonu našeho modelu. Další krátký tool výsledek nesmí bezdůvodně vyvolávat takový přepočet celé historie.

`--cache-ram` je serverová prompt/state cache, nikoliv expert cache nebo OS page cache. Rozpočet této cache a případných checkpointů musí plánovač počítat a ověřit na návratech mezi chaty.

Vision projektor musí odpovídat Flash-Next; generický název se shoduje s projekčním souborem našeho 27B, ale výstupní dimenze se liší. Uchovávat oddělené modelové adresáře/manifesty. Barevný obrázek je pouze smoke test: přijetí vyžaduje správné čtení textu a další nástrojovou akci v aktuálním UI.

Thinking/effort i strukturované nástroje mají podporu v modelové šabloně. Zachovat jejich dosavadní uživatelské ovládání. Výstup parsovat přes serverové strukturované API a ověřovat argumenty; neskrývat neplatné tool calls hádáním opravených hodnot. [Oficiální checkpoint a nastavení](https://huggingface.co/Qwen/Qwen3.8-Flash-Next).

## 7. Bezpečný upgrade závislostí

Výchozí runtime před implementací b10549, `b2e5e9b28`, Flash-Next neobsahuje. Upstream jej přidal v [PR 27742](https://github.com/ggml-org/llama.cpp/pull/27742). Kandidátem byl b10935, commit `8e330954adb6e86c329c9d7e338f01f93ffe4b88`; po dokončení regresní matice současných modelů byl 13. 9. aktivován se zachovanou kopií b10549. Konkrétní výsledky jsou v [runtime protokolu](../distribution/LLAMA-b10935-VALIDATION.md).

Původní `scripts/download_llama.py` vybíral poslední dostupný release a před rozbalením nové verze mazal stávající adresář. Navazující implementace nahrazuje tuto cestu pinovaným stagingem a návratnou aktivací podle následujících požadavků:

- Stáhnout a rozbalit konkrétní pinovaný balík do stagingu vedle současného, s odpovídajícími CUDA DLL a hashi.
- Ověřit ovladač a backend, metadata, architektury a požadované flags. Úspěšné `--version` není funkční validace.
- Starý runtime a přesný dependency lock zachovat jako lokální poslední funkční verzi.
- Na nové sadě provést kompletní relevantní regresní matici, teprve potom atomicky aktivovat manifest runtime.
- Selhání instalace, loadu nebo ověřovacích kontrol vrátí původní sadu bez přepisu uživatelských dat a vah.
- Python knihovny aktualizovat jen tam, kde je to pro integraci nutné; testovat přesný výsledný lock v novém prostředí. Nerozšiřovat změnu na vše dostupné jen kvůli novému modelu.
- Žádné automatické přepisování systémového ovladače, Pythonu nebo PATH. Podporovanou distribuční sadu ověřit v Minimal i Full instalaci.

Uživatel nebude vybírat runtime. Cíl je jedna nová sada ověřená pro všechny modely. Pokud je nutné interně podržet starou sadu kvůli kompatibilitě, musí ji aplikace řídit transparentně a skutečně otestovat obě cesty; neoznačit regresi za vyřešenou pouhým přidáním druhého EXE.

### Povinná modelová regresní matice

| Existující model/varianta | Co musí projít na novém runtime |
|---|---|
| Qwen3.8-27B IQ3_S | vlastní KV profily, chat, thinking, tools, vision |
| Qwen3.8-27B Q4_K_M | podporované F16/Q8 KV profily, chat, thinking, tools, vision |
| Qwen3.8-27B Q5_K_M | dosavadní pracovní dlouhý kontext, thinking/effort, tools, vision |
| Ornith 1.5 35B-A3B Abliterated Q5 | vlastní sampling/šablona, thinking, tools, vision |
| Nemotron 3.5 Lightning Q4_K_XL | text, thinking on/off, tools, dlouhý kontext, CPU offload profily |
| Nemotron 3.5 Lightning Q5_K_XL | totéž, zvlášť těsné paměťové profily |
| Nový Flash-Next Q3_K_XL | vše výše relevantní včetně vision a plně využívaného okna alespoň 128k |

Nemotron je v této nabídce textový; absence jeho vision není regresí. Testovat produkčně podporované praktické profily a také reprezentativní slabší hardware. Běh všech vah na 5090 s pouhým omezením alokace nenahrazuje skutečnou 16GB kartu, jiný CPU nebo horší propustnost RAM.

U každé varianty porovnat původní a nový runtime za stejných podmínek: skutečné soubory, kvalitu výsledku, tool argumenty, thinking, cold/warm prefill, další tah, decode, RAM/VRAM, opakovaný start/stop a přepnutí tam i zpět. Izolovaně ověřit neúplný download, chybějící DLL/projektor, obnovu po chybě a restart aplikace.

Při první etapě znovu prošlo 366 core kontrol a 21 servisních testů. K tomu byly porovnány všechny současné modely ve 22 praktických KV profilech na obou runtime, dlouhé vstupy a téměř plné 192k okno Qwenu Q5. Výsledky i samostatně reprodukovaná dosavadní chyba při ukončování úlohy jsou v [protokolu b10935](../distribution/LLAMA-b10935-VALIDATION.md). Tím není ověřen Flash-Next, jiný fyzický hardware ani nový instalátor.

## 8. Konkrétní rozsah implementace

| Součást | Nutný zásah |
|---|---|
| `harness/gpu.py` + interní detekce/plánování | CPU topologie, RAM/commit, GPU/ovladač, plán pro konkrétní model a PC |
| `harness/config.py` | oddělit popis modelu, požadovaný kontext a vypočtené spouštěcí nastavení |
| `harness/application.py`, `model_switch.py` | jeden konzistentní plán pro všechny startovací cesty, správný runtime/config po přepnutí, rollback |
| `harness/servermgmt.py` | explicitní runtime, argv podle plánu, hlídání paměti při loadu a běhu |
| `scripts/download_models.py`, setup/backup | manifest všech shardů, revize/hash/velikosti, projektor, atomická značka úplnosti |
| `scripts/download_llama.py`, dependency setup | pinovaný staging, validace, atomické přepnutí, poslední funkční sada |
| `harness/web_api.py` a Settings | skutečná úplnost modelu a kontext; zachovat jednoduché uživatelské volby |
| `harness/llm.py`, `agent.py`, `session.py`, `context.py` | návaznost prefixu/stavu a modelově vhodné čekání na prefill při zachování STOP |
| Existující testy a instalátor | parametrizovaná matice všech modelů, skutečné dlouhé vstupy a vision, přenos na jiné PC |

Pozor: API dnes označuje model za instalovaný podle existence jediného souboru a vision podle položky v konfiguraci. Nový shardový model musí být „připravený“ až s kompletním validovaným manifestem. První shard o 11 MB je navíc pod dnešním downloader limitem 1 GiB.

Není potřeba přepisovat webovou aplikaci, SSE ani agentní smyčku od základu. Je potřeba dát současným cestám stejnou pravdu o aktuálním modelu, runtime a použitelné kapacitě.

## 9. Pořadí realizace a dokončení

1. Zaznamenat přesný současný baseline a ověřit jej se všemi šesti existujícími variantami, včetně přepínání a relevantních profilů.
2. Připravit nový pinovaný upstream runtime bokem a stejnou maticí prokázat kompatibilitu. Závislosti zatím neaktivovat v běžné instalaci.
3. Připravit detekci hardwaru, plánování, manifest shardů/projektoru a jednotnou cestu přepínání. Diagnostické výsledky ukládat v omezené podobě, nevytvářet další hromady pokusných prostředí.
4. Změřit Flash-Next Q3_K_XL + Q8 KV při 128k, potom 192k a 256k. Krátké smoke testy nejsou přijímací výsledky.
5. Dokázat plnou návaznost nástrojů, vision, komprese, STOP/steering a chatů při dlouhém kontextu; ověřit i hranici nedostatku paměti.
6. Na slabších strojích ověřit automaticky vybraný profil; případnou nižší kvantizaci nabízet v dosavadním modelovém výběru, s funkčním oknem nového modelu nejméně 128k.
7. Po splnění celé matice aktivovat a zabalit ověřenou sadu do nové verze aplikace. Modelová volba v UI funguje stejně jako dosud.

**Přijímací kritérium: uživatel přepne na Flash-Next a běžné funkce Marvina fungují s alespoň 128k Q8 kontextem, bez ručního nastavování a bez regrese ostatních modelů.** Výsledky navazující implementace a měření na 64 GB RAM následují v části 10.

## 10. Navazující implementace a první skutečná měření

Stav implementace 1.8.0 dne 13. 9. 2026: všechny čtyři soubory Flash-Next Q3 jsou stažené a ověřené proti pinovaným SHA-256. Celkem mají 90 890 357 824 bajtů včetně vlastního vision projektoru. Dlouhý test byl dokončen pro 128k profil; 256k profil prošel funkčními zkouškami na kratším vstupu. Slabší fyzické karty zatím ověřené nejsou.

Z dokončených GGUF vychází 26,822 GiB lookup tabulky, 51,990 GiB expertů, 4,984 GiB společných vah a 0,842 GiB projektoru. Manifest obsahuje také odvozený popis paměti svázaný s přesnou revizí a kontrolními součty. Díky tomu lze odmítnout zjevně nedostatečný počítač ještě před přenosem 90 GB; po stažení se znovu kontrolují skutečné soubory a aktuálně dostupné prostředky.

Na Windows se ukázaly podstatné rozdíly mezi způsoby načítání:

| Nastavení Q3 / 128k Q8 | Naměřený výsledek |
|---|---|
| `--lazy-mode on --load-mode mmap` | Krátká odpověď a thinking fungovaly, generování 17,34 tok/s. Při další úloze poklesla volná RAM pod 2 GiB a náš hlídač server ukončil; tento profil není přijatý. |
| `--lazy-mode on --load-mode none` | Na tomto PC skončilo načítání chybou inicializace CUDA; nepoužívat jako výsledný profil. |
| `--lazy-mode on --load-mode none --no-host` | Načtení přibližně 40 s, generování 27,29 tok/s. Prošly chat, thinking, tool roundtrip, dva obrázky, STOP při generování i prefillu a dvě skutečné agentní úlohy se zápisem a čtením souboru. Při kontrolním vzorku zbývalo přibližně 12 GiB RAM. |

V tomto upstream buildu je u Windows uvolňování dílčích mapovaných rozsahů prázdná operace. Loader přitom podporuje samostatné mapování lazy tensorů i při `load-mode none`. Nastavení `no-host` vynechá CUDA host buffers pro CPU váhy a umožní použít CPU buffer/repacking. To je podklad pro zvolenou kombinaci; přesný původ každého naměřeného rozdílu v paměti není izolován jedním experimentem. [Windows mmap](https://github.com/ggml-org/llama.cpp/blob/8e330954adb6e86c329c9d7e338f01f93ffe4b88/src/llama-mmap.cpp#L577), [samostatné lazy mapování](https://github.com/ggml-org/llama.cpp/blob/8e330954adb6e86c329c9d7e338f01f93ffe4b88/src/llama-model-loader.cpp#L1289), [výběr CPU bufferů](https://github.com/ggml-org/llama.cpp/blob/8e330954adb6e86c329c9d7e338f01f93ffe4b88/src/llama-model.cpp#L994).

Log funkčního běhu potvrzuje lazy PLE tensor 27 465 MiB, Q8 attention cache 1 632 MiB a Q8 indexer cache 204 MiB při 131 072 buňkách. GPU výpočetní buffer byl přibližně 1 859 MiB, recurrentní stav 113 MiB. Hodnota v konfiguračním plánu je odhad; rozhodující zůstávají skutečné alokace a funkční zkouška.

Windows topologie skutečně obsahuje 8 P a 12 E jader bez HT. P jádra mají logická ID `0,1,6,7,8,9,18,19`; nejsou to první osmice ID. Stejný vstup o 7 711 tokenech s vyhledáním tří údajů dopadl následovně:

| CPU pro prefill | První odpověď | Navazující otázka |
|---|---:|---:|
| 8 P jader | 68,437 s | 1,219 s |
| všech 20 fyzických jader | 85,829 s | 1,312 s |

Oba běhy použily stejných 32 CPU expertových vrstev a 128k Q8 profil. Automatický plán proto nyní preferuje detekovaná P jádra pro decode i prefill; u homogenního CPU používá fyzická jádra. Jde o změřenou volbu pro tento hybridní procesor, nikoliv univerzální tvrzení o všech CPU.

Původní závod při dokončování úlohy je opraven a testován. Současný Qwen Q5 prošel také novou cestou přes web: spuštění, odpověď, navazující zápis/čtení souboru a zastavení. Python balíčky zůstávají ve stejných 95 pinovaných verzích; `filelock` je pouze výslovně deklarovaný jako přímá závislost.

Artefakty jsou společně v `runtime/validation/flash-next/`: `preparation.json`, `memory-preflight.json`, `regression/results.json`, `initial-128k/results.json`, `resident-128k/results.json`, `no-host-128k/results.json`, `batch-p-128k/results.json` a `batch-all-128k/results.json`. Dlouhý pokus v `no-host-128k` byl záměrně přerušen kvůli porovnání CPU vláken; tato příčina je v reportu označena.

### Dokončené ověření a výsledná nabídka

| Profil | Skutečný vstup | První odpověď | Další otázka | Výsledek |
|---|---:|---:|---:|---|
| 128k Q8 | 122 397 tokenů | 1 053,687 s | 1,266 s | Všechny tři údaje správně; dalších 122 429 tokenů převzato z cache |
| 256k Q8 | 24 101 tokenů | 200,516 s | 1,187 s | Všechny tři údaje správně; alokace 262 144 tokenů potvrzena serverem |

Na obou profilech navíc prošla skutečná úloha `obrázek → write_file → read_file`, včetně kontroly přesných hodnot ve výsledném souboru. Reporty `qualified-128k/results.json` a `functional-256k/results.json` mají úspěšný výsledek. Minimální dostupná RAM byla přibližně 11,56 GiB, respektive 9,74 GiB. Hodnoty GPU z reportů zahrnují i jiné procesy a desktop a nejsou měřením samotných vah.

Model `flash_next_q3` je součástí nabídky Marvina 1.8.0. Výchozí požadavek je 256k Q8; plánovač podle aktuálně volné RAM/VRAM vybere 256k, 192k nebo 128k. Menší okno tomuto modelu nepřiděluje. Stávající šest variant a jejich parametry zůstávají oddělené od této nové politiky. Běžné automatické stahování modelů Flash-Next nevybere, dokud jej uživatel nezvolí.

Ve skutečném webovém UI proběhlo přepnutí Qwen Q5 → Flash-Next s automatickou volbou 256k, odpověď nad předchozí historií a nahrání obrázku s navazujícím zápisem/čtením souboru. Při nedostatku paměti před stahováním je požadavek odmítnut; neúspěšná změna vrací předchozí funkční model a skutečně použitá nastavení. Průběh stahování ukazuje bajty i procenta a launcher rozpozná kompletní instalaci obsahující pouze vnořené Flash shardy.

**Meze výsledku:** celé 256k okno nebylo naplněno. 192k je mezilehlý plánovaný profil, nikoliv samostatně změřený dlouhý běh. Výpočty pro 16/24GB karty v `portability-estimates.json` nepředstavují fyzické testy. Například při 2 GiB obsazené VRAM potřebuje vypočtený 16GB/128k profil téměř 56 GiB volné systémové RAM; samotný údaj 64 GB instalované RAM proto nestačí.

Nainstalovaná aplikace v `%LOCALAPPDATA%/QwenHarness` byla aktualizována z 1.6.2 na 1.8.0 pomocí Full instalátoru a offline balíčku. Následně prošlo 50 testů instalované aplikace a skutečné spuštění i ukončení posledního vybraného modelu Ornith. Při aktualizaci zůstalo všech 369 kontrolovaných souborů uživatelských dat byte-identických. Konečné instalované Python zdroje a manuály se shodují s výslednou distribucí.
