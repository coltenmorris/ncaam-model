# NCAAM Model (Python version of NCAAM Model v5.1.xlsm)

## Hosting on GitHub (runs every day, even with your PC off)

GitHub runs the model on its servers at about 10 AM and 5 PM Eastern, saves the pick
history, and publishes the dashboard as a web page you can open on your phone.

This version has no sub-folders, so everything uploads through the browser.

### 1. Upload the files
1. In your repo, click **Add file > Upload files**.
2. Open the unzipped folder, press **Ctrl+A** to select every file, and drag them onto
   the page. Files with the same names as ones already there get replaced.
3. Click **Commit changes**.

### 2. Create the daily schedule (one file, typed in)
1. Click **Add file > Create new file**.
2. In the name box type exactly: `.github/workflows/daily.yml`
   (typing the slashes creates the folders).
3. Open `daily.yml` from the zip in Notepad, copy everything, paste it in, and click
   **Commit changes**.

### 3. Odds API key
Already done if you added the `ODDS_API_KEY` secret. If not: **Settings > Secrets and
variables > Actions > New repository secret**, name `ODDS_API_KEY`, paste the key.

### 4. Point the web page at the workflow
**Settings > Pages > Build and deployment > Source**: change it to **GitHub Actions**.
(Nothing else to pick. This replaces the "Deploy from a branch" setting.)

### 5. Run it once
**Actions** tab > **Daily NCAAM update** (left side) > **Run workflow** > **Run workflow**.
After about 2 minutes you get a green check, and the page is live at
`https://YOUR-USERNAME.github.io/ncaam-model/`. The run's summary also shows the link.

### Good to know
- **Where things are:** the web page is the dashboard. The Excel version and the full
  pick history (CSV) are linked at the bottom of the page and saved in the repo's
  `docs` and `data` folders.
- **If a run fails:** GitHub emails you. Open the Actions tab, click the red run, and
  read the "Run the model" step. Each source's status is also listed at the bottom of
  the web page.
- **Changing settings:** edit `config.py` on github.com (pencil icon) and commit. The
  next run uses the new settings.
- **Barttorvik:** if Barttorvik ever blocks GitHub's servers, the run uses the last
  saved ratings and says so on the page.
- **Public repo:** anyone with the link can see the page and code, but not your key.
- **If you also set up the Windows tasks earlier,** turn them off so you don't keep two
  separate histories: `python setup_daily_tasks.py --remove`.
- **Run any date:** Actions > Daily NCAAM update > Run workflow, then type a date such as
  `tomorrow` or `2026-11-20`.

---

## Running on your own PC instead (optional)

Each run, automatically:
1. Grades earlier picks with ESPN final scores.
2. Downloads fresh Barttorvik T-Rank ratings.
3. Pulls the ESPN Division I schedule (with ESPN's DraftKings line).
4. Pulls lines from every US sportsbook on The Odds API (DraftKings, FanDuel,
   BetMGM, Caesars, and others) and builds a consensus line.
5. Pulls prediction-market win prices from Kalshi and Polymarket.
6. Runs every spreadsheet formula plus the sportsbook edge, logs the picks, and
   updates **output/NCAAM_Dashboard.xlsx**.

## One-time setup (Windows + PyCharm)
1. Unzip, then in PyCharm: File > Open > the NCAAM_Model folder.
2. Accept PyCharm's offer to create a virtual environment from requirements.txt
   (or open the Terminal tab and run `pip install -r requirements.txt`).
3. Put your Odds API key in `data/odds_api_key.txt` (create the file). Never put it in
   config.py, and never upload that file to the public repo. If GitHub and your PC both
   run every day, together they use about 240 of the 500 free monthly requests.
4. Right-click **main.py** > Run 'main' once to check it works.
5. Right-click **setup_daily_tasks.py** > Run. This creates two Windows Task
   Scheduler jobs (10:00 AM and 5:00 PM, set in `config.DAILY_RUN_TIMES`).

After that it runs by itself every day while you're signed in to Windows. If the
computer was off or asleep at a run time, it runs as soon as it wakes up.

Manage the daily tasks (PyCharm: Run > Edit Configurations > Parameters, or Terminal):

    python setup_daily_tasks.py --status    last run, next run, result
    python setup_daily_tasks.py --run-now   trigger a run right now
    python setup_daily_tasks.py --remove    turn the automatic runs off

## The dashboard (web page, plus output/NCAAM_Dashboard.xlsx locally)
| Sheet | What's on it |
|---|---|
| Today | Every game with a line, sorted by sportsbook edge: consensus line, best line at any book, projected margin, Edge Pick, model vs market win %, plus the original Games to Watch / Confidence / Model Pick |
| Success Rate | W-L-P, success rate and units for Sportsbook Edge picks (by edge size), Market picks, Games to Watch and Model Picks (by confidence). Also a daily trend table and a cumulative chart |
| History | Every logged pick with its line, result and final score |
| Full Slate | Every original spreadsheet column plus all odds columns |
| Odds by Book | Each book's spread, price and moneyline for each game |
| Ratings | Barttorvik ratings used for this run |
| Assumptions / Run Log | Model settings, and what each data source returned |

A dated copy is also saved to output/daily each day, and the raw slate to data/slates.
If the dashboard is open in Excel during a scheduled run, that update is saved as a
timestamped copy beside it. Close Excel before the run times to avoid this.

## Pick types tracked
- **Edge**: the side the projected margin favors against the line, graded against the
  spread. Edge size = |Proj T1 Margin + T1 Line|. Break-even at -110 is 52.4%.
- **Market**: model win % is 5+ points above Kalshi/Polymarket (or no-vig book) win %,
  graded straight up. Units are paid at the market price.
- **Watch** and **Model**: the original spreadsheet screens, graded against the spread.

Picks are only logged for games that haven't tipped off. The 5 PM run replaces the
morning's ungraded picks with the newer line, so the record reflects the latest
pre-game number.

## Running by hand
    python main.py                       today
    python main.py --date tomorrow       preview tomorrow's slate
    python main.py --grade-only          update results and success rates only
    python main.py --legacy              exact v5.1 spreadsheet math
    python main.py --no-log              don't log picks

## Settings
All model and odds settings are in config.py: weights, home court, tempo, confidence
tiers, which line the model uses (consensus or ESPN), edge buckets, run times.

## Team names
Name matching is automatic. If the console or log lists an unmatched team that is
Division I, add a line to team_aliases.csv (ESPN name, Barttorvik name).

## Prediction markets
Kalshi and Polymarket only list some college games, and they rename their listings
from time to time. The Run Log sheet says how many game markets each one returned. If
one shows 0 all season, find the series on their site and set `KALSHI_SERIES` or
`POLYMARKET_SERIES_ID` in config.py.

## Files
- daily.yml: the GitHub daily schedule (lives at .github/workflows/daily.yml in the repo)
- docs/ and data/: created by the first run (web page, pick history, saved ratings)
- web.py: builds the web dashboard
- main.py: run this
- setup_daily_tasks.py: turns on/off the automatic daily runs
- config.py: all settings
- espn.py: schedule, DraftKings line, final scores
- odds_api.py: multi-book lines and consensus
- markets.py: Kalshi and Polymarket
- torvik.py: Barttorvik ratings
- names.py: team name matching
- model.py: spreadsheet formulas and edge math
- tracker.py: pick log, grading and success rates
- report.py: console output and dashboard
- data/pick_history.csv: the full pick history (back this file up)
