import os 
import pytz
import json
import requests
import faiss
import re
import sqlite3
from functools import wraps
import requests
from sqlalchemy.orm import joinedload
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, session, g, send_from_directory, current_app
from flask import current_app, send_file
import secrets
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import uuid
from datetime import datetime
from werkzeug.utils import secure_filename
from . import classify_media
from .database import db, users, posts, media, notification
from .utils import classify_media
import numpy as np
import pickle
from flask import abort
from io import BytesIO
import pandas as pd
from math import ceil

main = Blueprint("main", __name__)

# Load .env
load_dotenv()

# Get absolute path safely
TREE_PATH = os.path.join(os.path.dirname(__file__), "data", "decision_tree.json")

# ==== Login decorator ====
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('user_id'):
            lang = request.args.get('lang', 'ar')
            flash('Please log in first.' if lang=='en' else 'الرجاء تسجيل الدخول أولاً.', 'warning')
            return redirect(url_for('main.login', lang=lang))
        return view(*args, **kwargs)
    return wrapped

# ==== Password & Phone Validation ====
PASSWORD_REGEX = re.compile(r'^(?=.*[A-Z])(?=.*\d).{6,}$')
PHONE_REGEX = re.compile(r'^\+?\d{8,15}$')

def valid_password(pw):
    return bool(PASSWORD_REGEX.match(pw))

def valid_phone(phone):
    return bool(PHONE_REGEX.match(phone))

# --- Pages ------------------------------------------------
@main.route('/')
@main.route('/home')
def home():
    lang = request.args.get('lang', 'ar')
    return render_template('home.html', lang=lang)

@main.route('/home_fully')
def home_fully():
    lang = request.args.get('lang', 'ar')
    return render_template('home_fully.html', lang=lang)

@main.route('/about')
def about():
    lang = request.args.get('lang', 'ar')
    return render_template('about.html', lang=lang)

@main.route('/guidebot')
def guidebot():
    lang = request.args.get('lang', 'ar')
    return render_template('guidebot.html', lang=lang)

# ==== Register ====
@main.route('/register', methods=['GET', 'POST'])
def register():
    lang = request.args.get('lang', 'ar')
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        email = (request.form.get('email') or '').strip()
        password = request.form.get('password') or ''

        errors = []
        if not username:
            errors.append("Username is required." if lang == 'en' else "اسم المستخدم مطلوب.")
        if not email:
            errors.append("Email is required." if lang == 'en' else "البريد الإلكتروني مطلوب.")
        if not password:
            errors.append("Password is required." if lang == 'en' else "كلمة المرور مطلوبة.")
        if password and not valid_password(password):
            errors.append(
                "Password must be at least 6 characters, include 1 uppercase and 1 number."
                if lang == 'en' else
                "كلمة المرور يجب أن تكون 6 أحرف على الأقل وتحتوي على حرف كبير واحد ورقم واحد."
            )
        # ✅ Use lowercase class name 'users'
        if users.query.filter_by(username=username).first():
            errors.append("Username already exists." if lang == 'en' else "اسم المستخدم موجود بالفعل.")
        if users.query.filter_by(email=email).first():
            errors.append("Email already exists." if lang == 'en' else "البريد الإلكتروني موجود بالفعل.")

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('register.html', lang=lang, form=request.form)

        pw_hash = generate_password_hash(password)
        user = users(username=username, email=email, password=pw_hash, is_guest=False)
        db.session.add(user)
        db.session.commit()

        session['user_id'] = user.id
        session['username'] = user.username
        session['is_guest'] = False

        flash("Registration successful." if lang == 'en' else "تم إنشاء الحساب بنجاح.", 'success')
        return redirect(url_for('main.home_fully', lang=lang))

    return render_template('register.html', lang=lang)


