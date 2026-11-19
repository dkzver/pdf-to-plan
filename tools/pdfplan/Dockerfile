# Сервис разбора PDF -> планировка.
# Сборка:  docker build -t pdfplan tools/pdfplan
# Запуск:  docker run -p 8791:8791 pdfplan
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# libgl/libglib нужны OpenCV, шрифты — для схемы
RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 libgl1 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# результаты разбора пишутся сюда; в проде лучше вынести в volume
RUN mkdir -p /app/out
VOLUME ["/app/out"]

EXPOSE 8791
# Render подставляет свой PORT — слушаем его, иначе 8791
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8791} --workers 1 --timeout-keep-alive 75"]
