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

api = "kV0HS8CSWr6NmORI1XIPRqXm62fujtio"

url = "https://otd.delhi.gov.in/api/realtime/VehiclePositions.pb?key={api}"

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

%pip install requests gtfs-realtime-bindings

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }
