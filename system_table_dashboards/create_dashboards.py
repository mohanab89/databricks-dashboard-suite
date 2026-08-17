# Databricks notebook source
# MAGIC %md
# MAGIC ## Instructions
# MAGIC - Attach notebook to a cluster (Serverless preferred).
# MAGIC - Run Cells 2, 3 and 4 for the input widget parameters to get polpulated.
# MAGIC - Fill in the parameters. Details on these parameters can be found [here](https://github.com/mohanab89/databricks-dashboard-suite#run-the-create_dashboards-notebook).
# MAGIC - Run the rest of the notebook to deploy dashboards.

# COMMAND ----------

# MAGIC %pip install databricks-sdk>=0.38.0
dbutils.library.restartPython()

# COMMAND ----------

from databricks.sdk import AccountClient
from databricks.sdk import WorkspaceClient
from databricks.sdk.service import jobs
from pyspark.errors import PySparkException

# Client initialized for the current workspace
w = WorkspaceClient()

warehouses = w.warehouses.list()
warehouse_names = [f"{w.name} - ({w.id})**" if w.enable_serverless_compute else f"{w.name} - ({w.id})" for w in warehouses]

# COMMAND ----------

dbutils.widgets.multiselect('actions', 'All', choices=['All', 'Deploy Dashboards', 'Publish Dashboards', 'Create Functions', 'Create/refresh Tables']) # Select the actions to perform
dbutils.widgets.dropdown('warehouse', warehouse_names[0], choices=warehouse_names) # Select a warehouse which would be used in dashboards
dbutils.widgets.text('catalog', 'main') # Provide a catalog where you have read/write permissions where required functions will be created. Catalog will be created if not found.
dbutils.widgets.text('schema', 'default') # Provide a schema where you have read/write permissions where required functions will be created. Schema will be created if not found.
dbutils.widgets.text('tags_to_consider_for_team_name', 'team_name,group') # Provide a comma separated list of tags that should be considered for getting team names
dbutils.widgets.text('account_host', 'https://accounts.cloud.databricks.com/') # Provide the host for account console
dbutils.widgets.text('account_id', '') # Provide the account identifier from account console
dbutils.widgets.text('client_id', '') # Provide a M2M client ID for authenticating to account level access
dbutils.widgets.text('client_secret', '') # Provide a M2M client secret for authenticating to account level

# COMMAND ----------

actions = dbutils.widgets.get('actions')
catalog = dbutils.widgets.get('catalog')
schema = dbutils.widgets.get('schema')
account_host = dbutils.widgets.get('account_host')
account_id = dbutils.widgets.get('account_id')
client_id = dbutils.widgets.get('client_id')
client_secret = dbutils.widgets.get('client_secret')
tags_to_consider_for_team_name = dbutils.widgets.get('tags_to_consider_for_team_name')
warehouse = dbutils.widgets.get('warehouse')
warehouse_id = warehouse.split("(")[1].split(")")[0]

try:
    spark.sql(f'USE CATALOG {catalog}')
except PySparkException as ex:
  if (ex.getErrorClass() == "NO_SUCH_CATALOG_EXCEPTION"):
    spark.sql(f'CREATE CATALOG IF NOT EXISTS {catalog}')
  else:
    raise
spark.sql(f'CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}')

# COMMAND ----------

import json
from pathlib import Path
import os
from pyspark.sql.types import StringType
from pyspark.sql.functions import col
from databricks.sdk.service.dashboards import Dashboard

# List all the JSON files from the current folder
def list_json_dash_files():
    notebook_folder = json.loads(
        dbutils.notebook.entry_point.getDbutils().notebook().getContext().safeToJson()
    )["attributes"]["notebook_path"]
    new_folder_name = "dashboard_assess_dbx_costs"
    dashboard_save_path = (
        f'{notebook_folder.rsplit("/", 1)[0]}/dashboard_assess_dbx_costs'
    )
    Path(new_folder_name).mkdir(parents=True, exist_ok=True)
    w.workspace.mkdirs(dashboard_save_path)  # ensure the workspace folder exists (idempotent)
    json_files = [
        f for f in os.listdir(".") if os.path.isfile(f) and f.endswith(".lvdash.json")
    ]
    print(f"Dashboard JSON files found: {json_files}")
    return json_files, dashboard_save_path


