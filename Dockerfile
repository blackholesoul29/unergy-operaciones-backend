FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libpq-dev gcc \
    libpango-1.0-0 libpangocairo-1.0-0 libcairo2 \
    libgdk-pixbuf2.0-0 libffi-dev shared-mime-info \
    fonts-liberation fontconfig \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["sh", "start.sh"]
