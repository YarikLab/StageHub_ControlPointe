import os
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, url_for
from flask_login import (
    LoginManager, UserMixin, current_user, login_required,
    login_user, logout_user
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-key-change-before-deployment")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{INSTANCE_DIR / 'stagehub.db'}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Войдите в аккаунт, чтобы открыть эту страницу."
login_manager.login_message_category = "info"


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(40), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    projects = db.relationship(
        "Project", backref="owner", lazy=True,
        cascade="all, delete-orphan"
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    venue = db.Column(db.String(120), nullable=False, default="")
    description = db.Column(db.Text, nullable=False, default="")
    equipment = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


@app.context_processor
def inject_globals():
    return {"app_name": "StageHub"}


@app.route("/")
def index():
    recent_projects = []
    if current_user.is_authenticated:
        recent_projects = (
            Project.query.filter_by(user_id=current_user.id)
            .order_by(Project.created_at.desc()).limit(3).all()
        )
    return render_template("index.html", recent_projects=recent_projects)


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("projects"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")

        if not username or not email or not password:
            flash("Заполните все обязательные поля.", "error")
        elif len(username) < 3 or len(username) > 40:
            flash("Имя пользователя должно содержать от 3 до 40 символов.", "error")
        elif len(password) < 8:
            flash("Пароль должен содержать не менее 8 символов.", "error")
        elif password != password_confirm:
            flash("Пароли не совпадают.", "error")
        elif User.query.filter(or_(User.username.ilike(username), User.email == email)).first():
            flash("Пользователь с таким именем или электронной почтой уже существует.", "error")
        else:
            user = User(username=username, email=email)
            user.set_password(password)
            db.session.add(user)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                flash("Не удалось создать аккаунт. Проверьте имя пользователя и электронную почту.", "error")
                return render_template("register.html")
            login_user(user)
            flash("Аккаунт создан. Добро пожаловать в StageHub!", "success")
            return redirect(url_for("projects"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("projects"))

    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter(
            or_(User.username.ilike(identifier), User.email == identifier.lower())
        ).first()

        if user is None or not user.check_password(password):
            flash("Неверное имя пользователя, электронная почта или пароль.", "error")
        else:
            login_user(user)
            flash("Вы успешно вошли в аккаунт.", "success")
            next_page = request.args.get("next", "")
            # Avoid open redirects: only allow local application paths.
            if next_page.startswith("/") and not next_page.startswith("//"):
                return redirect(next_page)
            return redirect(url_for("projects"))

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("Вы вышли из аккаунта.", "success")
    return redirect(url_for("index"))


@app.route("/projects")
@login_required
def projects():
    items = Project.query.filter_by(user_id=current_user.id).order_by(Project.created_at.desc()).all()
    return render_template("projects.html", projects=items)


@app.route("/projects/new", methods=["GET", "POST"])
@login_required
def project_create():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        venue = request.form.get("venue", "").strip()
        description = request.form.get("description", "").strip()
        equipment = request.form.get("equipment", "").strip()

        if not title:
            flash("Укажите название проекта.", "error")
        elif len(title) > 100 or len(venue) > 120:
            flash("Название или площадка слишком длинные.", "error")
        else:
            project = Project(
                title=title, venue=venue, description=description,
                equipment=equipment, user_id=current_user.id
            )
            db.session.add(project)
            db.session.commit()
            flash("Проект добавлен.", "success")
            return redirect(url_for("projects"))

    return render_template("project_form.html", project=None, page_title="Новый проект")


@app.route("/projects/<int:project_id>")
@login_required
def project_detail(project_id):
    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first_or_404()
    return render_template("project_detail.html", project=project)


@app.route("/projects/<int:project_id>/delete", methods=["POST"])
@login_required
def project_delete(project_id):
    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first_or_404()
    db.session.delete(project)
    db.session.commit()
    flash("Проект удалён.", "success")
    return redirect(url_for("projects"))


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(debug=True)
