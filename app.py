import streamlit as st
from openai import OpenAI
import os
import base64
import requests
import pandas as pd
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from sqlalchemy import create_engine, Column, Integer, String, Float
from sqlalchemy.orm import declarative_base, sessionmaker
from sarvamai import SarvamAI

# =============================
# CONFIG
# =============================
st.set_page_config(page_title="AI Agri Platform", layout="wide")
st.title("🌱 AI Powered Soil Health & Crop Advisory System")

# =============================
# DATABASE SETUP
# =============================
engine = create_engine("sqlite:///soil_reports.db")
Base = declarative_base()

class SoilReport(Base):
    __tablename__ = "soil_reports"
    id = Column(Integer, primary_key=True)
    farmer_name = Column(String)
    ph = Column(Float)
    nitrogen = Column(String)
    phosphorus = Column(String)
    potassium = Column(String)
    organic_carbon = Column(String)

Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()

# =============================
# HELPER FUNCTIONS
# =============================
def calculate_score(ph, nitrogen, phosphorus, potassium, organic):
    score = 100
    if ph > 8 or ph < 5.5: score -= 15
    if nitrogen == "Low": score -= 20
    if phosphorus == "Low": score -= 15
    if potassium == "Low": score -= 15
    if organic == "Low": score -= 20
    return max(score, 0)

def fertilizer_advice(nitrogen):
    return "यूरिया 45-50 kg प्रति एकड़ डालें।" if nitrogen=="Low" else "नाइट्रोजन संतुलित है।"

def get_weather(city):
    api_key = st.secrets.get("OPENWEATHER_API_KEY", "")
    if not api_key or not city.strip(): 
        return "मौसम डेटा उपलब्ध नहीं"
    try:
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}&units=metric"
        data = requests.get(url).json()
        return f"तापमान: {data['main']['temp']}°C, मौसम: {data['weather'][0]['description']}"
    except:
        return "मौसम डेटा उपलब्ध नहीं"

def generate_pdf_bytes(text):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    y = 750
    for line in text.split("\n"):
        c.drawString(40, y, line)
        y -= 15
    c.save()
    buffer.seek(0)
    return buffer

def text_to_speech(text):
    api_key = st.secrets.get("SARVAM_API_KEY", "")
    if not api_key: 
        st.warning("SarvamAI API key missing")
        return None
    os.environ["SARVAM_API_KEY"] = api_key
    client = SarvamAI(api_subscription_key=api_key)
    text = text[:1500]  # limit length for speed
    try:
        tts = client.text_to_speech.convert(text=text, target_language_code="hi-IN", model="bulbul:v3", speaker="shubh")
        audio_bytes = base64.b64decode(tts.audios[0])
        return BytesIO(audio_bytes)
    except Exception as e:
        st.warning("TTS failed: " + str(e))
        return None

# =============================
# OPENROUTER LLM CLIENT
# =============================
client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=st.secrets["OPENROUTER_API_KEY"])

@st.cache_data(show_spinner=False)
def get_analysis(ph, nitrogen, phosphorus, potassium, organic, weather_info):
    sample = f"""
pH: {ph}
Nitrogen: {nitrogen}
Phosphorus: {phosphorus}
Potassium: {potassium}
Organic Carbon: {organic}
"""
    prompt = f"""
आप भारतीय कृषि वैज्ञानिक हैं।
इस मिट्टी रिपोर्ट का विश्लेषण करें:
{sample}

मौसम जानकारी:
{weather_info}

सुधार योजना, फसल सुझाव और 6 महीने की योजना दें।
उत्तर हिंदी में दें।
"""
    response = client.chat.completions.create(
        model="openrouter/free",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content

import time  # <-- import time module

# =============================
# STREAMLIT UI
# =============================
farmer_name = st.text_input("👨‍🌾 किसान का नाम")
city = st.text_input("📍 शहर (मौसम सलाह हेतु)")

ph = st.number_input("pH मान", 0.0, 14.0, 7.0)
nitrogen = st.selectbox("Nitrogen", ["Low", "Medium", "High"])
phosphorus = st.selectbox("Phosphorus", ["Low", "Medium", "High"])
potassium = st.selectbox("Potassium", ["Low", "Medium", "High"])
organic = st.selectbox("Organic Carbon", ["Low", "Medium", "High"])

import concurrent.futures

if st.button("🔍 Analyze Soil"):
    timing_info = {}

    # 1️⃣ Save to DB
    start = time.time()
    report = SoilReport(
        farmer_name=farmer_name,
        ph=ph,
        nitrogen=nitrogen,
        phosphorus=phosphorus,
        potassium=potassium,
        organic_carbon=organic
    )
    session.add(report)
    session.commit()
    timing_info["DB Save"] = time.time() - start

    # 2️⃣ Score calculation
    start = time.time()
    score = calculate_score(ph, nitrogen, phosphorus, potassium, organic)
    timing_info["Score Calculation"] = time.time() - start

    # 3️⃣ Weather API
    start = time.time()
    weather_info = get_weather(city)
    timing_info["Weather API"] = time.time() - start

    # 4️⃣ Prepare final report template (without LLM/TTS yet)
    final_report_template = f"""
🌱 Soil Health Score: {score}/100

🌦 मौसम जानकारी:
{weather_info}
"""
    
    # 5️⃣ Run LLM and TTS concurrently
    start = time.time()
    with st.spinner("🤖 AI is analyzing soil and generating audio, please wait..."):
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future_llm = executor.submit(get_analysis, ph, nitrogen, phosphorus, potassium, organic, weather_info)
            # We'll generate TTS after we get analysis text
            analysis = future_llm.result()
            final_report = final_report_template + f"""
🤖 AI विश्लेषण:
{analysis}

💊 उर्वरक सलाह:
{fertilizer_advice(nitrogen)}
"""
            future_tts = executor.submit(text_to_speech, final_report)
            audio_buffer = future_tts.result()
    timing_info["LLM + TTS"] = time.time() - start

    # 6️⃣ PDF generation
    start = time.time()
    pdf_buffer = generate_pdf_bytes(final_report)
    timing_info["PDF Generation"] = time.time() - start

    # 7️⃣ Display final report
    st.success("📋 Final Soil Report")
    st.write(final_report)
    st.download_button("📄 Download PDF", pdf_buffer, file_name="Soil_Report.pdf")
    if audio_buffer:
        st.audio(audio_buffer)

    # 8️⃣ Print timing info
    #st.subheader("⏱ Module Execution Time (seconds)")
    #for module, t in timing_info.items():
    #    st.write(f"{module}: {t:.2f}s")

# =============================
# HISTORY SECTION
# =============================
st.subheader("📊 पिछले रिपोर्ट")
@st.cache_data
def get_history():
    return session.query(SoilReport).order_by(SoilReport.id.desc()).limit(5).all()

reports = get_history()
if reports:
    data = [{"Farmer": r.farmer_name, "pH": r.ph, "N": r.nitrogen,
             "P": r.phosphorus, "K": r.potassium, "Organic": r.organic_carbon} for r in reports]
    st.dataframe(pd.DataFrame(data))