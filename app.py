from flask import Flask, jsonify
from flasgger import Swagger
from swagger_config import SWAGGER_SETTINGS
from docs import health_check_docs

# Create Flask app
app = Flask(__name__)

# Apply Swagger configuration
app.config['SWAGGER'] = SWAGGER_SETTINGS

# Initialize Swagger
swagger = Swagger(app)

# Define route
@app.route('/')
def hello_world():
    return '<p> Hello world <p>'

@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "ok"}), 200

# Attach external Swagger documentation
health_check.__doc__ = health_check_docs

if __name__ == "__main__":
    app.run(debug=True)
