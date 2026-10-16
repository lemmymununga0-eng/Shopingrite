"""Entry point: `uvicorn main:app --reload` (run inside the backend folder)."""
from app.factory import create_app

app = create_app()
