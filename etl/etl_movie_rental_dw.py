import pandas as pd
from sqlalchemy import create_engine, text

USER     = "root"
PASSWORD = "12345"
HOST     = "127.0.0.1"
PORT     = "3306"

oltp = create_engine(f"mysql+pymysql://{USER}:{PASSWORD}@{HOST}:{PORT}/sakila")
dw   = create_engine(f"mysql+pymysql://{USER}:{PASSWORD}@{HOST}:{PORT}/movie_rental_dw")

print("Connected!")



def read(table, engine):
    with engine.connect() as conn:
        df = pd.read_sql(text(f"SELECT * FROM {table}"), conn)
    print(f"  Read {len(df)} rows from [{table}]")
    return df

def load(df, table):
    with dw.connect() as conn:
        conn.execute(text(f"DELETE FROM {table}"))
        conn.commit()
    df.to_sql(table, dw, if_exists="append", index=False)
    print(f"  Loaded {len(df)} rows into [{table}]")



print("\nLoading dim_date...")
dates = pd.date_range("2005-01-01", "2007-12-31")
dim_date = pd.DataFrame({
    "date_key"    : dates.strftime("%Y%m%d").astype(int),
    "full_date"   : dates.date,
    "day_of_week" : dates.day_name(),
    "day_number"  : dates.day,
    "month_number": dates.month,
    "month_name"  : dates.month_name(),
    "quarter"     : dates.quarter,
    "year"        : dates.year,
    "is_weekend"  : dates.dayofweek.isin([5, 6]).astype(int)
})
load(dim_date, "dim_date")



print("\nLoading dim_customer...")
customer = read("customer", oltp)
address  = read("address",  oltp)
city     = read("city",     oltp)
country  = read("country",  oltp)

dim_customer = (
    customer
    .merge(address, on="address_id", suffixes=("","_addr"))
    .merge(city,    on="city_id",    suffixes=("","_city"))
    .merge(country, on="country_id", suffixes=("","_ctry"))
)
dim_customer["full_name"]     = dim_customer["first_name"] + " " + dim_customer["last_name"]
dim_customer["active_status"] = dim_customer["active"].apply(lambda x: "Active" if x == 1 else "Inactive")
dim_customer = dim_customer[["customer_id","full_name","email","city","country","active_status"]]
load(dim_customer, "dim_customer")



print("\nLoading dim_film...")
film          = read("film",          oltp)
language      = read("language",      oltp)
film_category = read("film_category", oltp)
category      = read("category",      oltp)

dim_film = (
    film
    .merge(language[["language_id","name"]].rename(columns={"name":"language"}),
           on="language_id", suffixes=("","_lang"))
    .merge(film_category, on="film_id", suffixes=("","_fc"))
    .merge(category[["category_id","name"]].rename(columns={"name":"category"}),
           on="category_id", suffixes=("","_cat"))
)
dim_film = dim_film[["film_id","title","description","release_year",
                      "rating","rental_duration","rental_rate","length","language","category"]]
dim_film = dim_film.rename(columns={"length":"length_minutes"})
load(dim_film, "dim_film")


print("\nLoading dim_store...")
store = read("store", oltp)
staff = read("staff", oltp)

staff["manager_name"] = staff["first_name"] + " " + staff["last_name"]

dim_store = (
    store
    .merge(address,  on="address_id",        suffixes=("","_addr"))
    .merge(city,     on="city_id",            suffixes=("","_city"))
    .merge(country,  on="country_id",         suffixes=("","_ctry"))
    .merge(staff[["staff_id","manager_name"]],
           left_on="manager_staff_id",
           right_on="staff_id",
           suffixes=("","_staff"))
)
dim_store = dim_store[["store_id","city","country","address","manager_name"]]
load(dim_store, "dim_store")



print("\nLoading dim_staff...")
dim_staff = staff[["staff_id","full_name" if "full_name" in staff.columns else "first_name","email","store_id"]].copy()
dim_staff["full_name"] = staff["first_name"] + " " + staff["last_name"]
dim_staff = dim_staff[["staff_id","full_name","email","store_id"]]
load(dim_staff, "dim_staff")



print("\nLoading dim_location...")
dim_location = (
    address
    .merge(city,    on="city_id",    suffixes=("","_city"))
    .merge(country, on="country_id", suffixes=("","_ctry"))
)[["address","city","country","postal_code"]]
load(dim_location, "dim_location")



print("\nLoading fact_rental...")
rental    = read("rental",    oltp)
inventory = read("inventory", oltp)

with dw.connect() as conn:
    dc  = pd.read_sql(text("SELECT customer_key, customer_id FROM dim_customer"), conn)
    df2 = pd.read_sql(text("SELECT film_key, film_id FROM dim_film"),             conn)
    ds  = pd.read_sql(text("SELECT store_key, store_id FROM dim_store"),          conn)
    dst = pd.read_sql(text("SELECT staff_key, staff_id FROM dim_staff"),          conn)

