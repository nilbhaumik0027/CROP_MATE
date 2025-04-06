from flask import Flask, json, render_template, request, redirect, session, url_for, jsonify
from functools import lru_cache
import firebase_admin
from firebase_admin import credentials, auth, firestore
import requests
import os
from dotenv import load_dotenv
import uuid
from datetime import datetime
import google.generativeai as genai
import base64
import traceback

load_dotenv()

app = Flask(__name__)
app.secret_key = 'r9m*l27lchm@a@2s11%g%0symai@xvj(3)j24m#@u77kizci)1'

# Firebase admin SDK
cred = credentials.Certificate("authenticatpy-firebase-adminsdk-fbsvc-064478f5fb.json")
firebase_admin.initialize_app(cred)
db = firestore.client()
FIREBASE_API_KEY = os.getenv("FIREBASE_WEB_API_KEY")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")

# Gemini configuration
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-2.0-flash')


# ====================== Helper Functions ======================

def verify_user(email, password):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_API_KEY}"
    payload = {
        "email": email,
        "password": password,
        "returnSecureToken": True
    }
    response = requests.post(url, json=payload)
    if response.status_code == 200:
        return response.json()
    else:
        return None

def get_user():
    uid = session.get('uid')
    email = session.get('email')
    if not uid:
        return None, None, None
    doc = db.collection('users').document(uid).get()
    user_data = doc.to_dict() if doc.exists else {}
    return uid, email, user_data

@lru_cache(maxsize=128)
def get_weather(lat, lon):
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}&units=metric"
        data = requests.get(url).json()
        return f"{data['name']}: {data['weather'][0]['description'].title()}, {data['main']['temp']}°C"
    except Exception as e:
        print("Weather fetch error:", e)
        return "Unable to fetch weather"


@app.context_processor
def inject_weather():
    uid = session.get('uid')
    weather_info = "Loading weather..."
    
    if uid:
        user_doc = db.collection('users').document(uid).get()
        user_data = user_doc.to_dict() if user_doc.exists else {}
        lat = user_data.get('latitude', 22.34)
        lon = user_data.get('longitude', 87.23)
        weather_info = get_weather(lat, lon)

    return dict(weather_info=weather_info)

@app.route('/get_user_email')
def get_user_email():
    uid = session.get('uid')
    email = session.get('email')
    if uid and email:
        return email
    return "Guest"


# ====================== Auth Routes ======================

