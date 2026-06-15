import os

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

load_dotenv()

UPSTOX_API_KEY = os.getenv("UPSTOX_API_KEY")
UPSTOX_API_SECRET = os.getenv("UPSTOX_API_SECRET")
UPSTOX_REDIRECT_URI = os.getenv("UPSTOX_REDIRECT_URI")

UPSTOX_AUTH_URL = "https://api.upstox.com/v2/login/authorization/dialog"
UPSTOX_TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"

# In-memory token store
access_token_store = {"access_token": None}

router = APIRouter()


@router.get("/login")
def login():
    """Build the Upstox authorization URL. Does not open a browser."""
    auth_url = (
        f"{UPSTOX_AUTH_URL}?response_type=code"
        f"&client_id={UPSTOX_API_KEY}"
        f"&redirect_uri={UPSTOX_REDIRECT_URI}"
    )
    return {"auth_url": auth_url}


@router.get("/callback")
async def callback(code: str):
    """Exchange the authorization code for an access token."""
    data = {
        "code": code,
        "client_id": UPSTOX_API_KEY,
        "client_secret": UPSTOX_API_SECRET,
        "redirect_uri": UPSTOX_REDIRECT_URI,
        "grant_type": "authorization_code",
    }
    headers = {
        "accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(UPSTOX_TOKEN_URL, data=data, headers=headers)

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.text)

    token_data = response.json()
    access_token_store["access_token"] = token_data.get("access_token")

    html = """
    <html>
      <body style="font-family: sans-serif; text-align: center; padding-top: 50px;">
        <h2>Upstox connected successfully</h2>
        <p>This window will close automatically.</p>
        <script>window.close();</script>
      </body>
    </html>
    """
    return HTMLResponse(content=html)


@router.get("/token-status")
def token_status():
    return {"authenticated": access_token_store["access_token"] is not None}


def get_token():
    """Helper used by other modules to fetch the stored access token."""
    token = access_token_store.get("access_token")
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated with Upstox. Visit /login first.",
        )
    return token
