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

## Safety nets
| If this goes wrong… | What happens |
|---|---|
| A code bug | The regression tests run before every publish; if any fail, nothing is published and GitHub emails you. |
| Bad data that looks valid | `pipeline/sanity.py` compares each run with the last published one and blocks publishing on unrealistic jumps (poll average moves 3+ points, poll count falls 25%+, early-vote totals or a county's counted votes go down, market prices at 0 or 100%, win chance moves 25+ points with no votes counted). If the change is real, use **Run workflow** with "Publish even if the sanity checks flag a big change" ticked. |
| A data source is down | That source's last good data is used, and the page footer says which source could not be refreshed. |
| GitHub's timer runs late | Runs are scheduled off the hour (7:17, 12:17, 7:17 Central). The page shows a warning if it has not updated for 14+ hours. |
| Election night timing | Run `./election_night_backup.sh` on this Mac from about 6:50 p.m. Central on Nov 3. It triggers a refresh every 10 minutes by pushing an empty commit, which starts a run right away. |

## Rolling back
- **Undo the last code change:** `git revert HEAD && git push`. The site rebuilds from the previous code with current data.
- **Undo a specific change:** find it with `git log --oneline`, then `git revert <commit> && git push`.
- **Freeze the site as it is:** on GitHub, Actions → Refresh forecast → "…" → Disable workflow. The current site stays up and nothing new is published until you enable it again.
- Every run's data is saved in the repo history, so any earlier day can be restored.

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
