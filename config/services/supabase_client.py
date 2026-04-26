import requests
import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Headers
HEADERS_DB = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

HEADERS_AUTH = {
    "apikey": SUPABASE_KEY,
    "Content-Type": "application/json"
}


# CHECK CONNECTION
def check_connection():
    try:
        url = f"{SUPABASE_URL}/rest/v1/"
        response = requests.get(url, headers=HEADERS_DB)

        print("Status:", response.status_code)
        print("Response:", response.text)

        return response.status_code == 200

    except Exception as e:
        print("Lỗi:", str(e))
        return False


# AUTH
def register(email, password):
    url = f"{SUPABASE_URL}/auth/v1/signup"
    data = {"email": email, "password": password}

    response = requests.post(url, json=data, headers=HEADERS_AUTH)

    return response.json()


def login(email, password):
    url = f"{SUPABASE_URL}/auth/v1/token?grant_type=password"
    data = {"email": email, "password": password}

    response = requests.post(url, json=data, headers=HEADERS_AUTH)

    return response.json()


# DATABASE
def insert(table, data):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    return requests.post(url, json=data, headers=HEADERS_DB).json()


def select(table, query="*"):
    url = f"{SUPABASE_URL}/rest/v1/{table}?select={query}"
    return requests.get(url, headers=HEADERS_DB).json()


def update(table, column, value, data):
    url = f"{SUPABASE_URL}/rest/v1/{table}?{column}=eq.{value}"
    return requests.patch(url, json=data, headers=HEADERS_DB).json()


def delete(table, column, value):
    url = f"{SUPABASE_URL}/rest/v1/{table}?{column}=eq.{value}"
    return requests.delete(url, headers=HEADERS_DB).json()

if __name__ == "__main__":
    result = check_connection()
    print("Kết nối:", result)