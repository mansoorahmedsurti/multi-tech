import sys
import os
os.environ["OMP_NUM_THREADS"] = "1"

print("Importing sqlalchemy...")
from sqlalchemy import create_engine, text
print("Creating engine...")
engine = create_engine("postgresql://postgres:multi-techGOAT@db.hcccwrjngbsbftapzums.supabase.co:5432/postgres", connect_args={"connect_timeout": 5})

print("Connecting to database...")
try:
    with engine.connect() as connection:
        print("Executing query...")
        result = connection.execute(text("SELECT 1"))
        print("Result:", result.fetchone())
except Exception as e:
    print("Error connecting:", e)
