"""TEFA public data explorer: loaders, checks, map helpers."""
import pandas as _pd

# Keep reading .xlsx with openpyxl. pandas 3.1 plans to switch the default to calamine
# (and warns on every read when calamine is installed). The loaders were validated against
# openpyxl's output, and the hosted requirements don't include calamine. Legacy .xls
# (Legislative Council reports) is read with calamine explicitly in geo.read_r160.
_pd.set_option("io.excel.xlsx.reader", "openpyxl")
