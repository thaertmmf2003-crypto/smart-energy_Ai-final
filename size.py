import os

target_dir = r"C:\Users\HP\OneDrive\Desktop\FINAL PROJECT-1.2\FINAL PROJECT\smart-energy-ai"
files = [
    "app.py", "rag_service.py", "config.py", "report_service.py",
    "analytics.py", "prediction_engine.py", "impact_translation.py",
    "agent_learning.py", "execution_diagnosis.py", "requirements.txt",
    "Procfile", "railway.toml", "runtime.txt", ".env.example", "static/js/app.js"
]

for f in files:
    path = os.path.join(target_dir, f)
    if os.path.exists(path):
        print(f"{f}: {os.path.getsize(path)} bytes")

print("\nTemplates:")
templates_dir = os.path.join(target_dir, "templates")
if os.path.exists(templates_dir):
    for root, dirs, fs in os.walk(templates_dir):
        for file in fs:
            print(f"templates/{file}: {os.path.getsize(os.path.join(root, file))} bytes")

print("\nKnowledge:")
know_dir = os.path.join(target_dir, "knowledge", "energy")
if os.path.exists(know_dir):
    for root, dirs, fs in os.walk(know_dir):
        for file in fs:
            print(f"knowledge/energy/{file}: {os.path.getsize(os.path.join(root, file))} bytes")
