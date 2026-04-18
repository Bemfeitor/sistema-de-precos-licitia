#!/usr/bin/env python3
"""
Script para criar um usuário de teste no banco de dados.
"""
import sys
import os

# Add the api directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import all models first to register them with Base
from app.database import SessionLocal, Base, engine
from app.models import user, project, product, offer, quotation
from app.models.user import User
from app.utils.auth import hash_password

def create_test_user():
    db = SessionLocal()
    try:
        # Check if user already exists
        existing = db.query(User).filter(User.email == "test@example.com").first()
        if existing:
            print("[OK] Usuario test@example.com ja existe!")
            print(f"  ID: {existing.id}")
            print(f"  Nome: {existing.name}")
            return
        
        # Create test user
        user = User(
            email="test@example.com",
            name="Usuario Teste",
            password_hash=hash_password("test123")
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        
        print("[OK] Usuario criado com sucesso!")
        print(f"  Email: test@example.com")
        print(f"  Senha: test123")
        print(f"  ID: {user.id}")
        
    except Exception as e:
        print(f"[ERRO] Falha ao criar usuario: {e}")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    create_test_user()
