#!/usr/bin/env python
import streamlit as st
from openai import OpenAI
import os
import base64
import requests
import pandas as pd
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
# SOIL SCORE FUNCTION
# =============================
def calculate_score(ph, nitrogen, phosphorus, potassium, organic):
    score = 100
    if ph > 8 or ph < 5.5:
        score -= 15
    if nitrogen == "Low":
        score -= 20
    if phosphorus == "Low":
        score -= 15
    if potassium == "Low":
        score -= 15
    if organic == "Low":
        score -= 20
    return max(score, 0)

# =============================
# FERTILIZER CALCULATOR
# =============================
def fertilizer_advice(nitrogen):
    if nitrogen == "Low":
        return "यूरिया 45-50 kg प्रति एकड़ डालें।"
    return "नाइट्रोजन संतुलित है।"

# =============================
# WEATHER API
# =============================
def get_weather(city):    
    api_key = st.secrets.get("OPENWEATHER_API_KEY", "")
    if not api_key:
        return "मौसम डेटा उपलब्ध नहीं (API key missing)"
    try:
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}&units=metric"
        data = requests.get(url).json()
        return f"तापमान: {data['main']['temp']}°C, मौसम: {data['weather'][0]['description']}"
    except:
        return "मौसम डेटा उपलब्ध नहीं"

# =============================
# PDF GENERATOR
# =============================
import tempfile

def generate_pdf(text):
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    c = canvas.Canvas(tmp_file.name, pagesize=letter)
    y = 750
    for line in text.split("\n"):
        c.drawString(40, y, line)
        y -= 15
    c.save()
    return tmp_file.name

# =============================
# TTS FUNCTION (Hindi)
# =============================
def text_to_speech(text):
    api_key = st.secrets.get("SARVAM_API_KEY", "")
    if not api_key:
        st.warning("SarvamAI API key missing")
        return None
    os.environ["SARVAM_API_KEY"] = api_key
    client = SarvamAI(api_subscription_key=api_key)

    if len(text) > 2500:
        text = text[:2500]

    try:
        tts = client.text_to_speech.convert(
            text=text,
            target_language_code="hi-IN",
            model="bulbul:v3",
            speaker="shubh"
        )
        audio_bytes = base64.b64decode(tts.audios[0])
        with open("soil_audio.wav", "wb") as f:
            f.write(audio_bytes)
        return "soil_audio.wav"
    except Exception as e:
        st.warning("TTS failed: " + str(e))
        return None

# =============================
# OPENROUTER CLIENT (Cloud LLM)
# =============================
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=st.secrets["OPENROUTER_API_KEY"],
)

# =============================
# CACHE LLM RESPONSES
# =============================
@st.cache_data(show_spinner=False, ttl=3600)
def get_analysis(prompt):
    response = client.chat.completions.create(
        model="openrouter/free",  # Free shared model endpoint
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content

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

if st.button("🔍 Analyze Soil"):
    # Save to DB
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

    # Score and Weather
    score = calculate_score(ph, nitrogen, phosphorus, potassium, organic)
    weather_info = get_weather(city)

    # Prompt for LLM
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
    # Spinner while LLM runs
    with st.spinner("🤖 AI is analyzing soil, please wait..."):
        analysis = get_analysis(prompt)
    fertilizer = fertilizer_advice(nitrogen)

    final_report = f"""
🌱 Soil Health Score: {score}/100

🌦 मौसम जानकारी:
{weather_info}

🤖 AI विश्लेषण:
{analysis}

💊 उर्वरक सलाह:
{fertilizer}
"""

    st.success("📋 Final Soil Report")
    st.write(final_report)

    # PDF
    pdf_file = generate_pdf(final_report)
    st.download_button("📄 Download PDF", open(pdf_file, "rb"), file_name=pdf_file)

    # TTS
    audio_file = text_to_speech(final_report)
    st.audio(audio_file)

# =============================
# HISTORY SECTION
# =============================
st.subheader("📊 पिछले रिपोर्ट")
reports = session.query(SoilReport).order_by(SoilReport.id.desc()).limit(5).all()
data = [{
    "Farmer": r.farmer_name,
    "pH": r.ph,
    "N": r.nitrogen,
    "P": r.phosphorus,
    "K": r.potassium,
    "Organic": r.organic_carbon
} for r in reports]

if data:
    st.dataframe(pd.DataFrame(data))