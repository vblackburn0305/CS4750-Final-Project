import pymysql
import pymysql.cursors
from config import (CUSTOMER_DB_PASSWORD, CUSTOMER_DB_USER, DB_HOST, DB_NAME,
                    DB_PASSWORD, DB_UNIX_SOCKET, DB_USER)


def get_db(customer=False, customer_id=None):
    """Return a new database connection with DictCursor."""
    user = CUSTOMER_DB_USER if customer else DB_USER
    password = CUSTOMER_DB_PASSWORD if customer else DB_PASSWORD

    settings = dict(
        user=user,
        password=password,
        database=DB_NAME,
        cursorclass=pymysql.cursors.DictCursor,
        charset='utf8mb4',
        autocommit=False,
    )
    if DB_UNIX_SOCKET:
        settings['unix_socket'] = DB_UNIX_SOCKET
    else:
        settings['host'] = DB_HOST

    conn = pymysql.connect(
        **settings
    )
    if customer_id is not None:
        with conn.cursor() as cur:
            cur.execute('SET @app_customer_id = %s', (customer_id,))
    return conn


def query(sql, args=None, one=False, commit=False, customer=False, customer_id=None):
    """
    Execute a SQL statement and return results.
    - one=True  → return a single row dict (or None)
    - commit=True → commit after execution (for INSERT/UPDATE/DELETE)
    Returns (rows, lastrowid) for write queries, rows for reads.
    """
    conn = get_db(customer=customer, customer_id=customer_id)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, args or ())
            if commit:
                conn.commit()
                return cur.lastrowid
            result = cur.fetchone() if one else cur.fetchall()
            return result
    finally:
        conn.close()
