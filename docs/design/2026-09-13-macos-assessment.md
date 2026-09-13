# Marvin na macOS: technické posouzení

13. 9. 2026, zdrojový stav 1.8.0. Toto je posouzení rozsahu, nikoliv zahájení implementace nebo potvrzení kompatibility modelů na Macu.

## Jeden produkt se dvěma platformními vrstvami

React/TypeScript UI, FastAPI, ApplicationService, jedna sekvenční agentní smyčka, historie, projekty, komprese kontextu a většina dokumentových nástrojů mohou zůstat společné. Není důvod vytvářet dlouhodobě oddělený fork produktu.

Současný kód ale není připravený pouze na překompilování. Launcher používá Win32 a WebView2; správa procesů na více místech předává Windows creation flags; otevírání souborů používá `os.startfile`; detekce GPU stojí na `nvidia-smi`; runtime a privátní Python se hledají podle Windows adresářů a přípon. Tyto části je potřeba oddělit od aplikační logiky.

## Runtime a modely

První port bych založil na llama.cpp ARM64 + Metal. Zachová se HTTP rozhraní, chat templates a formát GGUF. Modelové soubory se tedy nemusí měnit jen kvůli změně systému. Každá architektura, kvantizace, vision projektor a KV typ však potřebuje vlastní ověření na Metal. Podpora CUDA sama o sobě kompatibilitu s Metal nedokazuje. [llama.cpp Metal](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md#metal-build).

MLX by bylo možné zkoumat jako další backend, ale pro první port není nezbytné zavádět jiné serverové API a další modelový formát.

## Paměť a výkon

Apple Silicon má paměť sdílenou CPU a GPU. Dnešních 64 GB systémové RAM plus 32 GB VRAM nelze zaměnit za Mac s 64 GB sjednocené paměti. Mac potřebuje jeden rozpočet pro váhy, KV, pracovní buffery a systém, včetně limitů GPU a paměťového tlaku. [Apple: unified memory](https://developer.apple.com/documentation/metal/mtldevice/hasunifiedmemory).

Znovu se musí určit vhodné modely a kvantizace, KV okna, batch sizes, CPU vlákna, režim načítání a cache. Windows volby Flash-Next `load-mode none`, `no-host` a P-core masky se nesmějí převzít bez měření. Naměřených 27 tok/s a čas dlouhého prefillu na RTX 5090 nejsou odhadem rychlosti na Macu.

## Desktop a distribuce

pywebview má macOS variantu přes Cocoa/WebKit, takže hlavní React UI může zůstat stejné. Potřebovali bychom vlastní ARM64 Python a lock závislostí, macOS launcher, `.app` balíček a samostatné sestavení/distribuci. Modely a proměnlivá data patří mimo podepsaný aplikační balíček, například do Application Support. [pywebview](https://pywebview.flowrl.com/guide/installation.html#macos), [Apple: podpis a notarizace](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution?language=objc).

Pro režim Počítač je třeba upravit snímání obrazovky, ovládání oken, klávesy a oprávnění. macOS řídí přístup k ovládání počítače přes Accessibility a ke snímání obrazovky samostatně. [Accessibility](https://support.apple.com/guide/mac-help/allow-accessibility-apps-to-access-your-mac-mh43185/mac), [screen recording](https://support.apple.com/en-euro/guide/mac-help/mchld6aa7d23/mac).

Datové formáty historie a projektů mohou zůstat společné; absolutní cesty a platformní části offline zálohy vyžadují přenosové úpravy. Windows Python/DLL záloha není macOS instalační balíček.

## Doporučený postup

1. Oddělit platformní operace a sestavovací manifesty; zachovat regresní testy Windows.
2. Na skutečném Apple Silicon Macu ověřit jeden existující model, chat, tools, vision, STOP a dlouhý kontext.
3. Připravit paměťové profily a desktopový balíček.
4. Ověřit režim Počítač a celý výběr podporovaných modelů.

Hlavním dlouhodobým nákladem je druhá kvalifikační a distribuční matice. Přesný rozsah ani termín nelze spolehlivě určit bez prvního běhu na konkrétním Macu a stanovení minimální podporované paměti.
