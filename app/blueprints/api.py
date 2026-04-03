from flask import Blueprint, jsonify, request
from flask_login import login_required

from app.models import Game, Person, db

api_bp = Blueprint("api", __name__)


@api_bp.route("/games/autocomplete")
@login_required
def autocomplete_games():
    query = request.args.get("q", "")[:100]
    results = Game.query.filter(Game.name.ilike(f"%{query}%")).order_by(Game.name).limit(10).all()
    return jsonify([{"id": g.id, "name": g.name} for g in results])


@api_bp.route("/people/autocomplete")
@login_required
def autocomplete_people():
    query = request.args.get("q", "")[:100]
    results = (
        Person.query.filter(
            db.or_(Person.first_name.ilike(f"%{query}%"), Person.last_name.ilike(f"%{query}%"))
        )
        .order_by(Person.first_name, Person.last_name)
        .limit(10)
        .all()
    )
    return jsonify([{"id": p.id, "name": f"{p.first_name} {p.last_name}"} for p in results])
