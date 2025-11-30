from flask import Flask, jsonify, request
from flasgger import Swagger
from swagger_config import SWAGGER_SETTINGS
from flask_sqlalchemy import SQLAlchemy
from flask_marshmallow import Marshmallow
from marshmallow import fields
from datetime import datetime

# ---------------------------------------------------
# App + Swagger + Database setup
# ---------------------------------------------------

app = Flask(__name__)

# Swagger config from your existing file
app.config["SWAGGER"] = SWAGGER_SETTINGS

# SQLite database file
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///observations.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
ma = Marshmallow(app)
swagger = Swagger(app)

# ---------------------------------------------------
# Allowed spectral indices (US-10 extra spec)
# ---------------------------------------------------
# These are the only spectral index keys we accept in spectral_indices.
ALLOWED_SPECTRAL_INDICES = {
    "NDVI": "Normalised Difference Vegetation Index",
    "EVI": "Enhanced Vegetation Index",
    "SAVI": "Soil-Adjusted Vegetation Index",
    "NDWI": "Normalised Difference Water Index",
    "GNDVI": "Green NDVI",
    "NDMI": "Normalised Difference Moisture Index",
    "NBR": "Normalised Burn Ratio",
}


def validate_spectral_indices_dict(spectral):
    """
    Validate that spectral_indices:
    - is a dict
    - is not empty
    - only contains keys in ALLOWED_SPECTRAL_INDICES
    - values are numeric (float/int)
    Returns: (ok: bool, error_msg_or_None)
    """
    if not isinstance(spectral, dict):
        return False, "spectral_indices must be a JSON object"

    if not spectral:
        return False, "spectral_indices must not be empty"

    invalid_keys = [k for k in spectral.keys() if k not in ALLOWED_SPECTRAL_INDICES]
    if invalid_keys:
        return False, (
            f"Invalid spectral index keys: {', '.join(invalid_keys)}. "
            f"Allowed indices are: {', '.join(sorted(ALLOWED_SPECTRAL_INDICES.keys()))}."
        )

    # check values are numeric
    for k, v in spectral.items():
        try:
            float(v)
        except (TypeError, ValueError):
            return False, f"spectral_indices['{k}'] must be numeric"

    return True, None


# ---------------------------------------------------
# Database model (US-10 + later stories)
# ---------------------------------------------------

class Observation(db.Model):
    """
    Observation stored in the database.

    Fields required for US-10:
    - timestamp
    - timezone
    - coordinates (latitude, longitude)
    - satellite_id
    - spectral_indices (restricted list of index names)
    - notes (required)

    Extra:
    - created_at is the record creation time (used for immutability rules)
    - data stores the original JSON payload for flexibility
    """
    __tablename__ = "observations"

    id = db.Column(db.Integer, primary_key=True)

    # Geospatial
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)

    # Time
    timestamp = db.Column(db.DateTime, nullable=False)   # observation time (ISO 8601)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Other metadata
    timezone = db.Column(db.String(64), nullable=False)
    satellite_id = db.Column(db.String(64), nullable=False)
    spectral_indices = db.Column(db.JSON, nullable=False)
    notes = db.Column(db.Text, nullable=False)  # now NOT NULL (required)

    # Raw payload for flexibility
    data = db.Column(db.JSON, nullable=False)

    def to_dict(self):
        """
        Shape returned by the API. This guarantees timestamp is ISO 8601
        when clients query stored data (US-10 acceptance criterion).
        """
        return {
            "id": self.id,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "timestamp": self.timestamp.isoformat(),
            "created_at": self.created_at.isoformat(),
            "timezone": self.timezone,
            "satellite_id": self.satellite_id,
            "spectral_indices": self.spectral_indices,
            "notes": self.notes,
            "data": self.data,
        }


# ---------------------------------------------------
# Marshmallow schema (validation for US-10)
# ---------------------------------------------------

class ObservationSchema(ma.Schema):
    """
    Marshmallow schema for validating request bodies and
    serialising responses where needed.
    """

    id = fields.Int(dump_only=True)
    latitude = fields.Float(required=True)
    longitude = fields.Float(required=True)

    # timestamp is required but we parse the string ourselves to support 'Z'
    timestamp = fields.String(required=True)
    timezone = fields.String(required=True)

    satellite_id = fields.String(required=True)
    # Dict of spectral indices: keys=str, values=float (but we also validate separately)
    spectral_indices = fields.Dict(
        keys=fields.String(),
        values=fields.Float(),
        required=True,
    )
    notes = fields.String(required=True)  # now required (no allow_none)

    created_at = fields.DateTime(dump_only=True)
    data = fields.Dict(dump_only=True)


observation_schema = ObservationSchema()
observations_schema = ObservationSchema(many=True)


# ---------------------------------------------------
# Helper functions
# ---------------------------------------------------

def parse_timestamp(ts_str):
    """
    Parse an ISO 8601 timestamp string into a datetime.

    Accepts:
    - '2025-01-10T12:00:00Z'
    - '2025-01-10T12:00:00+00:00'
    - '2025-01-10T12:00:00' (no timezone, treated as naive UTC)

    Returns: (datetime_or_None, error_message_or_None)
    """
    if not ts_str:
        return None, "timestamp is required"

    cleaned = str(ts_str).strip()

    # Support trailing 'Z'
    if cleaned.endswith("Z"):
        cleaned = cleaned.replace("Z", "+00:00")

    try:
        dt = datetime.fromisoformat(cleaned)
        return dt, None
    except ValueError:
        return None, (
            "Invalid timestamp format. Use ISO 8601 "
            "(e.g. 2025-01-10T12:00:00Z)."
        )


