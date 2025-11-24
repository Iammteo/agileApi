from flask  import  Flask, jsonify, request

app = Flask(__name__)

tasks = []

@app.route("/assignment", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy"}), 200

@app.route('/') 
def hello_world():
    return "<p>Hello, World! <p>"


@app.route("/assignment", methods = ["POST"])
def add_register():
    data = request.get_json()
    tasks.append(data)
    print(data)
    return jsonify({"message": "Task added successfully", "task": data})

if __name__ == "__main__":
    app.run(debug=True)