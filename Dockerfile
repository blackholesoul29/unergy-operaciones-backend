FROM python:3.12-slim

WORKDIR /app

# libreoffice-calc: recálculo headless de fórmulas en los Estados de Resultados (Panel Contable)
RUN apt-get update && apt-get install -y libpq-dev gcc libreoffice-calc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["sh", "start.sh"]
