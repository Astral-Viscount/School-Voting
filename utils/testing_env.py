import os
from dotenv import find_dotenv, load_dotenv

load_dotenv(override=True)

print("working directory:", os.getcwd())
print(".env location:", find_dotenv() or "NOT FOUND")
print("SECRET_KEY set:", bool(os.getenv("SECRET_KEY")))
print("GOOGLE_CLIENT_ID:", os.getenv("GOOGLE_CLIENT_ID"))
print("ADMIN_EMAILS:", os.getenv("ADMIN_EMAILS"))
print("SCHOOL_DOMAIN:", os.getenv("SCHOOL_DOMAIN"))