"""Buduje stronę ze statystykami drużyn.

Ligi (top 5): pliki CSV z football-data.co.uk, pobierane przy każdym uruchomieniu.
Puchary (Liga Mistrzów, Liga Europy, Liga Konferencji): publiczne dane meczowe ESPN
(nieoficjalne API, bez klucza). Pobrane mecze trafiają do data/cups_espn.json, więc każdy
mecz pobiera się tylko raz, a stan ostatniego pobrania jest w polu "_status".
Rezerwa: API-Football (sekret API_FOOTBALL_KEY) dla pucharów, których ESPN nie dało,
a dla Ligi Mistrzów zapis z data/ucl_snapshot.csv.

Wynik: site/index.html (statyczna strona, bez serwera).
"""
import csv
import io
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import urllib.request
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
SITE = os.path.join(ROOT, 'site')

LEAGUES = [('E0', 'Premier League', 'PL'), ('SP1', 'La Liga', 'LL'), ('I1', 'Serie A', 'SA'),
           ('D1', 'Bundesliga', 'BL'), ('F1', 'Ligue 1', 'L1')]
CUPS = [('UCL', 'Liga Mistrzów', 'LM', 2), ('UEL', 'Liga Europy', 'LE', 3), ('UECL', 'Liga Konferencji', 'LK', 848)]
# test modelu prognoz na sezonie 2025/26 (top 5 lig, walk-forward, scripts/tips.py)
# (sumy w meczu + zdarzenia drużynowe razem)
PREV_CALIB = {'safe': {'n': 28062, 'pred': 0.722, 'real': 0.726},
              'risky': {'n': 25400, 'pred': 0.500, 'real': 0.506}}
ESPN_SLUG = {'UCL': 'uefa.champions', 'UEL': 'uefa.europa', 'UECL': 'uefa.europa.conf'}
ESPN = 'https://site.api.espn.com/apis/site/v2/sports/soccer/'
API = 'https://v3.football.api-sports.io'
API_BUDGET = 90          # zapytań na jedno uruchomienie (darmowy plan: 100 dziennie)
API_PAUSE = 7            # sekundy między zapytaniami (limit na minutę)

