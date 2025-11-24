import streamlit as st
import requests
import json
from io import StringIO

API_URL = "https://<your-fastapi-endpoint>"  # or http://localhost:8000 for local

st.title("Productivity Tracker")

tickets = st.file_uploader("Upload Tickets CSV", type="csv")
calls = st.file_uploader("Upload Calls CSV", type="csv")

start = st.date_input("Start Date")
end = st.date_input("End Date")

if st.button("Process"):
    form = {
        "start_period": str(start) + "T00:00:00",
        "end_period": str(end) + "T23:59:59",
        "overlap_mode": "split",
        "default_shift_hours": 8
    }

    files = {}
    if tickets:
        files["tickets"] = ("tickets.csv", tickets.getvalue(), "text/csv")
    if calls:
        files["calls"] = ("calls.csv", calls.getvalue(), "text/csv")

    with st.spinner("Processing…"):
        r = requests.post(API_URL + "/process", data=form, files=files)

    if r.status_code != 200:
        st.error("Error: " + r.text)
    else:
        data = r.json()
        st.success("Processed successfully!")
        st.json(data)
