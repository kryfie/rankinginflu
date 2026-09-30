# InfluRank PL — starter repo

Monorepo dla MVP rankingu polskich twórców TikTok.

## W środku
- `apps/web` — obecny frontend Netlify.
- `apps/scanner` — scanner v0.1 publicznych stron TikToka.
- `packages/classifier` — PL Confidence + kategorie v0.1.
- `packages/ranking` — Influence Score v0.1.
- `database` — SQLite na etap eksperymentalny.
- `.github/workflows` — CI i ręczny test scannera.

## Ważne
`TikTokPublicProvider` czyta tylko dane osadzone w publicznie dostępnych stronach WWW. Nie loguje się, nie rozwiązuje CAPTCHA, nie obchodzi 403/429 i nie rotuje tożsamości. Jeśli TikTok ograniczy dostęp, skaner się zatrzymuje. Provider jest celowo wymienny.

## Pierwszy test lokalny
```bash
python -m venv .venv
```
Windows PowerShell:
```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```
Następnie przetestuj 1–3 znane publiczne konta:
```bash
python -m apps.scanner.scanner.cli scan @HANDLE --posts 10
```
Powstaną:
- `apps/scanner/data/influrank.db`
- `apps/web/data/creators.json`

## Discovery z hashtagów
Hashtagi startowe: `apps/scanner/config/hashtags.txt`
```bash
python -m apps.scanner.scanner.cli discover --limit 30 --posts 10
```
Najpierw testuj małą skalę. Publiczny HTML TikToka jest zmienny.

## Frontend
Frontend automatycznie próbuje wczytać `apps/web/data/creators.json`. Jeśli plik jest pusty, pokazuje dane demo. Po realnym skanie przełączy się na realny snapshot.

## Influence Score v0.1
- Reach 30%
- Engagement 25%
- Audience 20%
- Momentum 15%
- Consistency 10%

Na pierwszym dniu Momentum ma neutralne 50/100. Po 30 dniach liczymy growth z własnej historii.

## Netlify
Podłącz całe repo. `netlify.toml` publikuje tylko `apps/web`.

## Najbliższy milestone
1. 3 znane realne konta,
2. sprawdzenie followers / verified / posts / views / likes / comments / shares,
3. discovery 30–100 kont,
4. ręczna ocena PL Confidence,
5. dopiero potem Supabase i codzienny harmonogram.
