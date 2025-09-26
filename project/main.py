from fastapi import FastAPI, Request, Form, Response, Cookie, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import psycopg2
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel
from collections import defaultdict
from datetime import datetime, date
from itsdangerous import URLSafeSerializer
from typing import Optional, List
import time
import traceback
from fastapi import Query



app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
serializer = URLSafeSerializer("MY_SECRET_KEY")

templates = Jinja2Templates(directory=r"C:\Users\crazy\OneDrive\Documents\Desktop\summerintern\templates")

# PostgreSQL connection
pg_conn = None
while True:
    try:
        pg_conn = psycopg2.connect(
            host='localhost',
            database='database1',
            user='postgres',
            password='nandha102',
            cursor_factory=RealDictCursor
        )
        print("✅ PostgreSQL connected")
        break
    except Exception as e:
        print("❌ PostgreSQL connection error:", e)
        time.sleep(3)

# Models
class Item(BaseModel):
    medId: int
    name: str
    qty: int
    price: float
    total: float

class BillingData(BaseModel):
    user_id: str
    customer_name: str
    mobile_number: str
    district: str
    items: List[Item]
    add_date: str



# Routes
@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login", response_class=HTMLResponse)
def login(request: Request, response: Response, username: str = Form(...), password: str = Form(...)):
    try:
        cur = pg_conn.cursor()
        cur.execute("SELECT * FROM users WHERE name = %s", (username,))
        user = cur.fetchone()
        cur.close()

        if not user:
            return templates.TemplateResponse("login.html", {"request": request, "error": "User not found"})
        if user["password"] != password:
            return templates.TemplateResponse("login.html", {"request": request, "error": "Incorrect password"})

        session_data = serializer.dumps({"username": user["name"], "role": user["role"]})
        resp = RedirectResponse(url="/dashboard", status_code=303)
        resp.set_cookie(key="session", value=session_data, httponly=True)
        return resp

    except Exception:
        print("❌ Exception during login:")
        print(traceback.format_exc())
        return templates.TemplateResponse("login.html", {"request": request, "error": "Login error. Try again."})

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    try:
        cur = pg_conn.cursor()

        # Total counts
        cur.execute("SELECT COUNT(*) AS count FROM medicines")
        tot_med = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) AS count FROM sales")
        tot_sales = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) AS count FROM arrivals")
        tot_arrivals = cur.fetchone()["count"]

        # Alerts: Expiring within 10 days or low stock (<7)
        cur.execute("""
            SELECT name, expiry_date, quantity 
            FROM medicines
        """)
        medicines = cur.fetchall()

        alerts = []
        from datetime import datetime

        today = datetime.today().date()
        for med in medicines:
            expiry = med["expiry_date"]
            days_left = (expiry - today).days

            if days_left < 0:
                alerts.append(f"{med['name']} has already expired!")
            elif days_left <= 10:
                alerts.append(f"{med['name']} is expiring in {days_left} days!")

            if med["quantity"] < 7:
                alerts.append(f"{med['name']} stock is low ({med['quantity']} left).")

        cur.close()

        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "medicines": tot_med,
            "sales": tot_sales,
            "arrivals": tot_arrivals,
            "alerts": alerts
        })

    except Exception:
       
        return HTMLResponse(
            f"<h1>Server Error:<br><pre>{traceback.format_exc()}</pre></h1>", 
            status_code=500
        )

@app.get("/medicines", response_class=HTMLResponse)
def render_medicines(request: Request):
    return templates.TemplateResponse("medicines.html", {"request": request})

@app.get("/api/medicines")
def get_medicines():
    try:
        cur = pg_conn.cursor()
        cur.execute("""
            SELECT id, name, expiry_date, quantity, price 
            FROM medicines 
            WHERE expiry_date >= CURRENT_DATE
        """)
        data = cur.fetchall()
        cur.close()

        today = datetime.today().date()
        return {
            "medicines": [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "expiry_date": row["expiry_date"],
                    "quantity": row["quantity"],
                    "price": row["price"],
                    "low_stock": row["quantity"] < 5,
                    "expiring_soon": (row["expiry_date"] - today).days <= 10
                }
                for row in data
            ]
        }
    except Exception as e:
        return {"error": str(e)}



class Medicine(BaseModel):
    id: int | None = None
    name: str
    expiry_date: str
    quantity: int
    price: float
    added_date: str | None = None

