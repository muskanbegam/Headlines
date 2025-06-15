#!/bin/bash
echo "🚀 Starting database table creation..."
python -c "
from app import app, db
with app.app_context():
    db.create_all()
"
echo "🏁 Starting Gunicorn..."
gunicorn app:app