"""Regression tests. Run from project root:  PYTHONPATH=model:pipeline python3 -m unittest -v tests/test_forecast.py"""
import json, os, re, shutil, subprocess, sys, unittest
from datetime import datetime
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
        # synthetic data only: ignore today's real county reports and live counts
        cls._real = (EVm.load_reports, EVm.load_live, EVm.load_floor, EVm.load_published, EVm.load_live_days)
        EVm.load_reports, EVm.load_live, EVm.load_floor = (lambda: {}), (lambda: None), (lambda: {})
        EVm.load_published = lambda: dict(in_person={}, mail={}, through={})
        EVm.load_live_days = lambda: {}

    @classmethod
    def tearDownClass(cls):
        (cls.EVm.load_reports, cls.EVm.load_live, cls.EVm.load_floor, cls.EVm.load_published,
         cls.EVm.load_live_days) = cls._real

    def day_counts(self, day, factor):
        """2022's real day-`day` county numbers, scaled to 2026 registration (times factor)."""
        t22 = self.EVm.load_2022()
        dd = t22[t22.day == day].set_index("key")
        key = self.c.county.str.upper().str.replace(r"[^A-Z]", "", regex=True)
        out = {}
        for name, k, reg26, f in zip(self.c.county, key, self.c.reg26, factor):
            r = dd.loc[k]
            scale = reg26 / r.reg_voters * f
            out[name] = [int(r.cum_in_person * scale), int(r.cum_by_mail * scale), int(r.today_in_person * scale)]
        return out

    def analyze_with(self, day3, factor=None, day2=None):
        """Synthetic state files like the real ones: one per day (Oct. 19-21), days 1-2 from 2022, day 3 given."""
        factor = np.ones(len(self.c)) if factor is None else factor
        daily = {"10/19/2026": {"final": False, "counties": self.day_counts(1, factor)},
                 "10/20/2026": {"final": False, "counties": day2 or self.day_counts(2, factor)},
                 "10/21/2026": {"final": False, "counties": day3}}
        path = "data/ev_daily_2026.json"
        saved = open(path).read() if os.path.exists(path) else None
        try:
            json.dump(daily, open(path, "w"))
            return self.EVm.analyze(self.c, E.MAIL_SKEW, E.MAIL_SKEW_DEFAULT, E.EV_SKEW)
        finally:
            if saved is not None:
                open(path, "w").write(saved)

    def run_fake(self, factor):
        return self.analyze_with(self.day_counts(3, factor), factor)

    def run_edited(self, edit):
        """Synthetic day 3 at exactly 2022's pace, with some counties' day-3 numbers edited: edit(counties) in place."""
        counties = self.day_counts(3, np.ones(len(self.c)))
        edit(counties)
        return self.analyze_with(counties)

    def test_mail_not_loaded_compares_in_person_only(self):
        # Parker, Johnson, Lubbock on day 2: in-person votes in, mail 0. Keep the county, compare like with like.
        def edit(cs):
            for n in ("Parker", "Lubbock"):
                cs[n][1] = 0
        e = self.run_edited(edit)
        for n in ("Parker", "Lubbock"):
            x = e["counties"][n]
            self.assertFalse(x["missing"], n)
            self.assertTrue(x["mail_missing"], n)
            self.assertAlmostEqual(x["pace"], 1.0, delta=0.03)

    def test_token_same_day_count_is_not_a_report(self):
        # Johnson had 28 votes "today" by evening: compare through yesterday, not with a full 2022 day
        def edit(cs):
            in_, mail, today = cs["Johnson"]
            cs["Johnson"] = [in_ - today + 28, mail, 28]
        x = self.run_edited(edit)["counties"]["Johnson"]
        self.assertFalse(x["reported_today"])
        self.assertAlmostEqual(x["pace"], 1.0, delta=0.05)

    def test_county_far_below_state_norm_is_flagged(self):
        # a big county running far below every other county (a partial upload) is shown as not posted
        f = np.ones(len(self.c))
        f[list(self.c.county).index("Fort Bend")] = 0.45
        self.assertTrue(self.run_fake(f)["counties"]["Fort Bend"]["missing"])

    def test_late_upload_counts_through_its_file_day(self):
        # Fort Bend's Oct. 21 file jumped from day 1 to days 1-3 at once, with "1" voted "on the date": it runs
        # through day 3, not day 1
        one = np.ones(len(self.c))
        d1 = self.day_counts(1, one)["Fort Bend"]
        day2 = self.day_counts(2, one); day3 = self.day_counts(3, one)
        day2["Fort Bend"] = [d1[0], d1[1], 0]
        day3["Fort Bend"] = [day3["Fort Bend"][0], day3["Fort Bend"][1], 1]
        x = self.analyze_with(day3, one, day2)["counties"]["Fort Bend"]
        self.assertEqual(x["through_day"], 3)
        self.assertAlmostEqual(x["pace"], 1.0, delta=0.05)

    def test_state_glitch_holds_county_at_published_numbers(self):
        # Oct. 22: the state's file reset Webb from 4,921 in person + 241 mail to 1 + 0. Keep what we published,
        # don't block the site, and name the county.
        def edit(cs):
            cs["Webb"] = [1, 0, 0]
        real = self.EVm.load_published
        self.EVm.load_published = lambda: dict(in_person={"Webb": 4921}, mail={"Webb": 241}, through={"Webb": 1})
        try:
            x = self.run_edited(edit)["counties"]["Webb"]
        finally:
            self.EVm.load_published = real
        self.assertEqual(x["in_person"], 4921)
        self.assertIn("published", x["held"])

    def test_live_day_survives_tracker_reset(self):
        # Oct. 22: Dallas's tracker reset for day 4 before the state posted day 3. Day 3's saved live count must
        # still be counted: state through day 2 + saved day 3 + today's live count.
        one = np.ones(len(self.c))
        d2 = self.day_counts(2, one)
        day3 = self.day_counts(3, one)
        day3["Dallas"] = [d2["Dallas"][0], d2["Dallas"][1], 0]          # state hasn't posted Dallas's day 3
        live = {"date": "2026-10-22", "fetched": "2026-10-22T19:00:00+00:00",
                "counties": {"Dallas": {"today": 20000, "refreshed": "Thu Oct 22 1:00 PM"}}}
        real = (self.EVm.load_live, self.EVm.load_live_days)
        self.EVm.load_live = lambda: live
        self.EVm.load_live_days = lambda: {"Dallas": {"2026-10-21": 55560, "2026-10-22": 20000}}
        try:
            x = self.analyze_with(day3, one)["counties"]["Dallas"]
        finally:
            self.EVm.load_live, self.EVm.load_live_days = real
        self.assertEqual(x["in_person"], d2["Dallas"][0] + 55560 + 20000)
        self.assertEqual(x["through_day"], 4)

    def test_totals_never_drop_below_published(self):
        # a partial state file must not pull a county below what we already published, and the comparison day
        # follows the day that published total runs through
        f = np.ones(len(self.c))
        base = self.run_fake(f)["counties"]["Travis"]
        real = self.EVm.load_floor
        self.EVm.load_floor = lambda: {"Travis": {"in_person": base["in_person"] + 50000, "through_day": 3}}
        try:
            t = self.run_fake(f)["counties"]["Travis"]
        finally:
            self.EVm.load_floor = real
        self.assertGreaterEqual(t["in_person"], base["in_person"] + 50000)
        self.assertEqual(t["through_day"], 3)

    def test_lagging_county_compared_through_its_own_last_day(self):
        # Oct. 21 (day 3): Comal had only day 1 in the state's file. Compare with 2022's day 1, not day 3.
        one = np.ones(len(self.c))
        d1 = self.day_counts(1, one)["Comal"]
        day2, day3 = self.day_counts(2, one), self.day_counts(3, one)
        day2["Comal"] = [d1[0], d1[1], 0]; day3["Comal"] = [d1[0], d1[1], 0]
        x = self.analyze_with(day3, one, day2)["counties"]["Comal"]
        self.assertEqual(x["through_day"], 1)
        self.assertAlmostEqual(x["pace"], 1.0, delta=0.05)

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
        e = self.run_fake(np.ones(len(self.c)))
        self.assertTrue(e["counties"]["Harris"]["reported_today"])
        def edit(cs):
            in2, mail2, _ = self.day_counts(2, np.ones(len(self.c)))["Harris"]
            cs["Harris"] = [in2, mail2, 0]
        e2 = self.run_edited(edit)
        h2 = e2["counties"]["Harris"]
        self.assertFalse(h2["reported_today"])
        self.assertEqual(h2["through_day"], 2)
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
    def test_no_mail_only_early_vote_fields(self):
        # every early-vote number on the page must come from DATA.early (state + live), never the old mail-only field
        t = open("site/template.html").read()
        self.assertNotIn("c.ev)", t); self.assertNotIn("c.ev_index", t)

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

    def test_county_drop_warns_but_does_not_block(self):
        # one county's bad numbers must never stop the whole site (Oct. 22: Webb and Dallas blocked it 15 hours)
        import copy
        prev = copy.deepcopy(self.base); cur = copy.deepcopy(self.base)
        prev["senate"].update(early_in_person={"Travis": 64878, "Dallas": 100000}, early_mail={"Webb": 241})
        cur["senate"].update(early_in_person={"Travis": 46844, "Dallas": 100500}, early_mail={"Webb": 0})
        warnings = []
        probs = self.S.check(prev, cur, warnings)
        self.assertFalse(any("Travis" in p or "Webb" in p for p in probs), probs)
        self.assertTrue(any("Travis" in w for w in warnings) and any("Webb" in w for w in warnings), warnings)

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

    def test_live_today_only_key_counties_with_numbers(self):
        from races import KEY_COUNTIES
        L = json.load(open("site/data_senate.json"))["live_turnout"]
        names = {n for g in KEY_COUNTIES.values() for n in g}
        self.assertEqual(len(names), 18)
        for r in L["rows"]:
            self.assertIn(r["name"], names)
            self.assertGreater(r["in_person"], 0)                  # no rows before a county has in-person votes
            self.assertIn(r["name"], KEY_COUNTIES[r["group"]])
            self.assertEqual(set(r["base"]), {"2024", "2022", "2018"})
            self.assertEqual(r["ev"], r["in_person"] + r["mail"])   # cumulative = in person + mail

    def test_primary_turnout_is_consistent(self):
        p = json.load(open("site/data_senate.json"))["early"].get("primary")
        if not p:
            return
        t = p["turnout"]
        for k in ("dem", "rep"):
            self.assertLessEqual(t[f"{k}_voted"], t[f"{k}_base"])
            self.assertAlmostEqual(t[k], t[f"{k}_voted"] / t[f"{k}_base"])
        raw = json.dumps(json.load(open("data/primary_layer.json")))
        self.assertNotRegex(raw, r"\b\d{10}\b")                     # no voter IDs saved, totals only

    def test_denton_collin_comal_parsers(self):
        import county_reports as R
        den = ("NOVEMBER 3, 2026 GENERAL ELECTION\nVOTING BY PERSONAL APPEARANCE\n10/19 10/20 Total\n"
               "Daily Totals / Election Total 34740 31563 66303\nEarly\nArgyle Town Hall 586 498 1084\n")
        self.assertEqual(R.parse_denton_inperson(den), (66303, "10/20/2026", 31563))
        with self.assertRaises(ValueError):
            R.parse_denton_inperson(den.replace("66303", "66304"))
        mail = "10/07 10/08 10/20 Total\n Denton County 394 399 1 794\nState Rep.\n"
        self.assertEqual(R.parse_denton_mail(mail), 794)
        col = ("Check-in Summary by Polling Place Within Date Range\nCheck-in Date Range: 10/19/2026 through 10/21/2026\n"
               "EV036, The Grove at Frisco Commons EV036\n1,446\nEV038, Wylie Community Park Center EV038\n1,724\n"
               "Total\n3,170\nReport Date: 10/21/2026 12:20:01\n")
        self.assertEqual(R.parse_collin(col), (3170, "10/21/2026"))
        with self.assertRaises(ValueError):
            R.parse_collin(col.replace("3,170", "3,171"))           # sites must add up to the total
        self.assertEqual(R.count_voter_ids("1 SMITH, A 1012345678 101\n2 DOE, B 2098765432 205\n3 DOE, B 2098765432\n"), 2)

    def test_failed_county_source_keeps_last_good_report(self):
        import county_reports as R
        prev = {"Denton": dict(in_person=66303, mail=3725, through="10/20/2026", last_day=31563), "__fetched": "t0"}
        out = R.keep_last_good({"Denton": dict(error="curl exit 22")}, prev)
        self.assertEqual(out["Denton"]["in_person"], 66303)
        self.assertTrue(out["Denton"]["stale"])
        self.assertIn("error", out["Denton"])                         # still reported to the lag check

    def test_lag_check(self):
        from datetime import datetime
        import lag_check
        L = {"day": 3, "sources": [
            dict(name="Dallas", shown=True, through_day=3, source="live"),
            dict(name="Smith", shown=True, through_day=1, source="state"),
            dict(name="El Paso", shown=False, through_day=None, source="state", note="incomplete"),
            dict(name="Rural Texas", shown=True, through_day=None, source="state")]}
        noon = lag_check.behind(L, datetime(2026, 10, 21, 13, 0))
        self.assertEqual([x.split(":")[0] for x in noon], ["Smith", "El Paso"])
        self.assertEqual(lag_check.behind(L, datetime(2026, 10, 21, 9, 0)), [])   # mornings: normal overnight lag

    def test_county_by_day_adds_up(self):
        # each county's days add up to its latest totals, and only counts are stored
        days = json.load(open("data/primary_days.json"))
        last = days[max(days, key=lambda d: datetime.strptime(d, "%m/%d/%Y"))]
        B = json.load(open("site/data_senate.json"))["early"]["primary"]["by_day"]
        self.assertEqual(len(B["days"]), len(days))
        for name, rows in B["counties"].items():
            for j in range(3):
                self.assertGreaterEqual(sum(r[j] for r in rows), last[name][j], name)   # >= because drops clamp to 0
        self.assertNotRegex(open("data/primary_days.json").read(), r"\b\d{10}\b")

    def test_harris_report_parser(self):
        from county_reports import parse_harris
        txt = ("Monday Tuesday Wednesday\n19-Oct 20-Oct 21-Oct 22-Oct\n7am-7pm 7am-7pm\n"
               "1 Acres Homes MultiService Center SRD139 1,542 1,387 0000000000 2,929\n"
               "104,659 99,911 0000000000 204,570\n24,794 2,755 0000000000 27,549\n"
               "129,453 102,666 0000000000 232,119\n56,457 1,289 0000000000 57,746\n")
        self.assertEqual(parse_harris(txt), (204570, 27549, "10/20/2026", 99911))
        with self.assertRaises(ValueError):                         # rows that don't add up must not pass
            parse_harris(txt.replace("204,570", "204,571"))
        # Oct. 21 format: future days as "0" instead of "0000000000" (it was read as "through 10/30")
        txt2 = txt.replace("0000000000", "0 0")
        self.assertEqual(parse_harris(txt2), (204570, 27549, "10/20/2026", 99911))

    def test_tarrant_report_parser(self):
        from county_reports import parse_tarrant
        txt = ("November 3, 2026 - Joint General and Special Elections\nEarly Voting In Person Totals\nPage 1 of 1\n"
               "October 21, 2026\n 8:00:41AM\nTotal 10/19 10/20\nTotal 98,812 50,409 48,403\nACTIV 3,100 1,618 1,482\n")
        self.assertEqual(parse_tarrant(txt), (98812, "10/20", 48403, "October 21, 2026 8:00:41AM"))
        with self.assertRaises(ValueError):
            parse_tarrant("Total 10/19 10/20\nTotal 98,812 50,409\n")     # a missing day column must not pass

    def test_county_report_fills_incomplete_state_count(self):
        rep = json.load(open("data/county_reports.json"))["counties"].get("Tarrant", {})
        x = json.load(open("site/data_senate.json"))["early"]["counties"]["Tarrant"]
        if rep.get("in_person"):
            self.assertGreaterEqual(x["in_person"], rep["in_person"])
            self.assertFalse(x["missing"])

    def test_incomplete_state_counts_are_not_shown(self):
        # the state's day-1 file had Harris at 4 in-person votes; such a county must show as not posted
        d = json.load(open("site/data_senate.json"))
        E = d["early"]["counties"]
        for r in d["live_turnout"]["rows"]:
            if r["name"] != "Rural Texas":
                self.assertFalse(E[r["name"]]["missing"], r["name"])
        for name, x in E.items():
            if x["missing"]:
                self.assertIsNone(x["pace18"], name)

    def test_map_and_live_today_agree_for_every_live_county(self):
        for race in ("senate", "governor"):
            d = json.load(open(f"site/data_{race}.json"))
            e, rows = d["early"], d["live_turnout"]["rows"]
            for r in rows:
                if r["name"] == "Rural Texas":
                    continue
                x = e["counties"][r["name"]]
                self.assertEqual(x["ev"], r["ev"], r["name"])                             # same total as the map's Overall
                self.assertEqual(x["today"], r["today"], r["name"])
                self.assertEqual(x["ev22_raw"] or None, r["base"]["2022"], r["name"])     # same 2022 baseline
                if r["live"]:
                    self.assertIn(r["name"], e["live_counties"])

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


class Methodology(unittest.TestCase):
    def test_page_published_and_linked(self):
        self.assertTrue(open("public/methodology.html").read().startswith("<!doctype html>"))
        for page in ("index.html", "governor.html", "early.html"):
            self.assertIn('href="methodology.html"', open(f"public/{page}").read(), page)


class PublicGovernor(PublicSite):
    page, card = "governor.html", "share_governor.png"


class PublicEarly(PublicSite):
    page, card = "early.html", "share_early.png"


if __name__ == "__main__":
    unittest.main()
