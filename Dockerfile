FROM python:3.12-slim

WORKDIR /app

# libreoffice-calc: recálculo headless de fórmulas en los Estados de Resultados (Panel Contable).
# --no-install-recommends evita arrastrar los "recommends" pesados de LibreOffice
# (JRE, fuentes, paquete de ayuda…), que NO se usan para `soffice --headless
# --convert-to xlsx` y inflaban la imagen ~varios cientos de MB → el build de
# Railway fallaba ("Failed to build an image", OOM/disco). El núcleo de Calc se
# instala igual porque va como Depends, no como Recommends.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq-dev gcc libreoffice-calc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["sh", "start.sh"]
