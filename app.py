import os
import json
from datetime import datetime, timezone, timedelta
from functools import wraps

from flask import Flask, request, jsonify, g, current_app
from flask_sqlalchemy import SQLAlchemy
import jwt

db = SQLAlchemy()

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Observation(db.Model):
    __tablename__ = "observations"

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, nullable=False)
    timezone = db.Column(db.String(64), nullable=False)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    satellite_id = db.Column(db.String(64), nullable=False)
    spectral_indices = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = ["timestamp", "timezone", "latitude", "longitude", "satellite_id"]


def parse_iso8601(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Timestamp must be a string")

    # Handle trailing Z for UTC
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def format_iso8601(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    # Use Z for UTC
    return dt.isoformat().replace("+00:00", "Z")


def get_current_quarter_start() -> datetime:
    now = datetime.now(timezone.utc)
    quarter = ((now.month - 1) // 3) + 1
    start_month = 3 * (quarter - 1) + 1
    return datetime(now.year, start_month, 1, tzinfo=timezone.utc)


def is_historical_record(obs: Observation) -> bool:
    # Any record whose timestamp is before the start of the current quarter is "historical"
    q_start = get_current_quarter_start()
    return obs.timestamp < q_start


def observation_to_dict(obs: Observation) -> dict:
    return {
        "id": obs.id,
        "timestamp": format_iso8601(obs.timestamp),
        "timezone": obs.timezone,
        "latitude": obs.latitude,
        "longitude": obs.longitude,
        "satellite_id": obs.satellite_id,
        "spectral_indices": json.loads(obs.spectral_indices) if obs.spectral_indices else None,
        "notes": obs.notes,
    }


def validate_observation_payload(data, partial: bool = False):
    if not isinstance(data, dict):
        return None, ("INVALID_PAYLOAD", "Request body must be a JSON object.")

    errors = []

    if not partial:
        for field in REQUIRED_FIELDS:
            if field not in data:
                errors.append(f"Missing required field: {field}")

    # Timestamp
    ts = None
    if "timestamp" in data:
        try:
            ts = parse_iso8601(data["timestamp"])
        except Exception:
            errors.append("Invalid 'timestamp'. Must be ISO 8601 string.")
    elif not partial:
        # already counted as missing
        pass

    # Timezone
    tz = None
    if "timezone" in data:
        tz = data["timezone"]
        if not isinstance(tz, str) or not tz:
            errors.append("Invalid 'timezone'. Must be non-empty string.")

    # Latitude / Longitude
    lat = None
    if "latitude" in data:
        try:
            lat = float(data["latitude"])
        except Exception:
            errors.append("Invalid 'latitude'. Must be a number.")

    lon = None
    if "longitude" in data:
        try:
            lon = float(data["longitude"])
        except Exception:
            errors.append("Invalid 'longitude'. Must be a number.")

    # Satellite ID
    sat_id = None
    if "satellite_id" in data:
        sat_id = data["satellite_id"]
        if not isinstance(sat_id, str) or not sat_id:
            errors.append("Invalid 'satellite_id'. Must be non-empty string.")

    # Spectral indices (optional, should be JSON-serialisable)
    spectral_indices_json = None
    if "spectral_indices" in data and data["spectral_indices"] is not None:
        try:
            spectral_indices_json = json.dumps(data["spectral_indices"])
        except (TypeError, ValueError):
            errors.append("Invalid 'spectral_indices'. Must be JSON-serialisable.")

    # Notes (optional)
    notes = None
    if "notes" in data and data["notes"] is not None:
        notes = str(data["notes"])

    if errors:
        return None, ("VALIDATION_ERROR", "; ".join(errors))

    # Return normalised fields dict; for partial updates fields may be None / missing
    normalised = {}
    if ts is not None or (not partial and "timestamp" in data):
        normalised["timestamp"] = ts
    if tz is not None or (not partial and "timezone" in data):
        normalised["timezone"] = tz
    if lat is not None or (not partial and "latitude" in data):
        normalised["latitude"] = lat
    if lon is not None or (not partial and "longitude" in data):
        normalised["longitude"] = lon
    if sat_id is not None or (not partial and "satellite_id" in data):
        normalised["satellite_id"] = sat_id
    if "spectral_indices" in data:
        normalised["spectral_indices"] = spectral_indices_json
    if "notes" in data:
        normalised["notes"] = notes

    return normalised, None


# ---------------------------------------------------------------------------
# Auth helpers (simple JWT)
# ---------------------------------------------------------------------------

def jwt_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify(
                {"error": "UNAUTHENTICATED", "message": "Missing Bearer token."}
            ), 401

        token = auth_header.split(" ", 1)[1].strip()
        secret = current_app.config["JWT_SECRET_KEY"]
        try:
            payload = jwt.decode(token, secret, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            return jsonify(
                {"error": "UNAUTHENTICATED", "message": "Token has expired."}
            ), 401
        except jwt.InvalidTokenError:
            return jsonify(
                {"error": "UNAUTHENTICATED", "message": "Invalid token."}
            ), 401

        g.current_user = payload.get("sub")
        return fn(*args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app():
    app = Flask(__name__)

    # Basic config
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "DATABASE_URL", "sqlite:///observations.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY", "change-me-in-production")
    app.config["PROPAGATE_EXCEPTIONS"] = True

    db.init_app(app)

    with app.app_context():
        db.create_all()

    register_error_handlers(app)
    register_routes(app)

    return app


# ---------------------------------------------------------------------------
# Error handlers (JSON only)
# ---------------------------------------------------------------------------

def register_error_handlers(app: Flask):
    @app.errorhandler(400)
    def handle_400(err):
        return jsonify(
            {"error": "BAD_REQUEST", "message": getattr(err, "description", "Bad request.")}
        ), 400

    @app.errorhandler(401)
    def handle_401(err):
        return jsonify(
            {"error": "UNAUTHENTICATED", "message": getattr(err, "description", "Unauthenticated.")}
        ), 401

    @app.errorhandler(403)
    def handle_403(err):
        return jsonify(
            {"error": "FORBIDDEN", "message": getattr(err, "description", "Forbidden.")}
        ), 403

    @app.errorhandler(404)
    def handle_404(err):
        return jsonify(
            {"error": "NOT_FOUND", "message": getattr(err, "description", "Not found.")}
        ), 404

    @app.errorhandler(405)
    def handle_405(err):
        return jsonify(
            {"error": "METHOD_NOT_ALLOWED", "message": "Method not allowed."}
        ), 405

    @app.errorhandler(500)
    def handle_500(err):
        return jsonify(
            {"error": "INTERNAL_SERVER_ERROR", "message": "An unexpected error occurred."}
        ), 500


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def register_routes(app: Flask):
    # Health check (no auth)
    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok"}), 200

    # Simple login to get JWT (demo only)
    @app.route("/auth/login", methods=["POST"])
    def login():
        if not request.is_json:
            return jsonify(
                {"error": "INVALID_PAYLOAD", "message": "Request body must be JSON."}
            ), 400
        data = request.get_json(silent=True) or {}
        username = data.get("username")
        password = data.get("password")

        # In a real system, verify against a user store.
        valid_username = os.getenv("API_USERNAME", "admin")
        valid_password = os.getenv("API_PASSWORD", "password")

        if username != valid_username or password != valid_password:
            return jsonify(
                {"error": "UNAUTHENTICATED", "message": "Invalid credentials."}
            ), 401

        payload = {
            "sub": username,
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        token = jwt.encode(payload, app.config["JWT_SECRET_KEY"], algorithm="HS256")
        return jsonify({"access_token": token}), 200

    # CRUD for observations
    @app.route("/api/observations", methods=["GET", "POST"])
    @jwt_required
    def observations_collection():
        if request.method == "GET":
            return handle_observations_list()
        elif request.method == "POST":
            return handle_observation_create()

    @app.route("/api/observations/<int:obs_id>", methods=["GET", "PUT", "PATCH", "DELETE"])
    @jwt_required
    def observation_item(obs_id):
        if request.method == "GET":
            return handle_observation_get(obs_id)
        elif request.method == "PUT":
            return handle_observation_put(obs_id)
        elif request.method == "PATCH":
            return handle_observation_patch(obs_id)
        elif request.method == "DELETE":
            return handle_observation_delete(obs_id)

    # Bulk operations
    @app.route("/api/observations/bulk", methods=["POST", "PATCH"])
    @jwt_required
    def observations_bulk():
        if not request.is_json:
            return jsonify(
                {"error": "INVALID_PAYLOAD", "message": "Request body must be JSON."}
            ), 400

        payload = request.get_json(silent=True)
        if not isinstance(payload, list):
            return jsonify(
                {
                    "error": "INVALID_PAYLOAD",
                    "message": "Bulk operations require a JSON array of records.",
                }
            ), 400

        if request.method == "POST":
            return handle_bulk_create(payload)
        elif request.method == "PATCH":
            return handle_bulk_update(payload)

    # OpenAPI spec
    @app.route("/openapi.json", methods=["GET"])
    def openapi_json():
        return jsonify(OPENAPI_SPEC), 200

    # Swagger UI
    @app.route("/docs", methods=["GET"])
    def swagger_ui():
        # Swagger UI HTML loading swagger-ui via CDN
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Geospatial Intelligence API Docs</title>
            <link rel="stylesheet" type="text/css"
              href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
        </head>
        <body>
        <div id="swagger-ui"></div>
        <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
        <script>
        window.onload = function() {
          window.ui = SwaggerUIBundle({
            url: '/openapi.json',
            dom_id: '#swagger-ui'
          });
        };
        </script>
        </body>
        </html>
        """
        return html, 200, {"Content-Type": "text/html; charset=utf-8"}


# ---------------------------------------------------------------------------
# Handlers for observations
# ---------------------------------------------------------------------------

def handle_observations_list():
    # Filtering by date range and location via query params
    query = Observation.query

    start_ts_str = request.args.get("start_timestamp")
    end_ts_str = request.args.get("end_timestamp")

    try:
        if start_ts_str:
            start_ts = parse_iso8601(start_ts_str)
            query = query.filter(Observation.timestamp >= start_ts)
        if end_ts_str:
            end_ts = parse_iso8601(end_ts_str)
            query = query.filter(Observation.timestamp <= end_ts)
    except ValueError as e:
        return jsonify(
            {"error": "VALIDATION_ERROR", "message": f"Invalid date filter: {e}"}
        ), 400

    # Location bounding box filter (min_lat, max_lat, min_lon, max_lon)
    def parse_float_arg(name):
        val = request.args.get(name)
        if val is None:
            return None
        try:
            return float(val)
        except ValueError:
            raise ValueError(f"Query param '{name}' must be a number.")

    try:
        min_lat = parse_float_arg("min_lat")
        max_lat = parse_float_arg("max_lat")
        min_lon = parse_float_arg("min_lon")
        max_lon = parse_float_arg("max_lon")
    except ValueError as e:
        return jsonify(
            {"error": "VALIDATION_ERROR", "message": str(e)}
        ), 400

    if min_lat is not None:
        query = query.filter(Observation.latitude >= min_lat)
    if max_lat is not None:
        query = query.filter(Observation.latitude <= max_lat)
    if min_lon is not None:
        query = query.filter(Observation.longitude >= min_lon)
    if max_lon is not None:
        query = query.filter(Observation.longitude <= max_lon)

    observations = query.all()
    return jsonify([observation_to_dict(o) for o in observations]), 200


def handle_observation_create():
    if not request.is_json:
        return jsonify(
            {"error": "INVALID_PAYLOAD", "message": "Request body must be JSON."}
        ), 400

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(
            {
                "error": "INVALID_PAYLOAD",
                "message": "Request body must be a JSON object.",
            }
        ), 400

    normalised, err = validate_observation_payload(payload, partial=False)
    if err:
        code, message = err
        return jsonify({"error": code, "message": message}), 400

    obs = Observation(
        timestamp=normalised["timestamp"],
        timezone=normalised["timezone"],
        latitude=normalised["latitude"],
        longitude=normalised["longitude"],
        satellite_id=normalised["satellite_id"],
        spectral_indices=normalised.get("spectral_indices"),
        notes=normalised.get("notes"),
    )
    db.session.add(obs)
    db.session.commit()

    return jsonify(observation_to_dict(obs)), 201


def handle_observation_get(obs_id: int):
    obs = Observation.query.get(obs_id)
    if not obs:
        return jsonify({"error": "NOT_FOUND", "message": "Observation not found."}), 404
    return jsonify(observation_to_dict(obs)), 200


def handle_observation_put(obs_id: int):
    obs = Observation.query.get(obs_id)
    if not obs:
        return jsonify({"error": "NOT_FOUND", "message": "Observation not found."}), 404

    if is_historical_record(obs):
        return jsonify(
            {
                "error": "FORBIDDEN",
                "message": "Cannot modify records before the current quarter.",
            }
        ), 403

    if not request.is_json:
        return jsonify(
            {"error": "INVALID_PAYLOAD", "message": "Request body must be JSON."}
        ), 400

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(
            {
                "error": "INVALID_PAYLOAD",
                "message": "Request body must be a JSON object.",
            }
        ), 400

    normalised, err = validate_observation_payload(payload, partial=False)
    if err:
        code, message = err
        return jsonify({"error": code, "message": message}), 400

    obs.timestamp = normalised["timestamp"]
    obs.timezone = normalised["timezone"]
    obs.latitude = normalised["latitude"]
    obs.longitude = normalised["longitude"]
    obs.satellite_id = normalised["satellite_id"]
    obs.spectral_indices = normalised.get("spectral_indices")
    obs.notes = normalised.get("notes")

    db.session.commit()
    return jsonify(observation_to_dict(obs)), 200


def handle_observation_patch(obs_id: int):
    obs = Observation.query.get(obs_id)
    if not obs:
        return jsonify({"error": "NOT_FOUND", "message": "Observation not found."}), 404

    if is_historical_record(obs):
        return jsonify(
            {
                "error": "FORBIDDEN",
                "message": "Cannot modify records before the current quarter.",
            }
        ), 403

    if not request.is_json:
        return jsonify(
            {"error": "INVALID_PAYLOAD", "message": "Request body must be JSON."}
        ), 400

    payload = request.get_json(silent=True)

    # Guard against client accidentally sending a list to PATCH single record
    if isinstance(payload, list):
        return jsonify(
            {
                "error": "INVALID_PAYLOAD",
                "message": "Request body for /observations/<id> PATCH must be a JSON object. For bulk updates, use /observations/bulk with a JSON array.",
            }
        ), 400

    if not isinstance(payload, dict):
        return jsonify(
            {
                "error": "INVALID_PAYLOAD",
                "message": "Request body must be a JSON object.",
            }
        ), 400

    normalised, err = validate_observation_payload(payload, partial=True)
    if err:
        code, message = err
        return jsonify({"error": code, "message": message}), 400

    for key, value in normalised.items():
        setattr(obs, key, value)

    db.session.commit()
    return jsonify(observation_to_dict(obs)), 200


def handle_observation_delete(obs_id: int):
    obs = Observation.query.get(obs_id)
    if not obs:
        return jsonify({"error": "NOT_FOUND", "message": "Observation not found."}), 404

    if is_historical_record(obs):
        return jsonify(
            {
                "error": "FORBIDDEN",
                "message": "Cannot delete records before the current quarter.",
            }
        ), 403

    db.session.delete(obs)
    db.session.commit()
    return jsonify({"message": "Observation deleted."}), 200


def handle_bulk_create(records: list):
    created = []
    errors = []

    for idx, record in enumerate(records):
        normalised, err = validate_observation_payload(record, partial=False)
        if err:
            code, message = err
            errors.append(
                {
                    "index": idx,
                    "error": code,
                    "message": message,
                }
            )
            continue

        obs = Observation(
            timestamp=normalised["timestamp"],
            timezone=normalised["timezone"],
            latitude=normalised["latitude"],
            longitude=normalised["longitude"],
            satellite_id=normalised["satellite_id"],
            spectral_indices=normalised.get("spectral_indices"),
            notes=normalised.get("notes"),
        )
        db.session.add(obs)
        created.append(obs)

    db.session.commit()

    body = {
        "created": [observation_to_dict(o) for o in created],
        "errors": errors,
    }

    if errors:
        # Partial failure
        return jsonify(body), 207  # Multi-Status
    else:
        return jsonify(body), 201


def handle_bulk_update(records: list):
    updated = []
    errors = []

    for idx, record in enumerate(records):
        if not isinstance(record, dict):
            errors.append(
                {
                    "index": idx,
                    "error": "INVALID_PAYLOAD",
                    "message": "Each bulk update item must be a JSON object.",
                }
            )
            continue

        obs_id = record.get("id")
        if obs_id is None:
            errors.append(
                {
                    "index": idx,
                    "error": "VALIDATION_ERROR",
                    "message": "Missing 'id' for bulk update item.",
                }
            )
            continue

        obs = Observation.query.get(obs_id)
        if not obs:
            errors.append(
                {
                    "index": idx,
                    "error": "NOT_FOUND",
                    "message": f"Observation with id={obs_id} not found.",
                }
            )
            continue

        if is_historical_record(obs):
            errors.append(
                {
                    "index": idx,
                    "error": "FORBIDDEN",
                    "message": "Cannot modify records before the current quarter.",
                }
            )
            continue

        # Remove id before validation
        item_payload = dict(record)
        item_payload.pop("id", None)

        normalised, err = validate_observation_payload(item_payload, partial=True)
        if err:
            code, message = err
            errors.append(
                {
                    "index": idx,
                    "error": code,
                    "message": message,
                }
            )
            continue

        for key, value in normalised.items():
            setattr(obs, key, value)

        updated.append(obs)

    db.session.commit()

    body = {
        "updated": [observation_to_dict(o) for o in updated],
        "errors": errors,
    }

    if errors:
        return jsonify(body), 207
    else:
        return jsonify(body), 200


# ---------------------------------------------------------------------------
# OpenAPI specification (minimal but valid)
# ---------------------------------------------------------------------------

# OPENAPI_SPEC = {
#     "openapi": "3.0.0",
#     "info": {
#         "title": "Geospatial Intelligence API",
#         "version": "1.0.0",
#         "description": "Flask API for managing geospatial observations.",
#     },
#     "paths": {
#         "/health": {
#             "get": {
#                 "summary": "Health check",
#                 "responses": {
#                     "200": {
#                         "description": "API is healthy",
#                         "content": {
#                             "application/json": {
#                                 "schema": {
#                                     "type": "object",
#                                     "properties": {"status": {"type": "string"}},
#                                 }
#                             }
#                         },
#                     }
#                 },
#             }
#         },
#         "/auth/login": {
#             "post": {
#                 "summary": "Obtain JWT access token",
#                 "requestBody": {
#                     "required": True,
#                     "content": {
#                         "application/json": {
#                             "schema": {
#                                 "type": "object",
#                                 "properties": {
#                                     "username": {"type": "string"},
#                                     "password": {"type": "string"},
#                                 },
#                                 "required": ["username", "password"],
#                             }
#                         }
#                     },
#                 },
#                 "responses": {
#                     "200": {
#                         "description": "Login successful",
#                         "content": {
#                             "application/json": {
#                                 "schema": {
#                                     "type": "object",
#                                     "properties": {
#                                         "access_token": {"type": "string"}
#                                     },
#                                 }
#                             }
#                         },
#                     },
#                     "401": {
#                         "description": "Invalid credentials",
#                         "content": {
#                             "application/json": {"schema": {"$ref": "#/components/schemas/Error"}}
#                         },
#                     },
#                 },
#             }
#         },
#         "/api/observations": {
#             "get": {
#                 "summary": "List observations",
#                 "security": [{"bearerAuth": []}],
#                 "parameters": [
#                     {
#                         "name": "start_timestamp",
#                         "in": "query",
#                         "schema": {"type": "string", "format": "date-time"},
#                     },
#                     {
#                         "name": "end_timestamp",
#                         "in": "query",
#                         "schema": {"type": "string", "format": "date-time"},
#                     },
#                     {
#                         "name": "min_lat",
#                         "in": "query",
#                         "schema": {"type": "number"},
#                     },
#                     {
#                         "name": "max_lat",
#                         "in": "query",
#                         "schema": {"type": "number"},
#                     },
#                     {
#                         "name": "min_lon",
#                         "in": "query",
#                         "schema": {"type": "number"},
#                     },
#                     {
#                         "name": "max_lon",
#                         "in": "query",
#                         "schema": {"type": "number"},
#                     },
#                 ],
#                 "responses": {
#                     "200": {
#                         "description": "List of observations",
#                         "content": {
#                             "application/json": {
#                                 "schema": {
#                                     "type": "array",
#                                     "items": {"$ref": "#/components/schemas/Observation"},
#                                 }
#                             }
#                         },
#                     }
#                 },
#             },
#             "post": {
#                 "summary": "Create observation",
#                 "security": [{"bearerAuth": []}],
#                 "requestBody": {
#                     "required": True,
#                     "content": {
#                         "application/json": {
#                             "schema": {"$ref": "#/components/schemas/ObservationCreate"}
#                         }
#                     },
#                 },
#                 "responses": {
#                     "201": {
#                         "description": "Created",
#                         "content": {
#                             "application/json": {
#                                 "schema": {"$ref": "#/components/schemas/Observation"}
#                             }
#                         },
#                     },
#                     "400": {
#                         "description": "Validation error",
#                         "content": {
#                             "application/json": {"schema": {"$ref": "#/components/schemas/Error"}}
#                         },
#                     },
#                 },
#             },
#         },
#         "/api/observations/bulk": {
#             "post": {
#                 "summary": "Bulk create observations",
#                 "security": [{"bearerAuth": []}],
#                 "requestBody": {
#                     "required": True,
#                     "content": {
#                         "application/json": {
#                             "schema": {
#                                 "type": "array",
#                                 "items": {"$ref": "#/components/schemas/ObservationCreate"},
#                             }
#                         }
#                     },
#                 },
#                 "responses": {
#                     "201": {
#                         "description": "All records created successfully",
#                         "content": {
#                             "application/json": {
#                                 "schema": {"$ref": "#/components/schemas/BulkCreateResponse"}
#                             }
#                         },
#                     },
#                     "207": {
#                         "description": "Partial success",
#                         "content": {
#                             "application/json": {
#                                 "schema": {"$ref": "#/components/schemas/BulkCreateResponse"}
#                             }
#                         },
#                     },
#                 },
#             },
#             "patch": {
#                 "summary": "Bulk update observations",
#                 "security": [{"bearerAuth": []}],
#                 "requestBody": {
#                     "required": True,
#                     "content": {
#                         "application/json": {
#                             "schema": {
#                                 "type": "array",
#                                 "items": {
#                                     "allOf": [
#                                         {"$ref": "#/components/schemas/ObservationPatch"},
#                                         {
#                                             "type": "object",
#                                             "properties": {"id": {"type": "integer"}},
#                                             "required": ["id"],
#                                         },
#                                     ]
#                                 },
#                             }
#                         }
#                     },
#                 },
#                 "responses": {
#                     "200": {
#                         "description": "All updates applied",
#                         "content": {
#                             "application/json": {
#                                 "schema": {"$ref": "#/components/schemas/BulkUpdateResponse"}
#                             }
#                         },
#                     },
#                     "207": {
#                         "description": "Partial success",
#                         "content": {
#                             "application/json": {
#                                 "schema": {"$ref": "#/components/schemas/BulkUpdateResponse"}
#                             }
#                         },
#                     },
#                 },
#             },
#         },
#         "api/observations/{id}": {
#             "get": {
#                 "summary": "Get observation by id",
#                 "security": [{"bearerAuth": []}],
#                 "parameters": [
#                     {
#                         "name": "id",
#                         "in": "path",
#                         "required": True,
#                         "schema": {"type": "integer"},
#                     }
#                 ],
#                 "responses": {
#                     "200": {
#                         "description": "Observation",
#                         "content": {
#                             "application/json": {
#                                 "schema": {"$ref": "#/components/schemas/Observation"}
#                             }
#                         },
#                     },
#                     "404": {
#                         "description": "Not found",
#                         "content": {
#                             "application/json": {"schema": {"$ref": "#/components/schemas/Error"}}
#                         },
#                     },
#                 },
#             },
#             "put": {
#                 "summary": "Replace observation",
#                 "security": [{"bearerAuth": []}],
#                 "parameters": [
#                     {
#                         "name": "id",
#                         "in": "path",
#                         "required": True,
#                         "schema": {"type": "integer"},
#                     }
#                 ],
#                 "requestBody": {
#                     "required": True,
#                     "content": {
#                         "application/json": {
#                             "schema": {"$ref": "#/components/schemas/ObservationCreate"}
#                         }
#                     },
#                 },
#                 "responses": {
#                     "200": {
#                         "description": "Updated observation",
#                         "content": {
#                             "application/json": {
#                                 "schema": {"$ref": "#/components/schemas/Observation"}
#                             }
#                         },
#                     },
#                     "403": {
#                         "description": "Historical record forbidden to edit",
#                         "content": {
#                             "application/json": {"schema": {"$ref": "#/components/schemas/Error"}}
#                         },
#                     },
#                 },
#             },
#             "patch": {
#                 "summary": "Partially update observation",
#                 "security": [{"bearerAuth": []}],
#                 "parameters": [
#                     {
#                         "name": "id",
#                         "in": "path",
#                         "required": True,
#                         "schema": {"type": "integer"},
#                     }
#                 ],
#                 "requestBody": {
#                     "required": True,
#                     "content": {
#                         "application/json": {
#                             "schema": {"$ref": "#/components/schemas/ObservationPatch"}
#                         }
#                     },
#                 },
#                 "responses": {
#                     "200": {
#                         "description": "Updated observation",
#                         "content": {
#                             "application/json": {
#                                 "schema": {"$ref": "#/components/schemas/Observation"}
#                             }
#                         },
#                     },
#                     "403": {
#                         "description": "Historical record forbidden to edit",
#                         "content": {
#                             "application/json": {"schema": {"$ref": "#/components/schemas/Error"}}
#                         },
#                     },
#                 },
#             },
#             "delete": {
#                 "summary": "Delete observation",
#                 "security": [{"bearerAuth": []}],
#                 "parameters": [
#                     {
#                         "name": "id",
#                         "in": "path",
#                         "required": True,
#                         "schema": {"type": "integer"},
#                     }
#                 ],
#                 "responses": {
#                     "200": {
#                         "description": "Deleted",
#                         "content": {
#                             "application/json": {
#                                 "schema": {
#                                     "type": "object",
#                                     "properties": {"message": {"type": "string"}},
#                                 }
#                             }
#                         },
#                     },
#                     "403": {
#                         "description": "Historical record forbidden to delete",
#                         "content": {
#                             "application/json": {"schema": {"$ref": "#/components/schemas/Error"}}
#                         },
#                     },
#                 },
#             },
#         },
#     },
#     "components": {
#         "schemas": {
#             "Observation": {
#                 "type": "object",
#                 "properties": {
#                     "id": {"type": "integer"},
#                     "timestamp": {"type": "string", "format": "date-time"},
#                     "timezone": {"type": "string"},
#                     "latitude": {"type": "number"},
#                     "longitude": {"type": "number"},
#                     "satellite_id": {"type": "string"},
#                     "spectral_indices": {"type": "object"},
#                     "notes": {"type": "string"},
#                 },
#                 "required": [
#                     "id",
#                     "timestamp",
#                     "timezone",
#                     "latitude",
#                     "longitude",
#                     "satellite_id",
#                 ],
#             },
#             "ObservationCreate": {
#                 "type": "object",
#                 "properties": {
#                     "timestamp": {"type": "string", "format": "date-time"},
#                     "timezone": {"type": "string"},
#                     "latitude": {"type": "number"},
#                     "longitude": {"type": "number"},
#                     "satellite_id": {"type": "string"},
#                     "spectral_indices": {"type": "object"},
#                     "notes": {"type": "string"},
#                 },
#                 "required": [
#                     "timestamp",
#                     "timezone",
#                     "latitude",
#                     "longitude",
#                     "satellite_id",
#                 ],
#             },
#             "ObservationPatch": {
#                 "type": "object",
#                 "properties": {
#                     "timestamp": {"type": "string", "format": "date-time"},
#                     "timezone": {"type": "string"},
#                     "latitude": {"type": "number"},
#                     "longitude": {"type": "number"},
#                     "satellite_id": {"type": "string"},
#                     "spectral_indices": {"type": "object"},
#                     "notes": {"type": "string"},
#                 },
#             },
#             "Error": {
#                 "type": "object",
#                 "properties": {
#                     "error": {"type": "string"},
#                     "message": {"type": "string"},
#                 },
#             },
#             "BulkCreateResponse": {
#                 "type": "object",
#                 "properties": {
#                     "created": {
#                         "type": "array",
#                         "items": {"$ref": "#/components/schemas/Observation"},
#                     },
#                     "errors": {
#                         "type": "array",
#                         "items": {"$ref": "#/components/schemas/BulkError"},
#                     },
#                 },
#             },
#             "BulkUpdateResponse": {
#                 "type": "object",
#                 "properties": {
#                     "updated": {
#                         "type": "array",
#                         "items": {"$ref": "#/components/schemas/Observation"},
#                     },
#                     "errors": {
#                         "type": "array",
#                         "items": {"$ref": "#/components/schemas/BulkError"},
#                     },
#                 },
#             },
#             "BulkError": {
#                 "type": "object",
#                 "properties": {
#                     "index": {"type": "integer"},
#                     "error": {"type": "string"},
#                     "message": {"type": "string"},
#                 },
#             },
#         },
#         "securitySchemes": {
#             "bearerAuth": {
#                 "type": "http",
#                 "scheme": "bearer",
#                 "bearerFormat": "JWT",
#             }
#         },
#     },
# }


# ---------------------------------------------------------------------------
# OpenAPI specification (minimal but valid)
# ---------------------------------------------------------------------------

OPENAPI_SPEC = {
    "openapi": "3.0.0",
    "info": {
        "title": "Geospatial Intelligence API",
        "version": "1.0.0",
        "description": "Flask API for managing geospatial observations.",
    },
    "paths": {
        "/health": {
            "get": {
                "summary": "Health check",
                "responses": {
                    "200": {
                        "description": "API is healthy",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"status": {"type": "string"}},
                                }
                            }
                        },
                    }
                },
            }
        },
        "/auth/login": {
            "post": {
                "summary": "Obtain JWT access token",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "username": {"type": "string"},
                                    "password": {"type": "string"},
                                },
                                "required": ["username", "password"],
                            }
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": "Login successful",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "access_token": {"type": "string"}
                                    },
                                }
                            }
                        },
                    },
                    "401": {
                        "description": "Invalid credentials",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Error"}
                            }
                        },
                    },
                },
            }
        },
        "/api/observations": {
            "get": {
                "summary": "List observations",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    {
                        "name": "start_timestamp",
                        "in": "query",
                        "schema": {"type": "string", "format": "date-time"},
                    },
                    {
                        "name": "end_timestamp",
                        "in": "query",
                        "schema": {"type": "string", "format": "date-time"},
                    },
                    {
                        "name": "min_lat",
                        "in": "query",
                        "schema": {"type": "number"},
                    },
                    {
                        "name": "max_lat",
                        "in": "query",
                        "schema": {"type": "number"},
                    },
                    {
                        "name": "min_lon",
                        "in": "query",
                        "schema": {"type": "number"},
                    },
                    {
                        "name": "max_lon",
                        "in": "query",
                        "schema": {"type": "number"},
                    },
                ],
                "responses": {
                    "200": {
                        "description": "List of observations",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": {
                                        "$ref": "#/components/schemas/Observation"
                                    },
                                }
                            }
                        },
                    }
                },
            },
            "post": {
                "summary": "Create observation",
                "security": [{"bearerAuth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "$ref": "#/components/schemas/ObservationCreate"
                            }
                        }
                    },
                },
                "responses": {
                    "201": {
                        "description": "Created",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/Observation"
                                }
                            }
                        },
                    },
                    "400": {
                        "description": "Validation error",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Error"}
                            }
                        },
                    },
                },
            },
        },
        "/api/observations/bulk": {
            "post": {
                "summary": "Bulk create observations",
                "security": [{"bearerAuth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "array",
                                "items": {
                                    "$ref": "#/components/schemas/ObservationCreate"
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "201": {
                        "description": "All records created successfully",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/BulkCreateResponse"
                                }
                            }
                        },
                    },
                    "207": {
                        "description": "Partial success",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/BulkCreateResponse"
                                }
                            }
                        },
                    },
                },
            }
        },
        "/api/observations/{id}": {
            "get": {
                "summary": "Get observation by id",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    {
                        "name": "id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Observation",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Observation"}
                            }
                        },
                    },
                    "404": {
                        "description": "Not found",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Error"}
                            }
                        },
                    },
                },
            }
        },
    },
    "components": {
        "schemas": {
            "Observation": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "timestamp": {"type": "string", "format": "date-time"},
                    "timezone": {"type": "string"},
                    "latitude": {"type": "number"},
                    "longitude": {"type": "number"},
                    "satellite_id": {"type": "string"},
                    "spectral_indices": {"type": "object"},
                    "notes": {"type": "string"},
                },
                "required": [
                    "id",
                    "timestamp",
                    "timezone",
                    "latitude",
                    "longitude",
                    "satellite_id",
                ],
            },
            "ObservationCreate": {
                "type": "object",
                "properties": {
                    "timestamp": {"type": "string", "format": "date-time"},
                    "timezone": {"type": "string"},
                    "latitude": {"type": "number"},
                    "longitude": {"type": "number"},
                    "satellite_id": {"type": "string"},
                    "spectral_indices": {"type": "object"},
                    "notes": {"type": "string"},
                },
                "required": [
                    "timestamp",
                    "timezone",
                    "latitude",
                    "longitude",
                    "satellite_id",
                ],
            },
            "ObservationPatch": {
                "type": "object",
                "properties": {
                    "timestamp": {"type": "string", "format": "date-time"},
                    "timezone": {"type": "string"},
                    "latitude": {"type": "number"},
                    "longitude": {"type": "number"},
                    "satellite_id": {"type": "string"},
                    "spectral_indices": {"type": "object"},
                    "notes": {"type": "string"},
                },
            },
            "Error": {
                "type": "object",
                "properties": {
                    "error": {"type": "string"},
                    "message": {"type": "string"},
                },
            },
            "BulkCreateResponse": {
                "type": "object",
                "properties": {
                    "created": {
                        "type": "array",
                        "items": {"$ref": "#/components/schemas/Observation"},
                    },
                    "errors": {
                        "type": "array",
                        "items": {"$ref": "#/components/schemas/BulkError"},
                    },
                },
            },
            "BulkUpdateResponse": {
                "type": "object",
                "properties": {
                    "updated": {
                        "type": "array",
                        "items": {"$ref": "#/components/schemas/Observation"},
                    },
                    "errors": {
                        "type": "array",
                        "items": {"$ref": "#/components/schemas/BulkError"},
                    },
                },
            },
            "BulkError": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "error": {"type": "string"},
                    "message": {"type": "string"},
                },
            },
        },
        "securitySchemes": {
            "bearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
            }
        },
    },
}



# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)
