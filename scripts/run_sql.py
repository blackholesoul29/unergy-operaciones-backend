"""Ejecuta scripts/actualizar_proyectos_solares.sql contra la DB de Railway."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.core.database import SessionLocal

sql_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "actualizar_proyectos_solares.sql")
with open(sql_path, encoding="utf-8") as f:
    sql = f.read()

db = SessionLocal()
try:
    for statement in sql.split(";"):
        s = statement.strip()
        if s and not s.startswith("--"):
            db.execute(text(s))
    db.commit()
    print("OK - SQL ejecutado correctamente.")
except Exception as e:
    db.rollback()
    print(f"ERROR: {e}")
    raise
finally:
    db.close()
