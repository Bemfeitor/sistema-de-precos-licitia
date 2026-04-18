import sys
import os
from sqlalchemy.orm import Session
from app.database import SessionLocal, engine, Base
from app.models.user import User
from app.utils.auth import hash_password
from app.models import user, project, product, offer, quotation

def seed():
    print("Criando tabelas no banco de dados...")
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        admin_email = "admin@licitia.com.br"
        existing_user = db.query(User).filter(User.email == admin_email).first()
        
        if not existing_user:
            print(f"Criando usuário administrador: {admin_email}")
            new_user = User(
                email=admin_email,
                name="Administrador Licitia",
                password_hash=hash_password("admin123")
            )
            db.add(new_user)
            db.commit()
            print("Usuário administrador criado com sucesso!")
        else:
            print(f"Usuário {admin_email} já existe.")
            
    except Exception as e:
        print(f"Erro ao popular banco de dados: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed()
