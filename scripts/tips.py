"""Prognozy liczbowe (bramki, strzały, celne, rożne, faule, kartki) dla nadchodzących meczów.

Model: dla każdej statystyki drużyna ma siłę ataku (ile "robi") i obrony (ile "pozwala"),
liczone względem średniej danych rozgrywek i strony (dom/wyjazd), z większą wagą ostatnich
meczów i ściągnięciem do średniej przy małej liczbie meczów. Oczekiwana liczba w meczu:
  gospodarze = średnia_dom(rozgrywki) * atak(gosp.) * obrona(goście)
  goście     = średnia_wyjazd(rozgrywki) * atak(gości) * obrona(gosp.)
Rozkład sumy: rozkład ujemny dwumianowy (rozrzut dopasowany na sezonie 2025/26),
dla bramek Poisson.
"""
import math

# nazwa, indeksy (dom, wyjazd) w wektorze meczu, linie bukmacherskie
STATS = [
    ('goals', 'Bramki', 0, 1, [1.5, 2.5, 3.5, 4.5]),
    ('shots', 'Strzały', 2, 3, [x + 0.5 for x in range(14, 35)]),
    ('sot', 'Celne', 4, 5, [x + 0.5 for x in range(4, 15)]),
    ('corners', 'Rożne', 6, 7, [x + 0.5 for x in range(6, 14)]),
    ('fouls', 'Faule', 8, 9, [x + 0.5 for x in range(15, 33)]),
    ('cards', 'Kartki', 10, 11, [x + 0.5 for x in range(1, 8)]),
]
# wariancja sumy / średnia (dopasowane walk-forward na 2025/26, top 5 lig)
DISPERSION = {'goals': 1.1, 'shots': 1.3, 'sot': 1.2, 'corners': 1.3, 'fouls': 1.15, 'cards': 1.25}
# ile "średnich meczów" dokładamy do każdej drużyny (mniej = bardziej ufamy drużynie);
# dobrane na 2025/26: faule mocno zależą od drużyn, rożne/kartki/bramki słabo
SHRINK_BY = {'goals': 15, 'shots': 10, 'sot': 12, 'corners': 12, 'fouls': 5, 'cards': 12}
HALF_LIFE = 12      # po ilu meczach waga spada o połowę
COMP_PRIOR = 25     # ściąganie średnich rozgrywek do średniej ogólnej
MIN_GAMES = 4       # mniej meczów drużyny = "mało danych"
TARGET_P = 0.65     # minimalna szansa dla proponowanej linii


def _baselines(matches):
    """Średnie per (rozgrywki, strona) dla każdej statystyki, ściągnięte do ogólnej."""
    tot = {s[0]: [0.0, 0.0, 0] for s in STATS}
    per = {}
    for m in matches:
        c, v = m[1], m[4:]
        for key, _, ih, ia, _ in STATS:
            if v[ih] is None or v[ia] is None:
                continue
            t = tot[key]
            t[0] += v[ih]; t[1] += v[ia]; t[2] += 1
            p = per.setdefault((c, key), [0.0, 0.0, 0])
            p[0] += v[ih]; p[1] += v[ia]; p[2] += 1
    out = {}
    for key, *_ in STATS:
        h, a, n = tot[key]
        gh, ga = (h / n, a / n) if n else (1.0, 1.0)
        out[('*', key)] = (gh, ga)
        for (c, k2), (ph, pa, pn) in per.items():
            if k2 == key:
                out[(c, key)] = ((ph + COMP_PRIOR * gh) / (pn + COMP_PRIOR), (pa + COMP_PRIOR * ga) / (pn + COMP_PRIOR))
    return out


def base(bl, comp, key):
    return bl.get((comp, key)) or bl[('*', key)]


def ratings(matches):
    """Siła ataku i obrony drużyn (1.0 = średnio). matches: posortowane rosnąco po dacie."""
    bl = _baselines(matches)
    hist = {}
    for m in matches:
        hist.setdefault(m[2], []).append((m, True))
        hist.setdefault(m[3], []).append((m, False))
    out = {}
    decay = math.log(2) / HALF_LIFE
    for team, games in hist.items():
        r = {'n': len(games)}
        for key, _, ih, ia, _ in STATS:
            fa = fd = wsum = 0.0
            for age, (m, home) in enumerate(reversed(games)):
                v = m[4:]
                if v[ih] is None or v[ia] is None:
                    continue
                bh, ba = base(bl, m[1], key)
                w = math.exp(-decay * age)
                own, opp = (v[ih], v[ia]) if home else (v[ia], v[ih])
                exp_own, exp_opp = (bh, ba) if home else (ba, bh)
                fa += w * (own / exp_own if exp_own else 1.0)
                fd += w * (opp / exp_opp if exp_opp else 1.0)
                wsum += w
            k = SHRINK_BY[key]
            r[key] = ((fa + k) / (wsum + k), (fd + k) / (wsum + k))
        out[team] = r
    return out, bl


