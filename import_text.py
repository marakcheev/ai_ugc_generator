# import_test.py
imports = [
    "flask",
    "flask_cors",
    "openai",
    "werkzeug",
    "PIL",
    "celery",
    "flask_limiter",
    "flask_login",
]

for m in imports:
    try:
        __import__(m)
        print(f"✅ {m}")
    except Exception as e:
        print(f"❌ {m}: {e}")
