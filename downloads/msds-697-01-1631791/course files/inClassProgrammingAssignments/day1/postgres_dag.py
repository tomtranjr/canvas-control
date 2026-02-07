from airflow.sdk import DAG
from datetime import datetime
from airflow.providers.common.sql.operators.sql import SQLExecuteQueryOperator

with DAG(
    dag_id="local_postgres_example",
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    tags=["postgres", "local"],
) as dag:

    create_table = SQLExecuteQueryOperator(
        task_id="create_table",
        conn_id="local_postgres_connection",
        sql="""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            name TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """,
    )

    insert_data = SQLExecuteQueryOperator(
        task_id="insert_data",
        conn_id="local_postgres_connection",
        sql="""
        INSERT INTO users (name)
        VALUES ('Alice'), ('Bob');
        """,
    )

    query_data = SQLExecuteQueryOperator(
        task_id="query_data",
        conn_id="local_postgres_connection",
        sql="""
        SELECT * FROM users;
        """,
    )

    create_table >> insert_data >> query_data