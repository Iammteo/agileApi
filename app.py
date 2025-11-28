from flask import Flask, jsonify, request
from flasgger import Swagger
from swagger_config import SWAGGER_SETTINGS
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

# ---------------------------------------------------
# App + Swagger + Database setup
# ---------------------------------------------------

app = Flask(__name__)

# Apply Swagger configuration
app.config["SWAGGER"] = SWAGGER_SETTINGS

# SQLite database
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///observations.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Initialize extensions
db = SQLAlchemy(app)
swagger = Swagger(app)


# ---------------------------------------------------
# Database model
# ---------------------------------------------------

class Observation(db.Model):
    """
    Observation stored in the database.

    - latitude / longitude as separate columns for easy filtering
    - 'data' as JSON so the rest of the payload is flexible
    - 'timestamp' as the observation time used for date-range filtering
    - 'created_at' used for immutability (before current quarter = read-only)
    """
    __tablename__ = "observations"

    id = db.Column(db.Integer, primary_key=True)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    data = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    timestamp = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        """Return the API shape."""
        return {
            "id": self.id,
            "data": self.data,
        }


# ---------------------------------------------------
# Helpers
# ---------------------------------------------------

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


def parse_timestamp(ts_str):
    """
    Parse an ISO 8601 timestamp string into a datetime.
    Accepts e.g. '2025-01-10T12:00:00Z' or '2025-01-10T12:00:00+00:00'.
    Returns (datetime_or_None, error_message_or_None).
    """
    if not ts_str:
        return None, None

    cleaned = str(ts_str).strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned.replace("Z", "+00:00")

    try:
        dt = datetime.fromisoformat(cleaned)
        return dt, None
    except ValueError:
        return None, "Invalid timestamp format. Use ISO 8601 (e.g. 2025-01-10T12:00:00Z)."


def parse_date_param(date_str):
    """
    Parse a query date parameter into a date.
    Accepts:
    - 'YYYY-MM-DD'
    - Full ISO datetime like '2025-01-31T23:59:59Z' or '2025-01-31T23:59:59+00:00'

    Returns:
      (date_or_None, error_message_or_None)
    """
    if not date_str:
        return None, None

    cleaned = str(date_str).strip()

    # Strip accidental surrounding quotes
    if (cleaned.startswith('"') and cleaned.endswith('"')) or (
        cleaned.startswith("'") and cleaned.endswith("'")
    ):
        cleaned = cleaned[1:-1].strip()

    iso_candidate = cleaned
    if iso_candidate.endswith("Z"):
        iso_candidate = iso_candidate.replace("Z", "+00:00")

    # Try full ISO datetime / date
    try:
        dt = datetime.fromisoformat(iso_candidate)
        return dt.date(), None
    except ValueError:
        pass

    # Try first 10 chars as YYYY-MM-DD
    core = cleaned[:10]
    try:
        d = datetime.strptime(core, "%Y-%m-%d").date()
        return d, None
    except ValueError:
        return None, "Invalid date format. Use ISO 8601 (e.g. 2025-01-31 or 2025-01-31T23:59:59Z)."


def get_observation_date(obs):
    """
    Get the date used for filtering from the Observation.timestamp column.
    Returns a date object or None if not set.
    """
    if obs.timestamp is None:
        return None
    return obs.timestamp.date()


def get_current_quarter_start():
    """
    Start of current quarter (UTC, naive).
    Q1: Jan–Mar, Q2: Apr–Jun, Q3: Jul–Sep, Q4: Oct–Dec.
    """
    now = datetime.utcnow()
    current_q = ((now.month - 1) // 3) + 1
    start_month = (current_q - 1) * 3 + 1
    return datetime(now.year, start_month, 1)


def is_before_current_quarter(dt):
    """
    True if given datetime is before start of current quarter.
    If dt is None, treat as 'old' to be safe.
    """
    if dt is None:
        return True
    quarter_start = get_current_quarter_start()
    return dt < quarter_start


def record_is_immutable(obs):
    """
    Business rule for immutability:
    A record is immutable if its created_at is before the current quarter.
    """
    return is_before_current_quarter(obs.created_at)


# ---------------------------------------------------
# Error handlers
# ---------------------------------------------------

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found", "code": 404}), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error", "code": 500}), 500


@app.errorhandler(400)
def bad_request(error):
    return jsonify({"error": "Bad request", "code": 400}), 400


@app.errorhandler(405)
def method_not_allowed(error):
    return jsonify({
        "error": "METHOD_NOT_ALLOWED",
        "message": "The method is not allowed for the requested URL."
    }), 405


