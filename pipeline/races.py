"""Per-race settings. Everything race-specific in the pipeline and the page comes from here.
Margins are always Democrat minus Republican; 'd' and 'r' name the two candidates."""

RACES = {
    "senate": dict(
        office="U.S. Senate", page="index.html",
        d="Talarico", r="Paxton", d_full="James Talarico", r_full="Ken Paxton", d_init="T", r_init="P",
        context="In 2024, Ted Cruz won this seat by 8.5 points.",
        wiki="2026_United_States_Senate_election_in_Texas",
        kalshi_event="SENATETX-26", kalshi_d="James Talarico",
        poly_event="Texas Senate Election Winner", poly_d_question="Will the Democrats win",
        poly_url="https://polymarket.com/event/texas-senate-election-winner",
        kalshi_url="https://kalshi.com/markets/senatetx/texas-senate-race",
        results_race="U. S. SENATOR", results_d="TALARICO", results_r="PAXTON",
        # county pattern = 50/50 blend of these two past races (relative to the state)
        bases=("sen18", "sen24"),
        history=[dict(key="sen18", label="2018 Senate", short="2018", who="Cruz vs. O'Rourke"),
                 dict(key="sen24", label="2024 Senate", short="2024", who="Cruz vs. Allred")],
        fundamentals=0.495,
        # final poll average vs. result, newest first. Margins are for the race leader (+ = leader ahead).
        poll_history=[
            dict(year=2024, leader="Cruz", party="R", other="Allred", poll=4.0, result=8.5,
                 source="average of 538, RealClearPolitics, 270toWin and DDHQ"),
            dict(year=2020, leader="Cornyn", party="R", other="Hegar", poll=6.5, result=9.6, source="RealClearPolitics"),
            dict(year=2018, leader="Cruz", party="R", other="O'Rourke", poll=5.9, result=2.6,
                 source="our average of October polls (no published average)"),
        ],
    ),
    "governor": dict(
        office="Governor", page="governor.html",
        d="Hinojosa", r="Abbott", d_full="Gina Hinojosa", r_full="Greg Abbott", d_init="H", r_init="A",
        context="In 2022, Abbott beat Beto O'Rourke by 10.9 points.",
        wiki="2026_Texas_gubernatorial_election",
        kalshi_event="GOVPARTYTX-26", kalshi_d="Gina Hinojosa",
        poly_event="Texas Governor Election Winner", poly_d_question="Will the Democrats win",
        poly_url="https://polymarket.com/event/texas-governor-election-winner",
        kalshi_url="https://kalshi.com/markets/govpartytx/texas-governor",
        results_race="GOVERNOR", results_d="HINOJOSA", results_r="ABBOTT",
        bases=("gov18", "gov22"),
        history=[dict(key="gov18", label="2018 Governor", short="2018", who="Abbott vs. Valdez"),
                 dict(key="gov22", label="2022 Governor", short="2022", who="Abbott vs. O'Rourke")],
        fundamentals=0.47,
        poll_history=[
            dict(year=2022, leader="Abbott", party="R", other="O'Rourke", poll=8.9, result=10.9,
                 source="average of RealClearPolitics and 538"),
            dict(year=2018, leader="Abbott", party="R", other="Valdez", poll=18.3, result=13.3,
                 source="our average of October polls (no published average)"),
        ],
    ),
}


# Counties that matter to both parties, by the role they play (Rural Texas = the 173 rural counties combined).
KEY_COUNTIES = {
    "dem": ["Harris", "Dallas", "Bexar", "Travis", "El Paso"],
    "battle": ["Tarrant", "Collin", "Denton", "Williamson", "Fort Bend", "Hidalgo"],
    "rep": ["Montgomery", "Parker", "Comal", "Smith", "Johnson", "Lubbock", "Rural Texas"],
}


def margin_label(race, m, long=False):
    """+ = Democrat. 'Talarico +2.5' (long) or 'T+2.5'."""
    c = RACES[race]
    if abs(m) < 0.05:
        return "Even"
    if long:
        return f"{c['d'] if m > 0 else c['r']} +{abs(m):.1f}"
    return f"{c['d_init'] if m > 0 else c['r_init']}+{abs(m):.1f}"
