"""Interface layer (HTTP): thin FastAPI routes. No business logic lives here."""

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import HTMLResponse, JSONResponse

from app.service import ProcessReading, Reading, ReadingQueries, UnknownPatient

_STATUS_FOR_OUTCOME = {"stored": 201, "duplicate": 200}

_FORM_PAGE = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Mini HealthSuite</title></head>
<body>
<h1>Send one reading</h1>
<form id="reading">
  <label>Device <input name="device_id" value="dev-0001"></label><br>
  <label>Patient <input name="patient_ref" value="P0001"></label><br>
  <label>Heart rate <input name="heart_rate" type="number" value="72"></label><br>
  <label>SpO2 <input name="spo2" type="number" value="97"></label><br>
  <label>Temperature <input name="temperature" type="number" step="0.1" value="36.8"></label><br>
  <label>Seq <input name="seq" type="number" value="1"></label><br>
  <button type="submit">Send</button>
</form>
<pre id="result"></pre>
<script>
document.getElementById("reading").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const body = {
    device_id: form.get("device_id"), patient_ref: form.get("patient_ref"),
    heart_rate: Number(form.get("heart_rate")), spo2: Number(form.get("spo2")),
    temperature: Number(form.get("temperature")), seq: Number(form.get("seq")),
    sent_at: new Date().toISOString(),
  };
  const response = await fetch("/readings", {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
  });
  document.getElementById("result").textContent = response.status + " " + await response.text();
});
</script>
</body>
</html>"""


def create_app(process: ProcessReading, queries: ReadingQueries) -> FastAPI:
    app = FastAPI(title="Mini HealthSuite")

    @app.post("/readings")
    def post_reading(reading: Reading, response: Response) -> dict:
        try:
            outcome = process(reading)
        except UnknownPatient as exc:
            raise HTTPException(
                status_code=422, detail=f"unknown patient_ref: {exc}"
            ) from exc
        response.status_code = _STATUS_FOR_OUTCOME[outcome]
        return {"outcome": outcome}

    @app.get("/readings/latest")
    def latest_readings(limit: int = Query(50, ge=1, le=500)) -> list[dict]:
        return queries.latest(limit)

    @app.get("/stats")
    def stats() -> dict:
        return queries.stats()

    @app.get("/health")
    def health() -> JSONResponse:
        if queries.healthy():
            return JSONResponse({"status": "ok"})
        return JSONResponse({"status": "unavailable"}, status_code=503)

    @app.get("/", response_class=HTMLResponse)
    def form_page() -> str:
        return _FORM_PAGE

    return app
