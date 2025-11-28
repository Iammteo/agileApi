from flask import Flask, jsonify, request
from flasgger import Swagger
from swagger_config import SWAGGER_SETTINGS
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

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
    _tablename_ = "observations"

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
    """
    Not Found
    ---
    tags:
      - Errors
    responses:
      404:
        description: Endpoint not found
        schema:
          type: object
          properties:
            error:
              type: string
              example: Endpoint not found
            code:
              type: integer
              example: 404
    """
    return jsonify({"error": "Endpoint not found", "code": 404}), 404


@app.errorhandler(500)
def internal_error(error):
    """
    Internal Server Error
    ---
    tags:
      - Errors
    responses:
      500:
        description: Internal server error
        schema:
          type: object
          properties:
            error:
              type: string
              example: Internal server error
            code:
              type: integer
              example: 500
    """
    return jsonify({"error": "Internal server error", "code": 500}), 500


@app.errorhandler(400)
def bad_request(error):
    """
    Bad Request
    ---
    tags:
      - Errors
    responses:
      400:
        description: Bad request
        schema:
          type: object
          properties:
            error:
              type: string
              example: Bad request
            code:
              type: integer
              example: 400
    """
    return jsonify({"error": "Bad request", "code": 400}), 400


# -------------------------
# Helper: geospatial validation
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
    """
    Root endpoint
    Simple greeting to verify the API is running.
    ---
    tags:
      - System
    responses:
      200:
        description: Greeting message
        schema:
          type: object
          properties:
            message:
              type: string
              example: Hello World!
    """
    return jsonify({"message": "Hello World!"}), 200


@app.route("/health", methods=["GET"])
def health_check():
    """
    Health check
    A simple endpoint to verify the API is running.
    ---
    tags:
      - System
    responses:
      200:
        description: API is healthy
        schema:
          type: object
          properties:
            status:
              type: string
              example: ok
    """
    return jsonify({"status": "ok"}), 200


# -------------------------
# Observations: CRUD + filtering + geospatial
# -------------------------

@app.route("/observations", methods=["GET"])
def list_observations():
    """
    List observations
    Returns all observations, optionally filtered by generic fields and geospatial bounds.
    ---
    tags:
      - Observations
    parameters:
      - name: min_lat
        in: query
        type: number
        required: false
        description: Minimum latitude for bounding box filter.
      - name: max_lat
        in: query
        type: number
        required: false
        description: Maximum latitude for bounding box filter.
      - name: min_lon
        in: query
        type: number
        required: false
        description: Minimum longitude for bounding box filter.
      - name: max_lon
        in: query
        type: number
        required: false
        description: Maximum longitude for bounding box filter.
      - name: id
        in: query
        type: integer
        required: false
        description: Filter by observation ID.
      - name: any_other_field
        in: query
        type: string
        required: false
        description: >
          Any other query parameter will be matched against
          the corresponding key inside observation.data.
          (e.g. /observations?country=UK&sensor_type=rain)
    responses:
      200:
        description: Filtered list of observations
        schema:
          type: array
          items:
            type: object
            properties:
              id:
                type: integer
                example: 1
              data:
                type: object
                example:
                  latitude: 51.5
                  longitude: -0.12
                  country: "UK"
                  sensor_type: "rain"
      400:
        description: Bad request
        schema:
          type: object
          properties:
            error:
              type: string
            code:
              type: integer
    """
    query = Observation.query

    # --- Geospatial filters applied in SQL ---
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

    # --- Generic parameter-based filters ---
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
    Create an observation
    Creates a new observation with required latitude/longitude.
    ---
    tags:
      - Observations
    consumes:
      - application/json
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          description: Observation payload stored under data.
          required:
            - latitude
            - longitude
          properties:
            latitude:
              type: number
              example: 51.5
            longitude:
              type: number
              example: -0.12
            country:
              type: string
              example: UK
            sensor_type:
              type: string
              example: rain
    responses:
      201:
        description: Observation created
        schema:
          type: object
          properties:
            id:
              type: integer
              example: 1
            data:
              type: object
      400:
        description: Validation error (e.g. missing or invalid latitude/longitude)
        schema:
          type: object
          properties:
            error:
              type: string
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
    Get an observation
    Returns a single observation by ID.
    ---
    tags:
      - Observations
    parameters:
      - name: obs_id
        in: path
        type: integer
        required: true
        description: Observation ID.
    responses:
      200:
        description: Observation found
        schema:
          type: object
          properties:
            id:
              type: integer
            data:
              type: object
      404:
        description: Observation not found
        schema:
          type: object
          properties:
            error:
              type: string
    """
    obs = Observation.query.get(obs_id)
    if not obs:
        return jsonify({"error": "Observation not found"}), 404

    return jsonify(obs.to_dict()), 200


@app.route("/observations/<int:obs_id>", methods=["PUT"])
def replace_observation(obs_id):
    """
    Replace an observation
    Fully replaces an observation's data by ID (PUT).
    ---
    tags:
      - Observations
    consumes:
      - application/json
    parameters:
      - name: obs_id
        in: path
        type: integer
        required: true
        description: Observation ID.
      - name: body
        in: body
        required: true
        schema:
          type: object
          description: New observation payload (must include valid latitude/longitude).
          properties:
            latitude:
              type: number
              example: 40.7
            longitude:
              type: number
              example: -74.0
            country:
              type: string
              example: US
    responses:
      200:
        description: Observation updated
        schema:
          type: object
          properties:
            id:
              type: integer
            data:
              type: object
      400:
        description: Validation error
      404:
        description: Observation not found
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
    Patch an observation
    Partially updates an observation's data by ID (PATCH).
    ---
    tags:
      - Observations
    consumes:
      - application/json
    parameters:
      - name: obs_id
        in: path
        type: integer
        required: true
        description: Observation ID.
      - name: body
        in: body
        required: true
        schema:
          type: object
          description: Partial payload to merge into data.
          example:
            country: FR
    responses:
      200:
        description: Observation updated
        schema:
          type: object
          properties:
            id:
              type: integer
            data:
              type: object
      400:
        description: Validation error
      404:
        description: Observation not found
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
    Delete an observation
    Deletes an observation by ID.
    ---
    tags:
      - Observations
    parameters:
      - name: obs_id
        in: path
        type: integer
        required: true
        description: Observation ID.
    responses:
      200:
        description: Observation deleted
        schema:
          type: object
          properties:
            message:
              type: string
              example: Observation deleted successfully
      404:
        description: Observation not found
        schema:
          type: object
          properties:
            error:
              type: string
    """
    obs = Observation.query.get(obs_id)
    if not obs:
        return jsonify({"error": "Observation not found"}), 404

    db.session.delete(obs)
    db.session.commit()

    return jsonify({"message": "Observation deleted successfully"}), 200


if __name__ == "__main__":
    # Create the database tables if they don't exist yet
    with app.app_context():
        db.create_all()

    app.run(debug=True)