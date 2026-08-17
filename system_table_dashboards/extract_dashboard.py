# Databricks notebook source
# MAGIC %md
# MAGIC ## Instructions
# MAGIC - Attach notebook to a cluster (Serverless preferred).
# MAGIC - Run the setup cells above to populate the widget dropdowns.
# MAGIC - Fill in the parameters. Select the dashboard to extract and provide the catalog and schema that were used while deploying the dashboards.
# MAGIC - Run the rest of the notebook to extract the dashboard json into the current directory.

# COMMAND ----------

# MAGIC %pip install databricks-sdk>=0.38.0
dbutils.library.restartPython()

# COMMAND ----------

import json
from pathlib import Path
import os
import re

from databricks.sdk import WorkspaceClient
from databricks.sdk.service import jobs

# Client initialized for the current workspace
w = WorkspaceClient()

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


# Store each dataset query as a `queryLines` array (one element per line) instead of a
# single escaped string. This keeps SQL changes readable as line-by-line git diffs.
# Concatenating the queryLines reproduces the original query exactly, so the format
# round-trips cleanly on deploy. Idempotent: datasets that already use queryLines are
# left untouched.
def to_query_lines(parsed):
    for i, dataset in enumerate(parsed.get("datasets", [])):
        if "query" in dataset and "queryLines" not in dataset:
            new_dataset = {}
            for key, value in dataset.items():
                if key == "query":
                    new_dataset["queryLines"] = value.splitlines(keepends=True)
                else:
                    new_dataset[key] = value
            parsed["datasets"][i] = new_dataset
    return parsed


def extract_dashboard(selected_dashboard, catalog, schema):
    dashboard_id = w.workspace.get_status(
        f"{dashboard_save_path}/{selected_dashboard}"
    ).resource_id
    dash_details = w.lakeview.get(dashboard_id).serialized_dashboard
    replaced_dash = dash_details.replace(f"{catalog}", "{catalog}").replace(
        f"{schema}", "{schema}"
    )
    # Re-tokenize in-dashboard page links back to __PAGE__/<page_name> placeholders so the
    # dashboard id is not hardcoded in the repo. Must run before the generic URL stripping
    # below (which would otherwise swallow the /pages/<page_name> segment).
    replaced_dash = re.sub(
        r'https?://[^\s)"]+?/published/pages/([^\s)"?]+)(?:\?[^\s)"]*)?',
        r"__PAGE__/\1",
        replaced_dash,
    )
    urls = re.findall(r"https?://[^\s)]+?/dashboard[^\s)]+?/published[^\s)]*", replaced_dash)
    for url in urls:
        replaced_dash = replaced_dash.replace(f"{url}", "*")
    parsed_file = json.loads(replaced_dash)
    parsed_file = to_query_lines(parsed_file)

    with open(f"{selected_dashboard}", "w") as json_file:
        json_file.write(json.dumps(parsed_file, indent=2))
    print(f'Dashboard "{selected_dashboard}" extracted successfully')


json_files, dashboard_save_path = list_json_dash_files()

# COMMAND ----------

dbutils.widgets.dropdown('selected_dashboard', json_files[0], json_files, 'Dashboard to extract') # Select the dashboard to extract
dbutils.widgets.text('catalog', 'main') # Provide the catalog that was used when the dashboard was created
dbutils.widgets.text('schema', 'default') # Provide the schema that was used when the dashboard was created

# COMMAND ----------

selected_dashboard = dbutils.widgets.get('selected_dashboard')
catalog = dbutils.widgets.get('catalog')
schema = dbutils.widgets.get('schema')

# COMMAND ----------

print("Extracting dashboard...")
extract_dashboard(selected_dashboard, catalog, schema)