@app.get("/add_medicine", response_class=HTMLResponse)
def render_add_medicine_form(request: Request):
    return templates.TemplateResponse("add_medicine.html", {"request": request})

# 👇 This matches frontend's fetch('/add_med')
@app.post("/add_med")
def add_medicine(med: Medicine):
    try:
        cur = pg_conn.cursor()
        if med.id is None:
            cur.execute("""
                INSERT INTO medicines (name, expiry_date, quantity, price, added_date)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (med.name, med.expiry_date, med.quantity, med.price, med.added_date or datetime.now()))
        else:
            cur.execute("""
                INSERT INTO medicines (id, name, expiry_date, quantity, price, added_date)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (med.id, med.name, med.expiry_date, med.quantity, med.price, med.added_date or datetime.now()))
        new_id = cur.fetchone()["id"]
        pg_conn.commit()
        cur.close()
        return {"message": "Medicine added successfully", "id": new_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/report", response_class=HTMLResponse)
def generate_report(request: Request):
    try:
        cur = pg_conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT * FROM medicines")
        medicines = cur.fetchall()

        cur.execute("SELECT SUM(quantity) AS sum FROM medicines")
        total_qty = cur.fetchone()["sum"] or 0

        cur.execute("SELECT SUM(quantity_arrived) AS sum FROM arrivals")
        total_arrived = cur.fetchone()["sum"] or 0

        cur.execute("SELECT SUM(quantity_sold) AS sum FROM sales")
        total_sold = cur.fetchone()["sum"] or 0

        cur.execute("SELECT SUM(quantity_sold * price) AS sum FROM sales")
        total_amount = cur.fetchone()["sum"] or 0.0

        cur.execute("""
            SELECT sales_date::date as date,
                   SUM(quantity_sold) as sold,
                   SUM(quantity_sold * price) as earned
            FROM sales
            GROUP BY sales_date::date
            ORDER BY sales_date::date
        """)
        sales = cur.fetchall()

        cur.execute("""
            SELECT arrival_date::date as date,
                   SUM(quantity_arrived) as arrived
            FROM arrivals
            GROUP BY arrival_date::date
            ORDER BY arrival_date::date
        """)
        arrivals = cur.fetchall()

        report = defaultdict(lambda: {"arrived": 0, "sold": 0, "earned": 0.0})
        for row in arrivals:
            report[row["date"]]["arrived"] = row["arrived"]
        for row in sales:
            report[row["date"]]["sold"] = row["sold"]
            report[row["date"]]["earned"] = float(row["earned"])

        daily_report = [ {
            "date": dt,
            "arrived": report[dt]["arrived"],
            "sold": report[dt]["sold"],
            "earned": report[dt]["earned"]
        } for dt in sorted(report) ]

        cur.close()

        return templates.TemplateResponse("report.html", {
            "request": request,
            "medicines": medicines,
            "total_qty": total_qty,
            "total_arrived": total_arrived,
            "total_sold": total_sold,
            "total_amount": total_amount,
            "daily_report": daily_report
        })

    except Exception:
        print("Error in /report:", traceback.format_exc())
        return HTMLResponse(f"<h1>Error generating report</h1><pre>{traceback.format_exc()}</pre>", status_code=500)

@app.get("/billing", response_class=HTMLResponse)
def render_billing_form(request: Request):
    return templates.TemplateResponse("billing.html", {"request": request})

@app.post("/billing", response_class=HTMLResponse)
async def post_billing(data: BillingData):
    try:
        grand_total = sum(item.total for item in data.items)
        date_obj = datetime.fromisoformat(data.add_date)
        cur = pg_conn.cursor()

        for item in data.items:
            cur.execute("""
                INSERT INTO bills (id, name, phonenum, district, medicine_name, quantity, price, total_price, date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                data.user_id,
                data.customer_name,
                data.mobile_number,
                data.district,
                item.name,
                item.qty,
                item.price,
                item.total,
                date_obj
            ))

            cur.execute("UPDATE medicines SET quantity = quantity - %s WHERE id = %s", (item.qty, item.medId))
            cur.execute("INSERT INTO sales (med_id, quantity_sold, price, sales_date) VALUES (%s, %s, %s, %s)",
                        (item.medId, item.qty, item.price, date_obj))

        pg_conn.commit()
        cur.close()

        return HTMLResponse(content=f"""
            <h1>Billing completed for {data.customer_name}</h1>
            <p>Total: ₹ {grand_total:.2f}</p>
            <a href="/billing_details/{data.user_id}">View Bill</a>
        """)

    except Exception as e:
        pg_conn.rollback()
        print(traceback.format_exc())
        return JSONResponse(content={"error": str(e)}, status_code=500)

# ✅ Updated route to handle both /billing_details and /billing_details/{billing_id}
@app.get("/billing_details", response_class=HTMLResponse)
@app.get("/billing_details/{billing_id}", response_class=HTMLResponse)
def show_billing_details(request: Request, billing_id: Optional[int] = None):
    try:
        cur = pg_conn.cursor()
        if billing_id:
            cur.execute("SELECT * FROM bills WHERE id = %s", (billing_id,))
        else:
            cur.execute("SELECT * FROM bills ORDER BY date DESC LIMIT 10")
        rows = cur.fetchall()
        cur.close()

        if not rows:
            return templates.TemplateResponse("billing.html", {
                "request": request,
                "error": "Billing record not found."
            })

        return templates.TemplateResponse("billing_details.html", {
            "request": request,
            "billing_data": rows
        })

    except Exception:
        traceback.print_exc()
        return templates.TemplateResponse("billing.html", {
            "request": request,
            "error": "Error loading billing details."
        })



@app.get("/sales", response_class=HTMLResponse)
def daywise_sales(request: Request, sales_date: str = Query(None)):
    """
    Show all sales by default or filter by a specific date if 'sales_date' is provided.
    """
    try:
        cur = pg_conn.cursor()

        if sales_date:
            # Filter sales by date
            cur.execute(
                "SELECT * FROM sales WHERE sales_date::date = %s ORDER BY sales_date ASC;",
                (sales_date,)
            )
        else:
            # Fetch all sales
            cur.execute("SELECT * FROM sales ORDER BY sales_date ASC;")

        sales = cur.fetchall()
        cur.close()

        return templates.TemplateResponse(
            "sales.html",
            {"request": request, "sales": sales}
        )

    except Exception:
        traceback.print_exc()
        return HTMLResponse(
            content=f"<h1>Error fetching sales</h1><pre>{traceback.format_exc()}</pre>",
            status_code=500
        )


@app.get("/billing_history", response_class=HTMLResponse)
def show_all_billing(request: Request, q: Optional[str] = Query(None)):
    try:
        cur = pg_conn.cursor()

        if q:  # If search query provided
            search_pattern = f"%{q}%"
            cur.execute("""
                SELECT * FROM bills
                WHERE name ILIKE %s OR medicine_name ILIKE %s OR CAST(date AS TEXT) ILIKE %s
                ORDER BY date DESC
            """, (search_pattern, search_pattern, search_pattern))
        else:  # Default → all records
            cur.execute("SELECT * FROM bills ORDER BY id ASC")

        billing_records = cur.fetchall()
        cur.close()

        return templates.TemplateResponse("billing_history.html", {
            "request": request,
            "records": billing_records,
            "search_query": q  # optional: to prefill search box in template
        })
    except Exception:
        traceback.print_exc()
        return HTMLResponse(content="<h1>Error loading billing history</h1>", status_code=500)
    
@app.get("/medicine_arrivals", response_class=HTMLResponse)
def show_medicine_arrivals(request: Request, q: Optional[str] = Query(None)):
    try:
        cur = pg_conn.cursor()

        if q:
            search_pattern = f"%{q}%"
            cur.execute("""
                SELECT id, name, quantity, price, added_date, expiry_date
                FROM medicines
                WHERE name ILIKE %s OR CAST(added_date AS TEXT) ILIKE %s
                ORDER BY added_date DESC
            """, (search_pattern, search_pattern))
        else:
            cur.execute("""
                SELECT id, name, quantity, price, added_date, expiry_date
                FROM medicines
                ORDER BY added_date DESC
            """)

        arrivals = cur.fetchall()
        cur.close()

        return templates.TemplateResponse("medicine_arrivals.html", {
            "request": request,
            "arrivals": arrivals,
            "search_query": q
        })

    except Exception as e:
        import traceback; traceback.print_exc()
        return HTMLResponse(
            content=f"<h1>Error loading arrivals</h1><pre>{e}</pre>",
            status_code=500
        )