def parse_date_param(date_str):
    """
    Parse a query date parameter into a date for US-09 date range filtering.

    Accepts:
    - 'YYYY-MM-DD'
    - or full ISO datetime like '2025-01-31T23:59:59Z'
    - or '2025-01-31T23:59:59+00:00'

    Returns: (date_or_None, error_message_or_None)
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

    # Try just the first 10 chars as YYYY-MM-DD
    core = cleaned[:10]
    try:
        d = datetime.strptime(core, "%Y-%m-%d").date()
        return d, None
    except ValueError:
        return None, (
            "Invalid date format. Use ISO 8601 "
            "(e.g. 2025-01-31 or 2025-01-31T23:59:59Z)."
        )


def get_observation_date(obs):
    """
    Extract date part of the observation timestamp (for date-range filtering).
    """
    if obs.timestamp is None:
        return None
    return obs.timestamp.date()


def get_current_quarter_start():
    """
    Start of current quarter (UTC, naive datetime).

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
    A record is immutable if created before the current quarter.
    (Used by later user stories – left intact.)
    """
    return is_before_current_quarter(obs.created_at)


def build_observation_from_payload(payload):
    """
    Central helper used by POST/PUT for single records.

    - Validates required fields with Marshmallow.
    - Validates spectral_indices allowed keys.
    - Parses ISO 8601 timestamp.
    - Returns (Observation_instance_or_None, errors_or_None).
    """
    errors = observation_schema.validate(payload)
    if errors:
        return None, errors

    # Parse timestamp
    ts_dt, ts_err = parse_timestamp(payload.get("timestamp"))
    if ts_err:
        return None, {"timestamp": [ts_err]}

    # Spectral indices validation (allowed names + numeric values)
    spectral = payload.get("spectral_indices")
    ok, msg = validate_spectral_indices_dict(spectral)
    if not ok:
        return None, {"spectral_indices": [msg]}

    # Latitude / longitude numeric
    try:
        lat = float(payload["latitude"])
        lon = float(payload["longitude"])
    except (TypeError, ValueError):
        return None, {
            "latitude": ["must be numeric"],
            "longitude": ["must be numeric"],
        }

    obs = Observation(
        latitude=lat,
        longitude=lon,
        timestamp=ts_dt,
        timezone=payload["timezone"],
        satellite_id=payload["satellite_id"],
        spectral_indices=spectral,
        notes=payload["notes"],
        data=payload,
    )
    return obs, None


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
# Basic routes (left simple – other user stories)
# ---------------------------------------------------

@app.get("/")
def root():
    return jsonify({"message": "API is running"}), 200


@app.get("/health")
def health_check():
    return jsonify({"status": "ok"}), 200


# ---------------------------------------------------
# US-09 + US-10 + later: /api/observations
# ---------------------------------------------------

@app.get("/api/observations")
def list_observations():
    """
    GET /api/observations

    Supports:
    - Geospatial filters (US-09):
        min_lat, max_lat, min_lon, max_lon
    - Date range filters (US-09):
        start_date, end_date (based on timestamp)
    - Generic field filters (US-09):
        e.g. ?timezone=UTC&satellite_id=SAT-001
        -> matched against the JSON `data` payload.
    """
    query = Observation.query

    # -------- Geospatial filters (location filter for US-09) --------
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

    # -------- Date range filters (US-09) --------
    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")

    start_date, err = parse_date_param(start_date_str)
    if err:
        return jsonify({"error": f"Invalid start_date. {err}", "code": 400}), 400

    end_date, err = parse_date_param(end_date_str)
    if err:
        return jsonify({"error": f"Invalid end_date. {err}", "code": 400}), 400

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

    # -------- Generic parameter-based filters (US-09) --------
    ignored_keys = {
        "min_lat", "max_lat", "min_lon", "max_lon",
        "start_date", "end_date"
    }

    for key, value in request.args.items():
        if key in ignored_keys:
            continue

        # Filter by id if requested: /api/observations?id=3
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


@app.post("/api/observations")
def create_observation():
    """
    POST /api/observations

    - If body is a JSON object → create a single observation.
    - If body is a JSON array  → bulk create.

    US-10:
    - Given valid JSON payload (required fields present), when submitted, data persists.
    - Given missing required fields, when submitted, API returns 400.
    - Given stored data, when queried, timestamp follows ISO 8601 (via to_dict()).
    """
    payload = request.get_json()

    # ---------- Bulk create (list) ----------
    if isinstance(payload, list):
        if not payload:
            return jsonify({"error": "Request body is an empty list"}), 400

        created = []
        errors = []

        for idx, item in enumerate(payload):
            if not isinstance(item, dict):
                errors.append({"index": idx, "error": "Item is not a JSON object"})
                continue

            obs, err = build_observation_from_payload(item)
            if err:
                errors.append({"index": idx, "errors": err})
                continue

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

    # ---------- Single create (object) ----------
    payload = payload or {}

    obs, err = build_observation_from_payload(payload)
    if err:
        return jsonify({"errors": err}), 400

    db.session.add(obs)
    db.session.commit()
    return jsonify(obs.to_dict()), 201


@app.get("/api/observations/<int:obs_id>")
def get_observation(obs_id):
    obs = Observation.query.get(obs_id)
    if not obs:
        return jsonify({"error": "Observation not found"}), 404
    return jsonify(obs.to_dict()), 200


@app.route("/api/observations/<int:obs_id>", methods=["DELETE"])
def delete_observation(obs_id):
    obs = Observation.query.get(obs_id)
    if not obs:
        return jsonify({"error": "Observation not found"}), 404

    db.session.delete(obs)
    db.session.commit()

    return jsonify({"message": "Observation deleted successfully"}), 200

# ---------------------------------------------------
# Entrypoint
# ---------------------------------------------------

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
