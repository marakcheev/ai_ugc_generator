from openai import OpenAI
import os
from flask import Flask, request, jsonify
from flask_cors import CORS

# Load API key from environment
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("Please set the OPENAI_API_KEY environment variable")

# Initialize OpenAI client
client = OpenAI(api_key=api_key)

app = Flask(__name__)
CORS(app)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/chat", methods=["POST"])
def chat():
    """Simple text endpoint that forwards the user's message to the Chat API.

    Request JSON: { "message": "...", "model": "optional-model" }
    Response JSON: { "id": "...", "text": "assistant reply" }
    """
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"error": "Missing JSON body"}), 400

    message = data.get("message")
    model = data.get("model", "gpt-4o-mini")

    if not message:
        return jsonify({"error": "`message` field is required"}), 400

    try:
        # Create a chat completion using the SDK
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": message}],
            max_tokens=500,
        )

        # Extract text from common response shapes
        text = None
        if hasattr(resp, "choices") and len(resp.choices) > 0:
            choice = resp.choices[0]
            # try message.content or text
            if hasattr(choice, "message") and getattr(choice.message, "content", None) is not None:
                text = choice.message.content
            elif getattr(choice, "text", None) is not None:
                text = choice.text

        if text is None:
            # Fallback to stringifying the response
            text = str(resp)

        return jsonify({"id": getattr(resp, "id", None), "text": text})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    # Debug True is convenient for local testing; remove or set via env in production
    app.run(host="0.0.0.0", port=port, debug=True)
