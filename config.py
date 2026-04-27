import os


DB_HOST = os.environ.get('DB_HOST')
DB_USER = os.environ.get('DB_USER')
DB_PASSWORD = os.environ.get('DB_PASSWORD')
DB_NAME = os.environ.get('DB_NAME')
DB_UNIX_SOCKET = os.environ.get('DB_UNIX_SOCKET')

CUSTOMER_DB_USER = os.environ.get('CUSTOMER_DB_USER', DB_USER)
CUSTOMER_DB_PASSWORD = os.environ.get('CUSTOMER_DB_PASSWORD', DB_PASSWORD)

SECRET_KEY = os.environ.get('SECRET_KEY')

ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD')
