# Statystyki drużyn

Statyczna strona ze statystykami drużyn z top 5 lig (Premier League, La Liga, Serie A, Bundesliga, Ligue 1) i pucharów europejskich: wykres mecz po meczu, ranking i filtry (rozgrywki, statystyka, drużyna/rywale/suma, ostatnie 5/10/sezon, dom/wyjazd).

Wszystko działa za darmo na GitHubie, bez serwera:

- **GitHub Actions** (`.github/workflows/update.yml`) codziennie rano pobiera dane, buduje `site/index.html` i wypycha go na gałąź `gh-pages`.
- **GitHub Pages** serwuje stronę z gałęzi `gh-pages`.
- Przycisk **Odśwież dane** na stronie otwiera tę akcję. Stuknij **Run workflow**, a po 1–2 minutach strona ma nowe dane.

## Źródła

- Ligi: pliki CSV z [football-data.co.uk](https://www.football-data.co.uk/) (strzały, celne, rożne, faule, kartki, xG).
- Puchary: [API-Football](https://www.api-football.com/) (Liga Mistrzów, Liga Europy, Liga Konferencji), jeśli jest klucz. Bez klucza strona używa zapisu fazy ligowej Ligi Mistrzów z 20.10.2026 (`data/ucl_snapshot.csv`).

## Klucz API-Football (opcjonalnie)

1. Załóż darmowe konto na dashboard.api-football.com i skopiuj klucz.
2. W repo: **Settings → Secrets and variables → Actions → New repository secret**, nazwa `API_FOOTBALL_KEY`.
3. Uruchom akcję ręcznie. Darmowy plan to 100 zapytań dziennie, więc pierwsze pobranie wszystkich pucharów może potrwać 2–3 dni. Każdy mecz pobiera się tylko raz i zapisuje w `data/cups_api.json`.

## Lokalnie

```
python scripts/build.py   # wynik: site/index.html
```
