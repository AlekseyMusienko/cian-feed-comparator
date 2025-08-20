from flask import Flask, Response

app = Flask(__name__)

# Проверка на активность сервера
@app.route('/health')
def health_check():
    return Response("OK", status=200)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8443)
