import os
import logging
import oracledb

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Oracle connection details
ORACLE_USER = "ADMIN"
ORACLE_PASSWORD = "Morgan2322467@"
ORACLE_DSN = "(description= (retry_count=20)(retry_delay=3)(address=(protocol=tcps)(port=1522)(host=adb.us-phoenix-1.oraclecloud.com))(connect_data=(service_name=g87903d1f88b28c_cpgfyotds37pa1l2_medium.adb.oraclecloud.com))"
WALLET_LOCATION = "/home/ubuntu/oci_wallet"
WALLET_PASSPHRASE = os.getenv("WALLET_PASSPHRASE", "Mabus23224676@")

def test_connection():
    try:
        logger.info("Attempting to connect to Oracle database...")
        # Initialize the connection with wallet (mTLS)
        connection = oracledb.connect(
            user=ORACLE_USER,
            password=ORACLE_PASSWORD,
            dsn=ORACLE_DSN,
            wallet_location=WALLET_LOCATION,
            wallet_password=WALLET_PASSPHRASE
        )
        logger.info("Successfully connected to Oracle database!")

        # Create a test table
        with connection.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE test_connectivity (
                    id NUMBER PRIMARY KEY,
                    message VARCHAR2(100)
                )
            """)
            connection.commit()
            logger.info("Created test table 'test_connectivity'")

        # Insert a test row
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO test_connectivity (id, message) VALUES (1, 'Connection Test Successful')")
            connection.commit()
            logger.info("Inserted test row into 'test_connectivity'")

        # Query the table to verify
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM test_connectivity")
            row = cursor.fetchone()
            logger.info("Query result: %s", row)

        # Clean up (drop the table)
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE test_connectivity")
            connection.commit()
            logger.info("Dropped test table 'test_connectivity'")

        connection.close()
        logger.info("Connection closed successfully")

    except oracledb.Error as e:
        logger.error(f"Oracle connection failed: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise

if __name__ == "__main__":
    test_connection()
