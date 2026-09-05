# Marvin 1.6.2 - instalace pro Windows

## Nový počítač

1. Nainstalujte 64bitový Python 3.12 včetně Python Launcheru (`py`) a volby Add Python to PATH. Python je samostatný požadavek a není součástí tohoto balíčku.
2. Nainstalujte aktuální ovladač NVIDIA pro Windows. Vyberte model odpovídající paměti grafické karty. Pro běžné používání není potřeba samostatný CUDA Toolkit ani Node.js.
3. Spusťte `Marvin-Setup-1.6.2.exe`. Vyberte jazyk, cílový adresář a modely odpovídající grafické kartě. Výchozí umístění je `%LOCALAPPDATA%\QwenHarness`.
4. Na novém počítači ponechte zapnuté nastavení prostředí a modelů. Vytvoří Python prostředí a obstará zvolené modely a llama.cpp. Potřebuje internet, pokud nepoužijete odpovídající místní zálohu.
5. Spusťte Marvin z plochy nebo nabídky Start. Vybraný model se načte automaticky; při dalších spuštěních se použije naposledy úspěšně používaný model a profil KV cache.

Pro 32GB grafickou kartu začněte s Qwen Q5 a 8bitovou KV cache. Instalátor nabízí i profily pro menší karty. Na disku ponechte místo pro vybrané modely, prostředí aplikace a vlastní projekty.

## Použití místní zálohy

Samostatný adresář `QwenHarness-Offline-Backup` obsahuje instalátor 1.6.2, všechny místně dostupné modely a projektory, llama.cpp/CUDA a odpovídající zálohu Python balíčků. Přenášejte celý adresář včetně `manifest.json`. Kompletní záloha zabírá přibližně 123 GiB; velikost instalace závisí na obnovených nebo vybraných modelech.

- Spusťte instalátor přímo z adresáře zálohy. Vedle sebe najde `manifest.json` a zálohu si zapamatuje.
- Běžné nastavení nejprve zkouší síť; při nedostupnosti součásti použije zálohu. Záloha neblokuje internet.
- Pro přednostní obnovu místních souborů dokončete instalaci aplikace a v nabídce Start použijte **Marvin > Instalace z offline zálohy**. Vyberte adresář zálohy.
- Python 3.12 a ovladač NVIDIA je stále nutné nainstalovat samostatně. Pro počítač bez internetu si jejich instalátory připravte předem.

## Stávající počítač

Instalujte přes stávající adresář Marvina. Konverzace, projekty, paměti, vlastní skilly a stažené modely zůstanou na místě. Kvůli aktualizaci aplikaci neodinstalovávejte ani nemažte datový adresář. Před aktualizací zavřete Marvin a ukončete běžící úlohy.

## Obsah balíčku

- `Marvin-Setup-1.6.2.exe`: jeden instalátor pro nové instalace i aktualizace.
- `Marvin-Manual-EN.pdf` a `Marvin-Manual-CS.pdf`: kompletní uživatelské manuály.
- `INSTALL-EN.md` a `INSTALL-CS.md`: postup instalace.
- `SHA256SUMS.txt`: kontrolní součty výše uvedených souborů.

Distribuce neobsahuje konverzace, projekty, osobní paměti ani vlastní skilly majitele. Malý distribuční ZIP neobsahuje váhy modelů; ty se stáhnou nebo obnoví ze samostatné zálohy.