@app.route('/')
def login_page():
    return render_template('login.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        verified = verify_user(email, password)
        if verified:
            user = auth.get_user_by_email(email)
            session['uid'] = user.uid
            session['email'] = email
            return redirect('/dashboard')

        else:
            return render_template('login.html', error="Invalid email or password. Please try again.")

    success_msg = request.args.get('success')
    success_text = "Registration successful! Please log in." if success_msg else None

    return render_template('login.html', success=success_text)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        mobile = request.form.get('mobile', '')
        language = request.form.get('language', 'en')

        try:
            user = auth.create_user(email=email, password=password)
            db.collection('users').document(user.uid).set({
                'email': email,
                'mobile': mobile,
                'language': language
            })
            session['uid'] = user.uid
            session['email'] = email
            return redirect('/dashboard')
        except Exception as e:
            print(e)
            return render_template('register.html', error="Registration failed.")
    
    # This will handle GET request to show the register form
    return render_template('register.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')


# ====================== Dashboard & Pages ======================

@app.route('/get_weather_data')
def get_weather_route():
    lat = request.args.get('lat', default=22.34, type=float)
    lon = request.args.get('lon', default=87.23, type=float)
    return get_weather(lat, lon)


@app.route('/dashboard')
def dashboard():
    uid, email, user_data = get_user()
    if not uid:
        return redirect('/')
    return render_template('dashboard.html', user_email=email,user=user_data)

@app.route('/crop_advisory')
def crop_advisory():
    uid, email, user_data = get_user()
    if not uid:
        return redirect('/')
    return render_template('crop_advisory.html', user_email=email,user=user_data)

@app.route('/weather_forecast')
def weather_forecast():
    uid, email, user_data = get_user()
    if not uid:
        return redirect('/')
    return render_template('weather_forecast.html', user_email=email,user=user_data)

@app.route('/soil_health')
def soil_health():
    uid, email, user_data = get_user()
    if not uid:
        return redirect('/')

    advisory_docs = db.collection('users').document(uid).collection('crop_records').stream()
    advisory_records = [{**doc.to_dict(), 'id': doc.id} for doc in advisory_docs]

    return render_template('soil_health.html', user_email=email,user=user_data, advisory_records=advisory_records)

@app.route('/plant_disease')
def plant_disease():
    uid, email, user_data = get_user()
    if not uid:
        return redirect('/')
    return render_template('plant_disease.html', user_email=email, user=user_data)

@app.route('/market_prices')
def market_prices():
    uid, email, user_data = get_user()
    if not uid:
        return redirect('/')
    try:
        api_key = os.getenv("OGD_API_KEY")
        url = "https://api.data.gov.in/resource/b2fe069e-94d5-424c-bfe9-bc47b47bdc24"
        params = {
            "api-key": api_key,
            "format": "json",
            "limit": 20 # You can adjust this
        }

        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        records = data.get("records", [])
        # Format each record for the template
        prices = [{
            "crop": rec.get("crop"),
            "commodity": rec.get("commodity"),
            "msp": rec.get("msp"),
            "market_price": rec.get("weighted_average_price_october__2018")
        } for rec in records]

        return render_template("market_prices.html", prices=prices, user_email=email, user=user_data)
    except Exception as e:
        print("Error fetching market prices:", e)
        return render_template("market_prices.html", prices=[], user_email=email, user=user_data)

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    uid = session.get('uid')
    if not uid:
        return redirect(url_for('login'))

    db = firestore.client()
    user_ref = db.collection('users').document(uid)

    if request.method == 'POST':
        try:
            # Safely get existing data
            user_doc = user_ref.get()
            existing_data = user_doc.to_dict() if user_doc.exists else {}

            # Update profile with new form data
            updated_data = {
                'full_name': request.form.get('full_name') or existing_data.get('full_name'),
                'mobile': request.form.get('mobile') or existing_data.get('mobile'),
                'language': request.form.get('language') or existing_data.get('language'),
                'address': request.form.get('address') or existing_data.get('address'),
                'latitude': float(request.form.get('latitude') or existing_data.get('latitude') or 0),
                'longitude': float(request.form.get('longitude') or existing_data.get('longitude') or 0),
            }

            user_ref.update(updated_data)
            return redirect(url_for('profile'))
        except Exception as e:
            print("Update failed:", traceback.format_exc())
            return render_template('profile.html', profile={}, error="⚠️ Failed to update profile.")

    # Load user profile
    user_doc = user_ref.get()
    profile_data = user_doc.to_dict() if user_doc.exists else {}

    return render_template('profile.html', profile=profile_data)


# ====================== Clean Weather API ======================

@app.route('/get_weather')
def get_weather_api():
    lat = request.args.get('lat')
    lon = request.args.get('lon')
    if not lat or not lon:
        return jsonify({"error": "Missing coordinates"}), 400

    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}&units=metric"
        res = requests.get(url)
        data = res.json()

        weather_data = {
            'city': data.get('name'),
            'description': data['weather'][0]['description'].title(),
            'temp': data['main']['temp'],
            'sunrise': datetime.fromtimestamp(data['sys']['sunrise']).strftime('%H:%M'),
            'sunset': datetime.fromtimestamp(data['sys']['sunset']).strftime('%H:%M'),
            'date': datetime.now().strftime('%A, %d %B %Y')
        }

        return jsonify(weather_data)

    except Exception as e:
        print("Weather fetch error:", e)
        return jsonify({"error": "Failed to fetch weather"}), 500


# ====================== Crop Advisory APIs ======================

@app.route('/add_advisory', methods=['POST'])
def add_advisory():
    uid, _, _ = get_user()
    if not uid:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    record_id = str(uuid.uuid4())
    db.collection('users').document(uid).collection('crop_records').document(record_id).set(data)
    return jsonify({'message': 'Record saved successfully!'})

@app.route('/get_advisories')
def get_advisories():
    uid, _, _ = get_user()
    if not uid:
        return jsonify([])

    docs = db.collection('users').document(uid).collection('crop_records').stream()
    return jsonify([{**doc.to_dict(), 'id': doc.id} for doc in docs])

@app.route('/get_advice/<record_id>')
def get_advice(record_id):
    uid, _, _ = get_user()
    if not uid:
        return jsonify({'error': 'Unauthorized'}), 401

    doc = db.collection('users').document(uid).collection('crop_records').document(record_id).get()
    if not doc.exists:
        return jsonify({'error': 'Record not found'}), 404

    record = doc.to_dict()
    prompt = f"""
    I am a farmer with the following information:
    - Crop: {record['crop']}
    - Area of Land: {record['area']} acres
    - Location (Lat, Long): ({record['latitude']}, {record['longitude']})

    Based on this data, suggest best farming practices, irrigation strategies, pest control, and seasonal tips.
    Keep it brief, easy to understand, and relevant to Indian agriculture only 10 - 20 points.
    """
    try:
        response = model.generate_content(prompt)
        return jsonify({'advice': response.text.strip()})
    except Exception as e:
        return jsonify({'error': f'Gemini API error: {str(e)}'}), 500

