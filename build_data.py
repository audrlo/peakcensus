#!/usr/bin/env python3
"""
build_data.py — Census Data Pipeline
Downloads county population data (1900–2020), computes peak decade, outputs JSON.
"""

import csv
import io
import json
import os
import requests
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUTPUT_PATH = os.path.join(DATA_DIR, "county_peaks.json")

NBER_URL = "https://data.nber.org/census/population/cencounts/cencounts.csv"

CENSUS_API = {
    2000: "https://api.census.gov/data/2000/dec/sf1?get=P001001,NAME&for=county:*",
    2010: "https://api.census.gov/data/2010/dec/sf1?get=P001001,NAME&for=county:*",
    2020: "https://api.census.gov/data/2020/dec/dhc?get=P1_001N,NAME&for=county:*",
}

# FIPS renames: old → new
FIPS_RENAMES = {
    "46113": "46102",  # Shannon County SD → Oglala Lakota
    "02270": "02158",  # Wade Hampton AK → Kusilvak
}

STATE_FIPS_TO_NAME = {
    "01": "Alabama", "02": "Alaska", "04": "Arizona", "05": "Arkansas",
    "06": "California", "08": "Colorado", "09": "Connecticut", "10": "Delaware",
    "11": "District of Columbia", "12": "Florida", "13": "Georgia", "15": "Hawaii",
    "16": "Idaho", "17": "Illinois", "18": "Indiana", "19": "Iowa",
    "20": "Kansas", "21": "Kentucky", "22": "Louisiana", "23": "Maine",
    "24": "Maryland", "25": "Massachusetts", "26": "Michigan", "27": "Minnesota",
    "28": "Mississippi", "29": "Missouri", "30": "Montana", "31": "Nebraska",
    "32": "Nevada", "33": "New Hampshire", "34": "New Jersey", "35": "New Mexico",
    "36": "New York", "37": "North Carolina", "38": "North Dakota", "39": "Ohio",
    "40": "Oklahoma", "41": "Oregon", "42": "Pennsylvania", "44": "Rhode Island",
    "45": "South Carolina", "46": "South Dakota", "47": "Tennessee", "48": "Texas",
    "49": "Utah", "50": "Vermont", "51": "Virginia", "53": "Washington",
    "54": "West Virginia", "55": "Wisconsin", "56": "Wyoming", "60": "American Samoa",
    "66": "Guam", "69": "Northern Mariana Islands", "72": "Puerto Rico",
    "78": "Virgin Islands",
}

STATE_FIPS_TO_ABBR = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO",
    "09": "CT", "10": "DE", "11": "DC", "12": "FL", "13": "GA", "15": "HI",
    "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
    "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN",
    "28": "MS", "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
    "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD",
    "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA",
    "54": "WV", "55": "WI", "56": "WY", "72": "PR",
}


def download_nber_data():
    """Download and parse NBER cencounts.csv (1900-1990)."""
    print("Downloading NBER census data...")
    resp = requests.get(NBER_URL)
    resp.raise_for_status()

    reader = csv.DictReader(io.StringIO(resp.text))
    rows = []
    for row in reader:
        fips_raw = row.get("fips", "").strip()
        if not fips_raw or not fips_raw.isdigit():
            continue
        fips = fips_raw.zfill(5)
        # Skip state/national summaries (county portion is 000)
        if fips[2:] == "000":
            continue
        # Skip territories except PR
        state_fips = fips[:2]
        if int(state_fips) > 56 and state_fips != "72":
            continue

        record = {"fips": fips}
        for decade in range(1900, 2000, 10):
            col = f"pop{decade}"
            val = row.get(col, "").strip()
            try:
                record[f"pop_{decade}"] = int(float(val)) if val else 0
            except (ValueError, TypeError):
                record[f"pop_{decade}"] = 0
        # Keep the name from NBER
        record["nber_name"] = row.get("name", "").strip()
        rows.append(record)

    df = pd.DataFrame(rows)
    print(f"  NBER data: {len(df)} county records")
    return df


def download_census_api(year):
    """Download decennial census data from Census Bureau API."""
    url = CENSUS_API[year]
    print(f"Downloading Census API data for {year}...")
    resp = requests.get(url)
    resp.raise_for_status()
    data = resp.json()

    header = data[0]
    rows = []
    for row in data[1:]:
        state_fips = row[header.index("state")]
        county_fips = row[header.index("county")]
        fips = f"{state_fips.zfill(2)}{county_fips.zfill(3)}"
        pop_col = "P001001" if year <= 2010 else "P1_001N"
        pop_val = row[header.index(pop_col)]
        name = row[header.index("NAME")]
        try:
            pop = int(pop_val)
        except (ValueError, TypeError):
            pop = 0
        rows.append({"fips": fips, f"pop_{year}": pop, f"name_{year}": name})

    df = pd.DataFrame(rows)
    print(f"  Census {year}: {len(df)} county records")
    return df


