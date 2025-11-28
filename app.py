# from flask import Flask, jsonify
# from flasgger import Swagger
# from swagger_config import SWAGGER_SETTINGS
# from docs import health_check_docs

# # Create Flask app
# app = Flask(__name__)

# # Apply Swagger configuration
# app.config['SWAGGER'] = SWAGGER_SETTINGS

# # Initialize Swagger
# swagger = Swagger(app)

# # Define route
# @app.route('/')
# def hello_world():
#     return '<p> Hello world <p>'

# @app.route("/health", methods=["GET"])
# def health_check():
#     return jsonify({"status": "ok"}), 200

# # Attach external Swagger documentation
# health_check.__doc__ = health_check_docs

# if __name__ == "__main__":
#     app.run(debug=True)
# from flask import Flask, jsonify, request
# from flasgger import Swagger
# from swagger_config import SWAGGER_SETTINGS
# from docs import health_check_docs

# # Simple in-memory "database" for Sprint 1 (Story 3)
# OBSERVATIONS = {}
# NEXT_ID = 1

# # Create Flask app
# app = Flask(__name__)

# # Apply Swagger configuration
# app.config['SWAGGER'] = SWAGGER_SETTINGS

# # Initialize Swagger
# swagger = Swagger(app)

# #  ADD  ERROR HANDLERS
# @app.errorhandler(404)
# def not_found(error):
#     return jsonify({"error": "Endpoint not found", "code": 404}), 404

# @app.errorhandler(500)
# def internal_error(error):
#     return jsonify({"error": "Internal server error", "code": 500}), 500

# @app.errorhandler(400)
# def bad_request(error):
#     return jsonify({"error": "Bad request", "code": 400}), 400

# # -------------------------
# # Existing routes
# # -------------------------


# @app.route('/')
# def hello_world():
#     return jsonify({"message": "Hello World!"}), 200


# @app.route("/health", methods=["GET"])
# def health_check():
#     return jsonify({"status": "ok"}), 200


# # Attach external Swagger documentation to /health
# health_check.__doc__ = health_check_docs


# # -------------------------
# # Story 3: CRUD endpoints
# # -------------------------

# @app.route("/observations", methods=["GET"])
# def list_observations():
#     """
#     List all observations.
#     """
#     # Return a list of all stored observations
#     return jsonify(list(OBSERVATIONS.values())), 200


# @app.route("/observations", methods=["POST"])
# def create_observation():
#     """
#     Create a new observation.
#     """
#     global NEXT_ID

#     payload = request.get_json() or {}

#     # For now, we just store whatever JSON comes in under 'data'
#     observation = {
#         "id": NEXT_ID,
#         "data": payload
#     }
#     OBSERVATIONS[NEXT_ID] = observation
#     NEXT_ID += 1

#     # 201 Created
#     return jsonify(observation), 201


# @app.route("/observations/<int:obs_id>", methods=["GET"])
# def get_observation(obs_id):
#     """
#     Get a single observation by ID.
#     """
#     observation = OBSERVATIONS.get(obs_id)
#     if not observation:
#         return jsonify({"error": "Observation not found"}), 404
    
#         payload = request.get_json() or {}
#         observation["data"] = payload

#     return jsonify(observation), 200


# @app.route("/observations/<int:obs_id>", methods=["PUT"])
# def replace_observation(obs_id):
#     """
#     Replace an observation (full update).
#     """
#     observation = OBSERVATIONS.get(obs_id)
#     if not observation:
#         return jsonify({"error": "Observation not found"}), 404

#     payload = request.get_json() or {}
#     observation["data"] = payload

#     return jsonify(observation), 200


# @app.route("/observations/<int:obs_id>", methods=["PATCH"])
# def patch_observation(obs_id):
#     """
#     Partially update an observation.
#     """
#     observation = OBSERVATIONS.get(obs_id)
#     if not observation:
#         return jsonify({"error": "Observation not found"}), 404

