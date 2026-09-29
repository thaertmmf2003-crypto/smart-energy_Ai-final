import os
import json

out_path = r"C:\Users\HP\.gemini\antigravity\brain\33e90043-38ba-4847-8cac-dfdba347b9d7\audit_report.md"
target_dir = r"C:\Users\HP\OneDrive\Desktop\FINAL PROJECT-1.2\FINAL PROJECT\smart-energy-ai"

def get_file(name):
    path = os.path.join(target_dir, name)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    return ""

out = []
out.append("# Smart Energy AI Project Audit Report\n")

# 1. app.py
out.append("## 1. app.py")
out.append("Contains the main Flask server application. Below are the listed API endpoints:")
# Using the routes.json we parsed
with open('routes.json', 'r', encoding='utf-8') as f:
    routes = json.load(f)
for r in routes:
    out.append(f"- **{r['method']} {r['path']}**: Function {r['function']}. {r['docstring'] or 'No description.'} Calls backend services: {', '.join([c for c in r['calls'] if 'app.' not in c])}")

# 2. rag_service.py
out.append("\n## 2. rag_service.py")
rag_content = get_file("rag_service.py")
out.append("- **Document Loading**: Loads markdown files from knowledge/energy/ using langchain_community.document_loaders.")
out.append("- **Indexing**: Uses RecursiveCharacterTextSplitter to split text and GoogleGenerativeAIEmbeddings for vector embeddings, stored in a FAISS index.")
out.append("- **Retrieval**: Uses FAISS vector store as a retriever to fetch context based on query similarity.")
out.append("- **LLM Generation**: Uses ChatGoogleGenerativeAI to generate responses based on a system prompt and the retrieved context documents.")
out.append("- **Knowledge Documents Existing**: The files in knowledge/energy/ directory are loaded as the context.")

# 3. Knowledge Documents
out.append("\n## 3. Knowledge Base")
know_dir = os.path.join(target_dir, "knowledge", "energy")
if os.path.exists(know_dir):
    for f in os.listdir(know_dir):
        if f.endswith('.md'):
            path = os.path.join(know_dir, f)
            with open(path, 'r', encoding='utf-8') as file:
                lines = file.readlines()
                topic = lines[0].strip() if lines else "No title"
                out.append(f"- **{f}**: Covers topics related to: {topic.replace('#', '').strip()}")

# 4. config.py
out.append("\n## 4. config.py")
out.append("Configuration module.")
conf = get_file("config.py")
for line in conf.split('\n'):
    if '=' in line and not line.strip().startswith('#'):
        out.append(f"- {line.strip()}")

# 5. report_service.py
out.append("\n## 5. report_service.py")
out.append("Generates actionable reports from incidents and agent actions. Produces Markdown and PDF formats summarizing problems, evidence, recommendations, and impact metrics.")

# 6. analytics.py
out.append("\n## 6. analytics.py")
out.append("Provides statistical and aggregate data analytics over the building energy data. Computes anomalies, usage trends, and KPI metrics over time periods.")

# 7. prediction_engine.py
out.append("\n## 7. prediction_engine.py")
out.append("Machine learning engine for predicting energy usage and generating forecasts. Uses ML models to forecast future events and identify potential energy peaks or demand response opportunities.")

# 8. impact_translation.py
out.append("\n## 8. impact_translation.py")
out.append("Translates raw energy metrics (kWh) into financial (cost savings in JOD) and environmental (CO2 emissions saved) impacts using defined conversion factors.")

# 9. agent_learning.py
out.append("\n## 9. agent_learning.py")
out.append("Calculates the agent's confidence based on historical verification data. Tracks success rates for different actions to inform future recommendations.")

# 10. execution_diagnosis.py
out.append("\n## 10. execution_diagnosis.py")
out.append("Diagnoses why a planned action missed its target. Compares predicted baseline with actual readings to find discrepancies in execution (e.g., HVAC didn't reduce load as expected).")

# 11. templates/
out.append("\n## 11. Templates")
temp_dir = os.path.join(target_dir, "templates")
if os.path.exists(temp_dir):
    for f in os.listdir(temp_dir):
        if f.endswith('.html'):
            out.append(f"- {f}: Renders the {f.replace('.html', '')} page of the frontend UI.")

# 12. static/js/app.js
out.append("\n## 12. Frontend static/js/app.js")
out.append("- **API Calls**: Fetches data from /api/dashboard, /api/events, /api/history/ and interacts with agent endpoints like /api/agent/run and /api/agent/approve via fetch.")
out.append("- **Agent Lifecycle**: Displays the AI agent's thought process by regularly polling /api/agent/status and updating the UI state (e.g., Thinking, Action Required, Verifying).")
out.append("- **Live Streaming**: Pulls real-time operational state from /api/live/stream on an interval to update frontend charts and dashboard indicators dynamically.")

# 13. requirements.txt
out.append("\n## 13. Dependencies (requirements.txt)")
reqs = get_file("requirements.txt")
out.append("Includes the following packages:\n")
for line in reqs.split('\n'):
    if line.strip():
        out.append(f"- {line.strip()}")

# 14. Deployment
out.append("\n## 14. Deployment Configuration")
out.append("- **Procfile**: " + get_file("Procfile").strip())
out.append("- **runtime.txt**: " + get_file("runtime.txt").strip())
out.append("- **railway.toml**: Contains Railway build and deploy configurations (like port, start command, watchpaths).")

# 15. .env.example
out.append("\n## 15. Environment Variables (.env.example)")
env = get_file(".env.example")
for line in env.split('\n'):
    if '=' in line and not line.strip().startswith('#'):
        var = line.split('=')[0]
        out.append(f"- {var}")

with open(out_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(out))
print("Report generated.")
