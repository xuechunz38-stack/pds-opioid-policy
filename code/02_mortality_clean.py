"""Clean CDC county-year drug overdose deaths from the Vital Statistics archive.

The D1-D4 categories cover drug poisonings by intent; they are not opioid-specific.
County-years with explicit "Missing" counts remain null, while county-years with
no D1-D4 records are assigned zero.

Usage:
    python 02_mortality_clean.py ~/pds-data/US_VitalStatistics.zip \
        ../data/intermediate/mortality_county_year.parquet
"""

import argparse
import re
import zipfile

import pandas as pd

INPUT_COLUMNS = [
    "County Code",
    "Year",
    "Drug/Alcohol Induced Cause Code",
    "Deaths",
]
OVERDOSE_CODES = {"D1", "D2", "D3", "D4"}
GROUP_KEYS = ["county_fips", "year"]
MEMBER_PATTERN = re.compile(r"Underlying Cause of Death, (\d{4})\.txt$")


def clean_archive(zip_path):
    """Return one row per county and year, preserving unavailable counts as null."""
    county_years = []
    overdose_rows = []

    with zipfile.ZipFile(zip_path) as archive:
        members = []
        for member in archive.namelist():
            match = MEMBER_PATTERN.fullmatch(member)
            if match:
                members.append((int(match.group(1)), member))

        if not members:
            raise ValueError("No annual 'Underlying Cause of Death, YYYY.txt' files found")

        file_years = [year for year, _ in members]
        if len(file_years) != len(set(file_years)):
            raise ValueError("Archive contains more than one file for a year")

        for file_year, member in sorted(members):
            with archive.open(member) as raw:
                frame = pd.read_csv(
                    raw,
                    sep="\t",
                    usecols=INPUT_COLUMNS,
                    dtype=str,
                )

            has_county = frame["County Code"].notna()
            has_year = frame["Year"].notna()
            if (has_county != has_year).any():
                raise ValueError(f"Incomplete county-year key in {member}")
            frame = frame.loc[has_county & has_year].copy()

            years = pd.to_numeric(frame["Year"], errors="coerce")
            if years.isna().any() or not years.eq(file_year).all():
                raise ValueError(f"Year values do not match {member}")

            county_code = frame["County Code"].str.strip()
            valid_county_code = county_code.str.fullmatch(r"\d{1,5}")
            if not valid_county_code.all():
                raise ValueError(f"Invalid county code in {member}")

            frame["county_fips"] = county_code.str.zfill(5)
            frame["year"] = years.astype("int64")
            county_years.append(frame[GROUP_KEYS].drop_duplicates())

            overdose = frame[
                frame["Drug/Alcohol Induced Cause Code"].isin(OVERDOSE_CODES)
            ].copy()
            if overdose.empty:
                continue

            key_and_code = GROUP_KEYS + ["Drug/Alcohol Induced Cause Code"]
            if overdose.duplicated(key_and_code).any():
                raise ValueError(f"Duplicate overdose cause rows in {member}")

            raw_deaths = overdose["Deaths"].str.strip()
            count_is_missing = raw_deaths.eq("Missing")
            deaths = pd.to_numeric(raw_deaths.mask(count_is_missing), errors="coerce")
            invalid_count = deaths.isna() & ~count_is_missing
            if invalid_count.any():
                values = sorted(raw_deaths[invalid_count].unique().tolist())
                raise ValueError(f"Unexpected death counts in {member}: {values}")
            if deaths.notna().any() and (
                deaths.dropna().lt(0).any() or deaths.dropna().mod(1).ne(0).any()
            ):
                raise ValueError(f"Death counts must be non-negative integers in {member}")

            overdose["deaths"] = deaths.astype("Int64")
            overdose["count_is_missing"] = count_is_missing
            overdose_rows.append(
                overdose[
                    GROUP_KEYS + ["deaths", "count_is_missing"]
                ]
            )

    all_county_years = pd.concat(county_years, ignore_index=True).drop_duplicates()
    if overdose_rows:
        overdose = pd.concat(overdose_rows, ignore_index=True)
        totals = (
            overdose.groupby(GROUP_KEYS)
            .agg(
                drug_overdose_deaths=("deaths", lambda counts: counts.sum(min_count=1)),
                count_is_missing=("count_is_missing", "any"),
            )
            .reset_index()
        )
        result = all_county_years.merge(
            totals,
            on=GROUP_KEYS,
            how="left",
            validate="one_to_one",
        )
    else:
        result = all_county_years.copy()
        result["drug_overdose_deaths"] = 0
        result["count_is_missing"] = False

    result["drug_overdose_deaths"] = result["drug_overdose_deaths"].fillna(0)
    result.loc[result["count_is_missing"].fillna(False), "drug_overdose_deaths"] = pd.NA
    result["drug_overdose_deaths"] = result["drug_overdose_deaths"].astype("Int64")
    return result.drop(columns="count_is_missing").sort_values(GROUP_KEYS)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("zip_path", help="Vital Statistics ZIP containing annual text files")
    parser.add_argument("output", help="output county-year Parquet path")
    args = parser.parse_args()

    result = clean_archive(args.zip_path)
    result.to_parquet(args.output, index=False)

    missing = int(result["drug_overdose_deaths"].isna().sum())
    print(f"Wrote {len(result):,} county-year rows to {args.output}")
    print(f"Counties: {result['county_fips'].nunique():,}")
    print(f"Years: {result['year'].min()}-{result['year'].max()}")
    print(f"County-years with unavailable overdose counts: {missing:,}")


if __name__ == "__main__":
    main()