# ==== Login ====
@main.route('/login', methods=['GET','POST'])
def login():
    lang = request.args.get('lang', 'ar')
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''

        if not username or not password:
            flash(
                "Username and password are required." if lang=='en' else "اسم المستخدم وكلمة المرور مطلوبان.",
                'danger'
            )
            return render_template('login.html', lang=lang, form=request.form)

        # ✅ Use lowercase class name 'users'
        user = users.query.filter_by(username=username).first()

        if not user or not check_password_hash(user.password, password):
            flash(
                "Invalid username or password." if lang=='en' else "اسم المستخدم أو كلمة المرور غير صحيح.",
                'danger'
            )
            return render_template('login.html', lang=lang, form=request.form)

        session['user_id'] = user.id
        session['username'] = user.username
        session['is_guest'] = user.is_guest

        flash(f"Welcome, {user.username}!" if lang=='en' else f"مرحباً، {user.username}!", 'success')
        return redirect(url_for('main.home_fully', lang=lang))

    return render_template('login.html', lang=lang)



# ==== Logout ====
@main.route('/logout')
def logout():
    lang = request.args.get('lang', 'ar')
    session.clear()
    flash("You have been logged out." if lang=='en' else "تم تسجيل الخروج.", 'info')
    return redirect(url_for('main.home', lang=lang))


# ==== Guest Start ====
@main.route('/guest-start')
def guest_start():
    lang = request.args.get('lang', 'ar')
    username = f"Guest-{secrets.token_hex(2)}"
    random_pw = generate_password_hash(secrets.token_urlsafe(16))
    
    
    user = users(username=username, email=None, password=random_pw, is_guest=True)
    db.session.add(user)
    db.session.commit()

    session['user_id'] = user.id
    session['username'] = username
    session['is_guest'] = True

    return redirect(url_for('main.home_fully', lang=lang))





@main.route('/statistics')
def statistics():
    lang = request.args.get('lang', 'ar')
    return render_template('statistics.html', lang=lang)



@main.route('/advices', methods=['GET'])
def advices():
    lang = request.args.get('lang', 'ar')
    # Render the page
    return render_template('advices.html', lang=lang)


@main.route('/safe_routes')
def safe_routes():
    lang = request.args.get('lang', 'ar')
    return render_template('safe_routes.html', lang=lang)


@main.route('/food_supply')
def food_supply():
    lang = request.args.get('lang', 'en')
    return render_template('food_supply.html', lang=lang)


@main.route('/decision')
def decision():
    lang = request.args.get('lang', 'en')
    return render_template('decision.html', lang=lang)

@main.route('/mental_aspect')
def mental_aspect():
    lang = request.args.get('lang', 'en')
    return render_template('mental_aspect.html', lang=lang)




@main.route('/old')
def old():
    lang = request.args.get('lang', 'en')
    return render_template('old.html', lang=lang)



# ==== Post submission ====
@main.route('/post', methods=['GET', 'POST'])
def post():
    lang = request.args.get('lang', 'ar')
    errors = {}
    if request.method == 'POST':
        user_id = session.get('user_id')
        if not user_id:
            return redirect(url_for('main.login', lang=lang))

        age = request.form.get('age')
        gender = request.form.get('gender')
        state = request.form.get('state')
        locality = request.form.get('locality')
        misinfo = request.form.get('misinfo')
        followup = request.form.get('followup')
        decision = request.form.get('decision')
        danger = request.form.get('danger')
        content = (request.form.get('story') or "").strip()
        time = request.form.get('time') 

        # Validation
        if not age: errors["age"] = "Age is required" if lang == "en" else "العمر مطلوب"
        if not gender: errors["gender"] = "Gender is required" if lang == "en" else "الجنس مطلوب"
        if not state: errors["state"] = "Region is required" if lang == "en" else "الولاية مطلوبة"
        if not time: errors["time"] = "Time is required" if lang == "en" else "الوقت مطلوب"
        if not misinfo: errors["misinfo"] = "Type of misinformation is required" if lang == "en" else "نوع المعلومة مطلوب"
        if not decision: errors["decision"] = "Decision selection is required" if lang == "en" else "القرار مطلوب"
        if not danger: errors["danger"] = "Danger level is required" if lang == "en" else "مستوى الخطورة مطلوب"
        if not content: errors["story"] = "Story cannot be empty" if lang == "en" else "القصّة مطلوبة"

        if errors:
            return render_template("post.html", lang=lang, errors=errors,
                                   age=age, gender=gender, state=state,
                                   locality=locality, misinfo=misinfo,
                                   followup=followup, decision=decision,
                                   danger=danger, story=content, time=time)

        # ✅ Update user info if needed
        user_obj = users.query.get(user_id)
        if user_obj:
            if age: user_obj.age_group = age   # match your users table column
            if gender: user_obj.gender = gender

        # ✅ Use 'posts' class
        new_post = posts(
            content=content,
            user_id=user_id,
            state=state,
            locality=locality,
            misinfo_type=misinfo,
            followup=followup,
            decision=(decision == "True"),
            danger_level=danger,
            created_at=datetime.utcnow(),
            time=time
        )
        db.session.add(new_post)
        db.session.commit()  # commit to get new_post.id

        # Handle media upload
        files = request.files.getlist('media')
        upload_folder = os.path.join('app', 'uploads')
        os.makedirs(upload_folder, exist_ok=True)
        for file in files:
            if file and file.filename:
                filename = secure_filename(file.filename)
                filepath = os.path.join(upload_folder, filename)
                file.save(filepath)
                media_item = media(
                    filename=filename,
                    media_type=file.mimetype.split('/')[0],
                    post_id=new_post.id
                )
                db.session.add(media_item)

        # Notifications for other users
        other_users = users.query.filter(users.id != user_id, users.is_guest == False).all()
        for u in other_users:
            notif = notification(user_id=u.id, message="New Story Has Been Posted.")
            db.session.add(notif)

        db.session.commit()
        return redirect(url_for('main.posts_list', lang=lang))

    return render_template("post.html", lang=lang, errors={})

# Inject notifications
# ------------------------
@main.app_context_processor
def inject_notifications():
    user_id = session.get("user_id")
    notifs = []
    unread_count = 0

    if user_id:
        
        notifs = notification.query.filter_by(user_id=user_id).order_by(notification.created_at.desc()).limit(5).all()
        unread_count = notification.query.filter_by(user_id=user_id, is_read=False).count()

    return dict(notifications=notifs, unread_count=unread_count)


@main.route("/notifications/read_all")
def read_all_notifications():
    user_id = session.get("user_id")
    if user_id:
        notification.query.filter_by(user_id=user_id, is_read=False).update({"is_read": True})
        db.session.commit()
    return redirect(request.referrer or url_for("main.home"))


# ------------------------
# Serve uploaded files
# ------------------------
@main.route('/uploads/<filename>')
def uploaded_file(filename):
    upload_folder = os.path.join(current_app.root_path, 'uploads')
    return send_from_directory(upload_folder, filename)


# ------------------------
@main.route('/posts', methods=['GET'])
def posts_list():
    lang = request.args.get('lang', 'ar')

    # ✅ Collect multiple filters (they can come from query params)
    type_value = request.args.get('type')
    followup_value = request.args.get('followup')
    danger_value = request.args.get('danger')
    state_value = request.args.get('state')
    time_value = request.args.get('time')
    owner_value = request.args.get('owner')

    # ✅ Base query
    query = posts.query.options(joinedload(posts.user), joinedload(posts.media_items))

    # ✅ Apply filters if they exist
    if type_value:
        query = query.filter(posts.misinfo_type == type_value)
    if followup_value:
        query = query.filter(posts.followup == followup_value)
    if danger_value:
        query = query.filter(posts.danger_level == danger_value)
    if state_value:
        query = query.filter(posts.state == state_value)
    if time_value:
        query = query.filter(posts.time == time_value)
    if owner_value == "me" and session.get("user_id"):
        query = query.filter(posts.user_id == session["user_id"])

    # ✅ Pagination setup
    page = request.args.get('page', 1, type=int)
    per_page = 4  # posts per page

    total_posts = query.count()
    total_pages = ceil(total_posts / per_page)

    # ✅ Get paginated posts only for this page
    paginated_posts = query.order_by(posts.created_at.desc(), posts.id.desc()) \
                           .offset((page - 1) * per_page) \
                           .limit(per_page) \
                           .all()

    # ✅ Pass all current filters to the template (for button display)
    return render_template(
        'posts_list.html',
        lang=lang,
        posts=paginated_posts,
        current_page=page,
        total_pages=total_pages,
        type_value=type_value,
        followup_value=followup_value,
        danger_value=danger_value,
        state_value=state_value,
        time_value=time_value,
        owner_value=owner_value
    )


