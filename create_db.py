import pandas as pd
import sqlite3

# создаем подключение к БД
conn = sqlite3.connect("dashboard.db")

# загружаем CSV
aqtobe = pd.read_csv("aqtobeMay.csv")
atyrau = pd.read_csv("atyrauMay.csv")
karaganda = pd.read_csv("karagandaMay.csv")

# переносим в БД
aqtobe.to_sql("aqtobe", conn, if_exists="replace", index=False)
atyrau.to_sql("atyrau", conn, if_exists="replace", index=False)
karaganda.to_sql("karaganda", conn, if_exists="replace", index=False)

# закрываем подключение
conn.close()

print("БД создана")