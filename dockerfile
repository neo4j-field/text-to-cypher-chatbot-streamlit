FROM python:3.11-slim
MAINTAINER alexanderfournier


# Set the working directory in the container
WORKDIR /app

COPY resources/ ./resources
COPY app.py .
COPY neo4jwriter.py .
COPY service.py .
COPY drivers.py .
COPY ui/ ./ui
COPY requirements.txt .


RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8501

CMD ["streamlit", "run", "app.py"]
