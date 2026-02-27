FROM python:3.11-slim


WORKDIR /app


RUN apt-get update && apt-get install -y \
    gcc \
    pkg-config \
    default-libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


COPY . .


RUN mkdir -p uploads logs


EXPOSE 5000

# Run the app
CMD ["python", "run.py"]