# ------------------------
# Edit post
# ------------------------
@main.route('/post/<int:post_id>/edit', methods=['GET', 'POST'])
def edit_post(post_id):
    
    post_obj = posts.query.get_or_404(post_id)
    if post_obj.user_id != session.get('user_id'):
        abort(403)

    if request.method == 'POST':
        post_obj.content = request.form.get('story')
        db.session.commit()
        flash("✅ Your post was updated successfully!", "success")
        return redirect(url_for('main.posts_list'))

    return render_template('edit_post.html', post=post_obj)


# ------------------------
# Delete post
# ------------------------
@main.route('/post/<int:post_id>/delete', methods=['POST'])
def delete_post(post_id):
   
    post_obj = posts.query.get_or_404(post_id)
    if post_obj.user_id != session.get('user_id'):
        abort(403)

    db.session.delete(post_obj)
    db.session.commit()
    flash("🗑 Your post was deleted successfully.", "success")
    return redirect(url_for('main.posts_list'))







# ==== Stories endpoint ====
@main.route('/get_stories/<decision_type>', methods=['GET'])
def get_stories(decision_type):
    story_posts = posts.query.filter_by(misinfo_type=decision_type).all()
    story_list = []
    for s in story_posts:
        story_list.append({
            "id": s.id,
            "content": s.content,
            "author": s.user.username if s.user else "Anonymous",
            "created_at": s.created_at.strftime("%Y-%m-%d")
        })
    return jsonify(story_list)




# --- ADMIN CREDENTIALS (REPLACE / MOVE to env in production) ---
ADMIN_USERNAME = "ADMIN"
ADMIN_PASSWORD = "ADMIN123SLMT"

# --- decorator to protect admin routes ---
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("main.admin_login"))
        return f(*args, **kwargs)
    return decorated

# ---- Admin login route ----
@main.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    lang = request.args.get('lang', 'ar')
    if request.method == 'POST':
        username = (request.form.get('username') or "").strip()
        password = (request.form.get('password') or "").strip()

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            session['admin_username'] = username
            flash("Welcome, admin.", "success")
            return redirect(url_for('main.admin_dashboard'))
        else:
            flash("Invalid admin username or password.", "danger")

    return render_template('admin_login.html', lang=lang)

# ---- Admin logout ----
@main.route('/admin/logout')
@admin_required
def admin_logout():
    session.pop('admin_logged_in', None)
    session.pop('admin_username', None)
    flash("Admin logged out.", "success")
    return redirect(url_for('main.admin_login'))

# ---- Dashboard (list posts) ----
@main.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    lang = request.args.get('lang', 'ar')
    all_posts = posts.query.options(
        joinedload(posts.user),
        joinedload(posts.media_items)
    ).order_by(posts.created_at.desc(), posts.id.desc()).all()

    return render_template('admin_dashboard.html', lang=lang, posts=all_posts)


@main.route('/admin/export')
@admin_required
def admin_export():
    all_posts = posts.query.options(
        joinedload(posts.user),
        joinedload(posts.media_items)
    ).order_by(posts.created_at.desc(), posts.id.desc()).all()

    rows = []
    for p in all_posts:
        rows.append({
            "Post ID": p.id,
            "Created At": p.created_at.strftime("%Y-%m-%d %H:%M:%S") if p.created_at else "",
            "User ID": p.user_id,
            "Gender": (p.user.gender if p.user else ""),
            "Age": (p.user.age_group if p.user else ""),
            "Story Time": p.time or "",
            "State": p.state or "",
            "Locality": p.locality or "",
            "Misinfo Type": p.misinfo_type or "",
            "Followup": p.followup or "",
            "Decision": "Yes" if p.decision else "No",
            "Danger Level": p.danger_level or "",
            "Content": p.content or ""
        })

    # create DataFrame and write to bytes buffer
    df = pd.DataFrame(rows, columns=[
        "Post ID", "Created At", "User ID", "Gender", "Age", "Story Time",
        "State", "Locality", "Misinfo Type", "Followup", "Decision",
        "Danger Level", "Content"
    ])

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='posts')
    output.seek(0)

    fname = f"posts_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(
        output,
        as_attachment=True,
        download_name=fname,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@main.route("/misinfo_type")
def misinfo_type():
    lang = request.args.get("lang", "ar")
    return render_template("misinfo_type.html", lang=lang)