#     payload = request.get_json() or {}

#     # Make sure observation["data"] is a dict
#     if not isinstance(observation["data"], dict):
#         observation["data"] = {}

#     if isinstance(payload, dict):
#         observation["data"].update(payload)

#     return jsonify(observation), 200


# @app.route("/observations/<int:obs_id>", methods=["DELETE"])
# def delete_observation(obs_id):
#     """
#     Delete an observation.
#     """
#     observation = OBSERVATIONS.get(obs_id)
#     if not observation:
#         return jsonify({"error": "Observation not found"}), 404

#     del OBSERVATIONS[obs_id]
#     # 204 No Content
#     return jsonify({"message": "Observation deleted successfully"}), 200


# if __name__ == "__main__":
#     app.run(debug=True)

from flask import Flask, jsonify, request
from flasgger import Swagger
from swagger_config import SWAGGER_SETTINGS
from docs import health_check_docs
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta 
import jwt
from functools import wraps


SECRET_KEY = "super-secret-key"   






# Create Flask app
app = Flask(__name__)

# Apply Swagger configuration
app.config["SWAGGER"] = SWAGGER_SETTINGS

# --- Database configuration (SQLite, auto-creates observations.db) ---
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///observations.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Initialize SQLAlchemy
db = SQLAlchemy(app)

# Initialize Swagger
swagger = Swagger(app)


# -------------------------
# Database model
# -------------------------

class Observation(db.Model):
    """
    Observation stored in the database.

    We keep:
    - latitude / longitude as separate columns for easy filtering
    - 'data' as JSON so the rest of the payload is still flexible
    """
    __tablename__ = "observations"

    id = db.Column(db.Integer, primary_key=True)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    data = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        """Return the API shape: {id, data}."""
        return {
            "id": self.id,
            "data": self.data
        }


# -------------------------
# Error handlers
# -------------------------

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found", "code": 404}), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error", "code": 500}), 500


@app.errorhandler(400)
def bad_request(error):
    return jsonify({"error": "Bad request", "code": 400}), 400


# -------------------------
# Helper: geospatial validation (US-10)
# -------------------------

def validate_geospatial(payload):
    """
    Ensure payload has valid latitude/longitude.
    - Both must be present
    - Both must be numeric
    - latitude ∈ [-90, 90], longitude ∈ [-180, 180]
    Mutates payload so they are stored as floats.
    """
    lat = payload.get("latitude")
    lon = payload.get("longitude")

    if lat is None or lon is None:
        return False, "latitude and longitude are required"

    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return False, "latitude and longitude must be numeric"

    if not (-90 <= lat <= 90):
        return False, "latitude must be between -90 and 90"

    if not (-180 <= lon <= 180):
        return False, "longitude must be between -180 and 180"

    payload["latitude"] = lat
    payload["longitude"] = lon
    return True, ""


# -------------------------
# Basic routes
# -------------------------

@app.route("/")
def hello_world():
    return jsonify({"message": "Hello World!"}), 200


@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "ok"}), 200


# Attach external Swagger documentation to /health
health_check.__doc__ = health_check_docs


# -------------------------
# Story 3 + Story 9 + Story 10: CRUD + filtering + geospatial
# -------------------------

