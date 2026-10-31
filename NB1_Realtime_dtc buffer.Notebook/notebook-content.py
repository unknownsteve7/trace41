# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {
# META     "lakehouse": {
# META       "default_lakehouse": "d601c8f4-e344-4fec-8704-4efa67e1cd62",
# META       "default_lakehouse_name": "trace_lakehouse",
# META       "default_lakehouse_workspace_id": "3287aba2-ea38-440d-8c5e-48bd2dc8059b",
# META       "known_lakehouses": [
# META         {
# META           "id": "d601c8f4-e344-4fec-8704-4efa67e1cd62"
# META         }
# META       ]
# META     },
# META     "environment": {
# META       "environmentId": "c910e466-07e9-8dd5-4b5f-fb9fa2ad69fe",
# META       "workspaceId": "00000000-0000-0000-0000-000000000000"
# META     }
# META   }
# META }

# CELL ********************

import requests

OTD_API_KEY = "kV0HS8CSWr6NmORI1XIPRqXm62fujtio"

endpoint = "https://otd.delhi.gov.in/api/realtime/VehiclePositions.pb"

response = requests.get(
    endpoint,
    params={"key": OTD_API_KEY},
    timeout=30
)

print("Status Code:", response.status_code)
print("Content Type:", response.headers.get("Content-Type"))
print("Response Size:", len(response.content), "bytes")


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

from google.transit import gtfs_realtime_pb2

feed = gtfs_realtime_pb2.FeedMessage()

if response.status_code == 200:
    feed.ParseFromString(response.content)

    print("GTFS Version:", feed.header.gtfs_realtime_version)
    print("Total Vehicles:", len(feed.entity))
else:
    raise Exception(f"API request failed: {response.status_code}")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

vehicles = []
poll_ts = feed.header.timestamp
for entity in feed.entity:
    if entity.HasField("vehicle"):
        vehicle = entity.vehicle
        position = vehicle.position

        speed_mps = (
            position.speed
            if position.HasField("speed")
            else None
        )

        vehicles.append({
            "vehicle_id": vehicle.vehicle.id,
            "trip_id": vehicle.trip.trip_id if vehicle.trip.HasField("trip_id") else None,
            "route_id": vehicle.trip.route_id if vehicle.trip.HasField("route_id") else None,
            "vehicle_start_time" :vehicle.start_time if vehicle.HasField("start_time") else None,
            "vehicle_start_date" :vehicle.start_date if vehicle.HasField("start_date") else None,
            "stop_id": vehicle.stop_id if vehicle.HasField("stop_id") else None,
            "current_stop_sequence": vehicle.current_stop_sequence if vehicle.HasField("current_stop_sequence") else None,
            "vehicle_current_status":vehicle.current_status if vehicle.HasField("current_status") else None,
            "latitude": position.latitude if position.HasField("latitude") else None,
            "longitude": position.longitude if position.HasField("longitude") else None,
            "speed_mps": speed_mps,
            "speed_kmh": speed_mps * 3.6 if speed_mps is not None else None,
            "poll_timestamp": poll_ts
            "vehicle_timestamp": vehicle.timestamp if vehicle.HasField("timestamp") else None
        })

import pandas as pd

df = pd.DataFrame(vehicles)

display(df.head(10))

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }
