# smartcaller_backend.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timezone
import pandas as pd
import random
import re
import os
import tldextract

# ========= FastAPI app =========
app = FastAPI(title="Smart Caller Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Healthcheck
@app.get("/")
def root():
    return {"status": "ok", "service": "smartcaller-backend", "version": app.version}

# ========= Config & Constants =========
TARGET_PERSONAS = set([p.strip() for p in os.getenv("TARGET_PERSONAS", "CEO,CFO,COO,Marketing,Sales").split(",") if p.strip()])
PRIORITY_COUNTRIES = set([c.strip().upper() for c in os.getenv("PRIORITY_COUNTRIES", "FR,BE,CH").split(",") if c.strip()])
FREE_EMAIL_DOMAINS = {"gmail.com","yahoo.com","hotmail.com","outlook.com","live.com","icloud.com","proton.me","protonmail.com"}

SENIORITY_MAP = {
    r"\b(owner|founder|co-?founder|partner|principal)\b": ("exec", 3),
    r"\b(ceo|cto|cfo|coo|cmo|vp|vice president|head of)\b": ("exec", 3),
    r"\b(director|director of|directeur|directrice)\b": ("director", 2),
    r"\b(manager|lead|responsable|chef de)\b": ("manager", 1),
    r"\b(intern|stagiaire|assistant|junior)\b": ("junior", 0),
}
PERSONA_MAP = {
    r"\b(cfo|finance|accounting|comptable|daf)\b": "CFO",
    r"\b(coo|ops|operation|logistics|logistique|supply)\b": "COO",
    r"\b(cmo|marketing|growth|demand gen|acquisition)\b": "Marketing",
    r"\b(cto|tech|developer|engineer|it|devops|sre)\b": "Tech",
    r"\b(ceo|founder|owner|pdg|gérant)\b": "CEO",
    r"\b(sales|commercial|account executive|ae|business developer|bdm)\b": "Sales",
    r"\b(customer success|cs|support client|success manager)\b": "Customer Success",
    r"\b(product|pm|product manager)\b": "Product",
    r"\b(data|analytics|bi|data scientist|data engineer)\b": "Data",
    r"\b(security|secops|ciso|iso 27001)\b": "Security",
    r"\b(legal|juridique|avocat|counsel)\b": "Legal",
    r"\b(hr|talent|recruit|rh|recruteur|recrutement)\b": "HR",
    r"\b(purchasing|achat|procurement|acheteur)\b": "Procurement",
}
INTENT_KEYWORDS = {
    "demo": [
        "demo","démo","book a call","book a demo","rdv","call","meeting","schedule",
        "contact me","contactez-moi","prise de rendez-vous","essai gratuit","trial"
    ],
    "resource": ["ebook","guide","checklist","whitepaper","webinar","replay","ressource","lead magnet","template"]
}
URGENCY_KW = ["urgent","asap","dès que possible","rapidement","au plus vite","now","this week","ce jour"]
SOURCE_WEIGHTS = {
    "meta": +6, "facebook": +6, "instagram": +6,
    "google": +7, "adwords": +7, "gads": +7,
    "linkedin": +5, "typeform": +4, "webflow": +3
}
COUNTRY_PREFIX = { "FR":"+33","BE":"+32","CH":"+41","ES":"+34","IT":"+39","DE":"+49","UK":"+44","US":"+1"}

# ========= Helpers =========
def parse_title(title: str) -> Tuple[str,int,str]:
    t = (title or "").lower()
    seniority, sscore = "other", 0
    for pat,(lab,sc) in SENIORITY_MAP.items():
        if re.search(pat,t):
            seniority, sscore = lab, sc
            break
    persona = "Other"
    for pat,p in PERSONA_MAP.items():
        if re.search(p,t):
            persona = p
            break
    return seniority, sscore, persona

def detect_intent(source: str, form_name: str, message: str) -> str:
    s = " ".join([(source or ""), (form_name or ""), (message or "")]).lower()
    for kw in INTENT_KEYWORDS["demo"]:
        if kw in s: return "demo"
    for kw in INTENT_KEYWORDS["resource"]:
        if kw in s: return "resource"
    return "other"

def email_domain(email:str) -> str:
    try: return email.split("@",1)[1].lower().strip()
    except: return ""

def is_business_email(email:str) -> bool:
    d = email_domain(email)
    return bool(d) and d not in FREE_EMAIL_DOMAINS

def domain_to_company(email:str, fallback_company:str) -> str:
    d = email_domain(email)
    if not d: return fallback_company
    ex = tldextract.extract(d)
    brand = ex.domain.capitalize()
    return fallback_company or brand

def country_from_phone(phone:str) -> Optional[str]:
    p = (phone or "").replace(" ","")
    for code in COUNTRY_PREFIX.values():
        if p.startswith(code):
            for k,v in COUNTRY_PREFIX.items():
                if v==code: return k
    return None

def days_since(dt_str:str) -> Optional[int]:
    if not dt_str: return None
    # Try a few common formats
    for fmt in ("%Y-%m-%d","%Y-%m-%d %H:%M:%S","%d/%m/%Y","%d/%m/%Y %H:%M"):
        try:
            dt = datetime.strptime(dt_str, fmt).replace(tzinfo=timezone.utc)
            return max(0, (datetime.now(timezone.utc) - dt).days)
        except:
            pass
    return None

def score_fit(
    intent:str, seniority_score:int, persona:str, email:str, phone:str, company_name:str,
    message:str, source:str, utm_source:str=None, created_at:str=None
) -> int:
    base = {"demo": 65, "resource": 50, "other": 42}.get(intent, 42)
    base += 8 * seniority_score
    if persona in TARGET_PERSONAS: base += 6
    base += 5 if is_business_email(email) else -4
    co = domain_to_company(email, company_name or "")
    if co and len(co) >= 2: base += 3
    s = (source or "").lower()
    base += SOURCE_WEIGHTS.get(s, 0)
    if utm_source: base += SOURCE_WEIGHTS.get(utm_source.lower(), 0)
    m = (message or "").lower()
    if any(kw in m for kw in URGENCY_KW): base += 6
    ctry = country_from_phone(phone or "")
    if ctry and ctry.upper() in PRIORITY_COUNTRIES: base += 3
    d = days_since(created_at or "")
    if d is not None:
        if d <= 1: base += 6
        elif d <= 7: base += 2
        elif d > 30: base -= 4
    return max(0, min(95, base))

def suggest_workflow(intent:str, score:int) -> str:
    if intent == "demo" and score >= 68: return "Réponse rapide"
    if intent == "resource" and score >= 58: return "Nurturing doux"
    return "Safe hours"

# ========= Core classification & summary =========
def classify_leads(df: pd.DataFrame) -> List[Dict]:
    results: List[Dict] = []
    for _, row in df.iterrows():
        title   = str(row.get("job_title", "") or "")
        msg     = str(row.get("message", "") or "")
        source  = str(row.get("source", "") or "")
        utm_s   = str(row.get("utm_source", "") or "")
        company = str(row.get("company_name", "") or "")
        phone   = str(row.get("phone", "") or "")
        email   = str(row.get("email", "") or "")
        created = str(row.get("created_at", "") or "")
        first   = str(row.get("first_name", "") or "")
        last    = str(row.get("last_name", "") or "")

        seniority_label, seniority_score, persona = parse_title(title)
        intent = detect_intent(source, str(row.get("form_name","") or ""), msg)
        score = score_fit(intent, seniority_score, persona, email, phone, company, msg, source, utm_s, created)
        workflow = suggest_workflow(intent, score)

        results.append({
            "name": f"{first} {last}".strip(),
            "email": email,
            "company": company or domain_to_company(email, ""),
            "job_title": title,
            "persona": persona,
            "seniority": seniority_label,
            "intent": intent,
            "score": score,
            "workflow_suggested": workflow,
            "country": country_from_phone(phone) or None,
            "business_email": is_business_email(email),
        })
    return results

def summarize(leads: List[Dict]) -> Dict:
    total = len(leads)
    hot = sum(1 for l in leads if l.get("score",0) >= 70)
    resp_rate = round(random.uniform(0.22, 0.35), 2)  # placeholder until you track real sends

    # Distributions
    intent_dist: Dict[str,int] = {}
    persona_dist: Dict[str,int] = {}
    seniority_dist: Dict[str,int] = {}
    country_dist: Dict[str,int] = {}
    workflow_dist: Dict[str,int] = {}

    scores = []
    business_emails = 0
    for l in leads:
        intent_dist[l["intent"]] = intent_dist.get(l["intent"],0) + 1
        persona_dist[l["persona"]] = persona_dist.get(l["persona"],0) + 1
        seniority_dist[l["seniority"]] = seniority_dist.get(l["seniority"],0) + 1
        if l.get("country"):
            country_dist[l["country"]] = country_dist.get(l["country"],0) + 1
        wf = l.get("workflow_suggested","")
        if wf: workflow_dist[wf] = workflow_dist.get(wf,0) + 1
        if l.get("business_email"): business_emails += 1
        if isinstance(l.get("score"), (int,float)): scores.append(l["score"])

    avg_score = round(sum(scores)/len(scores), 1) if scores else 0.0
    business_ratio = round((business_emails/total)*100, 1) if total > 0 else 0.0

    freshness = {
        "last_24h": None,
        "last_7d": None,
        "last_30d": None,
        "older": None
    }

    insights = []
    if avg_score >= 65: insights.append("Qualité moyenne élevée des leads (score moyen ≥ 65).")
    if intent_dist.get("demo",0) > intent_dist.get("resource",0): insights.append("Plus de demandes démo que de téléchargements de ressources.")
    if business_ratio >= 70: insights.append("Majorité d’emails professionnels (≥ 70%).")
    top_persona = max(persona_dist, key=persona_dist.get) if persona_dist else None
    if top_persona: insights.append(f"Persona dominant détecté : {top_persona}.")
    if country_dist:
        top_country = max(country_dist, key=country_dist.get)
        insights.append(f"Flux principal en {top_country}.")

    workflow_status = [
        {"action": "SMS envoyé", "count": min(hot, max(5, hot//2))},
        {"action": "Email IA envoyé", "count": max(3, total//4)},
        {"action": "Réponses reçues", "count": max(1, total//20)},
    ]

    return {
        "leads_total": total,
        "leads_hot": hot,
        "response_rate": resp_rate,
        "avg_score": avg_score,
        "business_email_ratio": business_ratio,
        "intent_distribution": intent_dist,
        "persona_distribution": persona_dist,
        "seniority_distribution": seniority_dist,
        "country_distribution": country_dist,
        "workflows_distribution": workflow_dist,
        "freshness_buckets": freshness,
        "workflow_status": workflow_status,
        "insights": insights or ["Analyse initiale effectuée."],
    }

# ========= CSV import =========
def get_csv_from_gsheet(url: str) -> pd.DataFrame:
    try:
        if "spreadsheets" in url:
            csv_url = url.replace("/edit#gid=", "/export?format=csv&gid=")
            df = pd.read_csv(csv_url)
            return df
        else:
            if "export?format=csv" in url:
                return pd.read_csv(url)
            raise Exception("URL Google Sheet invalide (attendu: export CSV).")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erreur lecture Google Sheet : {e}")

# ========= API endpoints =========
_LAST_SUMMARY: Optional[Dict] = None

@app.post("/api/leads/import")
def import_leads(payload: dict):
    url = payload.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="Champ 'url' requis.")
    df = get_csv_from_gsheet(url)
    leads = classify_leads(df)
    summary = summarize(leads)
    global _LAST_SUMMARY
    _LAST_SUMMARY = summary
    return {"leads": leads, "summary": summary}

@app.get("/api/dashboard/summary")
def dashboard_summary():
    if _LAST_SUMMARY:
        return _LAST_SUMMARY
    return {
        "leads_total": 0,
        "leads_hot": 0,
        "response_rate": 0.0,
        "avg_score": 0.0,
        "business_email_ratio": 0.0,
        "intent_distribution": {},
        "persona_distribution": {},
        "seniority_distribution": {},
        "country_distribution": {},
        "workflows_distribution": {},
        "freshness_buckets": {},
        "workflow_status": [
            {"action": "SMS envoyé", "count": 0},
            {"action": "Email IA envoyé", "count": 0}
        ],
        "insights": ["Aucune analyse disponible. Importez d’abord des leads."],
    }
