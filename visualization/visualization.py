import pandas as pd
import matplotlib.pyplot as plt
from sqlalchemy import create_engine, text



USER     = "root"
PASSWORD = "12345"   
HOST     = "127.0.0.1"
PORT     = "3306"

dw = create_engine(f"mysql+pymysql://{USER}:{PASSWORD}@{HOST}:{PORT}/movie_rental_dw")



with dw.connect() as conn:

    rentals_by_month = pd.read_sql(text("""
        SELECT d.month_name AS Month, COUNT(*) AS Rentals
        FROM fact_rental fr
        JOIN dim_date d ON fr.date_key = d.date_key
        GROUP BY d.month_number, d.month_name
        ORDER BY d.month_number
    """), conn)

    top_films = pd.read_sql(text("""
        SELECT f.title AS Film, COUNT(*) AS Rentals
        FROM fact_rental fr
        JOIN dim_film f ON fr.film_key = f.film_key
        GROUP BY f.title
        ORDER BY Rentals DESC
        LIMIT 10
    """), conn)

    by_category = pd.read_sql(text("""
        SELECT f.category AS Category, COUNT(*) AS Rentals
        FROM fact_rental fr
        JOIN dim_film f ON fr.film_key = f.film_key
        GROUP BY f.category
        ORDER BY Rentals DESC
    """), conn)

#  Line Plot — Rentals by Month


rentals_by_month.plot(x="Month", y="Rentals", kind="line")
plt.title("Rental Activity by Month")
plt.xlabel("Month")
plt.ylabel("Total Rentals")
plt.xticks(rotation=45)
plt.tight_layout()
plt.show()


#  Bar Chart — Top 10 Most Rented Films


top_films.plot(x="Film", y="Rentals", kind="bar")
plt.title("Top 10 Most Rented Films")
plt.xlabel("Film")
plt.ylabel("Total Rentals")
plt.xticks(rotation=45, ha="right")
plt.tight_layout()
plt.show()


#  Pie Chart — Rentals by Category

by_category.set_index("Category")["Rentals"].plot(kind="pie", autopct="%1.1f%%")
plt.ylabel("")
plt.title("Rentals by Film Category")
plt.tight_layout()
plt.show()

print("✅ Done!")