# ---------------------------------------------------
# Basic routes
# ---------------------------------------------------

@app.route("/")
def hello_world():
    return jsonify({"message": "Hello World!"}), 200


@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "ok"}), 200


# ---------------------------------------------------
# Observations: CRUD + filtering + bulk
# ---------------------------------------------------

@app.route("/observations", methods=["GET"])
def list_observations():
    """
    GET /observations
    Supports:
    - Geospatial filters: min_lat, max_lat, min_lon, max_lon
    - Date range filters: start_date, end_date (based on Observation.timestamp)
    - Generic field filters on data: e.g. country=UK, sensor=temperature
    """
    query = Observation.query

    # --- Geospatial filters in SQL ---
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

    # --- Date range filters based on Observation.timestamp ---
    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")

    start_date, err = parse_date_param(start_date_str)
    if err:
        return jsonify({"error": f"Invalid start_date format. {err}", "code": 400}), 400

    end_date, err = parse_date_param(end_date_str)
    if err:
        return jsonify({"error": f"Invalid end_date format. {err}", "code": 400}), 400

    if start_date or end_date:
        date_filtered = []
        for o in filtered:
            obs_date = get_observation_date(o)
            if obs_date is None:
                continue
            if start_date and obs_date < start_date:
                continue
            if end_date and obs_date > end_date:
                continue
            date_filtered.append(o)
        filtered = date_filtered

    # --- Generic filters on data + id ---
    ignored_keys = {
        "min_lat", "max_lat", "min_lon", "max_lon",
        "start_date", "end_date"
    }

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
    POST /observations
    - If body is a JSON object → create a single observation.
    - If body is a JSON array  → bulk create.
    """
    payload = request.get_json()

    # ---------- CASE 1: BULK (LIST) ----------
    if isinstance(payload, list):
        if not payload:
            return jsonify({"error": "Request body is an empty list"}), 400

        created = []
        errors = []

        for idx, item in enumerate(payload):
            if not isinstance(item, dict):
                errors.append({
                    "index": idx,
                    "error": "Item is not a JSON object"
                })
                continue

            ok, msg = validate_geospatial(item)
            if not ok:
                errors.append({"index": idx, "error": msg})
                continue

            ts_str = item.get("timestamp")
            obs_timestamp, err = parse_timestamp(ts_str)
            if err:
                errors.append({"index": idx, "error": err})
                continue

            obs = Observation(
                latitude=item["latitude"],
                longitude=item["longitude"],
                data=item,
                timestamp=obs_timestamp,
            )
            db.session.add(obs)
            db.session.flush()
            created.append(obs.to_dict())

        if created:
            db.session.commit()

        if not created and errors:
            return jsonify({
                "message": "No records created",
                "created": [],
                "errors": errors
            }), 400

        if created and errors:
            return jsonify({
                "message": "Some records created, some failed",
                "created": created,
                "errors": errors
            }), 207

        return jsonify({
            "message": "All records created successfully",
            "created": created,
            "errors": []
        }), 201

    # ---------- CASE 2: SINGLE OBJECT ----------
    payload = payload or {}

    ok, msg = validate_geospatial(payload)
    if not ok:
        return jsonify({"error": msg}), 400

    ts_str = payload.get("timestamp")
    obs_timestamp, err = parse_timestamp(ts_str)
    if err:
        return jsonify({"error": err}), 400

    obs = Observation(
        latitude=payload["latitude"],
        longitude=payload["longitude"],
        data=payload,
        timestamp=obs_timestamp,
    )
    db.session.add(obs)
    db.session.commit()

    return jsonify(obs.to_dict()), 201


@app.route("/observations/<int:obs_id>", methods=["GET"])
def get_observation(obs_id):
    obs = Observation.query.get(obs_id)
    if not obs:
        return jsonify({"error": "Observation not found"}), 404
    return jsonify(obs.to_dict()), 200


@app.route("/observations/<int:obs_id>", methods=["PUT"])
def replace_observation(obs_id):
    """
    Full update (PUT) – record must be mutable and payload must be valid.
    """
    obs = Observation.query.get(obs_id)
    if not obs:
        return jsonify({"error": "Observation not found"}), 404

    # Immutability check
    if record_is_immutable(obs):
        return jsonify({
            "error": "IMMUTABLE_RECORD",
            "message": "This observation was created before the current quarter and cannot be edited."
        }), 403

    payload = request.get_json() or {}

    ok, msg = validate_geospatial(payload)
    if not ok:
        return jsonify({"error": msg}), 400

    ts_str = payload.get("timestamp")
    obs_timestamp, err = parse_timestamp(ts_str)
    if err:
        return jsonify({"error": err}), 400

    obs.data = payload
    obs.latitude = payload["latitude"]
    obs.longitude = payload["longitude"]
    obs.timestamp = obs_timestamp

    db.session.commit()
    return jsonify(obs.to_dict()), 200


@app.route("/observations/<int:obs_id>", methods=["PATCH"])
def patch_observation(obs_id):
    """
    Partial update (PATCH) for a single observation.
    - Must send a JSON object (not a list).
    - Record must be mutable (current quarter).
    """
    obs = Observation.query.get(obs_id)
    if not obs:
        return jsonify({"error": "Observation not found"}), 404

    # Immutability check
    if record_is_immutable(obs):
        return jsonify({
            "error": "IMMUTABLE_RECORD",
            "message": "This observation was created before the current quarter and cannot be edited."
        }), 403

    payload = request.get_json()

    # Guard against list / wrong type
    if not isinstance(payload, dict):
        return jsonify({
            "error": "INVALID_PAYLOAD",
            "message": "Request body for /observations/<id> PATCH must be a JSON object. "
                       "For bulk updates, use /observations/bulk with a JSON array."
        }), 400

    if not isinstance(obs.data, dict):
        obs.data = {}

    merged = {**obs.data, **payload}

    # Validate lat/lon if changed
    if "latitude" in payload or "longitude" in payload:
        ok, msg = validate_geospatial(merged)
        if not ok:
            return jsonify({"error": msg}), 400

    # Handle timestamp if present
    if "timestamp" in merged:
        obs_timestamp, err = parse_timestamp(merged.get("timestamp"))
        if err:
            return jsonify({"error": err}), 400
        obs.timestamp = obs_timestamp

    obs.data = merged
    # merged should always contain latitude/longitude from original or patch
    obs.latitude = merged["latitude"]
    obs.longitude = merged["longitude"]

    db.session.commit()
    return jsonify(obs.to_dict()), 200


@app.route("/observations/<int:obs_id>", methods=["DELETE"])
def delete_observation(obs_id):
    obs = Observation.query.get(obs_id)
    if not obs:
        return jsonify({"error": "Observation not found"}), 404

    db.session.delete(obs)
    db.session.commit()

    return jsonify({"message": "Observation deleted successfully"}), 200


@app.route("/observations/bulk", methods=["PATCH"])
def bulk_update_observations():
    """
    Bulk PATCH update.
    Body: JSON array of objects with at least 'id' per item.
    Applies immutability rules per record.
    """
    payload = request.get_json()

    if not isinstance(payload, list) or not payload:
        return jsonify({"error": "Request body must be a non-empty JSON array"}), 400

    updated = []
    errors = []

    for idx, item in enumerate(payload):
        if not isinstance(item, dict):
            errors.append({"index": idx, "error": "Item is not a JSON object"})
            continue

        obs_id = item.get("id")
        if obs_id is None:
            errors.append({"index": idx, "error": "Missing 'id' field"})
            continue

        obs = Observation.query.get(obs_id)
        if not obs:
            errors.append({"index": idx, "error": f"Observation with id {obs_id} not found"})
            continue

        # Immutability check per record
        if record_is_immutable(obs):
            errors.append({
                "index": idx,
                "error": f"Observation with id {obs_id} is immutable (created before current quarter)"
            })
            continue

        if not isinstance(obs.data, dict):
            obs.data = {}

        merged = {**obs.data, **item}

        # Validate geospatial if changed
        if "latitude" in item or "longitude" in item:
            ok, msg = validate_geospatial(merged)
            if not ok:
                errors.append({"index": idx, "error": msg})
                continue

        # Validate timestamp if changed
        if "timestamp" in item:
            obs_timestamp, err = parse_timestamp(merged.get("timestamp"))
            if err:
                errors.append({"index": idx, "error": err})
                continue
            obs.timestamp = obs_timestamp

        obs.data = merged
        obs.latitude = merged["latitude"]
        obs.longitude = merged["longitude"]

        db.session.add(obs)
        db.session.flush()
        updated.append(obs.to_dict())

    if updated:
        db.session.commit()

    if not updated and errors:
        return jsonify({
            "message": "No records updated",
            "updated": [],
            "errors": errors
        }), 400

    if updated and errors:
        return jsonify({
            "message": "Some records updated, some failed",
            "updated": updated,
            "errors": errors
        }), 207

    return jsonify({
        "message": "All records updated successfully",
        "updated": updated,
        "errors": []
    }), 200


# ---------------------------------------------------
# Entry point
# ---------------------------------------------------

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