fact_rental = rental[rental["return_date"].notna()].copy()
fact_rental["rental_date"]          = pd.to_datetime(fact_rental["rental_date"])
fact_rental["return_date"]          = pd.to_datetime(fact_rental["return_date"])
fact_rental["rental_duration_days"] = (fact_rental["return_date"] - fact_rental["rental_date"]).dt.days
fact_rental["date_key"]             = fact_rental["rental_date"].dt.strftime("%Y%m%d").astype(int)

fact_rental = fact_rental.merge(
    inventory[["inventory_id","film_id","store_id"]], on="inventory_id", suffixes=("","_inv"))
fact_rental = fact_rental.merge(
    film[["film_id","rental_duration"]].rename(columns={"rental_duration":"expected_duration_days"}),
    on="film_id", suffixes=("","_film"))
fact_rental["late_return_flag"] = (
    fact_rental["rental_duration_days"] > fact_rental["expected_duration_days"]
).astype(int)

fact_rental = fact_rental.merge(dc,  on="customer_id", suffixes=("","_dc"))
fact_rental = fact_rental.merge(df2, on="film_id",     suffixes=("","_df"))
fact_rental = fact_rental.merge(ds,  on="store_id",    suffixes=("","_ds"))
fact_rental = fact_rental.merge(dst, on="staff_id",    suffixes=("","_dst"))
fact_rental["rental_count"] = 1

fact_rental = fact_rental[[
    "rental_id","date_key","customer_key","film_key",
    "store_key","staff_key","rental_duration_days",
    "expected_duration_days","late_return_flag","rental_count"
]]
fact_rental.dropna(inplace=True)
for col in ["date_key","customer_key","film_key","store_key","staff_key"]:
    fact_rental[col] = fact_rental[col].astype(int)
load(fact_rental, "fact_rental")



print("\nLoading fact_payment...")
payment = read("payment", oltp)

with dw.connect() as conn:
    dc  = pd.read_sql(text("SELECT customer_key, customer_id FROM dim_customer"), conn)
    dst = pd.read_sql(text("SELECT staff_key, staff_id FROM dim_staff"),          conn)
    fr  = pd.read_sql(text("SELECT rental_key, rental_id FROM fact_rental"),      conn)

fact_payment = payment.copy()
fact_payment["date_key"] = pd.to_datetime(fact_payment["payment_date"]).dt.strftime("%Y%m%d").astype(int)
fact_payment = fact_payment.merge(dc,  on="customer_id", suffixes=("","_dc"))
fact_payment = fact_payment.merge(dst, on="staff_id",    suffixes=("","_dst"))
fact_payment = fact_payment.merge(fr,  on="rental_id",   suffixes=("","_fr"))
fact_payment["payment_count"] = 1
fact_payment = fact_payment[[
    "payment_id","date_key","customer_key","staff_key","rental_key","amount","payment_count"
]]
fact_payment.dropna(inplace=True)
for col in ["date_key","customer_key","staff_key","rental_key"]:
    fact_payment[col] = fact_payment[col].astype(int)
load(fact_payment, "fact_payment")




print("\nLoading fact_inventory...")

with dw.connect() as conn:
    df2 = pd.read_sql(text("SELECT film_key, film_id FROM dim_film"),    conn)
    ds  = pd.read_sql(text("SELECT store_key, store_id FROM dim_store"), conn)

copies = (
    inventory.groupby(["film_id","store_id"])["inventory_id"]
    .nunique().reset_index()
    .rename(columns={"inventory_id":"total_copies"})
)
rental_store  = rental.merge(
    inventory[["inventory_id","film_id","store_id"]], on="inventory_id", suffixes=("","_inv"))
rentals_count = (
    rental_store.groupby(["film_id","store_id"])["rental_id"]
    .count().reset_index()
    .rename(columns={"rental_id":"times_rented"})
)
fact_inventory = copies.merge(rentals_count, on=["film_id","store_id"], how="left")
fact_inventory["times_rented"]      = fact_inventory["times_rented"].fillna(0).astype(int)
fact_inventory["availability_rate"] = (
    (1 - fact_inventory["times_rented"] / (fact_inventory["total_copies"] * 100)) * 100
).clip(lower=0).round(2)
fact_inventory = fact_inventory.merge(df2, on="film_id",  suffixes=("","_df"))
fact_inventory = fact_inventory.merge(ds,  on="store_id", suffixes=("","_ds"))
fact_inventory = fact_inventory[[
    "film_key","store_key","total_copies","times_rented","availability_rate"
]]
fact_inventory.dropna(inplace=True)
fact_inventory["film_key"]  = fact_inventory["film_key"].astype(int)
fact_inventory["store_key"] = fact_inventory["store_key"].astype(int)
load(fact_inventory, "fact_inventory")

print("\n✅ ETL Pipeline Completed Successfully!")