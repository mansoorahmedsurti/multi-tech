import os
os.environ["OMP_NUM_THREADS"] = "1"
import sys

print("Starting import test...")
print("Importing datetime...")
import datetime
print("Importing numpy...")
import numpy
print("Importing pandas...")
import pandas
print("Importing sqlalchemy...")
import sqlalchemy
print("Importing streamlit...")
import streamlit
print("All imports successful!")