@app.route("/observations", methods=["GET"])
def list_observations():
    """
    List all observations, with optional filtering (US-09).
    - Generic field-based filtering via query params:
        e.g. /observations?country=UK&sensor_type=rain
      matches keys inside observation.data.
    - Geospatial filtering via bounding box:
        /observations?min_lat=...&max_lat=...&min_lon=...&max_lon=...
    """
    query = Observation.query

    # --- Geospatial filters applied in SQL (US-10) ---
    min_lat = request.args.get("min_lat", type=float)
    max_lat = request.args.get("max_lat", type=float)
    min_lon = request.args.get("min_lon", type=float)
    max_lon = request.args.get("max_lon", type=float)

    if min_lat is not None:
        query = query.filter(Observation.latitude >= min_lat)
    if max_lat is not None:
        query = query.filter(Observation.latitude <= max_lat)
    if min_lon is not None:
        query = query.filter(Observation.longitude >= min_lon)
    if max_lon is not None:
        query = query.filter(Observation.longitude <= max_lon)

    results = query.all()
    filtered = results

    # --- Generic parameter-based filters (US-09) ---
    ignored_keys = {"min_lat", "max_lat", "min_lon", "max_lon"}

    for key, value in request.args.items():
        if key in ignored_keys:
            continue

        if key == "id":
            try:
                wanted_id = int(value)
            except ValueError:
                continue
            filtered = [o for o in filtered if o.id == wanted_id]
        else:
            new_filtered = []
            for o in filtered:
                data = o.data or {}
                if str(data.get(key)) == value:
                    new_filtered.append(o)
            filtered = new_filtered

    return jsonify([o.to_dict() for o in filtered]), 200


@app.route("/observations", methods=["POST"])
def create_observation():
    """
    Create a new observation (US-10: must include latitude/longitude).
    The client's JSON payload is stored under 'data', with an auto-generated 'id'.
    """
    payload = request.get_json() or {}

    ok, msg = validate_geospatial(payload)
    if not ok:
        return jsonify({"error": msg}), 400

    obs = Observation(
        latitude=payload["latitude"],
        longitude=payload["longitude"],
        data=payload
    )
    db.session.add(obs)
    db.session.commit()

    return jsonify(obs.to_dict()), 201


@app.route("/observations/<int:obs_id>", methods=["GET"])
def get_observation(obs_id):
    """
    Get a single observation by ID.
    """
    obs = Observation.query.get(obs_id)
    if not obs:
        return jsonify({"error": "Observation not found"}), 404

    return jsonify(obs.to_dict()), 200


@app.route("/observations/<int:obs_id>", methods=["PUT"])
def replace_observation(obs_id):
    """
    Replace an observation (full update).
    The client must send a complete payload, including valid latitude/longitude.
    """
    obs = Observation.query.get(obs_id)
    if not obs:
        return jsonify({"error": "Observation not found"}), 404

    payload = request.get_json() or {}

    ok, msg = validate_geospatial(payload)
    if not ok:
        return jsonify({"error": msg}), 400

    obs.data = payload
    obs.latitude = payload["latitude"]
    obs.longitude = payload["longitude"]

    db.session.commit()
    return jsonify(obs.to_dict()), 200


@app.route("/observations/<int:obs_id>", methods=["PATCH"])
def patch_observation(obs_id):
    """
    Partially update an observation.
    If latitude/longitude are included, they are validated.
    """
    obs = Observation.query.get(obs_id)
    if not obs:
        return jsonify({"error": "Observation not found"}), 404

    payload = request.get_json() or {}

    if not isinstance(obs.data, dict):
        obs.data = {}

    merged = {**obs.data, **payload}

    if "latitude" in payload or "longitude" in payload:
        ok, msg = validate_geospatial(merged)
        if not ok:
            return jsonify({"error": msg}), 400

    obs.data = merged
    obs.latitude = merged["latitude"]
    obs.longitude = merged["longitude"]

    db.session.commit()
    return jsonify(obs.to_dict()), 200


@app.route("/observations/<int:obs_id>", methods=["DELETE"])
def delete_observation(obs_id):
    """
    Delete an observation.
    """
    obs = Observation.query.get(obs_id)
    if not obs:
        return jsonify({"error": "Observation not found"}), 404

    db.session.delete(obs)
    db.session.commit()

    return jsonify({"message": "Observation deleted successfully"}), 200

@app.route("/observations/bulk", methods=["GET"])
def bulk_health_check():  
    """
    Health check for bulk operations endpoint.
    """
    return jsonify({"status": "bulk operations endpoint is healthy"}), 200


