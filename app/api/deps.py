from fastapi import Depends
from app.core.security import verify_auth0_token

async def get_current_user(token_payload: dict = Depends(verify_auth0_token)) -> dict:
    """
    Extracts the user ID ('sub') from the token. 
    You can use this 'sub' to query or sync user records inside Supabase.
    """
    user_id = token_payload.get("sub")
    
    # Optional: Fetch or verify user profile state from Supabase database here using user_id
    
    return {
        "auth0_id": user_id,
        "email": token_payload.get("email"),
        "payload": token_payload
    }
