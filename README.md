# Opioid Prescribing Policies: Florida and Washington

Practical Data Science team project (Xuechun Zhao, Tsaone Tapologo, Mark Li).

We estimate how Florida's 2010 and Washington's 2012 opioid prescribing regulations affected opioid shipments per capita and drug overdose deaths per 100,000 residents, using pre-post and difference-in-difference comparisons at the county-year level.

## Repository layout

| Path | Contents |
|---|---|
| `code/` | Pipeline scripts, numbered in the order they run |
| `data/intermediate/` | Cleaned county-year datasets (parquet, tracked with git-lfs) |
| `outputs/figures/` | Figures for the report |
| `report/` | Stakeholder report |

## Source data

Source files are not stored in this repository. Download them to a local folder outside the repo and pass their paths to the scripts.

| Source | Link |
|---|---|
| ARCOS opioid shipments, 2006 to 2019 (Washington Post, about 17.7 GB zipped) | https://gfx-data.news-engineering.aws.wapo.pub/ne-static/arcos/v2/bulk/arcos_all.zip |
| ARCOS data dictionary | https://github.com/wpinvestigative/arcos-api/blob/master/data/data_dictionary.csv |
| US Vital Statistics mortality, 2003 to 2015 (course-provided) | https://www.dropbox.com/s/kad4dwebr88l3ud/US_VitalStatistics.zip?dl=0 |

## Setup

Install [git-lfs](https://git-lfs.com) before cloning or pulling, so parquet files download correctly:

```bash
git lfs install
```

## Workflow

- Work on a feature branch and merge into `main` through a reviewed pull request.
- Write code as `.py` scripts, not notebooks.
- Never modify source data; write cleaned outputs to `data/intermediate/`.
