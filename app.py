import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px

# подключение к БД
conn = sqlite3.connect("dashboard.db")

# загрузка данных
aqtobe = pd.read_sql("SELECT * FROM aqtobe", conn)
atyrau = pd.read_sql("SELECT * FROM atyrau", conn)
karaganda = pd.read_sql("SELECT * FROM karaganda", conn)

# заголовок
st.title("Marketing Analytics Dashboard")

# выбор города
city = st.selectbox(
    "Выберите город",
    ["Aqtobe", "Atyrau", "Karaganda"]
)

# выбор таблицы
if city == "Aqtobe":
    df = aqtobe
elif city == "Atyrau":
    df = atyrau
else:
    df = karaganda

# показать данные
st.subheader("Таблица данных")
st.dataframe(df)

# информация
st.subheader("Количество строк")
st.write(len(df))

# график пропусков
st.subheader("Заполненность данных")

missing = df.isnull().sum().reset_index()
missing.columns = ["column", "missing"]

fig = px.bar(
    missing,
    x="column",
    y="missing"
)

st.plotly_chart(fig)

conn.close()