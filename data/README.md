# Calibration data

Raw downloads used to calibrate the simulation. The files themselves are git-ignored (about 4 MB);
this note records where they came from so they can be fetched again. Downloaded 2026-11-24.
Nothing in the simulation has been fitted to them yet.

## `uscrn/`: NOAA NCEI U.S. Climate Reference Network, hourly02

Source: https://www.ncei.noaa.gov/pub/data/uscrn/products/hourly02/ (public domain, U.S. Government work)

| File | Rows | SHA-256 |
|---|---|---|
| `CRNH0203-2024-AZ_Tucson_11_W.txt` | 8,784 hours | `df3770689f4cc18ae818ded93287d43da90a12943401ab7e114fcf0349ebcfea` |
| `CRNH0203-2025-AZ_Tucson_11_W.txt` | 8,760 hours | `8a3f9e470c96557cb21a0e1bab0f556630f4c8ec50965666a8f5a32a0677ea75` |
| `HEADERS.txt` (column names and units) | | `7a321027feb186ed49bead2d4315081270b9a2b8f03adaac9905f545fe4cc7a1` |
| `README.txt` (field descriptions) | | `4ace9cbbb3d63c98d8bbcf909e626d98ee4cc2ab8c1e4e59eece88eeec665872` |

Station: Tucson 11 W, Arizona, WBAN 53131, 32.24 N, 111.17 W. Whitespace-separated, 38 columns.
Times are hour-ending; UTC and local standard time are both given.

- **Missing values** use the lowest value of the field format (README note C): `-9999.0` for
  one-decimal fields such as `T_HR_AVG` and `P_CALC`, and `-99.000` for three-decimal fields
  such as `SOIL_MOISTURE_*`. Treat both as missing, never as readings.
- **Soil moisture** (m³/m³, volumetric) is reported only at **5 cm and 10 cm**. The 20, 50 and
  100 cm columns are 100% missing at this station.
- **Missing share** (soil moisture 5/10 cm, `T_HR_AVG`, `P_CALC`):
  2024: 7.8%, 7.8%, 8.0%, 0.0%. 2025: 0.03%, 0.03%, 0.03%, 0.02%.
- **2024 caveat:** from 1 January to 20 February 2024, temperature, humidity and soil readings drop
  out almost every night (about 19:00–08:00 local), while precipitation keeps reporting. That looks
  like a power problem in winter rather than random gaps, so nighttime is under-represented in those weeks.

## `mendeley/`: Mendeley Data, DOI 10.17632/jtsyb593fy.1

"Environmental Sensor Dataset for LSTM-Based Predictive Irrigation in Smart Home Gardening Using Edge IoT",
version 1, published 2026-06-01. Contributors: MD Nazmul Howlader; Fatema Tuz Zohora Priyanka
(Rajshahi University of Engineering and Technology). Licence: CC BY 4.0 (credit required).
https://data.mendeley.com/datasets/jtsyb593fy/1

| File | SHA-256 |
|---|---|
| `Edge_IoT_Predictive_Irrigation_Dataset.xlsx` (matches the checksum Mendeley publishes) | `840cb77e743ca6846d6d097cf054cb67c33f2286c547ab1a05adfc78be222686` |
| `metadata.json` (the dataset record from Mendeley's public API) | |

One sheet, 960 rows (20 days × 48), every 30 minutes from 2026-04-01 00:00 to 2026-04-20 23:30, no blanks.
Columns: `Timestamp`, `Day`, `Time`, `Temperature_C`, `Humidity_pct`, `Soil_Moisture_pct`,
`Light_Intensity`, `Pump_Status` (0/1).

Caveats: soil moisture is a sensor percentage (46.6–85.0), not volumetric m³/m³ like USCRN.
Temperature never goes below exactly 25.0 °C (182 rows sit on it), so it looks clipped. The pump
always runs for exactly 2 rows (1 hour), 14 times, roughly every other day, sometimes starting
when soil moisture is already 85%.