# Deploy dashboards from json files
def deploy_dashboards():
    # Get all JSON files in the current folder
    json_files, dashboard_save_path = list_json_dash_files()
    dash_name_id_dict = {}

    # Process each JSON
    for json_file in json_files:
        with open(json_file, "r") as file:
            data = file.read().rstrip()
        replaced_data = data.replace("{catalog}", catalog).replace("{schema}", schema)

        dash_name = json_file.split(".")[0]

        try:
            # Update if the dashboard exists
            dashboard_id = w.workspace.get_status(
                f"{dashboard_save_path}/{json_file}"
            ).resource_id
            curr_dash = w.lakeview.get(dashboard_id)
            curr_dash.serialized_dashboard = replaced_data
            dash_updated = w.lakeview.update(
                dashboard_id=dashboard_id,
                dashboard=curr_dash,
            )
            print(
                f'Dashboard "{dash_name}" updated successfully at {dash_updated.create_time}'
            )
            dash_name_id_dict[dash_name] = dashboard_id
        except Exception as e:
            # Create a new dashboard if it doesn't exist
            if "doesn't exist" in str(e):
                new_dash = Dashboard(
                    display_name=dash_name,
                    parent_path=dashboard_save_path,
                    serialized_dashboard=replaced_data,
                    warehouse_id=warehouse_id)
                dash_created = w.lakeview.create(dashboard=new_dash)
                dashboard_id = dash_created.dashboard_id
                print(
                    f'Dashboard "{dash_name}" created successfully at {dash_created.create_time}'
                )
                dash_name_id_dict[dash_name] = dashboard_id
            else:
                raise e

    # Update URLs in the index dashboard
    for json_file in json_files:
        if "Databricks" in json_file:
            with open(json_file, "r") as file:
                data = file.read().rstrip()
            replaced_data = data.replace("{catalog}", catalog).replace(
                "{schema}", schema
            )

            host_url = f"https://{spark.conf.get('spark.databricks.workspaceUrl')}"

            for dash_name, dashboard_id in dash_name_id_dict.items():
                str_to_replace = f"**[{dash_name}](*)**"
                to_replace_with = f"**[{dash_name}]({host_url}/dashboardsv3/{dashboard_id}/published)**"
                replaced_data = replaced_data.replace(
                    f"{str_to_replace}", f"{to_replace_with}"
                )

            dashboard_id = w.workspace.get_status(
                f"{dashboard_save_path}/{json_file}"
            ).resource_id
            curr_dash = w.lakeview.get(dashboard_id)
            curr_dash.serialized_dashboard = replaced_data
            dash_updated = w.lakeview.update(
                dashboard_id=dashboard_id,
                dashboard=curr_dash,
            )
            print(
                f'Dashboard "{dash_name}" updated successfully at {dash_updated.create_time} with links to other dashboards'
            )
            print(f"{host_url}/dashboardsv3/{dashboard_id}/published")
            break


# Publish dashboards
def publish_dashboards():
    json_files, dashboard_save_path = list_json_dash_files()

    for json_file in json_files:
        dash_name = json_file.split(".")[0]

        try:
            dashboard_id = w.workspace.get_status(
                f"{dashboard_save_path}/{json_file}"
            ).resource_id
            dash_published = w.lakeview.publish(
                dashboard_id=dashboard_id, warehouse_id=warehouse_id
            )
            print(
                f'Dashboard "{dash_name}" published successfully at {dash_published.revision_create_time}'
            )
        except Exception as e:
            print(f"Dashboard {dash_name} could not be published")
            raise e


def create_sql_functions():
    # Create function to extract job type from SKU
    print(f"Creating {catalog}.{schema}.job_type_from_sku function...")
    spark.sql(
        f"""CREATE OR REPLACE FUNCTION {catalog}.{schema}.job_type_from_sku(sku STRING)
          RETURNS STRING
          RETURN
          CASE
            WHEN sku LIKE '%JOBS_SERVERLESS%' THEN 'JOBS_SERVERLESS'
            WHEN sku LIKE '%JOBS_COMPUTE_(PHOTON)%' THEN 'JOBS_COMPUTE_PHOTON'
            WHEN sku LIKE '%JOBS_COMPUTE%' THEN 'JOBS_COMPUTE'
            WHEN sku IS NULL THEN 'UNKNOWN'
            ELSE 'OTHER'
          END;"""
    )
    print(f"Function {catalog}.{schema}.job_type_from_sku created successfully")

    # Create function to extract SQL type from SKU
    print(f"Creating {catalog}.{schema}.sql_type_from_sku function...")
    spark.sql(
        f"""CREATE OR REPLACE FUNCTION {catalog}.{schema}.sql_type_from_sku(sku STRING)
          RETURNS STRING
          RETURN
          CASE
            WHEN sku LIKE '%SERVERLESS_SQL%' THEN 'SQL_SERVERLESS'
            WHEN sku LIKE '%SQL_PRO%' THEN 'SQL_PRO'
            WHEN sku LIKE '%SQL%' THEN 'SQL_CLASSIC'
            WHEN sku IS NULL THEN 'UNKNOWN'
            ELSE 'OTHER'
          END;"""
    )
    print(f"Function {catalog}.{schema}.sql_type_from_sku created successfully")

    # Programatically create function to extract team name from the tags using input parameter
    print(f"Creating {catalog}.{schema}.team_name_from_tags function...")
    keys = [] if tags_to_consider_for_team_name == '' else tags_to_consider_for_team_name.split(",")
    param_cols = ["cluster_tags", "job_tags"]

    # Dynamically construct the CASE statement
    case_list = []
    for each_param_col in param_cols:
        case_statement = "CASE  \n"
        if len(keys) > 0:
            for key in keys:
                case_statement += f"WHEN map_contains_key({each_param_col}, '{key.strip()}') THEN lower({each_param_col}.`{key.strip()}`) \n"
        case_statement += f"WHEN map_contains_key({each_param_col}, 'LakehouseMonitoring') AND {each_param_col}.LakehouseMonitoring = 'true' THEN 'LakehouseMonitoring' \n"
        case_statement += f"ELSE NULL END AS {each_param_col}_team_name_init \n"
        case_list.append(case_statement)

    query = f"SELECT ifnull({param_cols[0]}_team_name_init, {param_cols[1]}_team_name_init) as team_name_init FROM \n (SELECT {', '.join(case_list)})"

    # Final SQL query
    query = f"(SELECT ifnull(team_name_init, 'unknown') AS team_name FROM \n ({query}))"

    # Create the function
    spark.sql(
        f"""create or replace function {catalog}.{schema}.team_name_from_tags(cluster_tags MAP<STRING,STRING>, job_tags MAP<STRING,STRING>)
        RETURNS STRING RETURN {query}"""
    )
    print(f"Function {catalog}.{schema}.team_name_from_tags created successfully")


