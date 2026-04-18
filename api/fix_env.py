content = """DATABASE_URL=postgresql://postgres:K6hQEApGHDckUIfM@db.kepshoeqyivtgsrolttt.supabase.co:5432/postgres
SECRET_KEY=9a2b8c7d6e5f4g3h2i1j0k9l8m7n6o5p
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440
GEMINI_API_KEY=AIzaSyAw_yi8tvmeokeXKnLwUiYX58k2O6hAwLw
FIRECRAWL_URL=http://licitia.alanturing.com.br:3002
"""
with open('.env', 'w', encoding='utf-8') as f:
    f.write(content)
from app.config import get_settings
s = get_settings()
print(f"URL: {s.DATABASE_URL}")
