from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator
from datetime import datetime,timedelta

with DAG(dag_id="msds_697_dag_1", 
         start_date=datetime(2025, 1, 23), 
         end_date=datetime(2026, 12, 31),
         schedule="@once") as dag:
         
     task1 = BashOperator(task_id="task1",
                          bash_command="echo 'Hello DDS SPRING 2026'")
     task1