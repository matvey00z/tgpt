FROM python:3.11.2-slim-bullseye

WORKDIR /app

# Install Poetry
RUN pip install poetry

# Copy only pyproject.toml and poetry.lock to cache dependencies
COPY pyproject.toml poetry.lock* ./

# Install dependencies without dev dependencies
RUN poetry config virtualenvs.create false \
    && poetry install --no-dev --no-interaction --no-ansi

# Copy the rest of the application
COPY src/* ./

CMD ["python", "bot.py"]
