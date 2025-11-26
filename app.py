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
from flask import Flask, jsonify, request
from flasgger import Swagger
from swagger_config import SWAGGER_SETTINGS
from docs import health_check_docs

# Simple in-memory "database" for Sprint 1 (Story 3)
OBSERVATIONS = {}
NEXT_ID = 1

# Create Flask app
app = Flask(__name__)

# Apply Swagger configuration
app.config['SWAGGER'] = SWAGGER_SETTINGS

# Initialize Swagger
swagger = Swagger(app)


# -------------------------
# Existing routes
# -------------------------

@app.route('/')
def hello_world():
    return '<p> Hello world <p>'


@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "ok"}), 200


# Attach external Swagger documentation to /health
health_check.__doc__ = health_check_docs


# -------------------------
# Story 3: CRUD endpoints
# -------------------------

@app.route("/observations", methods=["GET"])
def list_observations():
    """
    List all observations.
    """
    # Return a list of all stored observations
    return jsonify(list(OBSERVATIONS.values())), 200


@app.route("/observations", methods=["POST"])
def create_observation():
    """
    Create a new observation.
    """
    global NEXT_ID

    payload = request.get_json() or {}

    # For now, we just store whatever JSON comes in under 'data'
    observation = {
        "id": NEXT_ID,
        "data": payload
    }
    OBSERVATIONS[NEXT_ID] = observation
    NEXT_ID += 1

    # 201 Created
    return jsonify(observation), 201


@app.route("/observations/<int:obs_id>", methods=["GET"])
def get_observation(obs_id):
    """
    Get a single observation by ID.
    """
    observation = OBSERVATIONS.get(obs_id)
    if not observation:
        return jsonify({"error": "Observation not found"}), 404

    return jsonify(observation), 200


@app.route("/observations/<int:obs_id>", methods=["PUT"])
def replace_observation(obs_id):
    """
    Replace an observation (full update).
    """
    observation = OBSERVATIONS.get(obs_id)
    if not observation:
        return jsonify({"error": "Observation not found"}), 404

    payload = request.get_json() or {}
    observation["data"] = payload

    return jsonify(observation), 200


@app.route("/observations/<int:obs_id>", methods=["PATCH"])
def patch_observation(obs_id):
    """
    Partially update an observation.
    """
    observation = OBSERVATIONS.get(obs_id)
    if not observation:
        return jsonify({"error": "Observation not found"}), 404

    payload = request.get_json() or {}

    # Make sure observation["data"] is a dict
    if not isinstance(observation["data"], dict):
        observation["data"] = {}

    if isinstance(payload, dict):
        observation["data"].update(payload)

    return jsonify(observation), 200


@app.route("/observations/<int:obs_id>", methods=["DELETE"])
def delete_observation(obs_id):
    """
    Delete an observation.
    """
    observation = OBSERVATIONS.get(obs_id)
    if not observation:
        return jsonify({"error": "Observation not found"}), 404

    del OBSERVATIONS[obs_id]
    # 204 No Content
    return "", 204


if __name__ == "__main__":
    app.run(debug=True)
