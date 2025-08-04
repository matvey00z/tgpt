FROM python:3.13.5-slim-bullseye

WORKDIR /app

# Install Poetry
RUN pip install poetry

# Copy only pyproject.toml and poetry.lock to cache dependencies
COPY pyproject.toml poetry.lock* ./

RUN poetry install --no-interaction --no-ansi --no-root

# Copy the rest of the application
COPY src/* ./

CMD ["python", "bot.py"]
