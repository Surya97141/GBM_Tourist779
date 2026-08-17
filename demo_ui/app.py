"""Streamlit front end for the /recommend endpoint. Pure HTTP client -
talks to the already-running orchestrator over a real request, exactly
the way curl already does, and never imports anything from the backend.
This exists to make the same pipeline nicer to look at for a demo; it
changes nothing about how the pipeline itself behaves.

Run with the backend (agent_orchestrator/app.py) already running:
    streamlit run demo_ui/app.py
"""

import json
from pathlib import Path

import requests
import streamlit as st
from dotenv import load_dotenv

from weather import get_weather

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(Path(__file__).resolve().parent / ".env")

RECOMMEND_ENDPOINT = "http://127.0.0.1:8000/recommend"

DEMO_DESTINATIONS = [
    ("dest_001", "Amber Fort"),
    ("dest_006", "Jaigarh Fort"),
    ("dest_003", "Hawa Mahal"),
    ("dest_012", "Johari Bazaar"),
    ("dest_009", "Birla Mandir"),
]

DESTINATIONS_PATH = REPO_ROOT / "track_A_filtering" / "destinations.json"


def load_destination_coordinates():
    with open(DESTINATIONS_PATH, encoding="utf-8") as f:
        destinations = json.load(f)
    return {d["destination_id"]: (d["lat"], d["lng"]) for d in destinations}


SUBMIT_TIMEOUT_SECONDS = 15


def submit_photo(uploaded_file, destination_id):
    try:
        response = requests.post(
            RECOMMEND_ENDPOINT,
            data={"destination_id": destination_id},
            files={"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)},
            timeout=SUBMIT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError:
        return {
            "status": "error",
            "message": f"Could not reach the backend at {RECOMMEND_ENDPOINT}. Is agent_orchestrator/app.py running?",
        }
    except requests.exceptions.Timeout:
        return {"status": "error", "message": f"Request timed out after {SUBMIT_TIMEOUT_SECONDS} seconds."}
    except requests.exceptions.RequestException as e:
        return {"status": "error", "message": str(e)}


def render_recommendation_card(rec):
    with st.container(border=True):
        st.markdown(f"**{rec['name']}**")
        st.caption(f"{rec['category']} · {rec['distance_km']:.1f} km away")
        st.write(rec["explanation"])


def render_response(response):
    status = response.get("status")

    if status == "error":
        st.error(response["message"])
        return

    if status == "success":
        crowd_level = response.get("crowd_level")
        if crowd_level:
            st.error(f"Crowd level: {crowd_level}")
        else:
            st.error("This destination is currently crowded.")
        st.subheader("Nearby alternatives")
        for rec in response.get("recommendations", []):
            render_recommendation_card(rec)
        return

    if status == "not_barriered":
        crowd_level = response.get("crowd_level", "unknown")
        st.success(f"Crowd level: {crowd_level} — no rerouting needed, this destination looks fine to visit.")
        return

    if status == "unknown_destination":
        st.error(f"Unknown destination_id: {response.get('destination_id')}")
        return

    if status == "no_alternatives_found":
        crowd_level = response.get("crowd_level")
        if crowd_level:
            st.error(f"Crowd level: {crowd_level}")
        else:
            st.error("This destination is currently crowded.")
        radius_used = response.get("radius_used")
        radius_expanded = response.get("radius_expanded")
        if radius_expanded:
            st.warning(
                f"Looked within {radius_used} km (widened from the default search radius) "
                f"and found no clear alternative nearby."
            )
        else:
            st.warning(f"Looked within {radius_used} km and found no clear alternative nearby.")
        return

    st.warning(f"Unexpected response status: {status!r} — showing the raw response so nothing is hidden.")
    st.json(response)


st.title("Crowd Check Demo")
st.caption("Uploads a photo to the real recommendation pipeline running at " + RECOMMEND_ENDPOINT)

destination_names = [name for _, name in DEMO_DESTINATIONS]
destination_lookup = {name: dest_id for dest_id, name in DEMO_DESTINATIONS}
destination_coordinates = load_destination_coordinates()

selected_name = st.selectbox("Destination", destination_names)
selected_id = destination_lookup[selected_name]

coordinates = destination_coordinates.get(selected_id)
if coordinates is not None:
    weather = get_weather(*coordinates)
    if weather.get("available"):
        st.caption(f"{selected_name} — {weather['temperature']:.0f}°C, {weather['description']}")

uploaded_file = st.file_uploader("Photo of the destination", type=["jpg", "jpeg", "png"])

col1, col2 = st.columns(2)

with col1:
    if uploaded_file is not None:
        st.image(uploaded_file, caption="Uploaded photo")

if st.button("Check crowd & get alternatives", disabled=uploaded_file is None):
    with st.spinner("Checking..."):
        response = submit_photo(uploaded_file, selected_id)
    with col2:
        render_response(response)
