# # from flask import Flask, jsonify
# # from flasgger import Swagger
# # from swagger_config import SWAGGER_SETTINGS
# # from docs import health_check_docs

# # # Create Flask app
# # app = Flask(__name__)

# # # Apply Swagger configuration
# # app.config['SWAGGER'] = SWAGGER_SETTINGS

# # # Initialize Swagger
# # swagger = Swagger(app)

# # # Define route
# # @app.route('/')
# # def hello_world():
# #     return '<p> Hello world <p>'

# # @app.route("/health", methods=["GET"])
# # def health_check():
# #     return jsonify({"status": "ok"}), 200

# # # Attach external Swagger documentation
# # health_check.__doc__ = health_check_docs

# # if __name__ == "__main__":
# #     app.run(debug=True)
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


# # -------------------------
# # Existing routes
# # -------------------------

# @app.route('/')
# def hello_world():
#     return '<p> Hello world <p>'


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
#     return "", 204


# if __name__ == "__main__":
#     app.run(debug=True)
from flask import Flask, jsonify, request
from flasgger import Swagger
from swagger_config import SWAGGER_SETTINGS
from docs import health_check_docs
from datetime import datetime

# Temporary in-memory storage for observations
OBSERVATIONS = {}
NEXT_ID = 1

# Flask setup
app = Flask(__name__)
app.config["SWAGGER"] = SWAGGER_SETTINGS
swagger = Swagger(app)


# -------------------------
# Validation helpers
# -------------------------

# Fields that every observation must include
REQUIRED_FIELDS = [
    "timestamp",
    "timezone",
    "coordinates",
    "satellite_id",
    "spectral_indices",
    "notes",
]


def validate_iso8601(timestamp_str: str) -> bool:
    """
    Quick check to confirm the timestamp follows ISO 8601 format.
    """
    try:
        datetime.fromisoformat(timestamp_str)
        return True
    except (TypeError, ValueError):
        return False


def validate_observation_payload(payload):
    """
    Checks that the incoming JSON has all required fields
    and that values are in a reasonable format.
    """
    if not isinstance(payload, dict):
        return False, ({"error": "Invalid JSON body, expected an object"}, 400)

    # Identify missing fields
    missing = [f for f in REQUIRED_FIELDS if f not in payload]
    if missing:
        return (
            False,
            (
                {
                    "error": "Missing required fields",
                    "missing_fields": missing,
                },
                400,
            ),
        )

    # Make sure timestamp is in ISO format
    if not validate_iso8601(payload.get("timestamp")):
        return (
            False,
            (
                {
                    "error": "Invalid timestamp format",
                    "expected": "ISO 8601 (e.g. 2025-11-26T10:30:00)",
                },
                400,
            ),
        )

    # Coordinates should at least contain latitude and longitude
    coords = payload.get("coordinates")
    if not isinstance(coords, dict) or "lat" not in coords or "lon" not in coords:
        return (
            False,
            (
                {
                    "error": "Invalid coordinates",
                    "expected": {
                        "coordinates": {
                            "lat": "float",
                            "lon": "float",
                        }
                    },
                },
                400,
            ),
        )

    return True, None


# -------------------------
# Basic routes
# -------------------------

@app.route("/")
def hello_world():
    # Simple landing route
    return "<p> Hello world <p>"


@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "ok"}), 200


# Attach Swagger docs for /health
health_check.__doc__ = health_check_docs


# -------------------------
# Observation endpoints
# -------------------------

@app.route("/observations", methods=["GET"])
def list_observations():
    """
    Return all stored observations.
    """
    return jsonify(list(OBSERVATIONS.values())), 200


@app.route("/observations", methods=["POST"])
def create_observation():
    """
    Store a new observation record.
    """
    global NEXT_ID

    payload = request.get_json(silent=True)
    is_valid, error_resp = validate_observation_payload(payload)

    # Stop early if something is missing or malformed
    if not is_valid:
        error_body, status = error_resp
        return jsonify(error_body), status

    # Build a normalised observation record
    observation = {
        "id": NEXT_ID,
        "timestamp": payload["timestamp"],
        "timezone": payload["timezone"],
        "coordinates": payload["coordinates"],
        "satellite_id": payload["satellite_id"],
        "spectral_indices": payload["spectral_indices"],
        "notes": payload["notes"],
    }

    OBSERVATIONS[NEXT_ID] = observation
    NEXT_ID += 1

    return jsonify(observation), 201


@app.route("/observations/<int:obs_id>", methods=["GET"])
def get_observation(obs_id):
    """
    Look up an observation by its ID.
    """
    observation = OBSERVATIONS.get(obs_id)
    if not observation:
        return jsonify({"error": "Observation not found"}), 404

    return jsonify(observation), 200


@app.route("/observations/<int:obs_id>", methods=["PUT"])
def replace_observation(obs_id):
    """
    Fully replace an existing observation.
    """
    observation = OBSERVATIONS.get(obs_id)
    if not observation:
        return jsonify({"error": "Observation not found"}), 404

    payload = request.get_json(silent=True)
    is_valid, error_resp = validate_observation_payload(payload)

    if not is_valid:
        error_body, status = error_resp
        return jsonify(error_body), status

    updated = {
        "id": obs_id,
        "timestamp": payload["timestamp"],
        "timezone": payload["timezone"],
        "coordinates": payload["coordinates"],
        "satellite_id": payload["satellite_id"],
        "spectral_indices": payload["spectral_indices"],
        "notes": payload["notes"],
    }

    OBSERVATIONS[obs_id] = updated
    return jsonify(updated), 200


@app.route("/observations/<int:obs_id>", methods=["PATCH"])
def patch_observation(obs_id):
    """
    Apply a partial update to an observation.
    """
    observation = OBSERVATIONS.get(obs_id)
    if not observation:
        return jsonify({"error": "Observation not found"}), 404

    payload = request.get_json(silent=True) or {}

    if not isinstance(payload, dict):
        return jsonify({"error": "Invalid JSON body, expected an object"}), 400

    # Update only the fields that are present
    for key, value in payload.items():
        if key in REQUIRED_FIELDS:
            observation[key] = value

    return jsonify(observation), 200


@app.route("/observations/<int:obs_id>", methods=["DELETE"])
def delete_observation(obs_id):
    """
    Remove an observation from storage.
    """
    observation = OBSERVATIONS.get(obs_id)
    if not observation:
        return jsonify({"error": "Observation not found"}), 404

    del OBSERVATIONS[obs_id]
    return "", 204


if __name__ == "__main__":
    app.run(debug=True)
