FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY backend/requirements.txt .
RUN grep -vE '^(pytest|black|isort|flake8|mypy)' requirements.txt > req.txt \
 && pip install -r req.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/
COPY backend/ .
RUN rm -rf tests __pycache__ .env
EXPOSE 8001
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]