# Nazwy z football-data.co.uk i API-Football -> nazwy wyświetlane
NAME = {
    'Real Madrid': 'Real Madryt', 'Ath Madrid': 'Atlético Madryt', 'Atletico Madrid': 'Atlético Madryt',
    'Ath Bilbao': 'Athletic Bilbao', 'Athletic Club': 'Athletic Bilbao', 'Barcelona': 'FC Barcelona',
    'Betis': 'Real Betis', 'Sociedad': 'Real Sociedad', 'Celta': 'Celta Vigo', 'Vallecano': 'Rayo Vallecano',
    'Espanol': 'Espanyol', 'Alaves': 'Alavés', 'Malaga': 'Málaga', 'La Coruna': 'Deportivo La Coruña',
    'Santander': 'Racing Santander', 'Leganes': 'Leganés', 'Almeria': 'Almería',
    'Man City': 'Manchester City', 'Man United': 'Manchester United', "Nott'm Forest": 'Nottingham Forest',
    'Newcastle': 'Newcastle United', 'Wolves': 'Wolverhampton', 'Tottenham': 'Tottenham Hotspur',
    'West Ham': 'West Ham United', 'Leeds': 'Leeds United', 'Hull': 'Hull City', 'Ipswich': 'Ipswich Town',
    'Coventry': 'Coventry City',
    'Bayern Munich': 'Bayern Monachium', 'Bayern München': 'Bayern Monachium', 'Dortmund': 'Borussia Dortmund',
    'RB Leipzig': 'RB Lipsk', 'Leverkusen': 'Bayer Leverkusen', "M'gladbach": "Borussia M'gladbach",
    'Borussia Mönchengladbach': "Borussia M'gladbach", 'Ein Frankfurt': 'Eintracht Frankfurt',
    'FC Koln': '1. FC Köln', '1. FC Köln': '1. FC Köln', 'Stuttgart': 'VfB Stuttgart', 'Wolfsburg': 'VfL Wolfsburg',
    'Mainz': 'Mainz 05', 'FSV Mainz 05': 'Mainz 05', 'Hamburg': 'Hamburger SV', 'Werder Bremen': 'Werder Brema',
    'St Pauli': 'St. Pauli', 'FC St. Pauli': 'St. Pauli', 'Elversberg': 'SV Elversberg', 'Paderborn': 'SC Paderborn',
    'SC Freiburg': 'Freiburg', '1899 Hoffenheim': 'Hoffenheim', 'FC Augsburg': 'Augsburg', 'FC Union Berlin': 'Union Berlin',
    'Roma': 'AS Roma', 'Milan': 'AC Milan', 'Inter Milan': 'Inter', 'Verona': 'Hellas Verona',
    'Paris SG': 'Paris Saint-Germain', 'Paris Saint Germain': 'Paris Saint-Germain', 'Lens': 'RC Lens',
    'Marseille': 'Olympique Marsylia', 'Lyon': 'Olympique Lyon', 'Olympique Lyonnais': 'Olympique Lyon',
    'St Etienne': 'Saint-Étienne', 'Nice': 'OGC Nice', 'Stade Brestois 29': 'Brest', 'Stade Rennais': 'Rennes',
    'Le Havre AC': 'Le Havre',
    # nazwy ESPN
    'Internazionale': 'Inter', 'Brighton & Hove Albion': 'Brighton', 'Wolverhampton Wanderers': 'Wolverhampton',
    'Olympique de Marseille': 'Olympique Marsylia', 'Stade Brestois': 'Brest', 'RC Strasbourg Alsace': 'Strasbourg',
    'LOSC Lille': 'Lille', 'Lille OSC': 'Lille', 'AS Monaco': 'Monaco', 'TSG Hoffenheim': 'Hoffenheim',
    '1. FSV Mainz 05': 'Mainz 05', 'Mainz 05': 'Mainz 05', 'AFC Bournemouth': 'Bournemouth', 'Leeds United': 'Leeds United',
    'SC Paderborn 07': 'SC Paderborn', 'FC Schalke 04': 'Schalke 04', 'Hamburg SV': 'Hamburger SV',
    'Deportivo Alavés': 'Alavés', 'Celta de Vigo': 'Celta Vigo', 'RCD Espanyol': 'Espanyol', 'Real Oviedo': 'Oviedo',
}
SNAPSHOT_NAME = {'Real Madrid': 'Real Madryt'}
ABBR = {
    'Manchester City': 'MCI', 'Manchester United': 'MUN', 'Real Madryt': 'RMA', 'Real Betis': 'BET',
    'Real Sociedad': 'RSO', 'Atlético Madryt': 'ATM', 'Athletic Bilbao': 'ATH', 'Borussia Dortmund': 'BVB',
    "Borussia M'gladbach": 'BMG', 'Bayern Monachium': 'BAY', 'Bayer Leverkusen': 'B04', 'Paris Saint-Germain': 'PSG',
    'Paris FC': 'PFC', 'AS Roma': 'ROM', 'AC Milan': 'MIL', 'Inter': 'INT', 'RB Lipsk': 'RBL', 'RC Lens': 'LEN',
    'Olympique Marsylia': 'OM', 'Olympique Lyon': 'OL', 'Aston Villa': 'AVL', 'Nottingham Forest': 'NFO',
    'Newcastle United': 'NEW', 'West Ham United': 'WHU', 'Tottenham Hotspur': 'TOT', 'Crystal Palace': 'CRY',
    'Celta Vigo': 'CEL', 'Rayo Vallecano': 'RAY', 'Racing Santander': 'RAC', 'Deportivo La Coruña': 'DEP',
    'Eintracht Frankfurt': 'SGE', '1. FC Köln': 'KOE', 'VfB Stuttgart': 'VFB', 'VfL Wolfsburg': 'WOB',
    'Hamburger SV': 'HSV', 'Union Berlin': 'FCU', 'Hellas Verona': 'VER', 'FC Barcelona': 'BAR',
}
SKIP_WORDS = {'FC', 'AS', 'AC', 'RC', 'SC', 'CF', 'SV', 'VFB', 'VFL', 'OGC', 'TSG', '1', 'SSC', 'US', 'CD', 'UD',
              'RCD', 'CA', 'FK', 'SK', 'NK', 'PFC', 'AFC', 'BK', 'IF', 'KV', 'KRC', 'RSC', 'FSV'}


