FROM python:3.9-slim

WORKDIR /app

RUN pip install --upgrade pip
COPY streamlit_requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["streamlit", "run", "app.py", "--server.port", "8501"]
