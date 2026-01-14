from flask import Flask, render_template, request
import requests, os, base64, io
from PIL import Image

app = Flask(__name__)
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

API_KEY = "AIzaSyA1UBNJ6SSEsu-aCvjUQ5aZqSCgHxpXt7M"
MODEL_URL = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={API_KEY}"

# ---------------- RULES ----------------

def is_greeting(text):
    greetings = ["hi","hello","hey","good morning","good evening","how are you"]
    risky = ["click","verify","pay","money","rupees","rs","link"]
    t = text.lower()
    return len(t.split()) <= 9 and any(g in t for g in greetings) and not any(r in t for r in risky)

def has_prize_claim(text):
    prize = ["won","winner","lottery","prize","reward","jackpot"]
    money = ["rs","rupees","₹","thousand","lakh","crore"]
    t = text.lower()
    return any(p in t for p in prize) and any(m in t for m in money)

def has_forced_action(text):
    return any(w in text.lower() for w in ["click","verify","login","pay","transfer","claim","open"])

def has_money_request(text):
    return any(w in text.lower() for w in ["money","rupees","rs","send","need","want"])

def has_threat(text):
    threats = ["kill","murder","die","harm","attack","kidnap","rape","shoot","bomb","destroy"]
    return any(t in text.lower() for t in threats)

# ---------------- GEMINI TEXT ----------------

def gemini_explain_text(content):
    prompt = f"""
Explain briefly why the following message may be safe or risky.

Message:
\"\"\"{content}\"\"\"
"""
    try:
        r = requests.post(
            MODEL_URL,
            json={"contents":[{"parts":[{"text":prompt}]}]},
            timeout=15
        )
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except:
        return "AI explanation unavailable."

# ---------------- GEMINI IMAGE (OCR + ANALYSIS) ----------------

def gemini_analyze_image(path):
    img = Image.open(path).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode()

    prompt = """
1. Extract any visible text from this image (OCR).
2. Decide if the image is:
   - REAL_NORMAL
   - AI_GENERATED
   - SCAM_TEXT_IMAGE

Respond exactly in this format:

TEXT:
<extracted text>

TYPE:
<REAL_NORMAL / AI_GENERATED / SCAM_TEXT_IMAGE>
"""

    payload = {
        "contents":[{
            "parts":[
                {"text": prompt},
                {"inline_data":{"mime_type":"image/png","data":img_b64}}
            ]
        }]
    }

    try:
        r = requests.post(MODEL_URL, json=payload, timeout=20)
        return r.json()["candidates"][0]["content"]["parts"][0]["text"].lower()
    except:
        return ""

def looks_like_message_image(img):
    w, h = img.size
    return h / w > 1.3  # typical phone screenshot ratio

# ---------------- ROUTE ----------------

@app.route("/", methods=["GET","POST"])
def index():
    result = None

    if request.method == "POST":
        message = request.form.get("message","").strip()
        link = request.form.get("video_link","").strip()
        file = request.files.get("file")

        combined = f"{message} {link}".strip()

        # -------- TEXT & LINK --------
        if combined:
            if has_threat(combined):
                state, category, confidence = "DANGEROUS", "Threat / Extortion", 99
            elif has_prize_claim(combined):
                state, category, confidence = "DANGEROUS", "Lottery / Prize Scam", 95
            elif has_forced_action(combined):
                state, category, confidence = "DANGEROUS", "Forced Action / Phishing", 90
            elif has_money_request(combined):
                state, category, confidence = "UNVERIFIED", "Money Request", 45
            elif is_greeting(combined):
                state, category, confidence = "SAFE", "Normal Conversation", 5
            else:
                state, category, confidence = "SAFE", "General Text", 20

            result = {
                "state": state,
                "category": category,
                "confidence": confidence,
                "explanation": gemini_explain_text(combined)
            }

        # -------- IMAGE (SAFE vs FAKE ONLY) --------
        if file and file.filename:
            path = os.path.join(UPLOAD_DIR, file.filename)
            file.save(path)

            img = Image.open(path).convert("RGB")
            ai_text = gemini_analyze_image(path)

            # Scam text inside image
            if any(w in ai_text for w in [
                "won","lottery","prize","bank","account",
                "verify","click","rs","rupees","upi"
            ]):
                result = {
                    "state": "DANGEROUS",
                    "category": "Scam Screenshot",
                    "confidence": 95,
                    "explanation": "Scam-related text detected inside the image."
                }

            # OCR failed but looks like message screenshot
            elif looks_like_message_image(img):
                result = {
                    "state": "DANGEROUS",
                    "category": "Suspicious Message Image",
                    "confidence": 85,
                    "explanation": "Image looks like a message/notification screenshot. Marked unsafe by design."
                }

            # AI-generated image
            elif "ai_generated" in ai_text or "synthetic" in ai_text or "deepfake" in ai_text:
                result = {
                    "state": "DANGEROUS",
                    "category": "AI Generated / Fake Image",
                    "confidence": 90,
                    "explanation": "Image appears AI-generated or manipulated."
                }

            else:
                result = {
                    "state": "SAFE",
                    "category": "Real / Normal Image",
                    "confidence": 15,
                    "explanation": "No scam indicators detected."
                }

    return render_template("index.html", result=result)

if __name__ == "__main__":
    app.run(debug=True)