def create_update_tables():
    # Programatically create/update a table for workspace id to name mapping
    print(f"Creating {catalog}.{schema}.workspace_reference table...")
    spark.sql(
        f"CREATE TABLE IF NOT EXISTS {catalog}.{schema}.workspace_reference (workspace_id STRING, workspace_name STRING)"
    )
    try:
        a = AccountClient(
            host=account_host,
            account_id=account_id,
            client_id=client_id,
            client_secret=client_secret,
        )
        workspaces = [
            [workspace.workspace_id, workspace.workspace_name]
            for workspace in a.workspaces.list()
        ]
        workspace_ref = spark.createDataFrame(
            workspaces, ["workspace_id", "workspace_name"]
        )
        workspace_ref = workspace_ref.withColumn("workspace_id", col("workspace_id").cast(StringType()))
        workspace_ref.createOrReplaceTempView('workspace_ref')
        workspace_ref = spark.sql(
            f"""SELECT * FROM workspace_ref
            UNION
            select distinct workspace_id, workspace_id as workspace_name from system.billing.usage
            WHERE workspace_id NOT IN (SELECT workspace_id FROM workspace_ref)"""
        )
    except Exception as e:
        print("\t Creating default workspace_reference table.")
        workspace_ref = spark.sql(
            f"""SELECT * FROM {catalog}.{schema}.workspace_reference
            UNION
            select distinct workspace_id, workspace_id as workspace_name from system.billing.usage
            WHERE workspace_id NOT IN (SELECT workspace_id FROM {catalog}.{schema}.workspace_reference)"""
        )

    workspace_ref.write.mode("overwrite").saveAsTable(
        f"{catalog}.{schema}.workspace_reference"
    )
    print(f"Table {catalog}.{schema}.workspace_reference created/updated successfully")

    # Programatically create/update a table for warehouse id to name mapping
    print(f"Creating {catalog}.{schema}.warehouse_reference table...")
    spark.sql(
        f"CREATE TABLE IF NOT EXISTS {catalog}.{schema}.warehouse_reference (workspace_id STRING, warehouse_id STRING, warehouse_name STRING)"
    )
    warehouse_names = spark.sql(
        f"""WITH warehouse_names AS (
              SELECT
                workspace_id,
                GET_JSON_OBJECT(response.result, '$.id') AS warehouse_id,
                max(request_params.name) AS warehouse_name
              from
                system.access.audit
              WHERE
                service_name = 'databrickssql'
              group by
                workspace_id,
                GET_JSON_OBJECT(response.result, '$.id')
            ),
            union_warehouses AS (
              SELECT * FROM warehouse_names
              UNION
              SELECT * FROM {catalog}.{schema}.warehouse_reference
            )
            SELECT * FROM union_warehouses"""
    )

    warehouse_names.write.mode("overwrite").saveAsTable(
        f"{catalog}.{schema}.warehouse_reference"
    )
    print(f"Table {catalog}.{schema}.warehouse_reference created/updated successfully")

# COMMAND ----------

all_actions = actions.split(",")
for each_action in all_actions:
    if each_action == "Deploy Dashboards":
        print("Deploying dashboards...")
        deploy_dashboards()
    elif each_action == "Publish Dashboards":
        print("Publishing dashboards...")
        publish_dashboards()
    elif each_action == "Create Functions":
        print("Creating functions...")
        create_sql_functions()
    elif each_action == "Create/refresh Tables":
        print("Creating/refreshing tables...")
        create_update_tables()
    else:
        print(f"Performing all actions...")
        deploy_dashboards()
        publish_dashboards()
        create_sql_functions()
        create_update_tables()
        break
