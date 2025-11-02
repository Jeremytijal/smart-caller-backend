from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import random

app = FastAPI()

# CORS: allow frontend (Lovable) to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Healthcheck / root
@app.get("/")
def root():
    return {"status": "ok", "service": "smartcaller-backend", "version": "v2"}

def get_csv_from_gsheet(url: str) -> pd.DataFrame:
    try:
        if "spreadsheets" in url:
            csv_url = url.replace("/edit#gid=", "/export?format=csv&gid=")
            df = pd.read_csv(csv_url)
            return df
        else:
            raise Exception("URL invalide.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erreur lecture Google Sheet : {e}")

def classify_leads(df: pd.DataFrame):
    intents = ["demo", "resource", "other"]
    workflows = {
        "demo": "Réponse rapide",
        "resource": "Nurturing doux",
        "other": "Safe hours"
    }
    results = []
    for _, row in df.iterrows():
        intent = random.choice(intents)
        score = random.randint(40, 95)
        workflow = workflows[intent]
        results.append({
            "name": f"{row.get('first_name', '')} {row.get('last_name', '')}".strip(),
            "email": row.get("email", ""),
            "company": row.get("company_name", ""),
            "job_title": row.get("job_title", ""),
            "intent": intent,
            "score": score,
            "workflow_suggested": workflow
        })
    return results

@app.post("/api/leads/import")
def import_leads(payload: dict):
    url = payload.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="Champ 'url' requis.")
    df = get_csv_from_gsheet(url)
    leads = classify_leads(df)
    summary = {
        "leads_total": len(leads),
        "leads_hot": len([l for l in leads if l["score"] > 70]),
        "response_rate": round(random.uniform(0.2, 0.35), 2),
        "intent_distribution": {
            "demo": len([l for l in leads if l["intent"] == "demo"]),
            "resource": len([l for l in leads if l["intent"] == "resource"]),
            "other": len([l for l in leads if l["intent"] == "other"])
        },
        "workflow_status": [
            {"action": "SMS envoyé", "count": random.randint(5, 20)},
            {"action": "Email IA envoyé", "count": random.randint(3, 10)},
            {"action": "Réponses reçues", "count": random.randint(1, 5)}
        ],
        "insights": [
            "Les leads de démo réagissent 2× plus vite que les téléchargements.",
            "45 % de C-level détectés.",
            "Temps moyen de réaction : 6 minutes."
        ]
    }
    return {"leads": leads, "summary": summary}

@app.get("/api/dashboard/summary")
def dashboard_summary():
    data = {
        "leads_total": 48,
        "leads_hot": 17,
        "response_rate": 0.26,
        "intent_distribution": {"demo": 60, "resource": 25, "other": 15},
        "workflow_status": [
            {"action": "SMS envoyé", "count": 17},
            {"action": "Email IA envoyé", "count": 8},
            {"action": "Réponses reçues", "count": 2}
        ],
        "insights": [
            "Les leads de démo réagissent 2× plus vite.",
            "45 % de C-level détectés.",
            "Temps moyen de réaction : 6 min."
        ]
    }
    return data