def expected(rt, bl, comp, home, away, key):
    bh, ba = base(bl, comp, key)
    ah, dh = rt.get(home, {}).get(key, (1.0, 1.0))
    aa, da = rt.get(away, {}).get(key, (1.0, 1.0))
    return bh * ah * da, ba * aa * dh


def _pmf(mean, disp, kmax):
    """Rozkład P(X=k), k=0..kmax: ujemny dwumianowy (disp>1) albo Poisson."""
    mean = max(mean, 1e-6)
    if disp <= 1.0001:
        p = [math.exp(-mean)]
        for k in range(1, kmax + 1):
            p.append(p[-1] * mean / k)
        return p
    r = mean / (disp - 1.0)
    q = r / (r + mean)
    p = [q ** r]
    for k in range(1, kmax + 1):
        p.append(p[-1] * (k - 1 + r) / k * (1 - q))
    return p


def p_over(mean, disp, line):
    kmax = int(line)
    pmf = _pmf(mean, disp, kmax)
    return max(0.0, min(1.0, 1.0 - sum(pmf)))


def pick(mean, typical, key, lines):
    """Propozycja: strona zgodna z odchyleniem od typowego meczu, najbliższa linia z szansą >= TARGET_P."""
    disp = DISPERSION[key]
    over = mean >= typical
    best = None
    for ln in (sorted(lines, reverse=True) if over else sorted(lines)):
        p = p_over(mean, disp, ln)
        p = p if over else 1 - p
        if p >= TARGET_P:
            best = (('over' if over else 'under'), ln, p)
            break
    return best


def predict(matches, fixtures):
    """fixtures: [(iso_utc, comp, home, away, extra)]. Zwraca listę prognoz."""
    rt, bl = ratings(matches)
    out = []
    for when, comp, home, away, extra in fixtures:
        nh, na = rt.get(home, {}).get('n', 0), rt.get(away, {}).get('n', 0)
        row = {'t': when, 'c': comp, 'h': home, 'a': away, 'nh': nh, 'na': na, 'p': [], 'x': extra}
        for key, label, _, _, lines in STATS:
            eh, ea = expected(rt, bl, comp, home, away, key)
            mean = eh + ea
            if key == 'goals':
                row['g25'] = round(p_over(mean, DISPERSION['goals'], 2.5), 3)
            bh, ba = base(bl, comp, key)
            typical = bh + ba
            pk = pick(mean, typical, key, lines)
            if not pk:
                continue
            side, ln, p = pk
            p0 = p_over(typical, DISPERSION[key], ln)
            p0 = p0 if side == 'over' else 1 - p0
            hh = hit_history(matches, home, key, ln)
            ha = hit_history(matches, away, key, ln)
            if side == 'under':
                hh, ha = (hh[1] - hh[0], hh[1]), (ha[1] - ha[0], ha[1])
            row['p'].append({'k': key, 'm': round(mean, 1), 'eh': round(eh, 1), 'ea': round(ea, 1),
                             's': side, 'l': ln, 'pr': round(p, 3), 'lift': round(p - p0, 3),
                             'hh': list(hh), 'ha': list(ha)})
        out.append(row)
    return out


def hit_history(matches, team, key, line, n=10):
    """Ile z ostatnich n meczów drużyny miało sumę powyżej linii."""
    ih, ia = next((s[2], s[3]) for s in STATS if s[0] == key)
    games = [m for m in matches if team in (m[2], m[3]) and m[4 + ih] is not None][-n:]
    return sum(1 for m in games if m[4 + ih] + m[4 + ia] > line), len(games)


def summary(res):
    if not res:
        return None
    n = len(res)
    return {'n': n, 'pred': round(sum(r[1] for r in res) / n, 3), 'real': round(sum(1 for r in res if r[2]) / n, 3)}


def backtest(matches, min_games=MIN_GAMES):
    """Walk-forward: prognoza każdego meczu tylko z wcześniejszych danych. Zwraca listę (key, p, trafiony, lift)."""
    res = []
    dates = sorted({m[0] for m in matches})
    for d in dates:
        past = [m for m in matches if m[0] < d]
        today = [m for m in matches if m[0] == d]
        if len(past) < 40:
            continue
        rt, bl = ratings(past)
        for m in today:
            if rt.get(m[2], {}).get('n', 0) < min_games or rt.get(m[3], {}).get('n', 0) < min_games:
                continue
            v = m[4:]
            for key, _, ih, ia, lines in STATS:
                if v[ih] is None or v[ia] is None:
                    continue
                eh, ea = expected(rt, bl, m[1], m[2], m[3], key)
                bh, ba = base(bl, m[1], key)
                pk = pick(eh + ea, bh + ba, key, lines)
                if not pk:
                    continue
                side, ln, p = pk
                total = v[ih] + v[ia]
                hit = total > ln if side == 'over' else total < ln
                p0 = p_over(bh + ba, DISPERSION[key], ln)
                p0 = p0 if side == 'over' else 1 - p0
                res.append((key, p, hit, p - p0))
    return res
