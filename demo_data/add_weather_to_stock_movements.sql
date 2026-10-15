-- =============================================================
-- Parabellum ISOS - Store the weather on each Stock In / Stock Out
-- =============================================================
-- Adds three columns to the EXISTING stock_movements table. From now on the
-- app records Lipa City's weather for the day of every new Stock In / Stock
-- Out (from Open-Meteo) so the forecasting model can read it. The columns are
-- never shown in the app.
--
--   weather_temp_c       average temperature that day (deg C)
--   weather_rainfall_mm  rain that day (mm)
--   weather_wind_kmh     highest wind speed that day (km/h)
--
-- Movements recorded before this change keep NULL here (the app can't know
-- their weather retroactively). If the weather service can't be reached when
-- a movement is saved, the movement is still saved and these stay NULL.
--
-- SAFE TO RE-RUN. Does not drop or change any data.
-- HOW TO USE: Supabase -> SQL Editor -> New Query -> paste -> Run.
-- =============================================================

ALTER TABLE stock_movements
  ADD COLUMN IF NOT EXISTS weather_temp_c      NUMERIC(5,2),
  ADD COLUMN IF NOT EXISTS weather_rainfall_mm NUMERIC(8,2),
  ADD COLUMN IF NOT EXISTS weather_wind_kmh    NUMERIC(6,2);