def build_wiki_url(name, state_fips, fips):
    """Build Wikipedia URL for a county."""
    state_name = STATE_FIPS_TO_NAME.get(state_fips, "")
    county_fips_part = fips[2:]
    base = "https://en.wikipedia.org/wiki/"

    # DC
    if fips == "11001":
        return base + "Washington,_D.C."

    # Louisiana — parishes
    if state_fips == "22":
        # Name might already contain "Parish" or not
        parish = name.replace(" Parish", "").strip()
        return base + f"{parish}_Parish,_Louisiana".replace(" ", "_")

    # Alaska — boroughs/census areas
    if state_fips == "02":
        # Try to keep the full designation
        area = name.strip()
        # Common suffixes in Alaska: Borough, Census Area, Municipality, City and Borough
        return base + f"{area},_Alaska".replace(" ", "_")

    # Virginia independent cities (county FIPS >= 510)
    if state_fips == "51" and int(county_fips_part) >= 510:
        city = name.replace(" city", "").replace(" City", "").strip()
        return base + f"{city},_Virginia".replace(" ", "_")

    # Default: County
    county = name.replace(" County", "").strip()
    return base + f"{county}_County,_{state_name}".replace(" ", "_")


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    # Step 1: NBER data (1900-1990)
    nber_df = download_nber_data()

    # Step 2: Census API data (2000, 2010, 2020)
    api_dfs = {}
    for year in [2000, 2010, 2020]:
        api_dfs[year] = download_census_api(year)

    # Step 3: Merge all data by FIPS
    # Apply FIPS renames to NBER data
    nber_df["fips"] = nber_df["fips"].replace(FIPS_RENAMES)
    for year in api_dfs:
        api_dfs[year]["fips"] = api_dfs[year]["fips"].replace(FIPS_RENAMES)

    merged = nber_df.copy()
    for year in [2000, 2010, 2020]:
        adf = api_dfs[year][["fips", f"pop_{year}", f"name_{year}"]]
        merged = merged.merge(adf, on="fips", how="outer")

    # Fill NaN populations with 0
    pop_cols = [f"pop_{d}" for d in range(1900, 2030, 10)]
    for col in pop_cols:
        if col in merged.columns:
            merged[col] = merged[col].fillna(0).astype(int)

    print(f"\nMerged data: {len(merged)} counties")

    # Step 4: Compute peak decade for each county
    decade_cols = [c for c in pop_cols if c in merged.columns]
    decades = [int(c.split("_")[1]) for c in decade_cols]

    results = {}
    for _, row in merged.iterrows():
        fips = row["fips"]
        if not isinstance(fips, str) or len(fips) != 5:
            continue

        state_fips = fips[:2]
        # Skip territories except DC
        if int(state_fips) > 56 and state_fips != "72":
            continue

        # Get population values per decade
        pops = {d: int(row[f"pop_{d}"]) for d in decades if f"pop_{d}" in row.index}

        # Find peak decade
        peak_decade = max(pops, key=lambda d: pops[d])
        peak_pop = pops[peak_decade]

        # Get best available name
        name = ""
        for yr in [2020, 2010, 2000]:
            ncol = f"name_{yr}"
            if ncol in row.index and pd.notna(row[ncol]) and row[ncol]:
                name = str(row[ncol]).split(",")[0].strip()
                break
        if not name:
            name = str(row.get("nber_name", fips))

        state_abbr = STATE_FIPS_TO_ABBR.get(state_fips, "")
        state_name = STATE_FIPS_TO_NAME.get(state_fips, "")
        pop_2020 = pops.get(2020, 0)

        wiki_url = build_wiki_url(name, state_fips, fips)

        # Build full display name
        full_name = f"{name}, {state_abbr}" if state_abbr else name

        results[fips] = {
            "name": name,
            "fullName": full_name,
            "state": state_name,
            "peakDecade": peak_decade,
            "peakPop": peak_pop,
            "pop2020": pop_2020,
            "wikiUrl": wiki_url,
        }

    # Write output
    with open(OUTPUT_PATH, "w") as f:
        json.dump(results, f)

    print(f"\nWrote {len(results)} counties to {OUTPUT_PATH}")

    # Spot checks
    if "06037" in results:
        print(f"  LA County (06037): peak={results['06037']['peakDecade']}, pop2020={results['06037']['pop2020']}")
    if "20001" in results:
        print(f"  Allen County KS (20001): peak={results['20001']['peakDecade']}")
    if "36061" in results:
        print(f"  New York County (36061): peak={results['36061']['peakDecade']}, pop2020={results['36061']['pop2020']}")


if __name__ == "__main__":
    main()
