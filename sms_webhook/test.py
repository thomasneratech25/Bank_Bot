from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/sms", methods=["POST"])
def receive_sms():
    # PPPSCN may send JSON or form data
    data = request.get_json(silent=True)
    if data is None:
        data = request.form.to_dict()

    print("📩 Incoming SMS")
    print(data)

    return jsonify({"success": True}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000)
