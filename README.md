# Texas 2026 Forecast

Live forecasts for two 2026 Texas races:
- **U.S. Senate:** James Talarico (D) vs. Ken Paxton (R)
- **Governor:** Gina Hinojosa (D) vs. Greg Abbott (R)

| Page | Link |
|---|---|
| Senate | https://sujaynadkarni.github.io/texas-senate-forecast-2026/ |
| Governor | https://sujaynadkarni.github.io/texas-senate-forecast-2026/governor.html |
| Early voting | https://sujaynadkarni.github.io/texas-senate-forecast-2026/early.html |

- **Forecast (each race):** 50,000 simulated elections across all 254 counties, centered on that race's polling
  average, with statewide polling error, regional swings, county noise and turnout variation. County patterns come
  from past races for the same office (Senate 2018 + 2024; governor 2018 + 2022).
- **Split tickets:** where the Senate and governor forecasts differ most.
- **Early voting:** daily county turnout compared with the same day of early voting in 2022, and an estimate of
  whom the mix of voters favors. Turnout never moves the forecast.
- **Election night:** the needle updates from counted votes, county by county.

## How it updates
A GitHub Action (`.github/workflows/refresh.yml`) runs `./refresh.sh` twice a day during early voting and every
10 minutes on election night. It fetches polls, prediction-market prices, early-vote turnout and results, reruns
the model, builds the page and runs the regression tests. The site is published only if every test passes.
Run it by hand from the **Actions** tab ("Run workflow").

## Run locally
```
pip install -r requirements.txt
./refresh.sh
open public/index.html
```

## Layout
| Path | What |
|---|---|
| `pipeline/races.py` | per-race settings: candidates, poll page, markets, results feed, past races |
| `model/` | county data loading, simulation, backtests |
| `pipeline/fetch.py` | polls (Wikipedia), Kalshi, Polymarket, Texas SOS turnout and results |
| `pipeline/export.py` | runs the model, writes `site/data.json` |
| `pipeline/early_vote.py` | early-vote comparison with 2022 |
| `pipeline/share_card.py` | social preview images |
| `site/template.html` | the page template (one template, three pages) |
| `tests/` | regression tests |

## Sources
Texas Legislative Council (historical results), Texas Secretary of State (registration, turnout, results),
The Texas Tribune 2022 early voting tracker (2022 daily turnout), Wikipedia (poll list), Kalshi and Polymarket
(market prices), Harris County Clerk (mail ballot history), us-atlas (county shapes).

Independent statistical forecast; not affiliated with any campaign, party or news organization.
