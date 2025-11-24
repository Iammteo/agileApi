from flask  import  Flask, jsonify

app = Flask(__name__)


@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "ok"}), 200

@app.route('/') 
def hello_world():
    return "<p>Hello, World! <p>"


if __name__ == "__main__":
    app.run(debug=True)