"""Regression tests. Run from project root:  PYTHONPATH=model:pipeline python3 -m unittest -v tests/test_forecast.py"""
import json, os, re, shutil, subprocess, sys, unittest
import numpy as np, pandas as pd

sys.path[:0] = ["model", "pipeline"]
import simulate as S
from common import load, statewide
import export as E
import fetch as F
from races import RACES


class HistoricalData(unittest.TestCase):
    """County results must reproduce the official statewide outcomes."""
    @classmethod
    def setUpClass(cls):
        cls.c = load()

    def margin(self, race):
        c = self.c
        return (c[f"{race}_R"].sum() - c[f"{race}_D"].sum()) / c[f"{race}_total"].sum() * 100

    def test_254_counties(self):
        self.assertEqual(len(self.c), 254)
        self.assertEqual(self.c.fips.nunique(), 254)

    def test_official_margins(self):
        for race, official in (("sen18", 2.58), ("sen20", 9.64), ("sen24", 8.50), ("pres24", 13.66), ("gov22", 10.88)):
            self.assertAlmostEqual(self.margin(race), official, delta=0.05, msg=race)

    def test_every_county_has_a_region(self):
        self.assertTrue(self.c.region.notna().all())
        self.assertEqual(set(self.c.region), set(E.REGIONS))

    def test_primary_totals(self):
        self.assertEqual(int(self.c.dem_primary26.sum()), 2319187)
        self.assertEqual(int(self.c.rep_primary26.sum()), 2166910)


class Polls(unittest.TestCase):
    def test_parser_on_saved_pages(self):
        for key, race in RACES.items():
            rows = F.parse_polls(open(f"data/raw/wiki_{key}.txt").read(), race["d"], race["r"])
            self.assertGreaterEqual(len(rows), 40, key)
            for r in rows:
                self.assertTrue(30 <= r["d"] <= 65 and 30 <= r["r"] <= 65, (key, r))

    def test_rowspan_rows_keep_their_own_numbers(self):
        rows = F.parse_polls(open("data/raw/wiki_senate.txt").read(), "Talarico", "Paxton")
        bd = {(r["pop"], r["d"], r["r"]) for r in rows if r["pollster"] == "Big Data Poll"}
        self.assertEqual(bd, {("LV", 47.0, 45.0), ("RV", 46.0, 44.0)})

    def test_columns_follow_the_header(self):
        rows = F.parse_polls(open("data/raw/wiki_governor.txt").read(), "Hinojosa", "Abbott")
        cbs = [r for r in rows if r["pollster"].startswith("CBS News")][0]
        self.assertEqual((cbs["d"], cbs["r"]), (48.0, 52.0))           # Abbott 52, Hinojosa 48

    def test_average_is_sane(self):
        for key in RACES:
            avg, used = S.poll_average(pd.read_csv(f"data/polls_{key}.csv"))
            self.assertTrue(0.44 < avg < 0.56, key)
            self.assertGreaterEqual(len(used), 10)
            self.assertTrue((used.age >= 0).all(), "a poll is dated in the future")
            self.assertTrue((used.age <= 60).all())


