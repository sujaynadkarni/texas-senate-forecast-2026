# Texas Senate Forecast 2026

Live forecast for the 2026 U.S. Senate race in Texas: James Talarico (D) vs. Ken Paxton (R).

**Site:** https://sujaynadkarni.github.io/texas-senate-forecast-2026/

- **Forecast:** 50,000 simulated elections across all 254 counties, centered on the polling average,
  with statewide polling error, regional swings, county noise and turnout variation.
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
| `model/` | county data loading, simulation, backtests |
| `pipeline/fetch.py` | polls (Wikipedia), Kalshi, Polymarket, Texas SOS turnout and results |
| `pipeline/export.py` | runs the model, writes `site/data.json` |
| `pipeline/early_vote.py` | early-vote comparison with 2022 |
| `pipeline/share_card.py` | social preview image |
| `site/template.html` | the page |
| `tests/` | regression tests |

## Sources
Texas Legislative Council (historical results), Texas Secretary of State (registration, turnout, results),
The Texas Tribune 2022 early voting tracker (2022 daily turnout), Wikipedia (poll list), Kalshi and Polymarket
(market prices), Harris County Clerk (mail ballot history), us-atlas (county shapes).

Independent statistical forecast; not affiliated with any campaign, party or news organization.