@app.route("/observations/bulk", methods=["POST"])
def bulk_create_observations():
    """
    Bulk create observations.
    Accepts a JSON list of observation payloads.
    Performs validation for each item.
    If ANY record fails, ALL are rolled back.
    """
    payload = request.get_json()

    if not isinstance(payload, list):
        return jsonify({"error": "Request body must be a list"}), 400

    created = []
    errors = []

    # Validate each record before committing
    for index, item in enumerate(payload):
        ok, msg = validate_geospatial(item)
        if not ok:
            errors.append({
                "index": index,
                "error": msg,
                "record": item
            })

    # If any record invalid, return partial failure
    if errors:
        return jsonify({
            "message": "Bulk create failed",
            "errors": errors
        }), 400

    # If all records valid → insert them
    try:
        for item in payload:
            obs = Observation(
                latitude=item["latitude"],
                longitude=item["longitude"],
                data=item
            )
            db.session.add(obs)
            created.append(item)
        db.session.commit()

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Bulk create error: {str(e)}"}), 500

    return jsonify({
        "message": "Bulk create successful",
        "count": len(created),
        "records": created
    }), 201



@app.route("/observations/bulk", methods=["PUT"])
def bulk_update_observations():
    """
    Bulk update observations.
    Client must send a list of objects with {id, ...payload}
    If ANY record invalid or missing, whole request fails.
    """
    payload = request.get_json()

    if not isinstance(payload, list):
        return jsonify({"error": "Request body must be a list"}), 400

    errors = []

    # Validate all before performing updates
    for index, item in enumerate(payload):
        obs_id = item.get("id")
        if not obs_id:
            errors.append({
                "index": index,
                "error": "id is required for update",
                "record": item
            })
            continue

        obs = Observation.query.get(obs_id)
        if not obs:
            errors.append({
                "index": index,
                "error": f"Observation with id {obs_id} not found",
                "record": item
            })
            continue

        ok, msg = validate_geospatial(item)
        if not ok:
            errors.append({
                "index": index,
                "error": msg,
                "record": item
            })

    if errors:
        return jsonify({
            "message": "Bulk update failed",
            "errors": errors
        }), 400

    # If all good → perform updates
    try:
        for item in payload:
            obs = Observation.query.get(item["id"])
            obs.data = item
            obs.latitude = item["latitude"]
            obs.longitude = item["longitude"]
        db.session.commit()

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Bulk update error: {str(e)}"}), 500

    return jsonify({
        "message": "Bulk update successful",
        "count": len(payload)
    }), 200



"""JWT Authentication endpoints would go here (Story 12)"""

"""function to generate token"""

def create_token(user_id):
    payload = {
        "user_id": user_id,
        "exp": datetime.utcnow() + timedelta(hours=1),
        "iat": datetime.utcnow()
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")
    return token



"""decorator to protect routes"""

def jwt_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = None

        # Token must be passed via Authorization header
        if "Authorization" in request.headers:
            token = request.headers["Authorization"].replace("Bearer ", "")
        
        if not token:
            return jsonify({"error": "Missing token"}), 401
        
        try:
            decoded = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            request.user = decoded  # attach user to request
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401

        return f(*args, **kwargs)
    return wrapper



"""Login to get token"""
@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()

    if not data or data.get("username") != "admin" or data.get("password") != "password":
        return jsonify({"error": "Invalid credentials"}), 401

    token = create_token(user_id=1)
    return jsonify({"token": token}), 200

"""Protected route example"""

@app.route("/observations/protected", methods=["GET"])
@jwt_required
def protected_route():
    return jsonify({"message": f"Hello user {request.user['user_id']}!"})


if __name__ == "__main__":
    # Create the database tables if they don't exist yet
    with app.app_context():
        db.create_all()

    app.run(debug=True)
