# Install InfluRank discovery

Copy the folders/files from this package into the root of the existing `rankinginflu` repository.

Expected result:

```text
rankinginflu/
├── apps/
│   ├── discovery/
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── apify_client.py
│   │   ├── cli.py
│   │   ├── config.py
│   │   ├── models.py
│   │   ├── pipeline.py
│   │   ├── requirements.txt
│   │   ├── seeds.json
│   │   └── README.md
│   └── web/
│       └── data/
├── .github/
│   └── workflows/
│       └── discovery-manual.yml
├── .env.discovery.example
└── DISCOVERY_INSTALL.md
```

## First local test

Open PowerShell in the repo root:

```powershell
python -m pip install -r apps/discovery/requirements.txt
$env:APIFY_TOKEN="PASTE_YOUR_TOKEN_HERE"
python -m apps.discovery run --max-items 10 --min-followers 10000
```

Then check:

```text
apps/web/data/discovery_candidates.json
apps/web/data/scanner_queue.json
apps/web/data/discovery_raw.json
```

## GitHub Actions

In GitHub:

`Settings -> Secrets and variables -> Actions -> New repository secret`

Name:

```text
APIFY_TOKEN
```

Paste the Apify token as the value.

Then:

`Actions -> InfluRank discovery -> Run workflow`

Start with:
- max_items: `10`
- min_followers: `10000`
- sort_type: `RELEVANCE`
- date_range: `LAST_THREE_MONTHS`

If the test is correct, increase to 100 and later 1000.

## Why RELEVANCE is the default

Our small manual tests did not show reliable global ordering from `MOST_LIKED`.
The provider exposes the sort option, but InfluRank should deduplicate and rank creators using its own data instead of assuming the provider's result order is authoritative.

## Security

Never put the token into:
- `seeds.json`
- frontend JavaScript
- `creators.json`
- a committed `.env` file

Use a local environment variable or GitHub Actions secret.
