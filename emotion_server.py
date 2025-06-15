from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
import sqlite3
from transformers import pipeline
from datetime import datetime
from collections import Counter
import csv, os
                                        
app = Flask(__name__)
app.secret_key = "your_secret_key"

# DB 테이블 생성
def init_db():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()

    # 사용자 테이블
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')

    # 감정 분석 기반 RPG 진행도 저장 테이블
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS progress (
            username TEXT PRIMARY KEY,
            exp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            last_quest TEXT,
            last_emotion TEXT
        )
    ''')

    # 퀘스트 내역 기록 테이블
    conn.execute('''
        CREATE TABLE IF NOT EXISTS quest_history (
            username TEXT,
            emotion TEXT,
            quest TEXT,
            timestamp TEXT
        )
    ''')

    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect('users.db')
    conn.row_factory = sqlite3.Row
    return conn

emotion_classifier = pipeline("text-classification", model="j-hartmann/emotion-english-distilroberta-base", top_k=1)

init_db()

@app.route('/')
def home():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('index.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db()
        try:
            conn.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
            # progress도 초기화
            conn.execute("INSERT INTO progress (username) VALUES (?)", (username,))
            conn.commit()
            flash("회원가입 성공! 로그인해주세요.")
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash("이미 존재하는 아이디입니다.")
        finally:
            conn.close()
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username=? AND password=?", (username, password)).fetchone()
        conn.close()
        if user:
            session['user_id'] = user['username']
            return redirect(url_for('home'))
        else:
            flash("로그인 실패. 아이디 또는 비밀번호를 확인하세요.")
    return render_template('login.html')

@app.route('/status')
def status():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    username = session['user_id']
    conn = get_db()
    progress = conn.execute("SELECT * FROM progress WHERE username=?", (username,)).fetchone()
    conn.close()

    if not progress:
        flash("진행 데이터가 없습니다.")
        return redirect(url_for('home'))

    return render_template("status.html", progress=progress)

@app.route('/quest_history')
def quest_history():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    username = session['user_id']
    conn = get_db()
    history = conn.execute("SELECT * FROM quest_history WHERE username=?", (username,)).fetchall()
    conn.close()
    
    return render_template("quest_history.html", history=history)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/analyze', methods=['POST'])
def analyze():
    if 'user_id' not in session:
        return jsonify({"error": "로그인 필요"}), 403

    username = session['user_id']
    text = request.json.get('text')
    result = emotion_classifier(text)
    emotion = result[0][0]['label']
    score = round(result[0][0]['score'], 3)

    content_map = {
        "joy": {
            "message": "기쁜 하루였군요! 잘하셨어요 😊",
            "content": "joy_image.jpg",
            "character": "아이유",
            "quest": "컬러링 게임",
            "link_game": "https://www.tinytap.com/activities/g4wub/play/feeling-happy",
            "link_mv": "https://www.youtube.com/watch?v=0-q1KafFCLU",
            "exp": 5
        },
        "sadness": {
            "message": "슬픈 하루였나요? 괜찮아요, 함께 이겨내요! 💧",
            "content": "sadness_music.mp3",
            "character": "테일러 스위프트",
            "quest": "감정을 표현하는 게임과 음악",
            "link_game": "https://www.tinytap.com/activities/g3ctu/play/emotions-sad",
            "link_mv": "https://www.youtube.com/watch?v=q3zqJs7JUCQ",
            "exp": 4
        },
        "fear": {
            "message": "불안하셨군요. 호흡을 가다듬어볼까요? 🌬️",
            "content": "breathing_exercise.mp4",
            "character": "아이유",
            "quest": "불안 관리 인터랙티브 콘텐츠",
            "link_game": "https://ncase.me/anxiety/",
            "link_mv": "https://www.youtube.com/watch?v=0-q1KafFCLU",
            "exp": 6
        },
        "anger": {
            "message": "화가 나셨군요. 진정하는 시간이 필요해요 🔥",
            "content": "calm_video.mp4",
            "character": "세븐틴",
            "quest": "댄스 챌린지",
            "link_game": "https://www.tinytap.com/activities/g5i6d/play/anger-go-away-practicing-self-management",
            "link_mv": "https://www.youtube.com/watch?v=-GQg25oP0S4",
            "exp": 7
        },
        "neutral": {
            "message": "잔잔한 하루네요. 평온한 시간 되세요 🌿",
            "content": "neutral_background.png",
            "character": "세븐틴",
            "quest": "감정 퀴즈",
            "link_game": "https://pbskids.org/daniel/games/guess-the-feeling",
            "link_mv": "https://www.youtube.com/watch?v=-GQg25oP0S4",
            "exp": 3
        }
    }

    info = content_map.get(emotion, {})
    exp_gain = info.get("exp", 0)

    # DB에서 현재 경험치 가져오기 + 갱신
    conn = get_db()
    user_progress = conn.execute("SELECT * FROM progress WHERE username=?", (username,)).fetchone()

    if not user_progress:
        conn.execute("INSERT INTO progress (username, exp, level, last_quest, last_emotion) VALUES (?, ?, ?, ?, ?)",
                     (username, exp_gain, 1, info.get("quest", ""), emotion))
    else:
        new_exp = user_progress["exp"] + exp_gain
        new_level = (new_exp // 100) + 1
        conn.execute("UPDATE progress SET exp=?, level=?, last_quest=?, last_emotion=? WHERE username=?",
                     (new_exp, new_level, info.get("quest", ""), emotion, username))
    conn.commit()
    conn.close()

    log_dir = 'logs'
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"{username}_log.csv")
    with open(log_file, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), text, emotion, score, new_level])

    # 퀘스트 수행 내역 저장
    conn = get_db()

    conn.execute('''
        INSERT INTO quest_history (username, emotion, quest, timestamp)
        VALUES (?, ?, ?, ?)
    ''', (username, emotion, info.get("quest", ""), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    
    conn.commit()
    conn.close()

    return jsonify({
        "emotion": emotion,
        "confidence": score,
        "message": info.get("message", ""),
        "content": info.get("content", ""),
        "character": info.get("character", ""),
        "quest": info.get("quest", ""),
        "link_game": info.get("link_game", "#"),
        "link_mv": info.get("link_mv", "#"),
        "exp_gain": exp_gain,
        "level": (user_progress["exp"] + exp_gain) // 100 + 1 if user_progress else 1,
        "total_exp": user_progress["exp"] + exp_gain if user_progress else exp_gain
    })

@app.route('/history')
def history():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    log_path = f'logs/{session["user_id"]}_log.csv'
    if not os.path.exists(log_path):
        return render_template('history_blocked.html')

    with open(log_path, newline='', encoding='utf-8') as f:
        rows = list(csv.reader(f))

    if len(rows) < 10:
        return render_template('history_blocked.html')

    # 감정을 숫자로 매핑
    emotion_map = {
        "neutral": 0,
        "sadness": 1,
        "fear": 2,
        "anger": 3,
        "joy": 4
    }

    history_data = []
    for row in rows[-15:]:
        timestamp = row[0]
        emotion = row[2]
        level = int(row[4]) if len(row) >= 5 else 1  # 예외 대비
        emotion_val = emotion_map.get(emotion, -1)
        history_data.append({
            "time": timestamp,
            "emotion_val": emotion_val,
            "level": level
        })

    return render_template("history.html", history_data=history_data)

if __name__ == '__main__':
    app.run(debug=True)