def log(*a):
    print(*a, file=sys.stderr)


def plain(s):
    return unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()


def _key(name):
    words = [w for w in re.split(r"[\s\-./']+", plain(name).upper()) if w and w not in SKIP_WORDS]
    return ' '.join(words)


def key(name):
    """Klucz do dopasowania tej samej drużyny z różnych źródeł."""
    words = [w for w in re.split(r"[\s\-./']+", plain(name).upper()) if w and w not in SKIP_WORDS]
    return ' '.join(words)


def season_codes(today):
    start = today.year if today.month >= 7 else today.year - 1
    return start, f'{start % 100:02d}{(start + 1) % 100:02d}'


def http_get(url, headers=None, tries=3):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (stats report)', **(headers or {})})
    last = None
    for n in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = f'HTTP {e.code}'
            log('  błąd pobierania', url, last)
            if 400 <= e.code < 500 and e.code != 429:
                break
            time.sleep(5 * (n + 1))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = repr(e)[:150]
            log('  błąd pobierania', url, last)
            time.sleep(5 * (n + 1))
    raise RuntimeError(f'nie udało się pobrać {url} ({last})')


def probe(urls):
    """Diagnostyka: kod odpowiedzi i początek treści dla kilku adresów."""
    out = {}
    for u in urls:
        try:
            raw = http_get(u, tries=1)
            out[u] = f'OK {len(raw)} B: ' + raw[:120].decode('utf-8', 'replace')
        except Exception as e:
            out[u] = str(e)[-80:]
    return out


