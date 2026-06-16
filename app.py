from flask import Flask, render_template, request, jsonify
from scraper import search_one_part, aggregate_results

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/search/part", methods=["POST"])
def search_part():
    """Search a single part. Called once per part from the frontend."""
    body    = request.get_json(force=True)
    part    = body.get("part", "").strip()
    year    = body.get("year", "").strip()
    make    = body.get("make", "").strip()
    model   = body.get("model", "").strip()
    zipcode = body.get("zip", "").strip()
    radius  = int(body.get("radius", 50))

    if not part:
        return jsonify({"error": "Part name is required."}), 400
    if not zipcode:
        return jsonify({"error": "ZIP code is required."}), 400

    result = search_one_part(part, year, make, model, zipcode, radius)
    return jsonify(result)


@app.route("/api/aggregate", methods=["POST"])
def aggregate():
    """Combine individual part results into a ranked store list."""
    body         = request.get_json(force=True)
    parts        = body.get("parts", [])
    part_results = body.get("results", [])
    return jsonify(aggregate_results(parts, part_results))


if __name__ == "__main__":
    print("\n  Auto Parts Finder is running.")
    print("  Open your browser to:  http://localhost:5000\n")
    app.run(debug=False, port=5000)
