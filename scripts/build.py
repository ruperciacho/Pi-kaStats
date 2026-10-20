"""Buduje stronę ze statystykami drużyn.

Ligi (top 5): pliki CSV z football-data.co.uk, pobierane przy każdym uruchomieniu.
Puchary: API-Football (Liga Mistrzów, Liga Europy, Liga Konferencji), jeśli jest ustawiony
sekret API_FOOTBALL_KEY. Pobrane mecze trafiają do data/cups_api.json, więc każdy mecz
pobiera się tylko raz. Bez klucza używany jest zapis Ligi Mistrzów z data/ucl_snapshot.csv.

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
import urllib.request
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
SITE = os.path.join(ROOT, 'site')

LEAGUES = [('E0', 'Premier League', 'PL'), ('SP1', 'La Liga', 'LL'), ('I1', 'Serie A', 'SA'),
           ('D1', 'Bundesliga', 'BL'), ('F1', 'Ligue 1', 'L1')]
CUPS = [('UCL', 'Liga Mistrzów', 'LM', 2), ('UEL', 'Liga Europy', 'LE', 3), ('UECL', 'Liga Konferencji', 'LK', 848)]
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
              'RCD', 'CA', 'FK', 'SK', 'NK', 'PFC', 'AFC', 'BK', 'IF', 'KV', 'KRC', 'RSC'}


def log(*a):
    print(*a, file=sys.stderr)


def plain(s):
    return unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()


def key(name):
    """Klucz do dopasowania tej samej drużyny z różnych źródeł."""
    words = [w for w in re.split(r"[\s\-./']+", plain(name).upper()) if w and w not in SKIP_WORDS]
    return ' '.join(words)


def season_codes(today):
    start = today.year if today.month >= 7 else today.year - 1
    return start, f'{start % 100:02d}{(start + 1) % 100:02d}'


def http_get(url, headers=None, tries=3):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (stats report)', **(headers or {})})
    for n in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError) as e:
            log('  błąd pobierania', url, e)
            time.sleep(5 * (n + 1))
    raise RuntimeError('nie udało się pobrać ' + url)


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
    for code, label, _, lid in CUPS:
        try:
            fixtures = api_get(f'/fixtures?league={lid}&season={season}&status=FT-AET-PEN', apikey, budget)
        except RuntimeError as e:
            log('Puchar', label, '- brak danych:', e)
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
    os.makedirs(DATA, exist_ok=True)
    json.dump(cache, open(cache_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=0, sort_keys=True)
    rows = [v for k, v in sc.items() if not k.startswith('_')]
    return rows, ok_codes


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
    apikey = os.environ.get('API_FOOTBALL_KEY', '').strip()
    cup_rows, cup_codes, cup_source = [], set(), ''
    if apikey:
        try:
            cup_rows, cup_codes = load_cups(apikey, season_start)
            cup_source = 'API-Football'
        except Exception as e:  # puchary nie mogą zablokować aktualizacji lig
            log('Puchary z API-Football niedostępne:', e)
    if 'UCL' not in cup_codes:
        snap = load_snapshot(season_start)
        if snap:
            cup_rows = [r for r in cup_rows if r['comp'] != 'UCL'] + snap
            cup_codes.add('UCL')
            cup_source = (cup_source + ', ' if cup_source else '') + 'zapis Ligi Mistrzów z 20.10.2026'

    # Drużyny: najpierw ligowe (wyznaczają grupę), potem pucharowe dopasowane po kluczu
    teams, order, bykey = {}, [], {}

    def team(raw, group, source):
        name = (SNAPSHOT_NAME if source == 'snap' else NAME).get(raw, NAME.get(raw, raw))
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
    matches.sort(key=lambda m: (m[0], m[1]))
    present = {m[1] for m in matches}
    comps = {c: [l, s] for c, l, s in LEAGUES if c in present}
    for c, l, s, _ in CUPS:
        if c in present:
            comps[c] = [l, s]
    cups = [c for c, *_ in CUPS if c in present]
    groups = [[c, l] for c, l, _ in LEAGUES if c in present] + [['OTHER', 'Puchary – pozostałe kluby']]
    missing = [l for c, l, *_ in CUPS if c not in present]
    note = 'Źródła: football-data.co.uk (ligi)' + (f', {cup_source} (puchary)' if cup_source else '') + '. xG tylko tam, gdzie źródło je podaje.'
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
    open(os.path.join(SITE, '.nojekyll'), 'w').write('')
    log(f'Gotowe: {len(order)} drużyn, {len(matches)} meczów, rozgrywki: {", ".join(comps)}')


if __name__ == '__main__':
    main()
