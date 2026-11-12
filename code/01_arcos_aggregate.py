"""Aggregate ARCOS opioid shipments to county-year totals.

Streams the Washington Post ARCOS bulk file straight out of the zip archive
(about 245 GB unzipped), so the archive never has to be extracted. Keeps all
states, so control states can be chosen later without a second pass.

Output: one row per buyer state, buyer county, year, drug and buyer type, with total
morphine milligram equivalents (MME) shipped and the number of transactions.

Usage:
    python 01_arcos_aggregate.py ~/pds-data/arcos/arcos_all.zip arcos_county_year.parquet
    python 01_arcos_aggregate.py ~/pds-data/arcos/arcos_all.zip sample.parquet --nrows 500000
"""

import argparse
import io
import time
import zipfile

import pandas as pd

# Columns we need, as named in the ARCOS data dictionary. Matching is
# case-insensitive because the bulk file's header may differ in case.
NEEDED = [
    "BUYER_STATE",
    "BUYER_COUNTY",
    "TRANSACTION_DATE",
    "TRANSACTION_CODE",
    "CALC_BASE_WT_IN_GM",
    "MME_Conversion_Factor",
    "DRUG_NAME",
    "BUYER_BUS_ACT",
    "MME",  # precomputed in the bulk file; used to cross-check our calculation
]
# Kept by drug and buyer type so the team can later exclude drugs (for example
# buprenorphine, mainly used to treat opioid use disorder) or buyers (for example
# narcotic treatment programs dispensing methadone) without another full pass.
GROUP_KEYS = ["buyer_state", "buyer_county", "year", "drug_name", "buyer_bus_act"]


def open_member(zip_path):
    """Return the zip archive and the name of its single data file."""
    archive = zipfile.ZipFile(zip_path)
    members = [m for m in archive.infolist() if not m.is_dir()]
    data = max(members, key=lambda m: m.file_size)
    print(f"Reading {data.filename} ({data.file_size / 1e9:.1f} GB unzipped)")
    return archive, data.filename


def detect_layout(archive, member):
    """Find the delimiter and map our column names to the file's header."""
    with archive.open(member) as raw:
        header = io.TextIOWrapper(raw, encoding="utf-8", errors="replace").readline()
    sep = "\t" if header.count("\t") > header.count(",") else ","
    columns = [c.strip().strip('"') for c in header.rstrip("\n").split(sep)]
    lookup = {c.lower(): c for c in columns}
    missing = [c for c in NEEDED if c.lower() not in lookup]
    if missing:
        raise KeyError(f"Columns not found in file header: {missing}\nHeader: {columns}")
    return sep, {lookup[c.lower()]: c for c in NEEDED}


def extract_year(dates):
    """Get the year from TRANSACTION_DATE, which may be MMDDYYYY or YYYY-MM-DD."""
    s = dates.astype(str).str.strip()
    dashed = s.str.contains("-", regex=False)
    year = s.str[:4].where(dashed, s.str.zfill(8).str[-4:])
    return pd.to_numeric(year, errors="coerce").astype("Int64")


def aggregate_chunk(chunk, rename, stats):
    chunk = chunk.rename(columns=rename)
    stats["rows"] += len(chunk)
    stats["drugs"].update(chunk["DRUG_NAME"].dropna().unique())

    # The Post's data is limited to sales ("S"); keep the filter in case the
    # bulk file includes other transaction types.
    sales = chunk[chunk["TRANSACTION_CODE"].astype(str).str.strip() == "S"].copy()
    stats["non_sale_rows"] += len(chunk) - len(sales)

    weight = pd.to_numeric(sales["CALC_BASE_WT_IN_GM"], errors="coerce")
    factor = pd.to_numeric(sales["MME_Conversion_Factor"], errors="coerce")
    sales["opioid_mme"] = weight * 1000 * factor  # grams -> mg, then to MME
    stats["missing_mme_rows"] += int(sales["opioid_mme"].isna().sum())
    file_mme = pd.to_numeric(sales["MME"], errors="coerce")
    stats["mme_mismatch_rows"] += int(((sales["opioid_mme"] - file_mme).abs() > 0.01 * file_mme.abs() + 1e-6).sum())

    sales["buyer_state"] = sales["BUYER_STATE"].astype(str).str.strip().str.upper()
    sales["buyer_county"] = sales["BUYER_COUNTY"].astype(str).str.strip().str.upper()
    sales["drug_name"] = sales["DRUG_NAME"].astype(str).str.strip().str.upper()
    sales["buyer_bus_act"] = sales["BUYER_BUS_ACT"].astype(str).str.strip().str.upper()
    sales["year"] = extract_year(sales["TRANSACTION_DATE"])
    stats["missing_year_rows"] += int(sales["year"].isna().sum())

    return (
        sales.groupby(GROUP_KEYS, dropna=False)
        .agg(opioid_mme=("opioid_mme", "sum"), n_transactions=("opioid_mme", "size"))
        .reset_index()
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("zip_path")
    parser.add_argument("output")
    parser.add_argument("--chunksize", type=int, default=2_000_000)
    parser.add_argument("--nrows", type=int, default=None, help="read only the first N rows, for testing")
    args = parser.parse_args()

    archive, member = open_member(args.zip_path)
    sep, rename = detect_layout(archive, member)
    stats = {
        "rows": 0,
        "non_sale_rows": 0,
        "missing_mme_rows": 0,
        "mme_mismatch_rows": 0,
        "missing_year_rows": 0,
        "drugs": set(),
    }

    partials = []
    start = time.time()
    with archive.open(member) as raw:
        reader = pd.read_csv(
            raw,
            sep=sep,
            usecols=list(rename),
            dtype=str,
            chunksize=args.chunksize,
            nrows=args.nrows,
            encoding_errors="replace",
        )
        for i, chunk in enumerate(reader, start=1):
            partials.append(aggregate_chunk(chunk, rename, stats))
            print(f"chunk {i}: {stats['rows']:,} rows read, {time.time() - start:,.0f}s elapsed", flush=True)

    result = (
        pd.concat(partials)
        .groupby(GROUP_KEYS, dropna=False)[["opioid_mme", "n_transactions"]]
        .sum()
        .reset_index()
        .sort_values(GROUP_KEYS)
    )
    result.to_parquet(args.output, index=False)

    print(f"\nWrote {len(result):,} county-year rows to {args.output}")
    print(f"Rows read: {stats['rows']:,}")
    print(f"Non-sale rows dropped: {stats['non_sale_rows']:,}")
    print(f"Rows with missing MME: {stats['missing_mme_rows']:,}")
    print(f"Rows where our MME differs from the file's MME column by >1%: {stats['mme_mismatch_rows']:,}")
    print(f"Rows with unparsed year: {stats['missing_year_rows']:,}")
    print(f"Drugs present: {sorted(stats['drugs'])}")
    print(f"Years: {sorted(result['year'].dropna().unique().tolist())}")


if __name__ == "__main__":
    main()
