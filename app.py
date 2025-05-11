import os
import cv2
import csv
import numpy as np
import face_recognition
import sqlite3
from flask import Flask, render_template, Response, request, redirect, url_for, jsonify, session, send_file
from datetime import datetime
import uuid
import io
from PIL import Image

app = Flask(__name__)

app.secret_key = 'your_secret_key_here'

DB_PATH = 'face_attendance.db'

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT * FROM login WHERE username=? AND password=?", (username, password))
        user = c.fetchone()
        conn.close()        
        if user:  # You can replace this with database check
            session['logged_in'] = True
            return redirect(url_for('faculty_home'))
        else:
            return render_template('login.html', error="Invalid username or password.")
    
    return render_template('login.html')

# Add Faculty Home Page to show the attendance table
@app.route('/faculty_home')
def faculty_home():
    if 'logged_in' not in session:
        return redirect(url_for('login'))
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT DISTINCT class FROM student_records')
    classes = c.fetchall()
    conn.close()

    return render_template('faculty_home.html', classes=classes)

# Add route to download CSV for attendance
@app.route('/download_attendance/<class_name>', methods=['GET'])
def download_attendance(class_name):
    if 'logged_in' not in session:
        return redirect(url_for('login'))
    
    today = datetime.now().strftime('%Y-%m-%d')
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''SELECT name, reg_no, attendance_timestamp FROM attendance WHERE class = ? AND attendance_timestamp LIKE ?''', 
              (class_name, f'{today}%'))
    attendance_data = c.fetchall()
    conn.close()

    if not attendance_data:
        return "No attendance records found for today."

    # Generate CSV
    filename = f"{class_name}_{today}_attendance.csv"
    filepath = os.path.join('downloads', filename)
    with open(filepath, 'w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['Name', 'Roll Number', 'Attendance Timestamp'])
        for row in attendance_data:
            writer.writerow(row)

    return send_file(filepath, as_attachment=True)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS student_records (
                    name TEXT,
                    reg_no TEXT PRIMARY KEY,
                    image BLOB,
                    class TEXT,
                    encoding BLOB
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS attendance (
                    name TEXT,
                    reg_no TEXT,
                    attendance_timestamp TEXT,
                    class TEXT,
                    image BLOB
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS login (
                    username TEXT PRIMARY KEY,
                    password TEXT,
                    email TEXT
                )''')
    conn.commit()
    conn.close()


init_db()

def load_known_faces():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT reg_no, encoding FROM student_records")
    rows = c.fetchall()
    conn.close()

    known_encodings = []
    known_ids = []
    for reg_no, encoding_blob in rows:
        if encoding_blob:
            encoding_array = np.frombuffer(encoding_blob, dtype=np.float64)
            known_encodings.append(encoding_array)
            known_ids.append(reg_no)
    return known_encodings, known_ids

known_face_encodings, known_reg_nos = load_known_faces()

@app.route('/register_faculty', methods=['GET'])
def register_faculty():
    return render_template('register_faculty.html')

@app.route('/register_user', methods=['POST'])
def register_user():
    username = request.form.get('username')
    password = request.form.get('password')
    email = request.form.get('email')

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO login (username, password, email) VALUES (?, ?, ?)", 
                  (username, password, email))
        conn.commit()
        conn.close()
        return redirect(url_for('login'))  # Redirect to login after successful registration
    except sqlite3.IntegrityError:
        conn.close()
        return render_template('register.html', message="Username already exists. Please choose a different one.")


@app.route('/register')
def register_form():
    return render_template('register.html')

@app.route('/register_face', methods=['POST'])
def register_face():
    name = request.form.get('name')
    roll = request.form.get('roll')
    class_name = request.form.get('class')

    cap = cv2.VideoCapture(0)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        return render_template('register_fail.html', message="Camera not accessible.")

    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    face_locations = face_recognition.face_locations(rgb_frame)
    face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)

    if not face_encodings:
        return render_template('register_fail.html', message="No face detected.")

    new_encoding = face_encodings[0]
    for encoding in known_face_encodings:
        if face_recognition.compare_faces([encoding], new_encoding, tolerance=0.45)[0]:
            return render_template('register_fail.html', message="Face already registered.")

    img_pil = Image.fromarray(rgb_frame)
    img_byte_arr = io.BytesIO()
    img_pil.save(img_byte_arr, format='JPEG')
    img_bytes = img_byte_arr.getvalue()

    encoding_bytes = new_encoding.tobytes()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO student_records (name, reg_no, image, class, encoding) VALUES (?, ?, ?, ?, ?)",
                  (name, roll, img_bytes, class_name, encoding_bytes))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return render_template('register_fail.html', message="Roll number already exists.")
    conn.close()

    global known_face_encodings1, known_reg_nos1
    known_face_encodings1, known_reg_nos1 = load_known_faces()

    return render_template('register_success.html')

def is_attendance_already_marked(reg_no):
    now = datetime.now()
    current_hour = now.strftime('%Y-%m-%d %H')
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT attendance_timestamp FROM attendance WHERE reg_no = ?", (reg_no,))
    rows = c.fetchall()
    conn.close()
    for row in rows:
        if row[0].startswith(current_hour):
            return True
    return False

@app.route('/log_attendance')
def log_attendance():
    cap = cv2.VideoCapture(0)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        return render_template('attendance_result.html', status='error', message='Could not access camera.')

    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    face_locations = face_recognition.face_locations(rgb_frame)
    face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)

    if not face_encodings:
        return render_template('attendance_result.html', status='fail', message='No face detected. Try again.')

    encoding = face_encodings[0]
    matches = face_recognition.compare_faces(known_face_encodings, encoding, tolerance=0.45)
    face_distances = face_recognition.face_distance(known_face_encodings, encoding)

    if any(matches):
        best_match_index = np.argmin(face_distances)
        matched_reg_no = known_reg_nos[best_match_index]

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT name, class FROM student_records WHERE reg_no = ?", (matched_reg_no,))
        result = c.fetchone()
        conn.close()
        if not result:
            return render_template('attendance_result.html', status='fail', message='Student record not found.')

        name, class_name = result
        if is_attendance_already_marked(matched_reg_no):
            return render_template('attendance_result.html', status='info', message='Your Attendance has already been recorded for this hour.')

        img_pil = Image.fromarray(rgb_frame)
        img_byte_arr = io.BytesIO()
        img_pil.save(img_byte_arr, format='JPEG')
        img_bytes = img_byte_arr.getvalue()

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO attendance (name, reg_no, attendance_timestamp, class, image) VALUES (?, ?, ?, ?, ?)",
                  (name, matched_reg_no, now, class_name, img_bytes))
        conn.commit()
        conn.close()

        return render_template('attendance_result.html', status='success', message=f'Attendance recorded for {name}.')

    return render_template('attendance_result.html', status='fail', message='Face not recognized. Please register.')

@app.route('/')
def index():
    return render_template('index.html')

# @app.route('/login')
# def login():
#     return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))



if __name__ == '__main__':
    app.run(debug=True)
