import streamlit as st
import pandas as pd
import joblib

# -------------------------------
# Load trained model
# -------------------------------
model = joblib.load("model.pkl")

st.title("Pump Impeller Diameter Prediction")

st.subheader("Enter Pump Parameters")

# -------------------------------
# NUMERIC INPUTS
# -------------------------------
stages = st.number_input("Stages", min_value=1.0, step=1.0)
flow = st.number_input("Flow")
head = st.number_input("Head")
speed = st.number_input("Speed")
pump_efficiency = st.number_input("Pump Efficiency")
pumpbkw_wkw = st.number_input("Pump BKW (Water kW)")

# -------------------------------
# PUMP TYPE (FULLY CATEGORICAL)
# -------------------------------
pump_type = st.selectbox(
    "Pump Type",
    [
        'RN 100', 'RN 100 A', 'RN 100 S', 'RN 125',
        'RN 32', 'RN 40', 'RN 40 VERT', 'RN 50',
        'RN 50 A', 'RN 65', 'RN 80',
        'RNV 100', 'RNV 32', 'RNV 80'
    ]
)

# -------------------------------
# OTHER CATEGORICAL DROPDOWNS
# -------------------------------
diffuser_moc = st.selectbox(
    "Diffuser MOC",
    [
        '2.5-3 NICI + COAT', 'ASTM A216 GR WCB', 'ASTM A743 CA6NM',
        'ASTM A743 GR CF3M', 'ASTM A743 GR CF8', 'ASTM A743 GR CF8M',
        'ASTM A890 GR CD4MCuN', 'CA15', 'CE3MN',
        'CI IS 210 GR 1.5-2%NICI', 'CI IS 210 GR 2-2.5%NICI',
        'CI IS 210 GR 2.5-3%NICI', 'CI IS 210 GR FG260'
    ]
)

impeller_moc = st.selectbox(
    "Impeller MOC",
    [
        'AS PER IDENTICAL ORDER', 'ASTM A216 GR WCB',
        'ASTM A743 GR CA15', 'ASTM A743 GR CA6NM',
        'ASTM A743 GR CF3M', 'ASTM A743 GR CF8',
        'ASTM A743 GR CF8M', 'ASTM A890 GR CD4MCuN',
        'CE3MN', 'CI IS 210 GR FG260',
        'FG220 ( Cast Iron )', 'IS 28 GR1',
        'IS 318 GR II', 'IS 318 GR LTB2',
        'IS 318 GRI', 'IS 318 GRV(LTB6)', 'LTB1'
    ]
)

# -------------------------------
# PREDICT BUTTON
# -------------------------------
if st.button("Predict Impeller Diameter"):

    user_input = pd.DataFrame([{
        "stages": stages,
        "flow": flow,
        "head": head,
        "speed": speed,
        "pump_efficiency": pump_efficiency,
        "diffuser_moc": diffuser_moc,
        "impeller_moc": impeller_moc,
        "pumpbkw_wkw": pumpbkw_wkw,
        "pump_type": pump_type   # fully categorical string
    }])

    prediction = model.predict(user_input)

    full_dia = prediction[0][0]
    trim_dia = prediction[0][1]

    st.success(f"Predicted Full Diameter: {round(full_dia, 2)} mm")
    st.success(f"Predicted Trimmed Diameter: {round(trim_dia, 2)} mm")
    