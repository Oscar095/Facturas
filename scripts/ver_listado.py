import httpx

c = httpx.Client(base_url="http://127.0.0.1:8000", timeout=30)
r = c.post("/api/auth/login", data={"username": "oscar.orozco03@gmail.com", "password": "Admin1234*"})
c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
r = c.get("/api/facturas?pagina=1")
print("status:", r.status_code)
print("total:", r.json().get("total"))
print("items:", len(r.json().get("items", [])))
print(r.text[:300])