class Model(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c, _ = S.build(load())

    def run_sim(self, center, n=20_000, seed=5, **kw):
        S.RNG = np.random.default_rng(seed)
        return S.simulate(self.c, center, n=n, **kw)

    def test_deterministic_with_seed(self):
        a, b = self.run_sim(0.51), self.run_sim(0.51)
        self.assertTrue(np.array_equal(a["state_share"], b["state_share"]))

    def test_centered_on_target(self):
        r = self.run_sim(0.515)
        self.assertAlmostEqual(float(np.median(r["state_share"])), 0.515, delta=0.003)

    def test_tied_race_is_near_coin_flip(self):
        self.assertAlmostEqual(self.run_sim(0.5)["win"].mean(), 0.5, delta=0.03)

    def test_monotonic_in_polls(self):
        p = [self.run_sim(x)["win"].mean() for x in (0.48, 0.50, 0.52)]
        self.assertTrue(p[0] < p[1] < p[2], p)

    def test_county_order_is_plausible(self):
        r = self.run_sim(0.5125)
        p = dict(zip(self.c.county, (r["share"] > 0.5).mean(0)))
        self.assertGreater(p["Travis"], 0.99)
        self.assertLess(p["Montgomery"], 0.01)
        self.assertTrue(0.3 < p["Tarrant"] <= 1.0)

    def test_governor_pattern_uses_governor_races(self):
        c, _ = S.build(load(), bases=RACES["governor"]["bases"])
        c["_rate"] = c.gov22_total / c.reg22
        share, _ = S.replay(c, "gov22_d2", "_rate")
        self.assertAlmostEqual((1 - 2 * share) * 100, 10.9, delta=0.8)   # Abbott +10.9 in 2022
        self.assertFalse(np.allclose(c.rel_blend, self.c.rel_blend))

    def test_replay_2018_matches_history(self):
        self.c["_rate"] = self.c.sen18_total / self.c.reg18
        share, _ = S.replay(self.c, "sen18_d2", "_rate")
        self.assertAlmostEqual((1 - 2 * share) * 100, 2.9, delta=0.6)   # Cruz +2.6 at 2018 turnout


class Backtest(unittest.TestCase):
    """Run as of 2018 and 2024 with only earlier data: actual must land inside the 80% band."""
    def check(self, a, b, rate, reg, poll, actual):
        c = load()
        for x in (a, b):
            c[f"rel_{x}"] = c[f"{x}_d2"] - statewide(c, f"{x}_d2", f"{x}_total")
        c["rel_bt"] = 0.5 * c[f"rel_{a}"] + 0.5 * c[f"rel_{b}"]
        c["primary_adj"] = 0.0
        c["exp_votes"] = c[reg] * c[f"{rate}_total"] / c[f"reg{rate[-2:]}"]
        S.RNG = np.random.default_rng(3)
        r = S.simulate(c, poll, pattern="rel_bt", n=20_000)
        lo, hi = np.percentile(r["state_share"], [10, 90])
        act = statewide(c, f"{actual}_d2", f"{actual}_total")
        self.assertTrue(lo <= act <= hi, (lo, act, hi))
        called = (((r["share"] > .5).mean(0) > .5) == (c[f"{actual}_d2"].values > .5)).sum()
        self.assertGreaterEqual(called, 240)
        return r["win"].mean(), act

    def test_2018(self):
        p, act = self.check("sen14", "pres16", "sen14", "reg18", 0.5 - 0.0588 / 2, "sen18")
        self.assertLess(p, 0.5)            # favored the eventual winner (Cruz)

    def test_2024(self):
        p, act = self.check("sen18", "sen20", "sen20", "reg24", 45.4 / 94.8, "sen24")
        self.assertLess(p, 0.5)


class Nowcast(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c, _ = S.build(load())
        S.RNG = np.random.default_rng(9)
        cls.res = S.simulate(cls.c, 0.512, n=20_000)

    def fake_results(self, sim, frac):
        out = {}
        for j, name in enumerate(self.c.county):
            v = self.res["votes"][sim, j] * frac
            s = self.res["share"][sim, j]
            out[name] = dict(d=int(v * s), r=int(v * (1 - s)), total=int(v),
                             precincts_reporting=int(frac * 100), precincts_total=100)
        return out

    def test_no_votes_means_no_update(self):
        empty = {n: dict(d=0, r=0, total=0, precincts_reporting=0, precincts_total=100) for n in self.c.county}
        self.assertIsNone(E.nowcast(self.c, self.res, empty))

    def test_full_count_converges_to_truth(self):
        for sim in (0, 1, 2, 3):
            truth = self.res["state_share"][sim] > 0.5
            out = E.nowcast(self.c, self.res, self.fake_results(sim, 1.0))
            self.assertEqual(out["p"] > 0.5, truth)
            self.assertTrue(out["p"] > 0.97 or out["p"] < 0.03, out["p"])

    def test_partial_count_moves_toward_truth(self):
        lose = int(np.argmin(self.res["state_share"]))           # Paxton's best simulation
        out = E.nowcast(self.c, self.res, self.fake_results(lose, 0.5))
        self.assertLess(out["p"], self.res["win"].mean())


class EarlyBias(unittest.TestCase):
    """Mail/early ballots are counted first and lean bluer; the correction must fade to 0."""
    def test_full_count_has_no_bias(self):
        self.assertEqual(E.early_bias(1000, 1.0, 300, 300, 1000, 0.15), 0.0)

    def test_mail_only_count_gets_mail_lean(self):
        self.assertAlmostEqual(E.early_bias(200, 0.2, 300, 0, 1000, 0.15), 0.15, places=3)

    def test_fades_as_election_day_votes_arrive(self):
        early = E.early_bias(600, 0.6, 100, 500, 1000, 0.15)
        later = E.early_bias(800, 0.8, 100, 500, 1000, 0.15)
        self.assertGreater(early, later)
        self.assertGreater(later, 0)

    def test_harris_uses_its_own_history(self):
        self.assertAlmostEqual(E.MAIL_SKEW["Harris"], (41.0 - 11.3) / 200, places=3)


class Pollsters(unittest.TestCase):
    def test_sponsor_labels(self):
        house, sponsor = E.pollster_leans(pd.read_csv("data/polls_senate.csv"))
        self.assertEqual(sponsor("InsiderAdvantage (R)"), "Republican")
        self.assertEqual(sponsor("Texas Public Opinion Research (D)"), "Democratic")
        self.assertEqual(sponsor("Fabrizio Ward (R)/ Impact Research (D)"), "Bipartisan")
        self.assertEqual(sponsor("Emerson College"), "Independent")

    def test_house_effects_bounded_and_centered(self):
        house, _ = E.pollster_leans(pd.read_csv("data/polls_senate.csv"))
        v = np.array(list(house.values()))
        self.assertTrue((abs(v) < 6).all())
        self.assertLess(abs(v.mean()), 1.0)


class EarlyVote(unittest.TestCase):
    """Early-vote comparison with 2022, using a synthetic 'day 3' built from 2022's real day 3."""
    @classmethod
    def setUpClass(cls):
        import early_vote as EVm
        cls.EVm = EVm
        cls.c, _ = S.build(load())
        cls.c["exp_share"] = 0.5 + cls.c.rel_blend
        cls.c.loc[cls.c.exp_share < .02, "exp_share"] = .02

    def run_fake(self, factor):
        t22 = self.EVm.load_2022()
        d3 = t22[t22.day == 3].set_index("key")
        key = self.c.county.str.upper().str.replace(r"[^A-Z]", "", regex=True)
        counties = {}
        for name, k, reg26, f in zip(self.c.county, key, self.c.reg26, factor):
            r = d3.loc[k]
            scale = reg26 / r.reg_voters * f
            counties[name] = [int(r.cum_in_person * scale), int(r.cum_by_mail * scale), int(r.today_in_person * scale)]
        path = "data/ev_daily_2026.json"
        saved = open(path).read() if os.path.exists(path) else None
        try:
            json.dump({"10/21/2026": {"final": False, "counties": counties}}, open(path, "w"))
            return self.EVm.analyze(self.c, E.MAIL_SKEW, E.MAIL_SKEW_DEFAULT, E.EV_SKEW)
        finally:
            if saved is not None:
                open(path, "w").write(saved)

    def test_same_pace_as_2022_reads_as_even(self):
        e = self.run_fake(np.ones(len(self.c)))
        self.assertEqual(e["day"], 3)
        self.assertAlmostEqual(e["pace"], 1.0, delta=0.01)
        self.assertAlmostEqual(e["mix_effect_pts"], 0.0, delta=0.2)
        self.assertEqual(e["missing"], [])

    def test_blue_surge_helps_talarico(self):
        f = np.where(self.c.region.isin(["Urban core", "Big suburbs"]), 1.2, 1.0)
        e = self.run_fake(f)
        self.assertGreater(e["mix_effect_pts"], 0.5)
        self.assertGreater(e["mix_effect_votes"], 0)
        self.assertTrue(any("better for Talarico" in x for x in e["story"]))

    def test_rural_surge_helps_paxton(self):
        f = np.where(self.c.region.isin(["Rural", "Outer suburbs"]), 1.25, 1.0)
        e = self.run_fake(f)
        self.assertLess(e["mix_effect_pts"], -0.5)

    def test_unreported_county_is_flagged_not_counted(self):
        f = np.where(self.c.county == "Bexar", 0.0, 1.0)
        e = self.run_fake(f)
        self.assertIn("Bexar", e["missing"])
        self.assertAlmostEqual(e["pace"], 1.0, delta=0.01)

    def test_partial_day_is_compared_fairly(self):
        # Harris has not posted today: its total is through yesterday, so compare with 2022 through day 2
        t22 = self.EVm.load_2022()
        d2 = t22[t22.day == 2].set_index("key")
        f = np.ones(len(self.c))
        e = self.run_fake(f)
        h = e["counties"]["Harris"]
        self.assertTrue(h["reported_today"])
        path = "data/ev_daily_2026.json"
        saved = open(path).read()
        try:
            fake = json.loads(json.dumps({"10/21/2026": {"final": False, "counties": {}}}))
            r = d2.loc["HARRIS"]; scale = self.c.set_index("county").reg26["Harris"] / r.reg_voters
            base = self.run_fake(f)
            counties = {n: [v["in_person"], v["mail"], v["today"]] for n, v in base["counties"].items()}
            counties["Harris"] = [int(r.cum_in_person * scale), int(r.cum_by_mail * scale), 0]
            fake["10/21/2026"]["counties"] = counties
            json.dump(fake, open(path, "w"))
            e2 = self.EVm.analyze(self.c, E.MAIL_SKEW, E.MAIL_SKEW_DEFAULT, E.EV_SKEW)
        finally:
            open(path, "w").write(saved)
        h2 = e2["counties"]["Harris"]
        self.assertFalse(h2["reported_today"])
        self.assertAlmostEqual(h2["pace"], 1.0, delta=0.02)          # through yesterday vs 2022 through day 2
        self.assertEqual(e2["today"]["counties"], e["today"]["counties"] - 1)

    def test_today_matches_2022_at_same_pace(self):
        e = self.run_fake(np.ones(len(self.c)))
        self.assertAlmostEqual(e["today"]["vs22"], 1.0, delta=0.02)

    def test_2018_comparison_covers_30_largest(self):
        e = self.run_fake(np.ones(len(self.c)))
        self.assertEqual(e["n_top"], 30)
        self.assertIsNotNone(e["counties"]["Harris"]["pace18"])
        self.assertIsNone(e["counties"]["Loving"]["pace18"])
        self.assertEqual(len(e["series_top"]["y2018"]), 12)

    def test_projection_near_2022_at_same_pace(self):
        e = self.run_fake(np.ones(len(self.c)))
        # same pace as 2022 -> 2022's final turnout grown by registration (about 17.7M -> 19.0M voters)
        growth = self.c.reg26.sum() / self.EVm.load_2022().query("day == 12").reg_voters.sum()
        self.assertAlmostEqual(e["projected_turnout"] / e["final_2022_votes"], growth, delta=0.03)


class SiteData(unittest.TestCase):
    race = "senate"

    @classmethod
    def setUpClass(cls):
        cls.d = json.load(open(f"site/data_{cls.race}.json"))
        cls.paths = json.load(open("data/tx_paths.json"))

    def test_schema(self):
        for k in ("race", "cand", "generated", "mode", "needle", "forecast", "polls", "markets", "counties", "early", "scenarios", "poll_history", "others"):
            self.assertIn(k, self.d)
        self.assertIn(self.d["mode"], ("pre", "early", "live", "final"))
        self.assertEqual(len(self.d["counties"]), 254)

    def test_probabilities_valid(self):
        for x in [self.d["needle"]["p"], self.d["forecast"]["p"]] + [c["p"] for c in self.d["counties"]]:
            self.assertTrue(0 <= x <= 1)

    def test_every_county_on_map(self):
        self.assertEqual({c["fips"] for c in self.d["counties"]}, set(self.paths["counties"]))

    def test_markets_present(self):
        self.assertEqual({m["source"] for m in self.d["markets"]}, {"Kalshi", "Polymarket"})
        for m in self.d["markets"]:
            self.assertTrue(0 < m["d"] < 1)

    def test_names_match_race(self):
        self.assertEqual(self.d["cand"]["d"], RACES[self.race]["d"])
        self.assertEqual(self.d["race"], self.race)

    def test_lines_are_ordered(self):
        for c in self.d["counties"]:
            L = c.get("lines")
            if L and None not in L.values():
                self.assertLessEqual(L["r"], L["even"]); self.assertLessEqual(L["even"], L["d"])

    def test_turnout_names_match(self):
        if os.path.exists("data/turnout.json"):
            names = {c["name"] for c in self.d["counties"]}
            self.assertEqual(set(json.load(open("data/turnout.json"))["counties"]), names)

    def test_early_vote_total_matches_feed(self):
        if self.d.get("early_vote"):
            feed = json.load(open("data/turnout.json"))["counties"]
            self.assertEqual(self.d["early_vote"]["total"], sum(v["in_person"] + v["mail"] for v in feed.values()))


    def test_poll_history_newest_first(self):
        years = [r["year"] for r in self.d["poll_history"]]
        self.assertEqual(years, sorted(years, reverse=True))
        self.assertGreaterEqual(len(years), 2)

    def test_scenarios_name_real_counties(self):
        names = {c["name"] for c in self.d["counties"]}
        for sc in self.d["scenarios"]:
            ex = sc["uniform_examples"] + [e for g in sc["regions"] for e in g["examples"]]
            self.assertTrue(ex)
            for e in ex:
                self.assertIn(e["name"], names)
                moved = abs(e["after"] - e["before"])
                self.assertTrue(moved > 0)
            # the uniform shift moves every example by the same number of points
            self.assertTrue(all(abs(abs(e["after"] - e["before"]) - sc["uniform_pts"]) < 0.11 for e in sc["uniform_examples"]))


class SiteDataGovernor(SiteData):
    race = "governor"


class BuiltPage(unittest.TestCase):
    page, title = "index.html", "Texas Senate Forecast"

    @classmethod
    def setUpClass(cls):
        cls.html = open(f"build/{cls.page}").read()

    def test_placeholders_replaced(self):
        self.assertNotIn("/*__DATA__*/", self.html)
        self.assertNotIn("/*__PATHS__*/", self.html)

    def test_title_first(self):
        self.assertTrue(self.html.startswith(f"<title>{self.title}</title>"))

    def test_no_unfilled_placeholders(self):
        self.assertIsNone(re.search(r"__[A-Z_]+__", self.html))

    def test_light_only(self):
        self.assertNotIn("prefers-color-scheme: dark", self.html)
        self.assertNotIn('data-theme="dark"', self.html)

    def test_share_buttons(self):
        for host in ("twitter.com/intent/tweet", "facebook.com/sharer", "linkedin.com/sharing", "reddit.com/submit", "wa.me"):
            self.assertIn(host, self.html)

    def test_only_allowed_external_hosts(self):
        hosts = set(re.findall(r'(?:src|href)="https://([^/"]+)', self.html))
        allowed = {"fonts.googleapis.com", "fonts.gstatic.com"}
        self.assertTrue(hosts <= allowed, hosts - allowed)

    def test_script_parses(self):
        if not shutil.which("node"):
            self.skipTest("node not installed")
        js = self.html[self.html.rindex("<script>") + 8:self.html.rindex("</script>")]
        path = os.path.join(os.environ.get("TMPDIR", "/tmp"), "tx_page_check.js")
        open(path, "w").write(js)
        r = subprocess.run(["node", "--check", path], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


class Template(unittest.TestCase):
    """The template must stay race-neutral: names come from races.py, fields are d/r."""
    def test_no_hard_coded_candidates_or_old_fields(self):
        t = open("site/template.html").read()
        for bad in ("Talarico", "Paxton", "Hinojosa", "Abbott", ".talarico", ".paxton", "m24", "m18"):
            self.assertNotIn(bad, t, bad)


class Sanity(unittest.TestCase):
    """Bad-data guard between runs."""
    @classmethod
    def setUpClass(cls):
        import sanity
        cls.S = sanity
        cls.base = sanity.snapshot()

    def mutate(self, **changes):
        import copy
        cur = copy.deepcopy(self.base)
        for k, v in changes.items():
            cur["senate"][k] = v
        return cur

    def test_identical_run_passes(self):
        self.assertEqual(self.S.check(self.base, self.base), [])

    def test_first_run_has_nothing_to_compare(self):
        self.assertEqual(self.S.check(None, self.base), [])

    def test_poll_average_jump_blocks(self):
        cur = self.mutate(poll_avg=self.base["senate"]["poll_avg"] + 4)
        self.assertTrue(any("poll average" in p for p in self.S.check(self.base, cur)))

    def test_poll_count_collapse_blocks(self):
        cur = self.mutate(n_polls=int(self.base["senate"]["n_polls"] * 0.5))
        self.assertTrue(any("poll count" in p for p in self.S.check(self.base, cur)))

    def test_early_vote_drop_blocks(self):
        prev = self.mutate(early_total=100_000)
        cur = self.mutate(early_total=90_000)
        self.assertTrue(any("early-vote" in p for p in self.S.check(prev, cur)))

    def test_county_count_shrinking_blocks(self):
        prev = self.mutate(counted={"Harris": 500_000}, mode="live")
        cur = self.mutate(counted={"Harris": 400_000}, mode="live")
        self.assertTrue(any("Harris" in p for p in self.S.check(prev, cur)))

    def test_dead_market_blocks(self):
        cur = self.mutate(markets={"Kalshi": 0.0, "Polymarket": 0.6})
        self.assertTrue(any("Kalshi" in p for p in self.S.check(self.base, cur)))

    def test_needle_jump_without_votes_blocks(self):
        cur = self.mutate(needle=self.base["senate"]["needle"] - 0.3)
        self.assertTrue(any("win chance" in p for p in self.S.check(self.base, cur)))


class LiveCounties(unittest.TestCase):
    """County live-turnout parsers, checked against saved copies of the county pages (Oct. 19, 2026)."""
    @classmethod
    def setUpClass(cls):
        import fetch_live
        cls.F = fetch_live

    def test_electionlink_summary(self):
        r = self.F.parse_summary(open("tests/fixtures/electionlink_summary.html").read())
        self.assertEqual(r["ballots"], 10924)
        self.assertIn("Oct 19", r["refreshed"])

    def test_electionlink_hourly(self):
        h = self.F.parse_hourly(open("tests/fixtures/electionlink_hourly.html").read())
        self.assertEqual(len(h["10/19/2026"]), 13)
        self.assertEqual(h["10/19/2026"][:4], [2220, 2421, 3101, 3182])

    def test_bexar_dashboard(self):
        b = self.F.parse_bexar(open("tests/fixtures/bexar_dashboard.html").read())
        self.assertEqual(b["date"], "10/16/2026")
        self.assertGreaterEqual(b["sites"], 50)

    def test_dallas_vote_centers(self):
        f = json.load(open("tests/fixtures/dallas_vote_centers.json"))["features"]
        d = self.F.parse_dallas(f, 1792437124142)
        self.assertEqual(d["today"], 44378)
        self.assertGreater(d["sites"], 50)
        self.assertTrue(d["refreshed"].startswith("Mon Oct 19"))

    def test_archives_cover_the_comparison_days(self):
        for slug in ("travistx", "montgomerytx"):
            for yr in (2022, 2024):
                a = json.load(open(f"data/raw/live_archive_{slug}_{yr}.json"))
                self.assertIn(self.F.same_day(yr, 1), a)
        self.assertEqual(sum(json.load(open("data/raw/live_archive_travistx_2022.json"))["10/24/2022"]), 25337)


class BuiltGovernorPage(BuiltPage):
    page, title = "governor.html", "Texas Governor Forecast"

    def test_uses_governor_names(self):
        self.assertIn("Hinojosa", self.html); self.assertIn('"race":"governor"', self.html)


class BuiltEarlyPage(BuiltPage):
    page, title = "early.html", "Texas Early Vote Tracker"


class PublicSite(unittest.TestCase):
    """The GitHub Pages version: full documents, social preview tags, preview images."""
    page, card = "index.html", "share_senate.png"

    @classmethod
    def setUpClass(cls):
        cls.html = open(f"public/{cls.page}").read()

    def test_full_document(self):
        self.assertTrue(self.html.startswith("<!doctype html>"))
        self.assertEqual(self.html.count("<title>"), 1)
        self.assertIn('content="only light"', self.html.replace("color-scheme:only light", 'content="only light"'))

    def test_social_tags(self):
        for tag in ('property="og:title"', 'property="og:description"', 'property="og:image"', 'name="twitter:card"'):
            self.assertIn(tag, self.html)
        self.assertNotIn("claude.ai", self.html)

    def test_share_image(self):
        from PIL import Image
        self.assertEqual(Image.open(f"public/{self.card}").size, (1200, 630))
        self.assertIn(self.card, self.html)


class PublicGovernor(PublicSite):
    page, card = "governor.html", "share_governor.png"


class PublicEarly(PublicSite):
    page, card = "early.html", "share_early.png"


if __name__ == "__main__":
    unittest.main()