def decode(raw):
    for enc in ('utf-8-sig', 'cp1252', 'latin-1'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue


def num(v):
    v = (v or '').strip()
    return int(float(v)) if v else None


def fnum(v):
    v = (str(v) if v is not None else '').strip().rstrip('%')
    try:
        return round(float(v), 2) if v else None
    except ValueError:
        return None


def load_leagues(code_season):
    out = []
    for code, label, _ in LEAGUES:
        url = f'https://www.football-data.co.uk/mmz4281/{code_season}/{code}.csv'
        try:
            text = decode(http_get(url))
        except RuntimeError as e:
            log('POMIJAM ligę', label, e)
            continue
        n = 0
        for r in csv.DictReader(io.StringIO(text)):
            if not (r.get('HomeTeam') or '').strip() or num(r.get('FTHG')) is None:
                continue
            d = r['Date'].strip()
            date = datetime.strptime(d, '%d/%m/%Y' if len(d.split('/')[-1]) == 4 else '%d/%m/%y').strftime('%Y-%m-%d')
            vals = [num(r.get(k)) for k in ('FTHG', 'FTAG', 'HS', 'AS', 'HST', 'AST', 'HC', 'AC', 'HF', 'AF')]
            if any(v is None for v in vals):
                continue
            hy, ay, hr, ar = (num(r.get(k)) or 0 for k in ('HY', 'AY', 'HR', 'AR'))
            out.append({'date': date, 'comp': code, 'home': r['HomeTeam'].strip(), 'away': r['AwayTeam'].strip(),
                        'v': vals + [hy + hr, ay + ar, fnum(r.get('HxG')), fnum(r.get('AxG'))]})
            n += 1
        log(f'{label}: {n} meczów')
    return out


def api_get(path, apikey, budget):
    if budget[0] <= 0:
        raise RuntimeError('wyczerpany limit zapytań na to uruchomienie')
    budget[0] -= 1
    raw = http_get(API + path, {'x-apisports-key': apikey})
    time.sleep(API_PAUSE)
    js = json.loads(raw)
    errs = js.get('errors')
    if errs and (isinstance(errs, dict) and errs or isinstance(errs, list) and errs):
        raise RuntimeError(f'API-Football: {errs}')
    return js.get('response') or []


def stat_map(team_block):
    m = {}
    for s in team_block.get('statistics') or []:
        m[(s.get('type') or '').strip().lower()] = s.get('value')
    g = lambda *names: next((m[n] for n in names if n in m), None)
    shots, sot, corners, fouls = g('total shots'), g('shots on goal'), g('corner kicks'), g('fouls')
    yellow, red, xg = g('yellow cards'), g('red cards'), g('expected_goals', 'expected goals')
    if shots is None and sot is None:
        return None
    iv = lambda v: int(v) if isinstance(v, (int, float)) else int(str(v)) if str(v).isdigit() else 0
    return [iv(shots), iv(sot), iv(corners), iv(fouls), iv(yellow) + iv(red), fnum(xg)]


def load_cups(apikey, season):
    """Zwraca (mecze, użyte kody pucharów). Pobiera tylko mecze, których nie ma w pamięci podręcznej."""
    cache_path = os.path.join(DATA, 'cups_api.json')
    cache = json.load(open(cache_path, encoding='utf-8')) if os.path.exists(cache_path) else {}
    cache.setdefault(str(season), {})
    sc = cache[str(season)]
    budget = [API_BUDGET]
    ok_codes = set(code for code in sc.get('_ok', []))
    errors = {}
    for code, label, _, lid in CUPS:
        try:
            fixtures = api_get(f'/fixtures?league={lid}&season={season}&status=FT-AET-PEN', apikey, budget)
        except Exception as e:
            log('Puchar', label, '- brak danych:', e)
            errors[code] = str(e)[:300]
            continue
        ok_codes.add(code)
        todo = []
        for f in fixtures:
            rnd = (f.get('league') or {}).get('round') or ''
            if re.search(r'Qualifying|Preliminary|^Play-offs?$', rnd):
                continue
            fid = str(f['fixture']['id'])
            if fid not in sc:
                todo.append(f)
        log(f'{label}: {len(fixtures)} meczów zakończonych, do pobrania statystyk: {len(todo)}')
        for f in sorted(todo, key=lambda f: f['fixture']['date']):
            fid = str(f['fixture']['id'])
            try:
                stats = api_get(f'/fixtures/statistics?fixture={fid}', apikey, budget)
            except RuntimeError as e:
                log('  przerywam pobieranie statystyk:', e)
                break
            hid, aid = f['teams']['home']['id'], f['teams']['away']['id']
            byid = {b['team']['id']: stat_map(b) for b in stats if b.get('team')}
            h, a = byid.get(hid), byid.get(aid)
            if not h or not a:
                continue   # statystyki jeszcze niedostępne, spróbujemy następnym razem
            sc[fid] = {'date': f['fixture']['date'][:10], 'comp': code,
                       'home': f['teams']['home']['name'], 'away': f['teams']['away']['name'],
                       'v': [f['goals']['home'], f['goals']['away'], h[0], a[0], h[1], a[1], h[2], a[2], h[3], a[3],
                             h[4], a[4], h[5], a[5]]}
    sc['_ok'] = sorted(ok_codes)
    sc['_errors'] = errors   # ostatnie błędy API (do diagnozy)
    os.makedirs(DATA, exist_ok=True)
    json.dump(cache, open(cache_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=0, sort_keys=True)
    rows = [v for k, v in sc.items() if not k.startswith('_')]
    return rows, ok_codes


def _int(v):
    try:
        return int(float(str(v).strip().rstrip('%')))
    except (TypeError, ValueError):
        return None


def load_espn(season_start, codes):
    """Puchary z ESPN. Zwraca (mecze, kody pucharów z danymi)."""
    from datetime import date
    cache_path = os.path.join(DATA, 'cups_espn.json')
    cache = json.load(open(cache_path, encoding='utf-8')) if os.path.exists(cache_path) else {}
    sc = cache.setdefault(str(season_start), {})
    status = {}
    start = date(season_start, 9, 1)                      # eliminacje kończą się w sierpniu
    end = min(datetime.now(timezone.utc).date(), date(season_start + 1, 6, 30))
    for code in codes:
        base = ESPN + ESPN_SLUG[code]
        st = {'znalezione': 0, 'zakonczone': 0, 'nowe': 0, 'bez_statystyk': 0, 'dni_sprawdzone': 0}
        days_done = set(sc.setdefault('_dni', {}).get(code, []))
        events, day_of, d, errors = [], {}, start, 0
        while d <= end:   # ESPN przyjmuje tylko pojedyncze daty
            ds = f'{d:%Y%m%d}'
            d += timedelta(days=1)
            if ds in days_done:
                continue
            try:
                js = json.loads(http_get(f'{base}/scoreboard?dates={ds}', tries=2))
            except Exception as e:
                errors += 1
                st['blad'] = 'scoreboard: ' + str(e)[:200]
                continue
            st['dni_sprawdzone'] += 1
            for ev in js.get('events') or []:
                events.append(ev)
                day_of[str(ev.get('id'))] = ds
            day_of.setdefault('_' + ds, ds)
            time.sleep(0.15)
        if errors and not events:
            status[code] = st
            log(code, 'ESPN niedostępne:', st.get('blad'))
            continue
        seen = set()
        for ev in events:
            eid = str(ev.get('id'))
            if eid in seen:
                continue
            seen.add(eid)
            st['znalezione'] += 1
            comp = (ev.get('competitions') or [{}])[0]
            stype = ((comp.get('status') or ev.get('status') or {}).get('type') or {})
            if not (stype.get('completed') or stype.get('state') == 'post'):
                continue
            st['zakonczone'] += 1
            if eid in sc:
                continue
            cs = comp.get('competitors') or []
            home = next((c for c in cs if c.get('homeAway') == 'home'), None)
            away = next((c for c in cs if c.get('homeAway') == 'away'), None)
            if not home or not away:
                continue
            tid = lambda c: str((c.get('team') or {}).get('id') or c.get('id'))
            stats = {}
            try:
                summ = json.loads(http_get(f'{base}/summary?event={eid}'))
                for t in (summ.get('boxscore') or {}).get('teams') or []:
                    stats[str((t.get('team') or {}).get('id'))] = {s.get('name'): s.get('displayValue', s.get('value'))
                                                                   for s in t.get('statistics') or []}
                if '_nazwy_statystyk' not in status and stats:
                    status['_nazwy_statystyk'] = sorted(next(iter(stats.values())).keys())
            except Exception as e:
                st['blad_summary'] = str(e)[:200]
            time.sleep(0.3)
            # zapas: statystyki z samego scoreboardu
            for c in (home, away):
                if not stats.get(tid(c)) and c.get('statistics'):
                    stats[tid(c)] = {s.get('name'): s.get('displayValue') for s in c['statistics']}
            h, a = stats.get(tid(home)), stats.get(tid(away))
            if not h or not a or _int(h.get('totalShots')) is None or _int(a.get('totalShots')) is None:
                st['bez_statystyk'] += 1
                continue
            cards = {tid(home): 0, tid(away): 0}
            have_cards = all(x.get('yellowCards') is not None for x in (h, a))
            if not have_cards:   # kartki z listy zdarzeń meczu
                for det in comp.get('details') or []:
                    t = str((det.get('team') or {}).get('id'))
                    if t in cards and (det.get('yellowCard') or det.get('redCard')):
                        cards[t] += 1
            def side(x, t):
                g = lambda n: _int(x.get(n)) or 0
                cr = g('yellowCards') + g('redCards') if have_cards else cards[t]
                return [g('totalShots'), g('shotsOnTarget'), g('wonCorners'), g('foulsCommitted'), cr]
            hv, av = side(h, tid(home)), side(a, tid(away))
            sc[eid] = {'date': (ev.get('date') or comp.get('date') or '')[:10], 'comp': code,
                       'home': (home.get('team') or {}).get('displayName', '?'),
                       'away': (away.get('team') or {}).get('displayName', '?'),
                       'v': [_int(home.get('score')) or 0, _int(away.get('score')) or 0,
                             hv[0], av[0], hv[1], av[1], hv[2], av[2], hv[3], av[3], hv[4], av[4], None, None]}
            st['nowe'] += 1
        # dzień uznajemy za zamknięty, gdy minęły 2 dni i wszystkie jego mecze są zapisane
        pending = {day_of[str(ev.get('id'))] for ev in events if str(ev.get('id')) not in sc}
        cutoff = f'{end - timedelta(days=2):%Y%m%d}'
        checked = {v for k, v in day_of.items()}
        days_done |= {ds for ds in checked if ds <= cutoff and ds not in pending}
        sc['_dni'][code] = sorted(days_done)
        status[code] = st
        log(code, 'ESPN:', st)
    if all(c in status and 'blad' in status[c] for c in codes):
        status['_probe'] = probe([
            ESPN + 'uefa.europa/scoreboard',
            ESPN + 'uefa.europa/scoreboard?dates=20261022',
        ])
    sc['_status'] = status
    sc['_aktualizacja'] = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    os.makedirs(DATA, exist_ok=True)
    json.dump(cache, open(cache_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=0, sort_keys=True)
    rows = [v for k, v in sc.items() if not k.startswith('_')]
    return rows, {r['comp'] for r in rows}


ESPN_LEAGUE = {'E0': 'eng.1', 'SP1': 'esp.1', 'I1': 'ita.1', 'D1': 'ger.1', 'F1': 'fra.1'}


def load_fixtures(now, horizon=3):
    """Nadchodzące mecze z dziś i `horizon` kolejnych dni (czas polski):
    ligi z football-data.co.uk/fixtures.csv (z kursami) i z ESPN, puchary z ESPN."""
    try:
        from zoneinfo import ZoneInfo
        uk, pl = ZoneInfo('Europe/London'), ZoneInfo('Europe/Warsaw')
    except Exception:
        uk = pl = timezone.utc
    start_pl = now.astimezone(pl).replace(hour=0, minute=0, second=0, microsecond=0)
    lo, hi = now - timedelta(hours=2), (start_pl + timedelta(days=horizon + 1)).astimezone(timezone.utc)
    out, seen = [], set()

    def add(when, comp, home, away, extra):
        k = (when[:10], comp, home, away)
        if k not in seen:
            seen.add(k)
            out.append((when, comp, home, away, extra))

    league_codes = {c for c, _, _ in LEAGUES}
    try:
        text = decode(http_get('https://www.football-data.co.uk/fixtures.csv'))
        for r in csv.DictReader(io.StringIO(text)):
            div = (r.get('Div') or '').strip()
            if div not in league_codes or not (r.get('HomeTeam') or '').strip():
                continue
            d = r['Date'].strip()
            fmt = '%d/%m/%Y' if len(d.split('/')[-1]) == 4 else '%d/%m/%y'
            t = (r.get('Time') or '').strip() or '15:00'
            dt = datetime.strptime(f'{d} {t}', fmt + ' %H:%M').replace(tzinfo=uk).astimezone(timezone.utc)
            if not lo <= dt <= hi:
                continue
            add(dt.strftime('%Y-%m-%dT%H:%M:00Z'), div, r['HomeTeam'].strip(), r['AwayTeam'].strip(),
                {'o25': fnum(r.get('Avg>2.5')), 'u25': fnum(r.get('Avg<2.5'))})
    except Exception as e:
        log('Terminarz lig z football-data niedostępny:', e)
    slugs = {**ESPN_SLUG, **ESPN_LEAGUE}   # ligi z ESPN uzupełniają terminarz football-data na cały tydzień
    for code, slug in slugs.items():
        for i in range(horizon + 1):
            day = (now + timedelta(days=i)).date()
            try:
                js = json.loads(http_get(f'{ESPN}{slug}/scoreboard?dates={day:%Y%m%d}', tries=2))
            except Exception as e:
                log('Terminarz ESPN', code, day, e)
                continue
            for ev in js.get('events') or []:
                comp = (ev.get('competitions') or [{}])[0]
                stype = ((comp.get('status') or ev.get('status') or {}).get('type') or {})
                if stype.get('state') not in (None, 'pre'):
                    continue
                cs = comp.get('competitors') or []
                home = next((c for c in cs if c.get('homeAway') == 'home'), None)
                away = next((c for c in cs if c.get('homeAway') == 'away'), None)
                when = ev.get('date') or comp.get('date') or ''
                if not home or not away or not when:
                    continue
                try:
                    dt = datetime.fromisoformat(when.replace('Z', '+00:00'))
                except ValueError:
                    continue
                if not lo <= dt <= hi:
                    continue
                add(dt.strftime('%Y-%m-%dT%H:%M:00Z'), code, (home.get('team') or {}).get('displayName', ''),
                    (away.get('team') or {}).get('displayName', ''), {})
            time.sleep(0.15)
    log(f'Terminarz: {len(out)} meczów (dziś + {horizon} dni)')
    return out


def load_snapshot(season_start):
    p = os.path.join(DATA, 'ucl_snapshot.csv')
    if not os.path.exists(p):
        return []
    out = []
    for r in csv.DictReader(open(p, encoding='utf-8')):
        if r['date'] < f'{season_start}-07-01' or r['date'] > f'{season_start + 1}-06-30':
            continue
        g = lambda k: int(r[k])
        out.append({'date': r['date'], 'comp': 'UCL', 'home': r['home'], 'away': r['away'], 'snap': True,
                    'v': [g('hg'), g('ag'), g('h_shots'), g('a_shots'), g('h_sot'), g('a_sot'), g('h_corners'),
                          g('a_corners'), g('h_fouls'), g('a_fouls'), g('h_yellow') + g('h_red'),
                          g('a_yellow') + g('a_red'), None, None]})
    return out


def main():
    now = datetime.now(timezone.utc)
    season_start, code_season = season_codes(now)
    league_rows = load_leagues(code_season)
    all_cups = [c for c, *_ in CUPS]
    cup_rows, src = [], {}
    try:
        rows, ok = load_espn(season_start, all_cups)
        cup_rows += rows
        src.update({c: 'ESPN' for c in ok})
    except Exception as e:  # puchary nie mogą zablokować aktualizacji lig
        log('Puchary z ESPN niedostępne:', e)
    apikey = os.environ.get('API_FOOTBALL_KEY', '').strip()
    if apikey and any(c not in src for c in all_cups):
        try:
            rows, ok = load_cups(apikey, season_start)
            rows = [r for r in rows if r['comp'] not in src]
            cup_rows += rows
            src.update({r['comp']: 'API-Football' for r in rows})
        except Exception as e:
            log('Puchary z API-Football niedostępne:', e)
    if 'UCL' not in src:
        snap = load_snapshot(season_start)
        if snap:
            cup_rows += snap
            src['UCL'] = 'Sportradar'
    by_src = {}
    for c, label, *_ in CUPS:
        if c in src:
            by_src.setdefault(src[c], []).append(label)
    cup_source = ', '.join(f'{s} ({", ".join(ls)})' for s, ls in by_src.items())

    # Drużyny: najpierw ligowe (wyznaczają grupę), potem pucharowe dopasowane po kluczu
    teams, order, bykey = {}, [], {}
    NAMEK = {_key(k): v for k, v in NAME.items()}

    def team(raw, group, source):
        name = (SNAPSHOT_NAME if source == 'snap' else NAME).get(raw) or NAME.get(raw) or NAMEK.get(_key(raw)) or raw
        k = key(name)
        if k in bykey:
            name = bykey[k]
        elif key(raw) in bykey:
            name = bykey[key(raw)]
        if name not in teams:
            teams[name] = group
            order.append(name)
            bykey[key(name)] = name
            bykey.setdefault(key(raw), name)
        return name

    matches = []
    for r in league_rows:
        matches.append([r['date'], r['comp'], team(r['home'], r['comp'], 'fd'), team(r['away'], r['comp'], 'fd')] + r['v'])
    for r in cup_rows:
        src = 'snap' if r.get('snap') else 'api'
        matches.append([r['date'], r['comp'], team(r['home'], 'OTHER', src), team(r['away'], 'OTHER', src)] + r['v'])

    # Prognozy na nadchodzące mecze
    def resolve(raw):
        name = NAME.get(raw) or NAMEK.get(_key(raw)) or raw
        for k in (key(name), key(raw)):
            if k in bykey:
                return bykey[k]
        return None

    tips_data = None
    try:
        import tips as TP
        hist = sorted(matches, key=lambda m: m[0])
        fx, fx_at = [], {}
        for when, comp, h, a, extra in load_fixtures(now):
            rh, ra = resolve(h), resolve(a)
            if not (rh and ra):
                log('Terminarz: nie rozpoznano drużyny', comp, h, '-', a)
                continue
            k = (comp, rh, ra)
            if k in fx_at:            # ten sam mecz z dwóch źródeł: zostaw wersję z kursami
                if extra and not fx[fx_at[k]][4]:
                    fx[fx_at[k]] = (fx[fx_at[k]][0], comp, rh, ra, extra)
                continue
            fx_at[k] = len(fx)
            fx.append((when, comp, rh, ra, extra))
        preds = TP.predict(hist, fx)
        bt = lambda r: TP.summary(TP.backtest(hist, risky=r) + TP.backtest(hist, risky=r, scope='team'))
        calib = {'safe': {'season': bt(False), 'prev': PREV_CALIB['safe']},
                 'risky': {'season': bt(True), 'prev': PREV_CALIB['risky']}}
        tips_data = {'fx': preds, 'calib': calib,
                     'min_games': TP.MIN_GAMES, 'labels': {k: l for k, l, *_ in TP.STATS}}
    except Exception as e:  # prognozy nie mogą zablokować strony
        import traceback
        log('Prognozy niedostępne:', e)
        traceback.print_exc()

    used, abbr = set(), {}
    for n in order:
        a = ABBR.get(n)
        if not a or a in used:
            words = [w for w in re.split(r"[\s\-./']+", plain(n)) if w and w.upper() not in SKIP_WORDS]
            base = (max(words, key=len) if words else plain(n)).upper()
            a, i = base[:3], 3
            while a in used and i < len(base):
                a, i = base[:2] + base[i], i + 1
        used.add(a)
        abbr[n] = a

    idx = {n: i for i, n in enumerate(order)}
    for m in matches:
        m[2], m[3] = idx[m[2]], idx[m[3]]
    if tips_data:
        for f in tips_data['fx']:
            f['h'], f['a'] = idx[f['h']], idx[f['a']]
    matches.sort(key=lambda m: (m[0], m[1]))
    present = {m[1] for m in matches}
    comps = {c: [l, s] for c, l, s in LEAGUES if c in present}
    for c, l, s, _ in CUPS:
        if c in present:
            comps[c] = [l, s]
    cups = [c for c, *_ in CUPS if c in present]
    groups = [[c, l] for c, l, _ in LEAGUES if c in present] + [['OTHER', 'Puchary – pozostałe kluby']]
    missing = [l for c, l, *_ in CUPS if c not in present]
    note = 'Źródła: football-data.co.uk (ligi)' + (f', {cup_source}' if cup_source else '') + '. xG tylko dla lig.'
    if missing:
        note += ' Brak danych: ' + ', '.join(missing) + '.'
    data = {'teams': [[n, abbr[n], teams[n]] for n in order], 'matches': matches, 'comps': comps, 'cups': cups,
            'groups': groups, 'note': note}

    tpl = open(os.path.join(ROOT, 'scripts', 'template.html'), encoding='utf-8').read()
    try:
        from zoneinfo import ZoneInfo
        local = now.astimezone(ZoneInfo('Europe/Warsaw'))
    except Exception:
        local = now.astimezone(timezone(timedelta(hours=1)))
    body = tpl.replace('__DATA__', json.dumps(data, ensure_ascii=False, separators=(',', ':'))) \
              .replace('__ASOF__', local.strftime('%d.%m.%Y, %H:%M'))
    head, rest = body.split('<main', 1)
    html = ('<!doctype html>\n<html lang="pl">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            + head + '</head>\n<body>\n<main' + rest + '\n</body>\n</html>\n')
    os.makedirs(SITE, exist_ok=True)
    open(os.path.join(SITE, 'index.html'), 'w', encoding='utf-8').write(html)

    # Osobna strona z typami (typy.html), ze wspólnym wyglądem
    style = re.search(r'<style>(.*?)</style>', tpl, re.S).group(1)
    links = ''.join(l + '\n' for l in re.findall(r'<link [^>]+>', tpl))
    tdata = {'teams': [[n, abbr[n]] for n in order], 'comps': comps, 'cups': cups, 'tips': tips_data}
    tbody = open(os.path.join(ROOT, 'scripts', 'tips_template.html'), encoding='utf-8').read() \
        .replace('__HEAD__', links).replace('__STYLE__', style) \
        .replace('__DATA__', json.dumps(tdata, ensure_ascii=False, separators=(',', ':'))) \
        .replace('__ASOF__', local.strftime('%d.%m.%Y, %H:%M'))
    thead, trest = tbody.split('<main', 1)
    open(os.path.join(SITE, 'typy.html'), 'w', encoding='utf-8').write(
        '<!doctype html>\n<html lang="pl">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        + thead + '</head>\n<body>\n<main' + trest + '\n</body>\n</html>\n')
    open(os.path.join(SITE, '.nojekyll'), 'w').write('')
    log(f'Gotowe: {len(order)} drużyn, {len(matches)} meczów, rozgrywki: {", ".join(comps)}')


if __name__ == '__main__':
    main()
