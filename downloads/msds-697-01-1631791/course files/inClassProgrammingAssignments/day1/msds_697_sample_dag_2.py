from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator
from airflow.providers.standard.operators.python import PythonOperator
from datetime import datetime,timedelta

with DAG(dag_id="msds_697_dag_2", 
         start_date=datetime(2025, 1, 23), 
         end_date=datetime(2025, 12, 31),
         schedule="@once") as dag:
         
    def py_function():
        print("I am called from airflow python operator")
         
    task1 = BashOperator(task_id="task1",
                         bash_command="echo 'Hello Mahesh'")

    task2 = PythonOperator(task_id="task2",
                           python_callable=py_function,)
    task1 >> task2