# Last run: Sat Mar 14 18:01:17 UTC 2026
# Import Packages
from google.cloud import bigquery
import pandas as pd
import datetime
import os  

# Initialize Client
client = bigquery.Client()

now = datetime.datetime.now()  # Use datetime.datetime
year = now.year
month = now.strftime("%b").lower()  # jan, feb, mar

table_suffix = f"{year}_{month}"

# Define Table ID
table_id = f"data-storage-485106.investing.crypto_{table_suffix}"

# Define SQL Query to Retrieve All Records from BigQuery
sql = (f"""
        SELECT *
        FROM `{table_id}`
       """)

crypto = client.query(sql).to_dataframe()

# Save to CSV
crypto.to_csv("storage/cryptocurrency.csv", index=False, encoding='utf-8')
