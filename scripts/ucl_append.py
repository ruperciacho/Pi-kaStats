"""Dopisuje nowe mecze Ligi Mistrzów do data/ucl_snapshot.csv.

Użycie: python scripts/ucl_append.py nowe.json
nowe.json to lista obiektów:
  {"id": "74165940", "date": "2026-10-20", "home": "<nazwa Sportradar>", "away": "<nazwa Sportradar>",
   "hg": 1, "ag": 0, "home_stats": {...team_stats gospodarzy...}, "away_stats": {...team_stats gości...}}
gdzie *_stats to obiekty team_stats z fetch_sports_data(game_stats) bez zmian.
Mecze już obecne (po id) są pomijane. Nieznane nazwy drużyn trafiają do data/ucl_teams.csv bez zmian.
"""
import csv, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP = os.path.join(ROOT, 'data', 'ucl_snapshot.csv')
TEAMS = os.path.join(ROOT, 'data', 'ucl_teams.csv')
FIELDS = ['date', 'id', 'home', 'away', 'hg', 'ag',
          'h_shots', 'h_sot', 'h_corners', 'h_fouls', 'h_yellow', 'h_red', 'h_off', 'h_poss',
          'a_shots', 'a_sot', 'a_corners', 'a_fouls', 'a_yellow', 'a_red', 'a_off', 'a_poss']


def side(st, p):
    g = lambda k: int(st.get(k) or 0)
    return {p + 'shots': g('shots_total'), p + 'sot': g('shots_on_target'), p + 'corners': g('corner_kicks'),
            p + 'fouls': g('fouls'), p + 'yellow': g('yellow_cards'), p + 'red': g('red_cards') + g('yellow_red_cards'),
            p + 'off': g('offsides'), p + 'poss': g('ball_possession')}


def main(path):
    rows = list(csv.DictReader(open(SNAP, encoding='utf-8')))
    have = {r['id'] for r in rows}
    teams = {r['sportradar']: r['name'] for r in csv.DictReader(open(TEAMS, encoding='utf-8'))}
    new_teams = []
    added = 0
    for m in json.load(open(path, encoding='utf-8')):
        mid = str(m['id']).replace('sr:sport_event:', '')
        if mid in have:
            continue
        for t in (m['home'], m['away']):
            if t not in teams:
                teams[t] = t
                new_teams.append(t)
        r = {'date': m['date'][:10], 'id': mid, 'home': teams[m['home']], 'away': teams[m['away']],
             'hg': int(m['hg']), 'ag': int(m['ag'])}
        r.update(side(m['home_stats'], 'h_'))
        r.update(side(m['away_stats'], 'a_'))
        rows.append(r)
        have.add(mid)
        added += 1
    rows.sort(key=lambda r: (r['date'], int(r['id'])))
    with open(SNAP, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    if new_teams:
        with open(TEAMS, 'a', encoding='utf-8', newline='') as f:
            csv.writer(f).writerows([[t, t] for t in new_teams])
    print(f'Dopisano {added} meczów, razem {len(rows)}. Nowe drużyny: {new_teams or "brak"}')


main(sys.argv[1])
