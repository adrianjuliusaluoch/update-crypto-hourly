#!/usr/bin/env python3
"""
Fetch crypto market data from CoinGecko and publish it straight to Kaggle.
Replaces the old BigQuery load/read step (quota exceeded) with a
download-existing -> append -> dedupe -> re-upload cycle against your
existing Kaggle dataset.

Auth: Kaggle CLI must be authenticated the way your other pipelines already
are (~/.kaggle/kaggle.json, or KAGGLE_USERNAME + KAGGLE_KEY env vars / secrets).

Dataset slug: read straight from storage/dataset-metadata.json — the same
file Kaggle already uses for your crypto-market-data dataset. If that file
isn't in storage/ yet, drop it in there (or set a KAGGLE_DATASET env var)
and this runs with no other changes.

    pip install kaggle requests pandas
"""

import os
import json
import subprocess
from datetime import datetime, timedelta, timezone

import requests
import pandas as pd

WORK_DIR = "storage"
CSV_PATH = os.path.join(WORK_DIR, "cryptocurrency.csv")
METADATA_PATH = os.path.join(WORK_DIR, "dataset-metadata.json")

os.makedirs(WORK_DIR, exist_ok=True)

API_URL = "https://api.coingecko.com/api/v3/coins/markets"
PARAMS = {
    "vs_currency": "usd",
    "order": "market_cap_desc",
    "per_page": 10,
    "page": 1,
    "sparkline": "false",
    "price_change_percentage": "7d",
}

DEDUP_COLS = [
    "timestamp", "name", "symbol", "price_usd", "vol_24h",
    "total_vol", "chg_24h", "chg_7d", "market_cap",
]


def get_dataset_slug() -> str:
    """Pull the Kaggle dataset id from storage/dataset-metadata.json. If that
    file doesn't exist yet but KAGGLE_DATASET is set, write a minimal one —
    Kaggle needs this file present for both create and version pushes."""
    if os.path.exists(METADATA_PATH):
        with open(METADATA_PATH) as f:
            return json.load(f)["id"]

    env_slug = os.environ.get("KAGGLE_DATASET")
    if env_slug:
        with open(METADATA_PATH, "w") as f:
            json.dump({
                "title": env_slug.split("/")[-1].replace("-", " ").title(),
                "id": env_slug,
                "licenses": [{"name": "CC0-1.0"}],
            }, f)
        print(f"No {METADATA_PATH} found — created one for {env_slug}.")
        return env_slug

    raise FileNotFoundError(
        f"No {METADATA_PATH} found and no KAGGLE_DATASET env var set. "
        "Set KAGGLE_DATASET=username/dataset-slug, or drop a "
        "dataset-metadata.json into storage/."
    )


def fetch_crypto_data() -> pd.DataFrame:
    response = requests.get(API_URL, params=PARAMS)
    response.raise_for_status()
    df = pd.DataFrame(response.json())

    df["total_vol"] = (df["total_volume"] / df["total_volume"].sum()) * 100
    local_time = datetime.now(timezone.utc) + timedelta(hours=3)
    df["timestamp"] = local_time.strftime("%Y-%m-%d %H:%M:%S")

    df = df[[
        "timestamp", "name", "symbol", "current_price", "total_volume",
        "total_vol", "price_change_percentage_24h",
        "price_change_percentage_7d_in_currency", "market_cap",
    ]]
    df = df.rename(columns={
        "current_price": "price_usd",
        "total_volume": "vol_24h",
        "price_change_percentage_24h": "chg_24h",
        "price_change_percentage_7d_in_currency": "chg_7d",
    })

    df["price_usd"] = df["price_usd"].map("${:,.2f}".format)
    df["market_cap"] = df["market_cap"].map("${:,.0f}".format)
    df["vol_24h"] = df["vol_24h"].map("${:,.2f}".format)
    df["chg_24h"] = df["chg_24h"].map(lambda x: f"{x:+.2f}%" if pd.notna(x) else "N/A")
    df["chg_7d"] = df["chg_7d"].map(lambda x: f"{x:+.2f}%" if pd.notna(x) else "N/A")
    df["total_vol"] = df["total_vol"].map("{:.2f}%".format)

    return df


def download_existing_csv(dataset_slug: str) -> pd.DataFrame:
    """Pull the current CSV off Kaggle so new rows append to full history."""
    try:
        dl = subprocess.run(
            [
                "kaggle", "datasets", "download", "-d", dataset_slug,
                "-p", WORK_DIR, "--unzip", "--force",
            ],
            check=True, capture_output=True, text=True,
        )
        print(dl.stdout)
        # Show what actually landed in storage/, so a wrong/empty file is obvious
        print("Files in", WORK_DIR, "after download:")
        for f in os.listdir(WORK_DIR):
            fp = os.path.join(WORK_DIR, f)
            print(f"  {f} — {os.path.getsize(fp)} bytes")

        if os.path.exists(CSV_PATH):
            existing = pd.read_csv(CSV_PATH)
            print(f"Downloaded existing dataset: {existing.shape[0]} rows, columns: {list(existing.columns)}")
            return existing
        else:
            print(f"No {CSV_PATH} found after download/unzip — check the filename Kaggle stored it under above.")
    except subprocess.CalledProcessError as e:
        print(f"Could not download existing dataset (first run?):\nSTDOUT: {e.stdout}\nSTDERR: {e.stderr}")
    return pd.DataFrame()


def upload_to_kaggle() -> None:
    """Push the CSV to Kaggle. Tries 'version' (dataset already exists);
    if Kaggle says there's nothing to version yet, falls back to 'create'
    for the first-ever push. From the second run on, 'version' will work."""
    message = f"Auto-update {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    try:
        result = subprocess.run(
            ["kaggle", "datasets", "version", "-p", WORK_DIR, "-m", message, "-r", "zip"],
            check=True, capture_output=True, text=True,
        )
        print(result.stdout)
        return
    except subprocess.CalledProcessError as e:
        output = f"{e.stdout or ''}{e.stderr or ''}".lower()
        not_found = any(s in output for s in ("404", "not found", "doesn't exist", "does not exist"))
        if not not_found:
            print(f"Kaggle version push failed.\nSTDOUT: {e.stdout}\nSTDERR: {e.stderr}")
            raise
        print("Dataset doesn't exist on Kaggle yet — creating it for the first time instead.")

    result = subprocess.run(
        ["kaggle", "datasets", "create", "-p", WORK_DIR, "-r", "zip"],
        check=True, capture_output=True, text=True,
    )
    print(result.stdout)


def main() -> None:
    dataset_slug = get_dataset_slug()

    existing = download_existing_csv(dataset_slug)
    new_data = fetch_crypto_data()

    combined = pd.concat([existing, new_data], ignore_index=True) if not existing.empty else new_data

    cols = [c for c in DEDUP_COLS if c in combined.columns]
    before = len(combined)
    combined.drop_duplicates(subset=cols, inplace=True)
    print(f"Removed {before - len(combined)} duplicate rows.")

    combined.to_csv(CSV_PATH, index=False, encoding="utf-8")
    print(f"Saved {combined.shape} rows to {CSV_PATH}")

    upload_to_kaggle()
    print("Crypto data pushed to Kaggle successfully.")


if __name__ == "__main__":
    main()
