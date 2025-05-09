FROM python:3.9-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libaio1 \
    unzip \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Install Oracle Instant Client
RUN wget https://download.oracle.com/otn_software/linux/instantclient/211000/instantclient-basiclite-linux.x64-21.1.0.0.0.zip -O /tmp/instantclient.zip \
    && unzip /tmp/instantclient.zip -d /opt/oracle \
    && rm /tmp/instantclient.zip \
    && echo "/opt/oracle/instantclient_21_1" > /etc/ld.so.conf.d/oracle-instantclient.conf \
    && ldconfig

ENV LD_LIBRARY_PATH=/opt/oracle/instantclient_21_1

RUN pip install --upgrade pip
RUN pip install oracledb

COPY test_oracle_connectivity.py .

CMD ["python", "test_oracle_connectivity.py"]
