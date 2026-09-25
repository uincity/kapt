import pandas as pd
import numpy as np
import re

# Simulate link_prices on A10023975
master = pd.read_csv('data/releases/area_master_20260918/market_cap_area_master.csv')
d_master = master[master['kapt_code'] == 'A10023975']

print("Master types count:", len(d_master))
print("Master total households:", d_master['households'].sum())