@app.route('/update_advisory/<record_id>', methods=['POST'])
def update_advisory(record_id):
    uid, _, _ = get_user()
    if not uid:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    db.collection('users').document(uid).collection('crop_records').document(record_id).update(data)
    return jsonify({'message': 'Record updated successfully!'})

@app.route('/delete_advisory/<record_id>', methods=['DELETE'])
def delete_advisory(record_id):
    uid, _, _ = get_user()
    if not uid:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        db.collection('users').document(uid).collection('crop_records').document(record_id).delete()
        return jsonify({'message': 'Record deleted successfully!'})
    except Exception as e:
        return jsonify({'error': f'Failed to delete record: {str(e)}'}), 500


# ====================== Static Advisory Logic ======================

@app.route('/api/advisory')
def api_advisory():
    weather = request.args.get('weather', '').lower()
    if 'rain' in weather:
        message = "Avoid irrigation today due to expected rainfall."
    elif 'clear' in weather:
        message = "Ideal for pesticide spray. Soil is expected to dry faster."
    elif 'cloud' in weather:
        message = "Mild cloud cover expected. Monitor for fungal activity."
    else:
        message = "Monitor soil moisture and plan accordingly."
    return jsonify({"message": message})

@app.route('/get_soil_health', methods=['POST'])
def get_soil_health():
    uid, _, _ = get_user()
    if not uid:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    crop = data.get('crop')
    lat = data.get('latitude')
    lon = data.get('longitude')

    if not crop or not lat or not lon:
        return jsonify({'error': 'Missing fields'}), 400

    prompt = f"""
Okay, give a farmer-friendly guide to **soil health requirements** for **{crop}** cultivation in Indian conditions,
tailored for the location ({lat}, {lon}). Format it clearly using **markdown**.

Include:
- Ideal pH
- Essential nutrients (NPK)
- Fertilizer advice (with Indian terms like DAP, urea)
- Location-based suggestions if possible

Use bullet points and headings.
"""


    try:
        response = model.generate_content(prompt)
        return jsonify({'soil_health': response.text.strip()})
    except Exception as e:
        print("Gemini error:", e)
        return jsonify({'error': f'Gemini API error: {str(e)}'}), 500

# ====================== Plant Disease Detection ======================

@app.route('/detect_disease', methods=['GET', 'POST'])
def detect_disease():
    uid, email, user_data = get_user()
    if not uid:
        return redirect('/')
    if request.method == 'GET':
        return render_template('plant_disease.html')

    file = request.files.get('plantImage')
    if not file:
        return render_template('plant_disease.html', error='No image uploaded')

    try:
        # Read and encode image
        image_bytes = file.read()
        image_data = base64.b64encode(image_bytes).decode('utf-8')
        base64_string = f"data:image/jpeg;base64,{image_data}"

         # Get latitude and longitude from form (default to 0.0 if not provided)
        latitude = request.form.get('latitude', '')
        longitude = request.form.get('longitude', '')
        try:
            latitude = float(latitude)
            longitude = float(longitude)
        except ValueError:
            latitude, longitude = 0.0, 0.0  # fallback

        # Plant.id API request
        url = "https://plant.id/api/v3/health_assessment"
        payload = json.dumps({
            "images": [base64_string],
            "latitude": latitude,  # Make dynamic later
            "longitude": longitude,
            "similar_images": True
        })
        headers = {
            'Api-Key': os.getenv("PLANTID_API_KEY"),
            'Content-Type': 'application/json'
        }

        response = requests.request("POST",url, headers=headers, data=payload)
        result = response.json()

        # Extract diagnosis
        suggestions = result.get('health_assessment', {}).get('diseases', [])
        if not suggestions:
            diagnosis = "✅ No signs of disease detected. The plant looks healthy."
        else:
            diagnosis_list = [f"❌ {s['name']} - {s['probability'] * 100:.1f}%" for s in suggestions]
            diagnosis = "Possible issues:\n" + "\n".join(diagnosis_list)

        return render_template('plant_disease.html', result=diagnosis, image_url=base64_string, user_email=email, weather_info=get_weather(uid), user=user_data)

    except Exception as e:
        print("Error during plant disease diagnosis:", e)
        return render_template('plant_disease.html', error='Failed to analyze image',user_email=email, user=user_data)


# ====================== Run ======================

if __name__ == '__main__':
    app.run(debug=True)
