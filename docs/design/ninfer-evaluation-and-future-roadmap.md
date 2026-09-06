# Průzkum a vyhodnocení: Integrace NInfer do Marvin (Future Roadmap)

**Datum:** 6. 9. 2026

**Cílový model uživatele:** Qwen 3.8 27B ve variantě **Q5** (Q5_K_M) na **NVIDIA GeForce RTX 5090 (32 GB)**.

**Stav:** Zaznamenáno do plánu budoucího vývoje; realizace odložena.

---

## 1. Co je NInfer a jaké nabízí možnosti

**NInfer** (`Neroued/ninfer`) je vysoce specializovaný, od základu napsaný C++/CUDA inferenční engine optimalizovaný primárně pro architekturu NVIDIA Blackwell (`sm_120a`), konkrétně **RTX 5090**.

### Klíčové silné stránky:
* **Extrémní propustnost (tok/s)**: V komunitních měřeních dosahuje 200 až 500+ tokenů za sekundu díky:
  * Nativní akceleraci **NVFP4** (4bitový floating point) na tenzorových jádrech Blackwellu.
  * Spekulativnímu dekódování **MTP** (Multi-Token Prediction).
  * Fúzovaným CUDA kernelům a CUDA Graphs s fixní alokací paměti.
  * Kvantizované KV cache (INT8 nebo proprietární 4bitové formáty).
* **Kompatibilní API**: Poskytuje lokální HTTP server kompatibilní s OpenAI API (`/v1/chat/completions`), což by teoreticky umožnilo napojení stávajícího `LLMClient` v Marvinovi bez změn aplikační logiky.

---

## 2. Proč NInfer v současnosti nemůžeme použít pro stávající modely

### A. Nekompatibilita formátu modelů (GGUF vs. .ninfer)
* **Marvin používá GGUF**: Všechny modely v aplikaci (`runtime/models`, `config.yaml`) jsou standardní GGUF soubory (`Qwen3.8-27B-UD-Q5_K_M.gguf`, `Q4_K_M`, `IQ3_S`, `Ornith...gguf`).
* **NInfer nepodporuje GGUF**: NInfer je uzavřený specializovaný runtime a načítá výhradně vlastní proprietární jedno-souborové balíčky ve formátu **`.ninfer`** (např. z HuggingFace repozitářů `neroued/Qwen3.8-27B-nvfp4-NInfer`).
* **Závěr**: Žádný z našich stažených modelů nelze v NInfer spustit. Bylo by nutné stáhnout zcela nový balíček `.ninfer`.

### B. Absence kvantizace Q5 v NInfer
* **Cíl uživatele je Q5**: Požadavek cílí na vysokou přesnost a stabilitu uvažování modelu **Qwen 3.8 27B Q5**.
* **NInfer je postaven na 4bitech**: NInfer dosahuje své extrémní rychlosti právě využitím hardwarových 4bitových formátů:
  * **NVFP4** (FP4).
  * **groupwise-int** (INT4).
* **Kvalita pro agentní práci**: NInfer **nemá Q5 variantu**. Komunitní zkušenosti navíc ukazují, že ačkoliv je NVFP4 extrémně rychlé, u 4bitové kvantizace se občas objevují nepřesnosti ve strukturovaných výstupech a přísném volání nástrojů (tool calling) oproti vyšší přesnosti Q5_K_M v `llama.cpp`.

### C. Podpora Windows a multimédií
* **Platforma**: Upstream repozitář `Neroued/ninfer` je určen výhradně pro 64bitový Linux. Pro Windows 11 existují komunitní forky (např. `natpate/ninfer-windows`), které jsou však experimentální.
* **Vision projektor (mmproj)**: Marvin aktivně využívá multimediální schopnosti Qwen (analýza PDF, snímky obrazovky, Ctrl+V obrázky ze schránky přes `mmproj-F16.gguf`). V NInferu je podpora vision v raném stádiu.

---

## 3. Závěr a podmínky pro budoucí zařazení

Pro nasazení NInferu zatím nemáme potřebný model ani stabilní oficiální Windows runtime a NInfer nenabízí požadovanou kvantizaci Q5.

### Podmínky pro budoucí přehodnocení (Watchlist):
1. **Dostupnost vyšších přesností v NInfer**: Pokud autoři přidají podporu pro FP8 nebo 5–6bitové formáty zachovávající plnou uvažovací a syntaktickou přesnost Qwen 3.8 27B.
2. **Stabilní Windows runtime**: Oficiální binární distribuce NInfer pro Windows bez nutnosti kompilace experimentálních forků.
3. **Plná parita s vision a tool-calling**: Spolehlivá práce s multimodálními vstupy (obrázky ze schránky a PDF) a bezchybné generování argumentů nástrojů.

Do té doby zůstává primárním a vysoce stabilním inferenčním backendem pro Marvin **llama.cpp / llama-server** s CUDA akcelerací a kvantizací Q5_K_M s Q8_0 KV cache na RTX 5090.
