# Import Packages
import requests
import pandas as pd
import datetime
import os

# Fetch fresh data from CoinGecko instead of querying BigQuery
API_URL = "https://api.coingecko.com/api/v3/coins/markets"
PARAMS = {
    "vs_currency": "usd",
    "order": "market_cap_desc",
    "per_page": 10,
    "page": 1,
    "sparkline": "false",
    "price_change_percentage": "7d",
}

response = requests.get(API_URL, params=PARAMS)
new_data = pd.DataFrame(response.json())

new_data["total_vol"] = (new_data["total_volume"] / new_data["total_volume"].sum()) * 100
now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=3)
new_data["timestamp"] = now.strftime("%Y-%m-%d %H:%M:%S")

new_data = new_data[[
    "timestamp", "name", "symbol", "current_price", "total_volume",
    "total_vol", "price_change_percentage_24h",
    "price_change_percentage_7d_in_currency", "market_cap",
]]
new_data = new_data.rename(columns={
    "current_price": "price_usd",
    "total_volume": "vol_24h",
    "price_change_percentage_24h": "chg_24h",
    "price_change_percentage_7d_in_currency": "chg_7d",
})

new_data["price_usd"] = new_data["price_usd"].map("${:,.2f}".format)
new_data["market_cap"] = new_data["market_cap"].map("${:,.0f}".format)
new_data["vol_24h"] = new_data["vol_24h"].map("${:,.2f}".format)
new_data["chg_24h"] = new_data["chg_24h"].map(lambda x: f"{x:+.2f}%" if pd.notna(x) else "N/A")
new_data["chg_7d"] = new_data["chg_7d"].map(lambda x: f"{x:+.2f}%" if pd.notna(x) else "N/A")
new_data["total_vol"] = new_data["total_vol"].map("{:.2f}%".format)

# storage/cryptocurrency.csv was already pulled down from Kaggle by the
# "Download existing Kaggle Dataset" workflow step before this script ran
if os.path.exists("storage/cryptocurrency.csv"):
    crypto = pd.read_csv("storage/cryptocurrency.csv")
    crypto = pd.concat([crypto, new_data], ignore_index=True)
else:
    crypto = new_data

# Remove duplicate records
crypto.drop_duplicates(subset=[
    "timestamp", "name", "symbol", "price_usd", "vol_24h",
    "total_vol", "chg_24h", "chg_7d", "market_cap",
], inplace=True)

# Save to CSV — the "Update Kaggle Dataset" step pushes this as the new version
crypto.to_csv("storage/cryptocurrency.csv", index=False, encoding="utf-8")
