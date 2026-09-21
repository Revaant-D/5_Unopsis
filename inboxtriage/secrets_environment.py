"""
Loads secret configuration (SECRET_KEY, API keys, allowed hosts...) from the `.env` file.

We use the `django-environ` library to read key=value pairs from `.env` and expose them as
operating-system environment variables. This lets us:
  * keep secrets out of GitHub (`.env` is git-ignored),
  * use different values in development and production,
  * run the same code everywhere.

Example: if `.env` contains  OPENAI_API_KEY=sk-abc123  then  env('OPENAI_API_KEY')  returns it.
If a required variable is missing, environ raises ImproperlyConfigured, so the project fails
loudly instead of running with a missing or default secret.
"""

from pathlib import Path

import environ

# The reader object. Settings files call env('NAME') to fetch values.
env = environ.Env()

# Project root = the folder that contains manage.py and .env.
# This file is at <project>/inboxtriage/secrets_environment.py, so two .parent calls reach it.
# (base.py cannot lend us its BASE_DIR: base.py imports THIS file, so BASE_DIR does not exist yet.)
BASE_DIR = Path(__file__).resolve().parent.parent

# Load <project>/.env into the environment.
environ.Env.read_env(BASE_DIR / ".env")
