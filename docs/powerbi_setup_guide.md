# Power BI Dashboard Setup Guide (TRACE)

This guide explains how to build the 5-page **TRACE** Power BI dashboard using the datasets exported in [`dashboard/export/`](file:///c:/Users/nagam/z_world/trace41/trace41/dashboard/export/).

---

## 📥 Data Sources to Import
In Power BI Desktop, click **Get Data → Text/CSV** and import the following 6 files from `dashboard/export/`:

1. `pbi_fleet_kpis.csv`
2. `pbi_hourly_patterns.csv`
3. `pbi_bunching_hotspots.csv`
4. `pbi_complaints.csv`
5. `pbi_ml_metrics.csv`
6. `pbi_route_map_stops.csv`

---

## 📑 5-Page Dashboard Layout

### Page 1: Fleet Overview & Reliability KPIs
* **Top KPI Cards**:
  - Fleet On-Time Performance (OTP %): `14.4%` (5-min threshold)
  - Average Delay: `56.7 min`
  - Total Active Trips Monitored: `4,792`
  - Unique Routes Covered: `1,262`
* **Visual 1 (Bar Chart)**: Top 10 Worst Routes by Average Delay (using `pbi_fleet_kpis.csv`).
* **Visual 2 (Scatter Plot)**: Total Trips vs. Average Delay per Route.

---

### Page 2: Temporal & Hourly Trends
* **Visual 1 (Line Chart)**: Average Delay by Hour of Day (from `pbi_hourly_patterns.csv`).
* **Visual 2 (Column Chart)**: Trips Observed across Peak vs Off-Peak hours.
* **Callout Textbox**: 
  > *"Statistical test confirms significant delay clustering during mid-day dispatch waves compared to early morning operations."*

---

### Page 3: Headway Regularity & Bunching Hotspots
* **Visual 1 (Bar Chart)**: Routes with Highest Bunching Rates (`pbi_bunching_hotspots.csv`).
* **Visual 2 (Histogram / Scatter)**: Average Headway vs. Bunching Rate.
* **Callout Textbox**:
  > *"Spearman rank correlation (\rho = -0.481, p < 0.001) proves that tight headway intervals (< 2 min) drive severe bunching cascades across high-frequency corridors."*

---

### Page 4: Geographic Corridor Map
* **Visual 1 (Map Visual)**:
  - Latitude: `lat` (from `pbi_route_map_stops.csv`)
  - Longitude: `lon`
  - Tooltip: `stop_name`, `stop_id`
  - Highlights Delhi's major radial transit hubs (Azadpur, Kashmere Gate, Dhaula Kuan, Anand Vihar).

---

### Page 5: ML Delay Prediction & Passenger Feedback
* **Section A (ML Performance)**:
  - Table / Card: MAE (`39.2 min`), RMSE (`54.5 min`), Classification Accuracy (`83.7%`).
  - Bar Chart: Feature Importance (Route Profile 68.8%, Headway 24.7%, Ping Density 6.5%).
* **Section B (Passenger Feedback - Simulated)**:
  - Donut Chart: Complaint Categories (Late Arrival 37%, No Show 23%, Overcrowding 22%).
  - Image: Embed [`qr/sample_qr_bus_interior.png`](file:///c:/Users/nagam/z_world/trace41/trace41/qr/sample_qr_bus_interior.png) displaying the vehicle-specific complaint QR card.
  - Label: *"Passenger grievance data generated via synthetic simulation for architecture demonstration."*
